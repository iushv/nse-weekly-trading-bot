from __future__ import annotations

import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return [p for p in root.rglob("*") if p.is_file()]


def _should_rotate(path: Path, cutoff: datetime) -> bool:
    mtime = datetime.utcfromtimestamp(path.stat().st_mtime)
    return mtime < cutoff


def _archive_target(archive_root: Path, source_root: Path, source_file: Path) -> Path:
    rel = source_file.relative_to(source_root)
    base = archive_root / source_root.name / rel
    if source_file.suffix.lower() == ".gz":
        return base
    return Path(str(base) + ".gz")


def _archive_file(source_file: Path, target_file: Path) -> None:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if source_file.suffix.lower() == ".gz":
        shutil.copy2(source_file, target_file)
        return

    with source_file.open("rb") as src, gzip.open(target_file, "wb") as dst:
        shutil.copyfileobj(src, dst)


def rotate_directory(
    source_dir: str | Path,
    *,
    archive_root: str | Path = "archive",
    retention_days: int = 30,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    source = Path(source_dir)
    archive = Path(archive_root)
    pivot = now or datetime.utcnow()
    cutoff = pivot - timedelta(days=max(0, int(retention_days)))

    summary: dict[str, Any] = {
        "source": str(source),
        "archive_root": str(archive),
        "retention_days": int(retention_days),
        "dry_run": bool(dry_run),
        "files_examined": 0,
        "files_rotated": 0,
        "files_failed": 0,
        "bytes_rotated": 0,
        "artifacts": [],
        "errors": [],
    }

    if not source.exists():
        return summary

    for file_path in _iter_files(source):
        summary["files_examined"] += 1

        if file_path.name == ".gitkeep":
            continue
        if not _should_rotate(file_path, cutoff):
            continue

        try:
            target = _archive_target(archive, source, file_path)
            size_bytes = int(file_path.stat().st_size)
            summary["artifacts"].append(
                {
                    "source": str(file_path),
                    "target": str(target),
                    "bytes": size_bytes,
                }
            )

            if not dry_run:
                _archive_file(file_path, target)
                file_path.unlink()

            summary["files_rotated"] += 1
            summary["bytes_rotated"] += size_bytes
        except Exception as exc:
            summary["files_failed"] += 1
            summary["errors"].append(f"{file_path}: {exc}")

    return summary


def rotate_many(
    sources: list[str] | tuple[str, ...],
    *,
    archive_root: str | Path = "archive",
    retention_days: int = 30,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    results = [
        rotate_directory(
            source,
            archive_root=archive_root,
            retention_days=retention_days,
            dry_run=dry_run,
            now=now,
        )
        for source in sources
    ]

    return {
        "generated_at_utc": (now or datetime.utcnow()).isoformat() + "Z",
        "sources": list(sources),
        "archive_root": str(archive_root),
        "retention_days": int(retention_days),
        "dry_run": bool(dry_run),
        "files_examined": sum(int(r["files_examined"]) for r in results),
        "files_rotated": sum(int(r["files_rotated"]) for r in results),
        "files_failed": sum(int(r["files_failed"]) for r in results),
        "bytes_rotated": sum(int(r["bytes_rotated"]) for r in results),
        "results": results,
    }
