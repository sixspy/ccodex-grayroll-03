"""override_ttl_required_03 — 同主体覆盖锁争用双请求脚本。

场景：会话 A（模拟在飞）已占住某主体的覆盖写锁；随后 admin 与 writer 两个会话
并发向同一主体打覆盖写口。修复前无锁，双请求都落正式账（无锁双成）；
修复后两路都必须被同主体覆盖锁挡住，只留争用痕，正式覆盖册零增。

用法：
    python scripts/override_ttl_required_03.py            # 人类可读
    python scripts/override_ttl_required_03.py --json     # 测试器读取
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from db import connect  # noqa: E402

FLAG_ID = 3
ENV_ID = 3
HOLDER = "session-a"


def _token(client, username: str, password: str) -> str:
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _clear(conn, lock_key: str) -> None:
    conn.execute("DELETE FROM row_locks WHERE lock_key=?", (lock_key,))
    conn.execute("DELETE FROM contention_marks WHERE lock_key=?", (lock_key,))


def run() -> dict:
    subject = f"u-03-zheng-{uuid.uuid4().hex[:8]}"
    lock_key = f"override:{FLAG_ID}:{ENV_ID}:{subject}"
    expires_at = time.time() + 3600
    payload = {
        "flag_id": FLAG_ID,
        "env_id": ENV_ID,
        "subject_key": subject,
        "effect": "force_on",
        "note": "同主体覆盖锁争用夹具",
        "expires_at": expires_at,
    }
    summary: dict = {
        "subject": subject,
        "lock_key": lock_key,
        "holder": HOLDER,
        "responses": [],
    }
    with TestClient(app) as _bootstrap:
        pass
    with connect() as conn:
        _clear(conn, lock_key)
        conn.execute(
            "INSERT INTO row_locks(lock_key, holder, expires_at) VALUES(?,?,?)",
            (lock_key, HOLDER, time.time() + 20.0),
        )
        conn.commit()

    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def fire(username: str, password: str) -> None:
        with TestClient(app, raise_server_exceptions=False) as client:
            token = _token(client, username, password)
            heads = {"Authorization": f"Bearer {token}"}
            barrier.wait()
            r = client.post("/api/overrides", headers=heads, json=payload)
            try:
                body = r.json()
            except ValueError:
                body = {"raw": r.text[:400]}
            entry = {"session": username, "status": r.status_code, "body": body}
            with lock:
                summary["responses"].append(entry)

    threads = [
        threading.Thread(target=fire, args=("admin", "admin123")),
        threading.Thread(target=fire, args=("writer", "writer123")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(overrides)")}
        cols_sql = "id, subject_key, effect, active" + (", expires_at" if "expires_at" in cols else "")
        official = conn.execute(
            f"SELECT {cols_sql} FROM overrides WHERE subject_key=?", (subject,)
        ).fetchall()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "override_shadows" in tables:
            shadows = conn.execute(
                "SELECT id, status FROM override_shadows WHERE subject_key=?", (subject,)
            ).fetchall()
        else:
            shadows = []
        marks = conn.execute(
            "SELECT loser, winner FROM contention_marks WHERE lock_key=?", (lock_key,)
        ).fetchall()
        summary["official_rows"] = [dict(r) for r in official]
        summary["shadow_rows"] = [dict(r) for r in shadows]
        summary["contention_marks"] = [dict(r) for r in marks]
        summary["double_success"] = len([r for r in summary["responses"] if r["status"] == 200])
        _clear(conn, lock_key)
        conn.commit()

    summary["responses"].sort(key=lambda x: x["session"])
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = run()
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
