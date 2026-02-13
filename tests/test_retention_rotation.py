from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from trading_bot.monitoring.retention import rotate_directory, rotate_many


def _set_mtime(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def test_rotate_directory_archives_old_files(tmp_path):
    source = tmp_path / "logs"
    source.mkdir(parents=True)
    archive = tmp_path / "archive"

    old_file = source / "old.log"
    old_file.write_text("old", encoding="utf-8")
    new_file = source / "new.log"
    new_file.write_text("new", encoding="utf-8")

    now = datetime(2026, 2, 11, 12, 0, 0)
    _set_mtime(old_file, now - timedelta(days=45))
    _set_mtime(new_file, now - timedelta(days=5))

    result = rotate_directory(source, archive_root=archive, retention_days=30, dry_run=False, now=now)

    assert result["files_examined"] == 2
    assert result["files_rotated"] == 1
    assert old_file.exists() is False
    assert new_file.exists() is True

    archived_file = archive / "logs" / "old.log.gz"
    assert archived_file.exists() is True


def test_rotate_many_dry_run_keeps_files(tmp_path):
    source = tmp_path / "reports" / "audits"
    source.mkdir(parents=True)
    archive = tmp_path / "archive"

    old_file = source / "weekly_audit_20260101.json"
    old_file.write_text("{}", encoding="utf-8")

    now = datetime(2026, 2, 11, 12, 0, 0)
    _set_mtime(old_file, now - timedelta(days=60))

    result = rotate_many([str(source)], archive_root=archive, retention_days=30, dry_run=True, now=now)

    assert result["files_examined"] == 1
    assert result["files_rotated"] == 1
    assert result["files_failed"] == 0
    assert old_file.exists() is True
    assert not (archive / "audits" / "weekly_audit_20260101.json.gz").exists()
