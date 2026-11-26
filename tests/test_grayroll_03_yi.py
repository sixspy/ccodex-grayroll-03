"""grayroll-03 乙侧红测：求值页假绿。

失败测乙盯「另一面假绿」：
- 未升正的影子覆盖草案不得被求值页当作已强制开（假绿）；
- 已过失效时刻的正式强制开也不得永久命中（缺时刻导致的永久命中）。
"""
from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient

from app import app
from db import connect


def _h(client) -> dict[str, str]:
    r = client.post("/api/login", json={"username": "writer", "password": "writer123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _subject(prefix: str) -> str:
    return f"u-03-yi-{prefix}-{uuid.uuid4().hex[:8]}"


def _evaluate(client, headers, subject: str) -> dict:
    r = client.post(
        "/api/evaluate",
        headers=headers,
        json={"flag_key": "feed.ranking_v2", "env_code": "prod", "subject_key": subject},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_yi_unpromoted_shadow_override_is_not_forced_on():
    """未升正影子覆盖被求值页当已强制开 → 假绿红。"""
    with TestClient(app) as client:
        headers = _h(client)
        subject = _subject("shadow")
        r = client.post(
            "/api/overrides",
            headers=headers,
            json={
                "flag_id": 3,
                "env_id": 3,
                "subject_key": subject,
                "effect": "force_on",
                "note": "缺时刻影子草案假绿夹具",
            },
        )
        assert r.status_code == 200, r.text
        out = _evaluate(client, headers, subject)
        assert out["enabled"] is False, f"影子草案未升正却已强制开：{out}"
        assert not out["reason"].startswith("override:"), out
        assert out.get("pending_override_shadow"), out
        # 该主体在生产环境没有正式规则，未升正影子不得越过正式册
        assert out["reason"] in ("no_official_rule", "rule"), out


def test_yi_expired_official_override_does_not_hit_forever():
    """正式强制开过了失效时刻仍永久命中 → 假绿红。"""
    with TestClient(app) as client:
        headers = _h(client)
        subject = _subject("expired")
        now = time.time()
        with connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(overrides)")}
            assert "expires_at" in cols, "正式覆盖册缺失效时刻列，过期覆盖无法留痕"
            conn.execute(
                "INSERT INTO overrides(flag_id, env_id, subject_key, effect, note, active, updated_at, expires_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (3, 3, subject, "force_on", "已过失效时刻夹具", 1, now - 3600, now - 60),
            )
            conn.commit()
        out = _evaluate(client, headers, subject)
        assert out["enabled"] is False, f"过期覆盖仍永久命中：{out}"
        assert not out["reason"].startswith("override:"), out
        assert out.get("override_expired") is True, out


def test_yi_expiry_less_official_row_cannot_hit_forever():
    """老账验收：正式强制开缺失效时刻也不得永久命中，且须留到期痕。"""
    with TestClient(app) as client:
        headers = _h(client)
        subject = _subject("nottl")
        now = time.time()
        with connect() as conn:
            conn.execute(
                "INSERT INTO overrides(flag_id, env_id, subject_key, effect, note, active, updated_at, expires_at) "
                "VALUES(?,?,?,?,?,?,?,NULL)",
                (3, 3, subject, "force_on", "缺时刻老账夹具", 1, now),
            )
            conn.commit()
        out = _evaluate(client, headers, subject)
        assert out["enabled"] is False, f"缺时刻正式覆盖仍永久命中：{out}"
        assert out.get("override_missing_expiry") is True, out
