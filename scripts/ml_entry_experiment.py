from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FEATURE_COLUMNS: list[str] = [
    "weekly_rsi",
    "weekly_roc",
    "daily_rsi",
    "volume_ratio",
    "market_regime_confidence",
    "market_breadth_ratio",
    "expected_r_multiple",
    "confidence",
    "atr_pct",
    "stop_distance_pct",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return float(default)
        return out
    except (TypeError, ValueError):
        return float(default)


def _safe_bool_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return 1.0 if float(value) > 0 else 0.0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "up"}:
        return 1.0
    if text in {"0", "false", "no", "n", "down"}:
        return 0.0
    return float(default)


def _compute_auc(y_true: np.ndarray, probs: np.ndarray) -> float:
    y = y_true.astype(int)
    p = probs.astype(float)
    pos_count = int((y == 1).sum())
    neg_count = int((y == 0).sum())
    if pos_count == 0 or neg_count == 0:
        return 0.0
    order = np.argsort(p)
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1, dtype=float)
    rank_sum_pos = float(ranks[y == 1].sum())
    auc = (rank_sum_pos - (pos_count * (pos_count + 1) / 2.0)) / (pos_count * neg_count)
    return float(max(0.0, min(1.0, auc)))


def _binary_metrics(y_true: np.ndarray, probs: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    y = y_true.astype(int)
    pred = (probs >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    total = len(y)
    accuracy = float((tp + tn) / total) if total else 0.0
    precision = float(tp / (tp + fp)) if (tp + fp) else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) else 0.0
    return {
        "accuracy": accuracy,
        "auc": _compute_auc(y, probs),
        "precision": precision,
        "recall": recall,
    }


def _median_impute(x_train: np.ndarray, x_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    medians = np.nanmedian(x_train, axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)
    train_imp = np.where(np.isnan(x_train), medians, x_train)
    test_imp = np.where(np.isnan(x_test), medians, x_test)
    return train_imp, test_imp


def _standardize(x_train: np.ndarray, x_test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(x_train, axis=0)
    std = np.std(x_train, axis=0)
    std = np.where(std < 1e-9, 1.0, std)
    return ((x_train - mean) / std, (x_test - mean) / std)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -12.0, 12.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _fit_logistic_numpy(
    x: np.ndarray,
    y: np.ndarray,
    *,
    steps: int = 350,
    lr: float = 0.02,
    l2: float = 25.0,
) -> tuple[np.ndarray, float]:
    weights = np.zeros(x.shape[1], dtype=float)
    bias = 0.0
    n = max(1, len(y))
    yv = y.astype(float)

    for _ in range(steps):
        logits = x @ weights + bias
        probs = _sigmoid(logits)
        err = probs - yv
        grad_w = (x.T @ err) / n + (l2 * weights / n)
        grad_b = float(err.mean())
        weights -= lr * grad_w
        bias -= lr * grad_b
    return weights, bias


def _predict_logistic_numpy(x: np.ndarray, weights: np.ndarray, bias: float) -> np.ndarray:
    return _sigmoid(x @ weights + bias)


def extract_feature_row(trade: dict[str, Any]) -> dict[str, Any]:
    metadata = trade.get("metadata", {}) if isinstance(trade.get("metadata"), dict) else {}
    entry_price = _safe_float(trade.get("entry_price"), 0.0)
    stop_loss = _safe_float(trade.get("stop_loss"), 0.0)
    weekly_atr = _safe_float(metadata.get("weekly_atr"), 0.0)
    expected_r = _safe_float(metadata.get("expected_r_multiple"), 0.0)

    atr_pct = (weekly_atr / entry_price) if entry_price > 0 else 0.0
    stop_distance_pct = ((entry_price - stop_loss) / entry_price) if entry_price > 0 else 0.0

    return {
        "symbol": str(trade.get("symbol", "")),
        "entry_date": str(trade.get("entry_date", "")),
        "exit_reason": str(trade.get("exit_reason", "UNKNOWN")),
        "net_pnl": _safe_float(trade.get("net_pnl"), 0.0),
        "weekly_rsi": _safe_float(metadata.get("weekly_rsi"), 0.0),
        "weekly_roc": _safe_float(metadata.get("weekly_roc"), 0.0),
        "daily_rsi": _safe_float(metadata.get("daily_rsi"), 0.0),
        "volume_ratio": _safe_float(metadata.get("volume_ratio"), 0.0),
        "market_regime_confidence": _safe_float(
            metadata.get("market_regime_confidence", metadata.get("regime_confidence", 0.5)),
            0.5,
        ),
        "market_breadth_ratio": _safe_float(
            metadata.get("market_breadth_ratio", metadata.get("regime_breadth_ratio", 0.0)),
            0.0,
        ),
        "confidence": _safe_float(trade.get("confidence"), 0.0),
        "expected_r_multiple": expected_r,
        "atr_pct": _safe_float(atr_pct, 0.0),
        "stop_distance_pct": _safe_float(stop_distance_pct, 0.0),
        "outcome_label": 1 if _safe_float(trade.get("net_pnl"), 0.0) > 0 else 0,
    }


def build_training_frame(trades: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [extract_feature_row(item) for item in trades if isinstance(item, dict)]
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    for col in FEATURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = 0.0
    return frame


def _build_lgbm_classifier() -> Any:
    try:
        from lightgbm import LGBMClassifier
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing dependency: lightgbm. Install requirements and rerun.") from exc
    return LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        num_leaves=4,
        max_depth=3,
        min_child_samples=10,
        subsample=0.8,
        feature_fraction=0.8,
        reg_alpha=1.0,
        reg_lambda=1.0,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=-1,
    )


def _describe(values: np.ndarray) -> dict[str, float]:
    if len(values) == 0:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p90": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": int(len(values)),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p90": float(np.quantile(values, 0.90)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def _summarize_keep_mask(
    *,
    pnl: np.ndarray,
    keep: np.ndarray,
    stop_loss_mask: np.ndarray,
    trailing_winner_mask: np.ndarray,
    min_trades_kept: int,
) -> dict[str, Any]:
    kept_pnl = pnl[keep]
    sim_pnl = float(kept_pnl.sum()) if len(kept_pnl) else 0.0
    win_sum = float(kept_pnl[kept_pnl > 0].sum()) if len(kept_pnl) else 0.0
    loss_sum_abs = abs(float(kept_pnl[kept_pnl < 0].sum())) if len(kept_pnl) else 0.0
    if loss_sum_abs > 0:
        sim_pf = win_sum / loss_sum_abs
    elif win_sum > 0:
        sim_pf = 99.0
    else:
        sim_pf = 0.0
    return {
        "trades_kept": int(keep.sum()),
        "trades_rejected": int((~keep).sum()),
        "simulated_pnl": sim_pnl,
        "simulated_pf": float(sim_pf),
        "stop_loss_rejected": int((stop_loss_mask & (~keep)).sum()),
        "trailing_winners_rejected": int((trailing_winner_mask & (~keep)).sum()),
        "meets_min_trades": bool(int(keep.sum()) >= int(min_trades_kept)),
    }


def run_simple_rule_baseline(frame: pd.DataFrame, *, min_trades_kept: int) -> dict[str, Any]:
    if frame.empty:
        return {"rules": [], "best_rule": {}, "feature_distributions": {}}

    pnl = frame["net_pnl"].astype(float).to_numpy()
    exit_reason = frame["exit_reason"].astype(str).to_numpy()
    stop_loss_mask = exit_reason == "STOP_LOSS"
    trailing_winner_mask = (exit_reason == "TRAILING_STOP") & (pnl > 0)

    feature_distributions: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for feature in ("atr_pct", "stop_distance_pct"):
        values = frame[feature].astype(float).to_numpy()
        feature_distributions[feature] = {
            "stop_loss": _describe(values[stop_loss_mask]),
            "non_stop_loss": _describe(values[~stop_loss_mask]),
        }
        quantiles = np.quantile(values, [0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95])
        thresholds = sorted({round(float(q), 6) for q in quantiles if np.isfinite(q)})
        for threshold in thresholds:
            keep = values <= threshold
            summary = _summarize_keep_mask(
                pnl=pnl,
                keep=keep,
                stop_loss_mask=stop_loss_mask,
                trailing_winner_mask=trailing_winner_mask,
                min_trades_kept=min_trades_kept,
            )
            rows.append(
                {
                    "rule": f"reject_if_{feature}_gt",
                    "feature": feature,
                    "threshold": threshold,
                    **summary,
                }
            )

    if rows:
        eligible = [item for item in rows if bool(item["meets_min_trades"])]
        best = max(
            eligible if eligible else rows,
            key=lambda item: (float(item["simulated_pnl"]), float(item["simulated_pf"])),
        )
    else:
        best = {}
    return {"rules": rows, "best_rule": best, "feature_distributions": feature_distributions}


def run_loocv_predictions(frame: pd.DataFrame) -> tuple[np.ndarray, dict[str, float], str]:
    if frame.empty:
        raise SystemExit("No training rows found in trades file.")
    if frame["outcome_label"].nunique() < 2:
        raise SystemExit("Need both positive and negative outcomes for classification.")

    x = frame[FEATURE_COLUMNS].astype(float).to_numpy()
    y = frame["outcome_label"].astype(int).to_numpy()
    probs = np.zeros(len(frame), dtype=float)

    has_sklearn = importlib.util.find_spec("sklearn") is not None
    has_lightgbm = importlib.util.find_spec("lightgbm") is not None
    use_lgbm = has_sklearn and has_lightgbm
    backend = "lightgbm" if use_lgbm else "logistic_numpy_fallback"

    if use_lgbm:
        from sklearn.impute import SimpleImputer

        for idx in range(len(frame)):
            train_mask = np.ones(len(frame), dtype=bool)
            train_mask[idx] = False

            x_train = x[train_mask]
            y_train = y[train_mask]
            x_test = x[~train_mask]

            imputer = SimpleImputer(strategy="median")
            x_train_imp = imputer.fit_transform(x_train)
            x_test_imp = imputer.transform(x_test)

            model = _build_lgbm_classifier()
            model.fit(x_train_imp, y_train)
            probs[idx] = float(model.predict_proba(x_test_imp)[0][1])
    else:
        for idx in range(len(frame)):
            train_mask = np.ones(len(frame), dtype=bool)
            train_mask[idx] = False
            x_train = x[train_mask]
            y_train = y[train_mask]
            x_test = x[~train_mask]
            x_train_imp, x_test_imp = _median_impute(x_train, x_test)
            x_train_std, x_test_std = _standardize(x_train_imp, x_test_imp)
            w, b = _fit_logistic_numpy(x_train_std, y_train)
            probs[idx] = float(_predict_logistic_numpy(x_test_std, w, b)[0])

    metrics = _binary_metrics(y, probs, threshold=0.5)
    return probs, metrics, backend


def run_threshold_sweep(
    frame: pd.DataFrame,
    probs: np.ndarray,
    *,
    threshold_start: float,
    threshold_end: float,
    threshold_step: float,
    min_trades_kept: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if frame.empty:
        return [], {}

    thresholds = np.arange(threshold_start, threshold_end + 1e-9, threshold_step)
    pnl = frame["net_pnl"].astype(float).to_numpy()
    exit_reason = frame["exit_reason"].astype(str).to_numpy()
    stop_loss_mask = exit_reason == "STOP_LOSS"
    trailing_winner_mask = (exit_reason == "TRAILING_STOP") & (pnl > 0)

    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        keep = probs >= float(threshold)
        row = _summarize_keep_mask(
            pnl=pnl,
            keep=keep,
            stop_loss_mask=stop_loss_mask,
            trailing_winner_mask=trailing_winner_mask,
            min_trades_kept=min_trades_kept,
        )
        row["threshold"] = round(float(threshold), 4)
        rows.append(row)

    eligible = [r for r in rows if bool(r["meets_min_trades"])]
    if eligible:
        best = max(eligible, key=lambda item: (float(item["simulated_pnl"]), float(item["simulated_pf"])))
    else:
        best = max(rows, key=lambda item: float(item["simulated_pnl"]))
    return rows, best


def evaluate_threshold_at(
    frame: pd.DataFrame,
    probs: np.ndarray,
    *,
    threshold: float,
    min_trades_kept: int,
) -> dict[str, Any]:
    pnl = frame["net_pnl"].astype(float).to_numpy()
    exit_reason = frame["exit_reason"].astype(str).to_numpy()
    stop_loss_mask = exit_reason == "STOP_LOSS"
    trailing_winner_mask = (exit_reason == "TRAILING_STOP") & (pnl > 0)
    keep = probs >= float(threshold)
    out = _summarize_keep_mask(
        pnl=pnl,
        keep=keep,
        stop_loss_mask=stop_loss_mask,
        trailing_winner_mask=trailing_winner_mask,
        min_trades_kept=min_trades_kept,
    )
    out["threshold"] = round(float(threshold), 4)
    return out


def compute_feature_importance(frame: pd.DataFrame, *, backend: str) -> list[dict[str, Any]]:
    x = frame[FEATURE_COLUMNS].astype(float).to_numpy()
    y = frame["outcome_label"].astype(int).to_numpy()
    if backend == "lightgbm":
        from sklearn.impute import SimpleImputer

        model = _build_lgbm_classifier()
        imputer = SimpleImputer(strategy="median")
        x_imp = imputer.fit_transform(x)
        model.fit(x_imp, y)
        importance = getattr(model, "feature_importances_", np.zeros(len(FEATURE_COLUMNS)))
    else:
        x_imp, _ = _median_impute(x, x)
        x_std, _ = _standardize(x_imp, x_imp)
        w, _ = _fit_logistic_numpy(x_std, y)
        importance = np.abs(w)

    pairs = [
        {"feature": feature, "importance": float(score)}
        for feature, score in zip(FEATURE_COLUMNS, importance)
    ]
    return sorted(pairs, key=lambda item: float(item["importance"]), reverse=True)


def evaluate_decision_checks(*, auc: float, threshold_result: dict[str, Any]) -> dict[str, bool]:
    return {
        "stop_loss_rejected_at_least_2": int(threshold_result.get("stop_loss_rejected", 0)) >= 2,
        "incorrectly_rejected_winners_at_most_3": int(threshold_result.get("trailing_winners_rejected", 0)) <= 3,
        "simulated_pnl_positive": float(threshold_result.get("simulated_pnl", 0.0)) > 0.0,
        "auc_above_0_55": float(auc) > 0.55,
        "trades_kept_at_least_min": bool(threshold_result.get("meets_min_trades", False)),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quick LOOCV ML entry scoring experiment on backtest trades.")
    parser.add_argument("--trades-file", required=True, help="Backtest JSON containing trades (run_universe_backtest --include-trades)")
    parser.add_argument("--threshold-start", type=float, default=0.30)
    parser.add_argument("--threshold-end", type=float, default=0.70)
    parser.add_argument("--threshold-step", type=float, default=0.05)
    parser.add_argument("--min-trades-kept", type=int, default=35)
    parser.add_argument("--out", default="", help="Optional output JSON path")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _default_out_path() -> Path:
    out_dir = ROOT / "reports" / "ml"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"ml_entry_experiment_{stamp}.json"


def main() -> int:
    args = _build_parser().parse_args()
    trades_path = Path(args.trades_file)
    if not trades_path.is_absolute():
        trades_path = ROOT / trades_path
    if not trades_path.exists():
        raise SystemExit(f"Trades file not found: {trades_path}")

    payload = json.loads(trades_path.read_text(encoding="utf-8"))
    trades = payload.get("trades", [])
    if not isinstance(trades, list) or not trades:
        raise SystemExit(f"Trades file has no trades list: {trades_path}")

    frame = build_training_frame(trades)
    simple_rule_baseline = run_simple_rule_baseline(frame, min_trades_kept=int(args.min_trades_kept))
    probs, loocv_metrics, backend = run_loocv_predictions(frame)
    threshold_rows, best_threshold = run_threshold_sweep(
        frame,
        probs,
        threshold_start=float(args.threshold_start),
        threshold_end=float(args.threshold_end),
        threshold_step=float(args.threshold_step),
        min_trades_kept=int(args.min_trades_kept),
    )
    fixed_threshold = evaluate_threshold_at(
        frame,
        probs,
        threshold=0.5,
        min_trades_kept=int(args.min_trades_kept),
    )

    best_cut = float(best_threshold.get("threshold", 0.5))
    keep_best = probs >= best_cut
    keep_fixed = probs >= 0.5
    stop_loss_mask = frame["exit_reason"].astype(str) == "STOP_LOSS"
    trailing_winner_mask = (frame["exit_reason"].astype(str) == "TRAILING_STOP") & (frame["net_pnl"].astype(float) > 0)
    stop_loss_correct_best = int((stop_loss_mask.to_numpy() & (~keep_best)).sum())
    trailing_winners_rejected_best = int((trailing_winner_mask.to_numpy() & (~keep_best)).sum())
    stop_loss_correct_fixed = int((stop_loss_mask.to_numpy() & (~keep_fixed)).sum())
    trailing_winners_rejected_fixed = int((trailing_winner_mask.to_numpy() & (~keep_fixed)).sum())

    stop_loss_details = frame.loc[stop_loss_mask, ["symbol", "entry_date", "exit_reason", "net_pnl"]].copy()
    stop_loss_details["predicted_prob"] = probs[stop_loss_mask.to_numpy()]
    stop_loss_details["rejected_at_best_swept"] = (~keep_best)[stop_loss_mask.to_numpy()]
    stop_loss_details["rejected_at_fixed_0_5"] = (~keep_fixed)[stop_loss_mask.to_numpy()]

    winner_details = frame.loc[trailing_winner_mask, ["symbol", "entry_date", "exit_reason", "net_pnl"]].copy()
    winner_details["predicted_prob"] = probs[trailing_winner_mask.to_numpy()]
    winner_details["rejected_at_best_swept"] = (~keep_best)[trailing_winner_mask.to_numpy()]
    winner_details["rejected_at_fixed_0_5"] = (~keep_fixed)[trailing_winner_mask.to_numpy()]

    per_trade = frame[["symbol", "entry_date", "exit_reason", "net_pnl"]].copy()
    per_trade["predicted_prob"] = probs
    per_trade["predicted_label"] = (probs >= 0.5).astype(int)
    per_trade["kept_at_best_threshold"] = keep_best.astype(bool)

    checks_best = evaluate_decision_checks(auc=float(loocv_metrics.get("auc", 0.0)), threshold_result=best_threshold)
    checks_fixed = evaluate_decision_checks(auc=float(loocv_metrics.get("auc", 0.0)), threshold_result=fixed_threshold)
    pass_best = all(bool(v) for v in checks_best.values())
    pass_fixed = all(bool(v) for v in checks_fixed.values())
    decision = "PASS" if pass_fixed else "FAIL"
    decision_reason = (
        "fixed_threshold_0_5_passed"
        if pass_fixed
        else ("sweep_only_passed_overfit_risk" if pass_best else "both_failed")
    )

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "trades_file": str(trades_path),
        "sample_size": int(len(frame)),
        "model_backend": backend,
        "feature_columns": FEATURE_COLUMNS,
        "simple_rule_baseline": simple_rule_baseline,
        "loocv_metrics": loocv_metrics,
        "per_trade_predictions": per_trade.to_dict(orient="records"),
        "stop_loss_filtering": {
            "total_stop_loss_trades": int(stop_loss_mask.sum()),
            "correctly_rejected_at_best_swept": int(stop_loss_correct_best),
            "correctly_rejected_at_fixed_0_5": int(stop_loss_correct_fixed),
            "details": stop_loss_details.to_dict(orient="records"),
        },
        "winner_retention": {
            "total_trailing_stop_trades": int(trailing_winner_mask.sum()),
            "incorrectly_rejected_at_best_swept": int(trailing_winners_rejected_best),
            "incorrectly_rejected_at_fixed_0_5": int(trailing_winners_rejected_fixed),
            "details": winner_details.to_dict(orient="records"),
        },
        "threshold_sweep": threshold_rows,
        "best_threshold": best_threshold,
        "best_swept_threshold": best_threshold,
        "fixed_threshold_0_5": fixed_threshold,
        "feature_importance": compute_feature_importance(frame, backend=backend),
        "decision_checks": {
            "optimistic_best_swept": checks_best,
            "conservative_fixed_0_5": checks_fixed,
        },
        "decision_reason": decision_reason,
        "decision": decision,
    }

    out_path = Path(args.out) if args.out else _default_out_path()
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    if args.pretty:
        print(json.dumps(out, indent=2))
    else:
        print(json.dumps({"decision": out["decision"], "best_threshold": out["best_threshold"]}))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
