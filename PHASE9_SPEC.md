# Phase 9: Adaptive Trend System - Technical Specification

> Extracted from `IMPLEMENTATION_PLAN.md` to keep that file execution-focused.
> This document contains the full design spec for Phase 9 sub-items 9A-9J.

**Date**: 2026-02-12
**Status**: In progress (9A-9D implemented; 9E-9J pending)
**Prerequisite**: All Phase 1-8 items completed (37/37)

---

## Rationale

Parameter tuning is exhausted. 100+ experiments across 6 strategy variants, 150+ parameter combos, and defensive modes all failed to exceed 1/4 anchor passes. Root cause: daily-timeframe momentum with 15-23 trades/week generates 5.3-8.2% weekly transaction-cost drag (at 0.355% round-trip). No parameter set can overcome this structural deficit. Phase 9 shifts to a fundamentally different trading cadence and adds a self-improving ML layer.

---

## 9A: Adaptive Trend Following Strategy

- **File**: `trading_bot/strategies/adaptive_trend.py`
- Extends `BaseStrategy` (same `generate_signals` / `check_exit_conditions` interface)
- Weekly indicators computed from daily OHLCV (resample inside `generate_signals`):
  - Weekly EMA-10, EMA-30, ATR-10, RSI-10, ROC-4, Volume Ratio
- Hard regime gate: returns empty signal list when breadth < 50% OR ann_vol > 30% OR trend_down
- Entry: weekly trend structure (EMA-10 > EMA-30, close > EMA-10, ROC 2-20%, RSI 40-75) + daily pullback timing (close > SMA-20, within 1.5x ATR of weekly EMA-10, RSI 45-70)
- Exit: trailing stop at 2x weekly ATR (tightens to 1.5x after 10% gain), trend-break exit (weekly EMA crossover), time stop (30 days if gain < 3%)
- No fixed target price; trailing stop lets winners run
- Universe: top 40 Nifty 50 stocks (reuse existing fallback list in `market_data.py`)
- Position limits: max 3 new entries/week, max 5 total
- Economics: 2-4 trades/week x 0.355% = 0.7-1.4% weekly cost drag (vs 5.3%+ currently)

## 9B: Feature Persistence Layer

- **Files**: `trading_bot/data/storage/feature_store.py`, `trading_bot/data/storage/schemas.sql`
- New `trade_features` table (35 columns): technical features (weekly + daily), market features (breadth, regime, Nifty ROC), quality features (liquidity, sector), signal features (confidence, ML score), outcome fields (pnl, exit reason, MFE/MAE, outcome_label)
- `FeatureStore` class: `save_entry_features()`, `update_trade_outcome()`, `get_training_data()`
- Fixes critical gap: signal metadata currently lost after `pre_market_routine`
- Integration: `save_entry_features()` called in `main.py:_execute_entry()` after `_save_trade_to_db()`; `update_trade_outcome()` called in `main.py:_execute_exit()` after `_save_trade_to_db()`

## 9C: Adaptive Position Sizing

- **File**: `trading_bot/risk/position_sizer.py`
- New function `size_position_adaptive()` (existing `size_position()` preserved)
- Half-Kelly: `kelly = W - (1-W)/R`, use `kelly/2` capped at 6% per trade
- Confidence scaling: ML score maps to 0.5x-1.5x multiplier
- Drawdown reduction: linear scale-down from 100% at 0% DD to 40% at 15% DD
- Sector cap: reduce if sector exposure > 15% of portfolio

## 9D: BacktestEngine Trailing-Stop Support

- **File**: `trading_bot/backtesting/engine.py`
- Add `highest_close`, `lowest_close`, `metadata` fields to `Position` dataclass
- `_process_exits()` updates highest/lowest close before calling `check_exit_conditions()`

## 9E: ML Scoring Package

- **Files**: `trading_bot/ml/__init__.py`, `trading_bot/ml/scorer.py`
- `MLScorer` class with progressive modes:
  - < 100 completed trades: rules-only (confidence score passthrough)
  - 100-300 trades: ensemble (30% ML + 70% rules)
  - 300+ trades: ML-primary (70% ML + 30% rules)
- LightGBM classifier trained on 20 numeric features from `trade_features`
- TimeSeriesSplit CV (3 folds, no lookahead)
- Deploy gate: AUC > 0.55 required; falls back to rules if recent 30-trade accuracy < 52%
- Model persisted to `data/models/lgbm_scorer_latest.pkl`

## 9F: Automated Learning Loop

- **File**: `trading_bot/ml/learning_loop.py`
- `LearningLoop` class with three scheduled jobs:
  - Weekly (Sunday 18:35): `weekly_trade_analysis()` -- feature win/loss comparison, exit reason distribution
  - Monthly (first Sunday, 19:00): `monthly_retrain()` -- retrain ML model on rolling 6-month window
  - Quarterly (quarter months, first Sunday, 19:30): `quarterly_review()` -- full strategy report to `reports/ml/`
- Each job logs to `system_logs` and sends Telegram alert

## 9G: Orchestrator Integration

- **File**: `main.py`
- Initialize `AdaptiveTrendFollowingStrategy` when `ENABLE_ADAPTIVE_TREND=1`
- Initialize `FeatureStore` and `MLScorer` instances
- Wire `feature_store.save_entry_features()` into `_execute_entry()` (after `_save_trade_to_db`)
- Wire `feature_store.update_trade_outcome()` into `_execute_exit()` (after `_save_trade_to_db`)
- Add `_get_recent_trade_stats()` helper (queries last 20 closed adaptive trades for Kelly inputs)
- Schedule learning routines in `run()` method

## 9H: Configuration

- **Files**: `trading_bot/config/settings.py`, `.env.example`
- 16 new env vars: `ENABLE_ADAPTIVE_TREND`, `ADAPTIVE_TREND_WEEKLY_EMA_SHORT` (10), `ADAPTIVE_TREND_WEEKLY_EMA_LONG` (30), `ADAPTIVE_TREND_WEEKLY_ATR_PERIOD` (10), `ADAPTIVE_TREND_WEEKLY_RSI_PERIOD` (10), `ADAPTIVE_TREND_MIN_WEEKLY_ROC` (0.02), `ADAPTIVE_TREND_MAX_WEEKLY_ROC` (0.20), `ADAPTIVE_TREND_STOP_ATR_MULT` (2.0), `ADAPTIVE_TREND_MAX_POSITIONS` (5), `ADAPTIVE_TREND_MAX_NEW_PER_WEEK` (3), `ADAPTIVE_TREND_MIN_HOLD_DAYS` (5), `ADAPTIVE_TREND_TIME_STOP_DAYS` (30), `ADAPTIVE_TREND_PROFIT_PROTECT_PCT` (0.10), `ADAPTIVE_TREND_REGIME_MIN_BREADTH` (0.50), `ADAPTIVE_TREND_REGIME_MAX_VOL` (0.30), `ADAPTIVE_TREND_ML_ENABLED` (0)

## 9I: Dependencies

- **File**: `requirements.txt`
- Add: `lightgbm==4.2.0`, `scikit-learn==1.3.2`, `joblib==1.3.2`

## 9J: Test Suite

- **File**: `tests/test_adaptive_trend_strategy.py`
- 12 tests: hard regime gate, signal generation, position limits, trailing stop, profit protection, feature store CRUD, ML scorer modes, adaptive sizing, backtest integration, weekly resampling

---

## File Manifest

### New Files (6)
| File | Lines (est) | Purpose |
|------|-------------|---------|
| `trading_bot/strategies/adaptive_trend.py` | ~250 | Weekly trend + daily entry strategy with trailing stops |
| `trading_bot/data/storage/feature_store.py` | ~120 | Feature CRUD for trade_features table |
| `trading_bot/ml/__init__.py` | ~5 | Package init |
| `trading_bot/ml/scorer.py` | ~180 | LightGBM progressive scoring |
| `trading_bot/ml/learning_loop.py` | ~120 | Weekly/monthly/quarterly automation |
| `tests/test_adaptive_trend_strategy.py` | ~200 | 12 test cases |

### Modified Files (8)
| File | Change Summary |
|------|----------------|
| `trading_bot/data/storage/schemas.sql` | +35 lines: `trade_features` CREATE TABLE + 4 indexes |
| `trading_bot/strategies/__init__.py` | +2 lines: import + __all__ entry |
| `trading_bot/config/settings.py` | +25 lines: 16 env vars + validation |
| `trading_bot/risk/position_sizer.py` | +40 lines: `size_position_adaptive()` function |
| `trading_bot/backtesting/engine.py` | +8 lines: Position fields + exit tracking |
| `main.py` | +60 lines: init, feature wiring, learning scheduler |
| `.env.example` | +20 lines: new env vars with defaults |
| `requirements.txt` | +3 lines: lightgbm, scikit-learn, joblib |

### Canonical Anchor Validation Command (post-implementation only)
> This is the single canonical command used in both `IMPLEMENTATION_PLAN.md` and this spec.

```
ENABLE_ADAPTIVE_TREND=1 ENABLE_MOMENTUM_BREAKOUT=0 ENABLE_MEAN_REVERSION=0 ENABLE_SECTOR_ROTATION=0 ENABLE_BEAR_REVERSAL=0 ENABLE_VOLATILITY_REVERSAL=0 python scripts/multi_week_gate_search.py
```

### Recommended Initial Config
> These env vars now exist in the codebase (`trading_bot/config/settings.py`, `.env.example`).

```
ENABLE_MOMENTUM_BREAKOUT=0
ENABLE_MEAN_REVERSION=0
ENABLE_SECTOR_ROTATION=0
ENABLE_BEAR_REVERSAL=0
ENABLE_VOLATILITY_REVERSAL=0
ENABLE_ADAPTIVE_TREND=1
ADAPTIVE_TREND_ML_ENABLED=0
MAX_POSITIONS=5
RISK_PER_TRADE=0.015
MAX_POSITION_SIZE=0.20
MAX_PORTFOLIO_HEAT=0.10
```
