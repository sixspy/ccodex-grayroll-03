"""在线求值：给定主体键，返回开关在某环境是否命中。"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from auth import current_user
from db import connect
from policies import combine_rule, eval_percent
from validators import require_str

router = APIRouter(prefix="/api/evaluate", tags=["evaluate"])


class EvalIn(BaseModel):
    flag_key: str
    env_code: str
    subject_key: str


@router.post("")
def evaluate(body: EvalIn, authorization: str | None = Header(default=None)):
    current_user(authorization)
    flag_key = require_str(body.flag_key, "开关键", 2)
    env_code = require_str(body.env_code, "环境", 2)
    subject = require_str(body.subject_key, "主体键", 1)
    with connect() as conn:
        fl = conn.execute("SELECT * FROM flags WHERE key=?", (flag_key,)).fetchone()
        if not fl:
            raise HTTPException(404, detail="开关不存在")
        env = conn.execute("SELECT * FROM environments WHERE code=?", (env_code,)).fetchone()
        if not env:
            raise HTTPException(404, detail="环境不存在")
        if fl["status"] == "killed":
            return {
                "enabled": False,
                "reason": "flag_killed",
                "flag_key": flag_key,
                "env_code": env_code,
                "subject_key": subject,
            }
        if fl["status"] == "archived":
            return {
                "enabled": False,
                "reason": "flag_archived",
                "flag_key": flag_key,
                "env_code": env_code,
                "subject_key": subject,
            }
        ov = conn.execute(
            "SELECT * FROM overrides WHERE flag_id=? AND env_id=? AND subject_key=? AND active=1",
            (fl["id"], env["id"], subject),
        ).fetchone()
        expired = False
        forced_without_expiry = False
        if ov:
            if ov["expires_at"] is None:
                # 老账/绕过写口落下的强制开缺时刻：不得永久命中，回落正式规则并标痕
                ov = None
                forced_without_expiry = True
            elif float(ov["expires_at"]) <= time.time():
                # 正式覆盖已过失效时刻：不得永久命中，回落到正式规则
                ov = None
                expired = True
        if ov:
            enabled = ov["effect"] == "force_on"
            return {
                "enabled": enabled,
                "reason": f"override:{ov['effect']}",
                "flag_key": flag_key,
                "env_code": env_code,
                "subject_key": subject,
                "expires_at": ov["expires_at"],
                "version": None,
            }
        shadow = conn.execute(
            "SELECT * FROM override_shadows WHERE flag_id=? AND env_id=? AND subject_key=? AND status='open'",
            (fl["id"], env["id"], subject),
        ).fetchone()
        rule = conn.execute(
            "SELECT * FROM flag_rules WHERE flag_id=? AND env_id=? AND official=1",
            (fl["id"], env["id"]),
        ).fetchone()
        if not rule:
            out = {
                "enabled": False,
                "reason": "no_official_rule",
                "flag_key": flag_key,
                "env_code": env_code,
                "subject_key": subject,
            }
            if shadow:
                out["pending_override_shadow"] = {
                    "id": shadow["id"],
                    "effect": shadow["effect"],
                    "status": shadow["status"],
                }
            if expired:
                out["override_expired"] = True
            if forced_without_expiry:
                out["override_missing_expiry"] = True
            return out
        percent_hit = eval_percent(subject, int(rule["percent"]), flag_key)
        cohort_hit = False
        if rule["cohort_id"]:
            cohort_hit = bool(
                conn.execute(
                    "SELECT 1 FROM cohort_members WHERE cohort_id=? AND subject_key=?",
                    (rule["cohort_id"], subject),
                ).fetchone()
            )
        enabled = combine_rule(rule["kind"], percent_hit, cohort_hit)
        out = {
            "enabled": enabled,
            "reason": "rule",
            "kind": rule["kind"],
            "percent": rule["percent"],
            "percent_hit": percent_hit,
            "cohort_hit": cohort_hit,
            "version": rule["version"],
            "flag_key": flag_key,
            "env_code": env_code,
            "subject_key": subject,
        }
        if shadow:
            out["pending_override_shadow"] = {
                "id": shadow["id"],
                "effect": shadow["effect"],
                "status": shadow["status"],
            }
        if expired:
            out["override_expired"] = True
        if forced_without_expiry:
            out["override_missing_expiry"] = True
        return out


@router.get("/board")
def eval_board(authorization: str | None = Header(default=None)):
    """总览：各环境正式规则摘要。"""
    current_user(authorization)
    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT f.key AS flag_key, f.status, e.code AS env_code, r.kind, r.percent, r.version, r.cohort_id
                FROM flag_rules r
                JOIN flags f ON f.id=r.flag_id
                JOIN environments e ON e.id=r.env_id
                WHERE r.official=1
                ORDER BY f.key, e.risk_level
                """
            ).fetchall()
        ]
        by_status = [
            dict(x)
            for x in conn.execute("SELECT status, COUNT(*) c FROM flags GROUP BY status").fetchall()
        ]
    return {"rules": rows, "by_status": by_status}
