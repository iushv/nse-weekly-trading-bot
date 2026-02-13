from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKTEST_DIR = ROOT / "reports" / "backtests"
DEFAULT_LEDGER = BACKTEST_DIR / "experiment_ledger.csv"
LATEST_MULTI = BACKTEST_DIR / "latest_multi_week_gate_search.json"
LATEST_STRUCTURAL = BACKTEST_DIR / "latest_structural_gate_sweep.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _pick_best_multi(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    if not results:
        return {}
    return results[0] if isinstance(results[0], dict) else {}


def _pick_best_structural(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results", []) if isinstance(payload.get("results"), list) else []
    if not results:
        return {}
    return results[0] if isinstance(results[0], dict) else {}


def _best_worst_anchor(anchors: list[dict[str, Any]]) -> tuple[str, float, str, float]:
    if not anchors:
        return "", 0.0, "", 0.0
    best = max(anchors, key=lambda a: float(a.get("metrics", {}).get("total_return_pct", 0.0)))
    worst = min(anchors, key=lambda a: float(a.get("metrics", {}).get("total_return_pct", 0.0)))
    return (
        str(best.get("anchor", "")),
        float(best.get("metrics", {}).get("total_return_pct", 0.0)),
        str(worst.get("anchor", "")),
        float(worst.get("metrics", {}).get("total_return_pct", 0.0)),
    )


def _sum_closed_trades(anchors: list[dict[str, Any]]) -> int:
    total = 0
    for anchor in anchors:
        total += int(anchor.get("metrics", {}).get("closed_trades", 0))
    return total


def _collect_failed_gates(anchors: list[dict[str, Any]]) -> str:
    failures: list[str] = []
    for anchor in anchors:
        anchor_date = str(anchor.get("anchor", ""))
        ready = bool(anchor.get("ready_for_live", False))
        if ready:
            continue
        metrics = anchor.get("metrics", {}) if isinstance(anchor.get("metrics"), dict) else {}
        sharpe = float(metrics.get("sharpe_ratio", 0.0))
        win_rate = float(metrics.get("win_rate", 0.0))
        trades = int(metrics.get("closed_trades", 0))
        max_dd = abs(float(metrics.get("max_drawdown", 0.0)))
        if sharpe < 0.7:
            failures.append(f"{anchor_date}:sharpe")
        if win_rate < 0.5:
            failures.append(f"{anchor_date}:win_rate")
        if trades < 10:
            failures.append(f"{anchor_date}:closed_trades")
        if max_dd > 0.15:
            failures.append(f"{anchor_date}:max_drawdown")
    return ",".join(failures)


def _top_exit_reason(anchors: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for anchor in anchors:
        exit_analysis = anchor.get("exit_analysis", {}) if isinstance(anchor.get("exit_analysis"), dict) else {}
        breakdown = (
            exit_analysis.get("exit_reason_breakdown", {})
            if isinstance(exit_analysis.get("exit_reason_breakdown"), dict)
            else {}
        )
        for reason, value in breakdown.items():
            counts[str(reason)] = counts.get(str(reason), 0) + int(value)
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _build_row(
    multi_payload: dict[str, Any],
    structural_payload: dict[str, Any],
    decision: str,
    reject_reason: str,
    notes: str,
) -> dict[str, Any]:
    best_multi = _pick_best_multi(multi_payload)
    best_structural = _pick_best_structural(structural_payload)
    combo = best_multi.get("combo", {}) if isinstance(best_multi.get("combo"), dict) else {}
    anchors = best_multi.get("anchors", []) if isinstance(best_multi.get("anchors"), list) else []
    best_anchor, best_ret, worst_anchor, worst_ret = _best_worst_anchor(anchors)

    return {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "multi_week_artifact": str(multi_payload.get("generated_at_utc", "")),
        "structural_artifact": str(structural_payload.get("generated_at_utc", "")),
        "strategy_profile": str(combo.get("strategy_profile", "")),
        "regime_filter": str(combo.get("regime_filter", "")),
        "max_signals_per_day": str(combo.get("max_signals_per_day", "")),
        "min_expected_edge_pct": str(combo.get("min_expected_edge_pct", "")),
        "anchors_passed": int(best_multi.get("anchors_passed", 0)),
        "all_anchors_passed": bool(best_multi.get("all_anchors_passed", False)),
        "best_anchor": best_anchor,
        "best_anchor_return_pct": best_ret,
        "worst_anchor": worst_anchor,
        "worst_anchor_return_pct": worst_ret,
        "closed_trades_total": _sum_closed_trades(anchors),
        "failed_gates": _collect_failed_gates(anchors),
        "top_exit_reason": _top_exit_reason(anchors),
        "structural_ready_for_live": bool(best_structural.get("ready_for_live", False)),
        "decision": decision,
        "reject_reason": reject_reason,
        "notes": notes,
    }


def _write_row(ledger_path: Path, row: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(row.keys())
    exists = ledger_path.exists()
    with ledger_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append a row to experiment ledger from latest sweep artifacts.")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--decision", default="reject", choices=["adopt", "reject"])
    parser.add_argument("--reject-reason", default="")
    parser.add_argument("--notes", default="")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    multi_payload = _load_json(LATEST_MULTI)
    structural_payload = _load_json(LATEST_STRUCTURAL)
    row = _build_row(
        multi_payload=multi_payload,
        structural_payload=structural_payload,
        decision=args.decision,
        reject_reason=args.reject_reason,
        notes=args.notes,
    )
    ledger_path = Path(args.ledger).resolve()
    _write_row(ledger_path, row)
    print(f"Appended ledger row: {ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

