from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


BUCKETS = (
    (0, 7, "0_7_days"),
    (8, 30, "8_30_days"),
    (31, 90, "31_90_days"),
    (91, 10_000, "91_plus_days"),
)


def _iter_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    return [p for p in path.rglob("*") if p.is_file() and p.name != ".gitkeep"]


def _age_days(path: Path, now: datetime) -> int:
    modified = datetime.utcfromtimestamp(path.stat().st_mtime)
    delta = now - modified
    return max(0, int(delta.total_seconds() // 86400))


def _bucket_for_age(days: int) -> str:
    for start, end, label in BUCKETS:
        if start <= days <= end:
            return label
    return "unknown"


def profile_sources(
    sources: list[str] | tuple[str, ...],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    anchor = now or datetime.utcnow()

    result_sources: list[dict[str, Any]] = []
    total_files = 0
    total_bytes = 0

    for source in sources:
        root = Path(source)
        bucket_stats = {label: {"files": 0, "bytes": 0} for _, _, label in BUCKETS}

        files = _iter_files(root)
        source_files = 0
        source_bytes = 0

        for file_path in files:
            size = int(file_path.stat().st_size)
            days = _age_days(file_path, anchor)
            bucket = _bucket_for_age(days)
            if bucket not in bucket_stats:
                bucket_stats[bucket] = {"files": 0, "bytes": 0}
            bucket_stats[bucket]["files"] += 1
            bucket_stats[bucket]["bytes"] += size
            source_files += 1
            source_bytes += size

        total_files += source_files
        total_bytes += source_bytes

        old_bytes = bucket_stats["31_90_days"]["bytes"] + bucket_stats["91_plus_days"]["bytes"]
        old_ratio = (old_bytes / source_bytes) if source_bytes > 0 else 0.0

        if source_bytes == 0:
            suggested_retention = 30
        elif old_ratio > 0.60:
            suggested_retention = 21
        elif old_ratio > 0.35:
            suggested_retention = 30
        elif old_ratio > 0.15:
            suggested_retention = 45
        else:
            suggested_retention = 60

        result_sources.append(
            {
                "source": str(root),
                "exists": root.exists(),
                "files": source_files,
                "bytes": source_bytes,
                "bucket_stats": bucket_stats,
                "old_bytes_ratio": old_ratio,
                "suggested_retention_days": suggested_retention,
            }
        )

    weighted_retention = 30
    if total_bytes > 0:
        weighted = sum(item["suggested_retention_days"] * item["bytes"] for item in result_sources)
        weighted_retention = int(round(weighted / total_bytes))

    return {
        "generated_at_utc": anchor.isoformat() + "Z",
        "sources": list(sources),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "suggested_global_retention_days": weighted_retention,
        "profiles": result_sources,
        "next_review_by_utc": (anchor + timedelta(days=7)).isoformat() + "Z",
    }
