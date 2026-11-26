"""行锁与争用痕（嵌进发布/熔断/覆盖主写路径）。

同库单文件并发下，先把写锁落到库里再放行主写：
- 以条件 upsert 抢占（只有已过期或持有者相同才允许覆盖），rowcount=0 即争用；
- 争用败方只写 contention_marks，不碰正式账；
- 主写完成后按 holder 删锁，容忍被同主体后续持有者接管（不会误删他人锁）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect

router = APIRouter(prefix="/api/locks", tags=["locks"])
TTL = 20.0


def acquire(conn, key: str, holder: str) -> None:
    now = time.time()
    cur = conn.execute(
        "INSERT INTO row_locks(lock_key, holder, expires_at) VALUES(?,?,?) "
        "ON CONFLICT(lock_key) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at "
        "WHERE row_locks.expires_at <= ? OR row_locks.holder = excluded.holder",
        (key, holder, now + TTL, now),
    )
    took = cur.rowcount == 1
    # 抢占必须立即落库，后续读连接才看得见
    conn.commit()
    if not took:
        winner = conn.execute("SELECT holder FROM row_locks WHERE lock_key=?", (key,)).fetchone()
        winner_name = winner["holder"] if winner else "unknown"
        conn.execute(
            "INSERT INTO contention_marks(lock_key, loser, winner, created_at) VALUES(?,?,?,?)",
            (key, holder, winner_name, now),
        )
        conn.commit()
        raise HTTPException(409, detail="同主体覆盖锁争用，请稍后重试")


def release(conn, key: str, holder: str) -> None:
    conn.execute("DELETE FROM row_locks WHERE lock_key=? AND holder=?", (key, holder))
    conn.commit()


@router.get("/contention")
def list_contention(authorization: str | None = Header(default=None), limit: int = 40):
    current_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM contention_marks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"items": [dict(r) for r in rows]}
