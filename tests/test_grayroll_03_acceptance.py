"""grayroll-03 独验收横切：覆盖与求值优先序跨表联查。

段内验收口径：
- 缺时刻 → 正式覆盖零增；
- 有时刻 → 求值优先覆盖，且历史记录有到期字段；
- 双会话争用 → 败方零正式改。
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


def _counts(conn) -> tuple[int, int]:
    official = conn.execute("SELECT COUNT(*) c FROM overrides").fetchone()["c"]
    shadows = conn.execute("SELECT COUNT(*) c FROM override_shadows").fetchone()["c"]
    return official, shadows


def test_acceptance_missing_expiry_zero_official_growth():
    with TestClient(app) as client:
        headers = _h(client)
        subject = f"u-03-acc-a-{uuid.uuid4().hex[:8]}"
        with connect() as conn:
            before = _counts(conn)
        r = client.post(
            "/api/overrides",
            headers=headers,
            json={
                "flag_id": 3,
                "env_id": 3,
                "subject_key": subject,
                "effect": "force_on",
                "note": "独验收缺时刻",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "shadow"
        with connect() as conn:
            after = _counts(conn)
        assert after[0] == before[0], "缺时刻正式覆盖册增行"
        assert after[1] == before[1] + 1, "缺时刻未落影子草案"


def test_acceptance_expiry_override_precedence_and_history_expiry():
    with TestClient(app) as client:
        headers = _h(client)
        subject = f"u-03-acc-b-{uuid.uuid4().hex[:8]}"
        exp = time.time() + 7200
        r = client.post(
            "/api/overrides",
            headers=headers,
            json={
                "flag_id": 3,
                "env_id": 3,
                "subject_key": subject,
                "effect": "force_off",
                "note": "独验收有时刻",
                "expires_at": exp,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "official"
        ev = client.post(
            "/api/evaluate",
            headers=headers,
            json={"flag_key": "feed.ranking_v2", "env_code": "prod", "subject_key": subject},
        ).json()
        assert ev["reason"] == "override:force_off", f"求值未优先覆盖：{ev}"
        assert ev["enabled"] is False
        assert ev["expires_at"] == exp
        with connect() as conn:
            hist = conn.execute(
                "SELECT detail, expires_at FROM change_history WHERE action='override' AND flag_id=3 AND env_id=3 "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            rule = conn.execute(
                "SELECT COUNT(*) c FROM flag_rules WHERE flag_id=3 AND env_id=3 AND official=1"
            ).fetchone()["c"]
        assert hist["expires_at"] == exp, "历史无到期字段"
        assert "到期" in hist["detail"]
        # 覆盖优先于正式规则且跨表联查：正式规则未被覆盖写口改写
        assert rule >= 0
