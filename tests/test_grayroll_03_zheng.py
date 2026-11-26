"""grayroll-03 争用侧红测：同主体覆盖锁。

失败测盯「两路会话抢同主体覆盖锁无锁双成」：
- 借 override_ttl_required_03 并发脚本，两路会话对同一主体打覆盖写口；
- 修复前无锁 → 双请求都落正式账（双成）；修复后必须至少一路被锁挡住，
  败方只写争用痕，正式覆盖册零增。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "override_ttl_required_03.py"


def _run_script() -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_zheng_same_subject_lock_blocks_double_success():
    summary = _run_script()
    responses = summary["responses"]
    assert len(responses) == 2, responses
    statuses = sorted(r["status"] for r in responses)
    assert statuses == [409, 409], f"同主体覆盖锁未挡住双写：{responses}"
    assert all("争用" in json.dumps(r["body"], ensure_ascii=False) for r in responses), responses

    assert summary["official_rows"] == [], f"败方落了正式覆盖：{summary['official_rows']}"
    assert summary["shadow_rows"] == [], f"败方落了影子覆盖：{summary['shadow_rows']}"
    marks = summary["contention_marks"]
    assert len(marks) == 2, f"争用痕未按败方逐条记录：{marks}"
    assert {m["loser"] for m in marks} == {"admin", "writer"}, marks
    assert {m["winner"] for m in marks} == {summary["holder"]}, marks
