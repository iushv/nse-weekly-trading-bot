from __future__ import annotations

import numpy as np

from scripts.ml_entry_experiment import (
    FEATURE_COLUMNS,
    build_training_frame,
    evaluate_threshold_at,
    extract_feature_row,
    run_simple_rule_baseline,
    run_threshold_sweep,
)


def test_extract_feature_row_derives_expected_fields() -> None:
    trade = {
        "symbol": "ABC",
        "entry_date": "2025-10-10",
        "exit_reason": "STOP_LOSS",
        "entry_price": 100.0,
        "stop_loss": 94.0,
        "confidence": 0.72,
        "net_pnl": -250.0,
        "metadata": {
            "weekly_atr": 5.0,
            "weekly_rsi": 62.0,
            "weekly_roc": 0.08,
            "daily_rsi": 58.0,
            "volume_ratio": 1.2,
            "regime_confidence": 0.61,
            "regime_breadth_ratio": 0.54,
            "expected_r_multiple": 1.35,
        },
    }

    row = extract_feature_row(trade)
    assert row["symbol"] == "ABC"
    assert row["outcome_label"] == 0
    assert abs(row["atr_pct"] - 0.05) < 1e-9
    assert abs(row["stop_distance_pct"] - 0.06) < 1e-9
    assert abs(row["market_regime_confidence"] - 0.61) < 1e-9
    assert abs(row["market_breadth_ratio"] - 0.54) < 1e-9


def test_build_training_frame_has_all_feature_columns() -> None:
    trades = [
        {
            "symbol": "A",
            "entry_date": "2025-01-01",
            "exit_reason": "TRAILING_STOP",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "confidence": 0.8,
            "net_pnl": 100.0,
            "metadata": {},
        }
    ]
    frame = build_training_frame(trades)
    assert len(frame) == 1
    for feature in FEATURE_COLUMNS:
        assert feature in frame.columns


def test_threshold_sweep_best_threshold_respects_min_trades() -> None:
    frame = build_training_frame(
        [
            {"symbol": "A", "entry_date": "2025-01-01", "exit_reason": "STOP_LOSS", "entry_price": 100, "stop_loss": 90, "net_pnl": -500, "confidence": 0.5, "metadata": {}},
            {"symbol": "B", "entry_date": "2025-01-02", "exit_reason": "TRAILING_STOP", "entry_price": 100, "stop_loss": 90, "net_pnl": 600, "confidence": 0.5, "metadata": {}},
            {"symbol": "C", "entry_date": "2025-01-03", "exit_reason": "TRAILING_STOP", "entry_price": 100, "stop_loss": 90, "net_pnl": 400, "confidence": 0.5, "metadata": {}},
            {"symbol": "D", "entry_date": "2025-01-04", "exit_reason": "TIME_STOP", "entry_price": 100, "stop_loss": 90, "net_pnl": -200, "confidence": 0.5, "metadata": {}},
        ]
    )
    probs = np.array([0.20, 0.90, 0.70, 0.40], dtype=float)

    rows, best = run_threshold_sweep(
        frame,
        probs,
        threshold_start=0.30,
        threshold_end=0.70,
        threshold_step=0.20,
        min_trades_kept=2,
    )

    assert len(rows) == 3
    assert best["trades_kept"] >= 2
    assert float(best["simulated_pnl"]) >= 0.0


def test_simple_rule_baseline_returns_best_rule() -> None:
    frame = build_training_frame(
        [
            {"symbol": "A", "entry_date": "2025-01-01", "exit_reason": "STOP_LOSS", "entry_price": 100, "stop_loss": 90, "net_pnl": -400, "confidence": 0.4, "metadata": {"weekly_atr": 12}},
            {"symbol": "B", "entry_date": "2025-01-02", "exit_reason": "TRAILING_STOP", "entry_price": 100, "stop_loss": 95, "net_pnl": 300, "confidence": 0.6, "metadata": {"weekly_atr": 2}},
            {"symbol": "C", "entry_date": "2025-01-03", "exit_reason": "TRAILING_STOP", "entry_price": 100, "stop_loss": 95, "net_pnl": 250, "confidence": 0.7, "metadata": {"weekly_atr": 3}},
            {"symbol": "D", "entry_date": "2025-01-04", "exit_reason": "TIME_STOP", "entry_price": 100, "stop_loss": 94, "net_pnl": -100, "confidence": 0.5, "metadata": {"weekly_atr": 5}},
        ]
    )
    baseline = run_simple_rule_baseline(frame, min_trades_kept=2)
    assert "best_rule" in baseline
    assert baseline["best_rule"]["trades_kept"] >= 2
    assert baseline["best_rule"]["feature"] in {"atr_pct", "stop_distance_pct"}


def test_evaluate_threshold_at_reports_metrics() -> None:
    frame = build_training_frame(
        [
            {"symbol": "A", "entry_date": "2025-01-01", "exit_reason": "STOP_LOSS", "entry_price": 100, "stop_loss": 90, "net_pnl": -500, "confidence": 0.5, "metadata": {}},
            {"symbol": "B", "entry_date": "2025-01-02", "exit_reason": "TRAILING_STOP", "entry_price": 100, "stop_loss": 90, "net_pnl": 600, "confidence": 0.5, "metadata": {}},
            {"symbol": "C", "entry_date": "2025-01-03", "exit_reason": "TRAILING_STOP", "entry_price": 100, "stop_loss": 90, "net_pnl": 400, "confidence": 0.5, "metadata": {}},
            {"symbol": "D", "entry_date": "2025-01-04", "exit_reason": "TIME_STOP", "entry_price": 100, "stop_loss": 90, "net_pnl": -200, "confidence": 0.5, "metadata": {}},
        ]
    )
    probs = np.array([0.20, 0.90, 0.70, 0.40], dtype=float)
    row = evaluate_threshold_at(frame, probs, threshold=0.5, min_trades_kept=2)
    assert row["threshold"] == 0.5
    assert row["trades_kept"] == 2
    assert row["stop_loss_rejected"] == 1
