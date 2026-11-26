"""grayroll-03 甲侧红测：写口正式账实。

正确性口径拍板：覆盖强制开走乙路径——缺失效时刻只落影子覆盖草案，正式覆盖册零增；
显式携带失效时刻才同事务写正式覆盖行，并在变更历史留下到期字段。

本文件盯「写口正式账实」这一面：
- 缺失效时刻的强制开夹具不得在正式覆盖册建行（只能建影子草案）；
- 带失效时刻的强制开必须同事务写正式行，历史与求值都带到期痕迹。
"""
from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient

from app import app


def _h(client) -> dict[str, str]:
    r = client.post("/api/login", json={"username": "writer", "password": "writer123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _subject() -> str:
    return f"u-03-jia-{uuid.uuid4().hex[:8]}"


def _split(client, headers, subject: str) -> tuple[list[dict], list[dict]]:
    body = client.get("/api/overrides", headers=headers).json()
    official = [i for i in body.get("items", []) if i["subject_key"] == subject]
    shadows = [i for i in body.get("shadows", []) if i["subject_key"] == subject]
    return official, shadows


def test_jia_missing_expiry_creates_zero_official_rows():
    """失败测甲：缺失效时刻仍建正式覆盖行 → 红。"""
    with TestClient(app) as client:
        headers = _h(client)
        subject = _subject()
        r = client.post(
            "/api/overrides",
            headers=headers,
            json={
                "flag_id": 3,
                "env_id": 3,
                "subject_key": subject,
                "effect": "force_on",
                "note": "无失效时刻强制开夹具",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # 乙路径：缺时刻只许影子覆盖草案
        assert body.get("mode") == "shadow", body
        assert body.get("expires_at") is None, body

        official, shadows = _split(client, headers, subject)
        assert official == [], f"正式覆盖册不得新增：{official}"
        assert len(shadows) == 1, shadows
        assert shadows[0]["status"] == "open"
        assert shadows[0]["expires_at"] is None


def test_jia_with_expiry_writes_official_and_history_carries_expiry():
    """有时刻后同事务写正式覆盖，历史与求值均带到期字段。"""
    with TestClient(app) as client:
        headers = _h(client)
        subject = _subject()
        expires_at = time.time() + 3600
        r = client.post(
            "/api/overrides",
            headers=headers,
            json={
                "flag_id": 3,
                "env_id": 3,
                "subject_key": subject,
                "effect": "force_on",
                "note": "带失效时刻强制开",
                "expires_at": expires_at,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("mode") == "official", body
        assert body.get("expires_at") == expires_at

        official, shadows = _split(client, headers, subject)
        assert len(official) == 1, official
        assert official[0]["effect"] == "force_on"
        assert official[0]["active"] == 1
        assert official[0]["expires_at"] == expires_at
        assert shadows == []

        history = client.get("/api/history", headers=headers, params={"limit": 200}).json()["items"]
        hit = [
            h
            for h in history
            if subject in h["detail"]
            and h["action"] in ("override", "override_promote")
        ]
        assert hit, history[:5]
        assert hit[0]["expires_at"] == expires_at, hit[0]
        assert "到期" in hit[0]["detail"], hit[0]

        ev = client.post(
            "/api/evaluate",
            headers=headers,
            json={"flag_key": "feed.ranking_v2", "env_code": "prod", "subject_key": subject},
        )
        assert ev.status_code == 200, ev.text
        out = ev.json()
        assert out["enabled"] is True, out
        assert out["reason"].startswith("override:"), out
        assert out["expires_at"] == expires_at, out
