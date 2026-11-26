"""单点覆盖：强制开/关，优先于灰度比例。

正确性口径（grayroll-03 拍板）：覆盖强制开走乙路径。
- 缺失效时刻 → 只落影子覆盖草案，正式覆盖册零增（拒写正式账）；
- 显式携带失效时刻 → 同事务写正式覆盖行，并把到期时刻写进变更历史；
- 任何正式覆盖写都必须带失效时刻，缺时刻一律不建正式行。

同主体覆盖锁：同一 (flag, env, subject) 的覆盖写口串行化，败方只记争用痕、零正式改。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from audit_svc import write_audit, write_history
from auth import current_user, require_writer
from db import connect
from locks import acquire, release
from validators import require_effect, require_int, require_str

router = APIRouter(prefix="/api/overrides", tags=["overrides"])


class OverrideIn(BaseModel):
    flag_id: int
    env_id: int
    subject_key: str
    effect: str
    note: str = ""
    expires_at: float | None = None


def override_lock_key(flag_id: int, env_id: int, subject_key: str) -> str:
    return f"override:{flag_id}:{env_id}:{subject_key}"


def _fmt_expiry(expires_at: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at))


@router.get("")
def list_overrides(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT o.*, f.key AS flag_key, e.code AS env_code
                FROM overrides o
                JOIN flags f ON f.id=o.flag_id
                JOIN environments e ON e.id=o.env_id
                ORDER BY o.id DESC
                """
            ).fetchall()
        ]
        shadows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT s.*, f.key AS flag_key, e.code AS env_code
                FROM override_shadows s
                JOIN flags f ON f.id=s.flag_id
                JOIN environments e ON e.id=s.env_id
                ORDER BY s.id DESC
                """
            ).fetchall()
        ]
    return {"items": rows, "shadows": shadows}


@router.post("")
def upsert_override(body: OverrideIn, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    fid = require_int(body.flag_id, "开关", 1)
    eid = require_int(body.env_id, "环境", 1)
    sk = require_str(body.subject_key, "主体键", 2)
    effect = require_effect(body.effect)
    now = time.time()
    expires_at = body.expires_at
    key = override_lock_key(fid, eid, sk)
    with connect() as conn:
        acquire(conn, key, user["username"])
        try:
            if not conn.execute("SELECT 1 FROM flags WHERE id=?", (fid,)).fetchone():
                raise HTTPException(404, detail="开关不存在")
            if not conn.execute("SELECT 1 FROM environments WHERE id=?", (eid,)).fetchone():
                raise HTTPException(404, detail="环境不存在")

            if expires_at is None:
                # 乙路径：缺时刻一律只落影子覆盖草案，正式覆盖册零增
                sid = _write_shadow(conn, user, fid, eid, sk, effect, body.note, None, now)
                conn.commit()
                return {
                    "mode": "shadow",
                    "id": sid,
                    "effect": effect,
                    "expires_at": None,
                    "requires_expiry": True,
                    "path": "缺失效时刻只许影子覆盖草案，升正前正式覆盖册零改",
                }

            expires_at = float(expires_at)
            if expires_at <= now:
                raise HTTPException(400, detail="失效时刻须晚于当前时间")
            old = conn.execute(
                "SELECT * FROM overrides WHERE flag_id=? AND env_id=? AND subject_key=?",
                (fid, eid, sk),
            ).fetchone()
            # 同主体其余开放影子草案被本次正式写覆盖
            conn.execute(
                "UPDATE override_shadows SET status='superseded' "
                "WHERE flag_id=? AND env_id=? AND subject_key=? AND status='open'",
                (fid, eid, sk),
            )
            if old:
                conn.execute(
                    "UPDATE overrides SET effect=?, note=?, active=1, updated_at=?, expires_at=? WHERE id=?",
                    (effect, body.note or "", now, expires_at, old["id"]),
                )
                oid = old["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO overrides(flag_id, env_id, subject_key, effect, note, active, updated_at, expires_at) "
                    "VALUES(?,?,?,?,?,1,?,?)",
                    (fid, eid, sk, effect, body.note or "", now, expires_at),
                )
                oid = cur.lastrowid
            detail = f"{sk} -> {effect}（到期 {_fmt_expiry(expires_at)}）"
            write_audit(conn, user["username"], "override", "override", oid, f"{sk}:{effect}:ttl={expires_at}")
            write_history(
                conn,
                user["username"],
                "override",
                detail,
                flag_id=fid,
                env_id=eid,
                expires_at=expires_at,
            )
            conn.commit()
            return {"mode": "official", "id": oid, "effect": effect, "expires_at": expires_at}
        finally:
            release(conn, key, user["username"])
            conn.commit()


def _write_shadow(conn, user, fid, eid, sk, effect, note, expires_at, now) -> int:
    cur = conn.execute(
        "INSERT INTO override_shadows(flag_id, env_id, subject_key, effect, note, expires_at, status, created_at, created_by) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (fid, eid, sk, effect, note or "", expires_at, "open", now, user["username"]),
    )
    sid = cur.lastrowid
    write_audit(conn, user["username"], "override_shadow", "override_shadow", sid, f"{sk}:{effect}:shadow")
    write_history(
        conn,
        user["username"],
        "override_shadow",
        f"影子覆盖 {sk} -> {effect}（缺失效时刻，正式册零改）",
        flag_id=fid,
        env_id=eid,
        expires_at=None,
    )
    return sid


@router.post("/shadow/{shadow_id}/promote")
def promote_override_shadow(
    shadow_id: int,
    authorization: str | None = Header(default=None),
    expires_at: float | None = None,
):
    """影子覆盖升正：必须带失效时刻，同事务写正式覆盖行并记到期字段。"""
    user = current_user(authorization)
    require_writer(user)
    with connect() as conn:
        sh = conn.execute("SELECT * FROM override_shadows WHERE id=?", (shadow_id,)).fetchone()
        if not sh or sh["status"] != "open":
            raise HTTPException(400, detail="影子覆盖不可升正")
        fid, eid, sk = sh["flag_id"], sh["env_id"], sh["subject_key"]
        key = override_lock_key(fid, eid, sk)
        acquire(conn, key, user["username"])
        try:
            now = time.time()
            exp = expires_at if expires_at is not None else sh["expires_at"]
            if exp is None:
                raise HTTPException(400, detail="影子覆盖升正须带失效时刻，正式覆盖册零增")
            exp = float(exp)
            if exp <= now:
                raise HTTPException(400, detail="失效时刻须晚于当前时间")
            old = conn.execute(
                "SELECT * FROM overrides WHERE flag_id=? AND env_id=? AND subject_key=?",
                (fid, eid, sk),
            ).fetchone()
            # 同主体其余开放影子草案被本次正式升正取代
            conn.execute(
                "UPDATE override_shadows SET status='superseded' "
                "WHERE flag_id=? AND env_id=? AND subject_key=? AND status='open'",
                (fid, eid, sk),
            )
            if old:
                conn.execute(
                    "UPDATE overrides SET effect=?, note=?, active=1, updated_at=?, expires_at=? WHERE id=?",
                    (sh["effect"], sh["note"], now, exp, old["id"]),
                )
                oid = old["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO overrides(flag_id, env_id, subject_key, effect, note, active, updated_at, expires_at) "
                    "VALUES(?,?,?,?,?,1,?,?)",
                    (fid, eid, sk, sh["effect"], sh["note"], now, exp),
                )
                oid = cur.lastrowid
            conn.execute("UPDATE override_shadows SET status='promoted' WHERE id=?", (shadow_id,))
            detail = f"{sk} -> {sh['effect']}（到期 {_fmt_expiry(exp)}）"
            write_history(
                conn,
                user["username"],
                "override_promote",
                f"影子覆盖升正 {detail}",
                flag_id=fid,
                env_id=eid,
                expires_at=exp,
            )
            write_audit(conn, user["username"], "override_promote", "override", oid, f"from_shadow={shadow_id}:ttl={exp}")
            conn.commit()
            return {"mode": "official", "id": oid, "effect": sh["effect"], "expires_at": exp}
        finally:
            release(conn, key, user["username"])
            conn.commit()


@router.post("/{override_id}/disable")
def disable_override(override_id: int, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    require_writer(user)
    with connect() as conn:
        row = conn.execute("SELECT * FROM overrides WHERE id=?", (override_id,)).fetchone()
        if not row:
            raise HTTPException(404, detail="覆盖不存在")
        key = override_lock_key(row["flag_id"], row["env_id"], row["subject_key"])
        acquire(conn, key, user["username"])
        try:
            conn.execute("UPDATE overrides SET active=0, updated_at=? WHERE id=?", (time.time(), override_id))
            write_history(
                conn,
                user["username"],
                "override_off",
                f"停用覆盖 {row['subject_key']}",
                flag_id=row["flag_id"],
                env_id=row["env_id"],
            )
            conn.commit()
        finally:
            release(conn, key, user["username"])
            conn.commit()
    return {"id": override_id, "active": 0}
