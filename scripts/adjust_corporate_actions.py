from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading_bot.config.settings import Config
from trading_bot.data.collectors.market_data import MarketDataCollector
from trading_bot.data.storage.database import Database


def _load_universe(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").splitlines()
    symbols = [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]
    return [symbol.replace(".NS", "").upper() for symbol in symbols]


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _sqlite_path_from_url(url: str) -> Path:
    text = str(url).strip()
    if text.startswith("sqlite:///"):
        return Path(text.replace("sqlite:///", "", 1))
    return Path("trading_bot.db")


def _json_dump(payload: dict, *, pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, indent=2)
    return json.dumps(payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect and adjust split/bonus corporate actions in price_data")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--universe-file", required=True, help="Universe symbols file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Detect only; no database writes")
    mode.add_argument("--apply", action="store_true", help="Detect and apply to a DB copy")
    mode.add_argument("--verify-only", action="store_true", help="Only verify remaining overnight jumps")
    parser.add_argument("--source-db", default="", help="Source sqlite DB path (default from Config.DATABASE_URL)")
    parser.add_argument("--work-db", default="", help="Adjusted DB output path for --apply / verify target")
    parser.add_argument(
        "--approval-manifest",
        default="",
        help="JSON manifest with actions[].approve=true entries to force-apply in --apply mode",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="When used with --approval-manifest and --apply, only apply approved manifest actions (skip auto-apply).",
    )
    parser.add_argument("--out", default="", help="Optional JSON artifact path")
    parser.add_argument("--force-overwrite", action="store_true", help="Overwrite --work-db if it exists")
    parser.add_argument(
        "--detect-threshold",
        type=float,
        default=float(Config.CORPORATE_ACTION_DETECT_THRESHOLD),
        help="Detection threshold on |factor-1|",
    )
    parser.add_argument(
        "--apply-threshold",
        type=float,
        default=float(Config.CORPORATE_ACTION_APPLY_THRESHOLD),
        help="Minimum |factor-1| required to apply split/bonus adjustments",
    )
    parser.add_argument(
        "--verify-threshold",
        type=float,
        default=float(Config.CORPORATE_ACTION_VERIFY_JUMP_THRESHOLD),
        help="Overnight jump threshold for verify mode",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print output JSON")
    return parser


def _default_out_path(mode: str, *, start: str, end: str) -> Path:
    out_dir = ROOT / "reports" / "data_quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"corporate_actions_{mode}_{start.replace('-', '')}_{end.replace('-', '')}_{stamp}.json"


def _resolve_db_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    source = Path(args.source_db).expanduser() if args.source_db else _sqlite_path_from_url(Config.DATABASE_URL)
    source = source if source.is_absolute() else (ROOT / source)
    work_raw = args.work_db if args.work_db else "trading_bot_adjusted.db"
    work = Path(work_raw).expanduser()
    work = work if work.is_absolute() else (ROOT / work)
    return source, work


def _clean_symbol(value: str) -> str:
    return str(value).replace(".NS", "").upper().strip()


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _load_approval_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    actions = payload.get("actions", [])
    approved: list[dict[str, Any]] = []
    invalid_count = 0
    for item in actions if isinstance(actions, list) else []:
        if not isinstance(item, dict):
            invalid_count += 1
            continue
        if not bool(item.get("approve", False)):
            continue
        symbol = _clean_symbol(item.get("symbol", ""))
        action_date = str(item.get("action_date", "")).strip()
        confirmed_type = str(item.get("confirmed_type", item.get("action_type", "unknown"))).strip().lower()
        raw_factor = item.get("adjustment_factor")
        if raw_factor is None:
            invalid_count += 1
            continue
        try:
            factor = float(cast(float | int | str, raw_factor))
        except (TypeError, ValueError):
            invalid_count += 1
            continue
        if not symbol or not action_date or factor <= 0:
            invalid_count += 1
            continue
        approved.append(
            {
                "symbol": symbol,
                "action_date": action_date,
                "action_type": confirmed_type or "unknown",
                "adjustment_factor": factor,
                "manifest_notes": str(item.get("notes", "")).strip(),
                "manifest_evidence": str(item.get("evidence", "")).strip(),
            }
        )
    return {
        "approved_actions": approved,
        "approved_count": len(approved),
        "total_actions": len(actions) if isinstance(actions, list) else 0,
        "invalid_or_skipped_entries": int(invalid_count),
    }


def _apply_manifest_actions(
    *,
    db: Database,
    pending_actions: list[dict[str, Any]],
    approved_actions: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    pending_by_key = {
        (_clean_symbol(item.get("symbol", "")), str(item.get("action_date", ""))): dict(item)
        for item in pending_actions
        if isinstance(item, dict)
    }
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for approved in approved_actions:
        key = (_clean_symbol(approved.get("symbol", "")), str(approved.get("action_date", "")))
        base = pending_by_key.get(key)
        if base is None:
            unmatched.append(dict(approved))
            continue
        merged = dict(base)
        merged["action_type"] = str(approved.get("action_type", merged.get("action_type", "unknown")))
        merged["adjustment_factor"] = float(approved.get("adjustment_factor", merged.get("adjustment_factor", 1.0)))
        merged["approval_source"] = "manifest"
        merged["manifest_notes"] = str(approved.get("manifest_notes", ""))
        merged["manifest_evidence"] = str(approved.get("manifest_evidence", ""))
        matched.append(merged)

    matched = sorted(matched, key=lambda item: (str(item.get("action_date", "")), str(item.get("symbol", ""))))
    summary: dict[str, Any] = {
        "approved_in_manifest": len(approved_actions),
        "matched_pending": len(matched),
        "unmatched": len(unmatched),
        "applied": 0,
        "rows_updated": 0,
        "unmatched_actions": unmatched,
        "applied_actions": [],
    }
    for action in matched:
        if dry_run:
            summary["applied_actions"].append({**action, "rows_updated": 0})
            continue
        db.upsert_corporate_actions(
            [
                {
                    "symbol": str(action.get("symbol", "")),
                    "action_date": str(action.get("action_date", "")),
                    "action_type": str(action.get("action_type", "unknown")),
                    "prev_close_db": action.get("prev_close_db"),
                    "prev_close_exchange": action.get("prev_close_exchange"),
                    "adjustment_factor": float(action.get("adjustment_factor", 1.0)),
                    "face_val_before": action.get("face_val_before"),
                    "face_val_after": action.get("face_val_after"),
                    "applied": 1,
                }
            ]
        )
        rows = db.apply_backward_adjustment(
            symbol=str(action.get("symbol", "")),
            action_date=str(action.get("action_date", "")),
            adjustment_factor=float(action.get("adjustment_factor", 1.0)),
        )
        db.mark_corporate_action_applied(
            symbol=str(action.get("symbol", "")),
            action_date=str(action.get("action_date", "")),
        )
        summary["applied"] = int(summary["applied"]) + 1
        summary["rows_updated"] = int(summary["rows_updated"]) + int(rows)
        summary["applied_actions"].append({**action, "rows_updated": int(rows)})
    return summary


def main() -> int:
    args = _build_parser().parse_args()
    start_date = _parse_date(args.start)
    end_date = _parse_date(args.end)
    if end_date < start_date:
        raise SystemExit("--end must be >= --start")

    universe_path = Path(args.universe_file)
    if not universe_path.is_absolute():
        universe_path = ROOT / universe_path
    symbols = _load_universe(universe_path)
    if not symbols:
        raise SystemExit(f"Universe file had no symbols: {universe_path}")

    source_db_path, work_db_path = _resolve_db_paths(args)
    if args.verify_only and not args.source_db and args.work_db:
        source_db_path = work_db_path
    if not source_db_path.exists():
        raise SystemExit(f"Source DB not found: {source_db_path}")
    manifest_info: dict | None = None
    if args.approval_manifest:
        manifest_path = Path(args.approval_manifest)
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        if not manifest_path.exists():
            raise SystemExit(f"Approval manifest not found: {manifest_path}")
        manifest_info = _load_approval_manifest(manifest_path)
        manifest_info["path"] = str(manifest_path)

    mode = "dry_run" if args.dry_run else "apply" if args.apply else "verify_only"
    target_db_path = source_db_path
    if args.apply:
        if source_db_path.resolve() == work_db_path.resolve():
            raise SystemExit("--work-db must be different from --source-db")
        if work_db_path.exists():
            if not args.force_overwrite:
                raise SystemExit(f"Work DB already exists: {work_db_path} (use --force-overwrite to replace)")
            work_db_path.unlink()
        work_db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_db_path, work_db_path)
        target_db_path = work_db_path

    work_db = Database(f"sqlite:///{target_db_path}")
    work_db.init_db()
    collector = MarketDataCollector(database=work_db)

    payload: dict = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "mode": mode,
        "range": {"start": str(start_date), "end": str(end_date)},
        "universe_file": str(universe_path),
        "symbols": len(symbols),
        "db": {
            "source": str(source_db_path),
            "target": str(target_db_path),
            "copied_for_apply": bool(args.apply),
        },
        "thresholds": {
            "detect": float(args.detect_threshold),
            "apply": float(args.apply_threshold),
            "verify": float(args.verify_threshold),
        },
    }
    if manifest_info is not None:
        payload["manifest"] = {
            "path": manifest_info.get("path", ""),
            "total_actions": int(manifest_info.get("total_actions", 0)),
            "approved_count": int(manifest_info.get("approved_count", 0)),
            "invalid_or_skipped_entries": int(manifest_info.get("invalid_or_skipped_entries", 0)),
            "manifest_only": bool(args.manifest_only),
        }

    if args.verify_only:
        warnings = collector.scan_overnight_jumps(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            threshold_pct=float(args.verify_threshold),
        )
        payload["verify"] = {
            "warning_count": len(warnings),
            "warnings": warnings,
        }
    else:
        detected_actions = collector.detect_corporate_actions_for_range(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            detect_threshold=float(args.detect_threshold),
        )
        type_counts = Counter(str(item.get("action_type", "unknown")) for item in detected_actions)
        auto_eligible = [
            action
            for action in detected_actions
            if collector.should_auto_apply_action(action, apply_threshold=float(args.apply_threshold))
        ]
        payload["detection"] = {
            "detected_count": len(detected_actions),
            "type_counts": dict(type_counts),
            "auto_apply_eligible_count": len(auto_eligible),
            "sample_actions": detected_actions[:25],
        }

        if args.apply:
            work_db.upsert_corporate_actions(detected_actions)
            pending_initial = work_db.list_corporate_actions(
                start_date=str(start_date),
                end_date=str(end_date),
                symbols=symbols,
                applied=0,
            )
            manifest_apply_summary: dict[str, Any] = {
                "approved_in_manifest": 0,
                "matched_pending": 0,
                "unmatched": 0,
                "applied": 0,
                "rows_updated": 0,
                "unmatched_actions": [],
                "applied_actions": [],
            }
            if manifest_info is not None and manifest_info.get("approved_actions"):
                manifest_apply_summary = _apply_manifest_actions(
                    db=work_db,
                    pending_actions=pending_initial,
                    approved_actions=list(manifest_info.get("approved_actions", [])),
                    dry_run=False,
                )

            auto_apply_summary: dict[str, Any] = {
                "detected": 0,
                "eligible": 0,
                "applied": 0,
                "rows_updated": 0,
                "skipped": 0,
                "applied_actions": [],
                "skipped_actions": [],
            }
            if not args.manifest_only:
                pending_after_manifest = work_db.list_corporate_actions(
                    start_date=str(start_date),
                    end_date=str(end_date),
                    symbols=symbols,
                    applied=0,
                )
                auto_apply_summary = collector.apply_corporate_actions(
                    pending_after_manifest,
                    dry_run=False,
                    apply_threshold=float(args.apply_threshold),
                )

            apply_summary = {
                "detected": int(len(pending_initial)),
                "eligible": _to_int(manifest_apply_summary.get("matched_pending", 0))
                + _to_int(auto_apply_summary.get("eligible", 0)),
                "applied": _to_int(manifest_apply_summary.get("applied", 0))
                + _to_int(auto_apply_summary.get("applied", 0)),
                "rows_updated": _to_int(manifest_apply_summary.get("rows_updated", 0))
                + _to_int(auto_apply_summary.get("rows_updated", 0)),
                "skipped": int(
                    max(
                        0,
                        len(pending_initial)
                        - _to_int(manifest_apply_summary.get("applied", 0))
                        - _to_int(auto_apply_summary.get("applied", 0)),
                    )
                ),
                "manifest_apply": manifest_apply_summary,
                "auto_apply": auto_apply_summary,
            }
            verify_warnings = collector.scan_overnight_jumps(
                start_date=start_date,
                end_date=end_date,
                symbols=symbols,
                threshold_pct=float(args.verify_threshold),
            )
            payload["apply"] = apply_summary
            payload["verify"] = {
                "warning_count": len(verify_warnings),
                "warnings": verify_warnings,
            }

    out_path = Path(args.out) if args.out else _default_out_path(mode, start=args.start, end=args.end)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_json_dump(payload, pretty=True), encoding="utf-8")
    print(_json_dump(payload, pretty=args.pretty))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
