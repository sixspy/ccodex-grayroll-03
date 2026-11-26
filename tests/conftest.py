"""测试隔离：每个测试会话用独立临时库，避免上一轮红测残留污染下一轮绿判。

生产/页面联调仍走 data/app.db；这里只改测试进程内的 db.DB_PATH。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import db as _db


@pytest.fixture(scope="session", autouse=True)
def _isolated_db():
    tmp = Path(tempfile.mkdtemp(prefix="grayroll-test-"))
    _db.DB_PATH = tmp / "app.db"
    yield
    for suffix in ("", "-wal", "-shm"):
        p = tmp / f"app.db{suffix}"
        if p.exists():
            p.unlink()
    tmp.rmdir()
