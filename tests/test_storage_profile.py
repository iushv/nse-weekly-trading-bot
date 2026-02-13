from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from trading_bot.monitoring.storage_profile import profile_sources


def _touch_with_age(path: Path, days_old: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 10, encoding="utf-8")
    ts = (datetime(2026, 2, 11, 12, 0, 0) - timedelta(days=days_old)).timestamp()
    os.utime(path, (ts, ts))


def test_storage_profile_buckets_and_suggestion(tmp_path):
    root = tmp_path / "reports" / "audits"
    _touch_with_age(root / "a.json", 2)
    _touch_with_age(root / "b.json", 20)
    _touch_with_age(root / "c.json", 45)
    _touch_with_age(root / "d.json", 120)

    result = profile_sources([str(root)], now=datetime(2026, 2, 11, 12, 0, 0))

    assert result["total_files"] == 4
    assert result["total_bytes"] == 40
    assert len(result["profiles"]) == 1

    profile = result["profiles"][0]
    buckets = profile["bucket_stats"]
    assert buckets["0_7_days"]["files"] == 1
    assert buckets["8_30_days"]["files"] == 1
    assert buckets["31_90_days"]["files"] == 1
    assert buckets["91_plus_days"]["files"] == 1
    assert profile["suggested_retention_days"] in {21, 30, 45, 60}
