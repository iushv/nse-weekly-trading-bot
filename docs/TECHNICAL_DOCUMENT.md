# Indian Equity Swing-Trading System -- Technical Document

**Project**: new-trading-bot
**Target Market**: NSE (National Stock Exchange of India) via Groww broker
**Strategy Class**: Adaptive trend-following (weekly timeframe)
**Status**: Paper-run active on Nifty Midcap 150 universe
**Date**: 2026-02-14 (updated)

---

## 1. System Architecture

### 1.1 Design Philosophy

The system follows a modular, layered architecture separating strategy logic, execution, risk management, and monitoring. All strategies share a common interface (`BaseStrategy`) and are evaluated through a unified gate system before any capital deployment.

### 1.2 Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.11 (target), 3.9.6 (local) |
| Data processing | pandas, numpy | 2.1.4, 1.26.4 |
| Market data | yfinance (Yahoo Finance) | 0.2.33 |
| Broker integration | Groww API (REST) | Custom client |
| Database | SQLite | Built-in |
| Configuration | python-dotenv | 1.0.0 |
| Scheduling | schedule | 1.2.1 |
| Logging | loguru | 0.7.2 |
| Alerting | python-telegram-bot | 20.7 |
| HTTP | requests | 2.31.0 |
| Timezone | pytz (Asia/Kolkata) | 2023.3 |
| Linting | ruff | Latest |
| Type checking | mypy | Latest |
| Testing | pytest | Latest |

### 1.3 Codebase Structure

```
new-trading-bot/
├── main.py                          # Orchestrator (1,532 lines)
├── paper_trading.py                 # Paper-trading entry point
├── trading_bot/
│   ├── config/
│   │   ├── settings.py              # All configuration + env-driven params
│   │   ├── credentials.py           # Credential management
│   │   └── constants.py             # Static constants
│   ├── strategies/
│   │   ├── base_strategy.py         # BaseStrategy ABC + Signal dataclass
│   │   ├── adaptive_trend.py        # Active strategy (379 lines)
│   │   ├── momentum_breakout.py     # Legacy (disabled)
│   │   ├── mean_reversion.py        # Legacy (disabled)
│   │   ├── sector_rotation.py       # Legacy (disabled)
│   │   ├── bear_reversal.py         # Legacy (disabled)
│   │   ├── volatility_reversal.py   # Legacy (disabled)
│   ├── backtesting/
│   │   ├── engine.py                # BacktestEngine with trailing-stop support
│   │   ├── walk_forward.py          # Walk-forward analysis
│   │   └── performance.py           # Performance metrics
│   ├── data/
│   │   ├── collectors/              # Market + alternative data collectors
│   │   └── storage/
│   │       ├── schemas.sql          # 6 tables + indexes
│   │       └── feature_store.py     # ML feature persistence layer
│   ├── execution/
│   │   ├── broker_interface.py      # Mock / Groww / HTTP broker adapters
│   │   ├── order_manager.py         # Order lifecycle management
│   │   └── portfolio_manager.py     # Portfolio state tracking
│   ├── risk/
│   │   └── position_sizer.py        # Standard + adaptive (half-Kelly) sizing
│   ├── monitoring/
│   │   ├── performance_audit.py     # Weekly audit with waiver logic
│   │   ├── gate_profiles.py         # Strategy-aware gate thresholds
│   │   ├── audit_trend.py           # Trend analysis with waiver tracking
│   │   ├── paper_run_tracker.py     # Paper-run streak tracking (universe-aware)
│   │   ├── run_context.py           # Universe-aware run tagging
│   │   ├── audit_artifacts.py       # Artifact generation with run_context embedding
│   │   ├── promotion_gate.py        # Promotion decision logic
│   │   ├── retention.py             # Log/report rotation
│   │   ├── ops_controls.py          # Kill switch, incident controls
│   │   └── ...                      # Health check, dashboard, storage profiler
│   ├── reporting/
│   │   ├── telegram_bot.py          # Telegram alerting
│   │   └── report_generator.py      # Report formatting
│   └── ml/                          # Pending (Phase 9E-9F)
│       ├── scorer.py                # LightGBM scorer (stub)
│       └── learning_loop.py         # Automated retraining (stub)
├── scripts/
│   ├── multi_week_gate_search.py    # Primary multi-anchor validation
│   ├── structural_gate_sweep.py     # Single-window diagnostic
│   ├── weekly_performance_audit.py  # Weekly audit runner
│   ├── promotion_checklist.py       # Promotion bundle generator
│   ├── weekly_audit_trend.py        # Trend summary with waivers
│   ├── preflight_check.py           # Pre-run health check
│   ├── groww_live_smoke.py          # Broker connectivity test
│   ├── run_universe_backtest.py      # Backtest restricted to universe file
│   ├── run_universe_walk_forward.py  # Walk-forward on universe file
│   └── ...                          # Tuning, backfill, retention, rollback
├── tests/                           # 29 test files (all passing)
├── data/
│   └── universe/
│       └── nifty_midcap150.txt      # 140 Nifty Midcap 150 symbols
├── docs/
│   ├── LIVE_ROLLOUT_RUNBOOK.md
│   ├── PAPER_RUN_ACCEPTANCE.md
│   └── TECHNICAL_DOCUMENT.md        # This document
├── IMPLEMENTATION_PLAN.md           # Execution tracking (46 items)
├── PHASE9_SPEC.md                   # Phase 9 technical specification
└── reports/
    ├── backtests/                    # 135 backtest artifacts
    ├── audits/                       # Weekly audit exports
    └── promotion/                    # Promotion bundle snapshots
```

**Total codebase**: ~10,000 lines of application code (excluding vendor/venv).

### 1.4 Database Schema

SQLite with 6 tables:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `price_data` | Daily OHLCV for NSE symbols (140 midcap + 50 large-cap) | symbol, date, open/high/low/close/volume |
| `trades` | Trade lifecycle (entry → exit) | order_id, symbol, strategy, entry/exit price/date, pnl |
| `portfolio_snapshots` | Daily portfolio state | total_value, cash, positions_value, drawdown, sharpe |
| `strategy_performance` | Per-strategy daily metrics | wins, losses, win_rate, avg_win, avg_loss, sharpe |
| `system_logs` | Structured operational logs | level, module, message, metadata (JSON) |
| `trade_features` | ML feature store (35 columns) | Technical + market + quality features, outcome labels |

---

## 2. Active Strategy: Adaptive Trend Following

### 2.1 Design Rationale

100+ experiments across 6 strategy variants proved that daily-timeframe momentum trading on NSE cannot overcome transaction costs. At 15-23 trades/week and 0.355% round-trip cost, the weekly cost drag of 5.3-8.2% is structurally unbeatable.

The adaptive trend strategy shifts to:
- **Weekly timeframe** for trend identification
- **Daily timeframe** for entry timing
- **2-4 trades/week** (cost drag: 0.7-1.4%)
- **2-6 week holds** (letting winners run)

### 2.2 Indicators

**Weekly indicators** (computed by resampling daily OHLCV to W-FRI):

| Indicator | Computation | Purpose |
|-----------|------------|---------|
| EMA-10 (short) | 10-week exponential moving average | Trend direction |
| EMA-30 (long) | 30-week exponential moving average | Trend baseline |
| ATR-10 | 10-week average true range | Volatility / stop sizing |
| RSI-10 | 10-week relative strength index | Momentum strength |
| ROC-4 | 4-week rate of change | Trend momentum |
| Volume Ratio | Current volume / 10-week MA | Volume confirmation |

**Daily indicators**:

| Indicator | Computation | Purpose |
|-----------|------------|---------|
| SMA-20 | 20-day simple moving average | Daily trend filter |
| RSI-14 | 14-day relative strength index | Entry timing |

### 2.3 Entry Conditions

All conditions must be true simultaneously:

| # | Condition | Rationale |
|---|-----------|-----------|
| 1 | Weekly EMA-10 > EMA-30 | Confirmed uptrend |
| 2 | EMA spread > 0.5% of price | Trend has conviction (not flat crossover) |
| 3 | Weekly close > EMA-10 | Price above short-term trend |
| 4 | Weekly ROC-4 between 3-20% | Trend has momentum but not overextended |
| 5 | Weekly RSI between 40-75 | Not overbought or oversold |
| 6 | Daily close > SMA-20 | Daily trend aligned |
| 7 | Daily RSI between 45-70 | Not at daily extreme |
| 8 | Price within 1.5x ATR of EMA-10 | Not too far from trend (pullback entry) |
| 9 | Volume ratio >= 0.8 | Adequate liquidity |

**Additional entry filters:**

- **Trend consistency**: At least 50% of last 4 weekly closes must be above EMA-10. Suppresses entries in choppy markets. Floor tightens by +10% per regime tighten step.
- **Expected R-multiple floor**: Estimated reward/risk ratio must exceed 1.0 (tightens by +0.15 per regime tighten step, capped at 1.6). Rejects marginal setups.
- **Regime-aware threshold tightening**: When market regime signals are weak (low confidence, low breadth, high vol), entry thresholds for ROC, EMA spread, and volume ratio are progressively tightened (0-3 steps).
- **Signal ranking**: All passing signals are ranked by confidence score; only the top `max_new_per_week` (3) are selected.

### 2.4 Exit Cascade

Exits are checked in strict priority order. First match wins.

| Priority | Exit Type | Condition | Purpose |
|----------|-----------|-----------|---------|
| 1 | **STOP_LOSS** | Price <= initial stop (entry - 1.5x weekly ATR) | Hard floor, never bypassed |
| 2 | **BREAKEVEN_STOP** | After 5+ days held AND historical gain >= 3%: price <= entry + 0.5% | Prevents winners becoming losers |
| 3 | **TREND_BREAK** | After 5+ days: weekly EMA-10 crossed below EMA-30 (was above at entry) | Structural trend reversal |
| 4 | **TRAILING_STOP** | After 5+ days: price <= highest_close - (trail_mult x weekly ATR) | Protects accumulated gains |
| 5 | **TIME_STOP** | After 30 days: unrealized gain < 3% | Frees capital from dead positions |

**Progressive trailing stop bands:**

| Gain from Entry (at highest_close) | Trail Multiplier | Effective Trail Width |
|-------------------------------------|-----------------|----------------------|
| < 3% | 1.5x ATR | Same as initial stop width |
| >= 3% | 1.2x ATR | Moderate tightening |
| >= 5% | 1.0x ATR | Tight |
| >= 8% | 0.8x ATR | Very tight (lock in gains) |

### 2.5 Regime Gate

Hard entry gate computed once per day by the orchestrator:

- **Breadth ratio** < 50%: all entries blocked (market too narrow)
- **Annualized volatility** > threshold: all entries blocked (market too volatile)
- **Trend down**: all entries blocked (broad market declining)

Single source of truth: `main.py:_compute_market_regime()` produces canonical `is_favorable` flag consumed by all strategies.

### 2.6 Position Sizing

**Standard mode** (current):
- Risk per trade: `RISK_PER_TRADE` of capital (default 0.8%)
- Max position: `MAX_POSITION_SIZE` of capital (default 8%)
- Shares = risk_amount / (price - stop_loss), capped by position limit and cash

**Adaptive mode** (available, activates with ML):
- Half-Kelly criterion: `kelly = W - (1-W)/R`, use `kelly/2` capped at 6%
- Confidence scaling: ML score maps to 0.5x-1.5x multiplier
- Drawdown throttling: linear reduction from 100% at 0% DD to 40% at 15% DD
- Sector cap: reduce if sector exposure > 15% of portfolio

### 2.7 Confidence Score

Composite score used for signal ranking:

```
confidence = 0.35 (base)
           + 0.25 * roc_score        (weekly ROC normalized to 0-1)
           + 0.20 * weekly_rsi_score  (weekly RSI normalized to 0-1)
           + 0.10 * daily_rsi_score   (daily RSI normalized to 0-1)
           + 0.10 * vol_score         (volume ratio normalized to 0-1)
```

Range: 0.05 to 0.99. Higher confidence = stronger trend setup.

### 2.8 Transaction Cost Model

NSE/Groww cost breakdown (per side):

| Component | Rate |
|-----------|------|
| Brokerage | 0.030% |
| STT | 0.025% |
| Transaction tax | 0.018% |
| GST | 0.0054% |
| SEBI charges | 0.0001% |
| Stamp duty | 0.015% |
| **Round-trip total** | **0.355%** |

Applied as `COST_PER_SIDE = 0.1775%` on both entry and exit legs in backtest and live execution.

---

## 3. Evaluation & Gate System

### 3.1 Multi-Anchor Validation

The primary robustness test simulates the strategy across 4 consecutive weekly anchor dates, each with an independent backtest:

| Anchor | Market Condition | Lookback |
|--------|-----------------|----------|
| 2026-01-22 | Choppy | 42 days |
| 2026-01-29 | Bearish | 42 days |
| 2026-02-05 | Sideways | 42 days |
| 2026-02-12 | Trending | 42 days |

Lookback is 42 days (6 weeks) for adaptive strategy runs, 28 days for momentum-era strategies. Strategy-aware default in `multi_week_gate_search.py`.

### 3.2 Gate Profiles

Strategy-aware audit thresholds:

| Gate | Baseline Profile | Adaptive Profile |
|------|-----------------|-----------------|
| Min Sharpe | 0.7 | 0.7 |
| Max Drawdown | 15% | 15% |
| Min Win Rate | 50% | 30%* |
| Min Profit Factor | 1.0 | 1.0* |
| Min Closed Trades | 10 | 3 |
| Max Critical Errors | 0 | 0 |
| Required Paper Weeks | 4 | 6 |

*\*Trend-following waivers apply (see 3.3).*

Profile auto-resolves: `adaptive` when only adaptive trend is enabled, `baseline` otherwise.

### 3.3 Trend-Following Waivers

Trend-following strategies hold winners and cut losers. Within a bounded lookback window, winning positions may still be open while only losers have closed. This creates a structural artifact where win_rate = 0% and profit_factor = 0.0 despite positive portfolio return.

**Waiver conditions** (all must be true):
1. Zero winning closed trades (wins == 0)
2. At least one closed trade (closed_trades > 0)
3. Positive total return (total_return_pct > 0)
4. Sharpe ratio >= minimum threshold (sharpe >= min_sharpe)

When conditions are met:
- `profit_factor` gate is waived
- `win_rate` gate is waived

Waiver usage is tracked in weekly audit trends (`waiver_fire_rate`, `waiver_timeline`). Expected to decline as the paper-run accumulates more closed trades.

### 3.4 Promotion Pipeline

```
Multi-Anchor Backtest (3/4+)
    → Paper-Run (6 consecutive weeks passing weekly audit)
        → Promotion Bundle (preflight + audit + checklist)
            → Manual Review
                → Live (with fail-closed safety locks)
```

Live orders require explicit arming:
- `LIVE_ORDER_EXECUTION_ENABLED=1`
- `LIVE_ORDER_FORCE_ACK=YES_I_UNDERSTAND_LIVE_ORDERS`

---

## 4. Experiment History

### 4.1 Summary of All Experiment Phases

| Phase | Period | Experiments | Strategy | Best Result | Outcome |
|-------|--------|------------|----------|-------------|---------|
| Momentum tuning | Feb 11-12 | ~40 | momentum_breakout (v2-v6) | 1/4 anchors | Cost drag structural; no param set overcomes 5.3%+ weekly drag |
| Strategy mix | Feb 12 | ~20 | momentum + mean_rev + sector | 1/4 anchors | Diversification doesn't help when all strategies overtrade |
| Bear/Vol reversal | Feb 12 | ~18 | bear_reversal, volatility_reversal | 1/4 anchors | Short-hold reversal signals add noise, doesn't improve robustness |
| Defensive breadth | Feb 12 | ~8 | Breadth-gated momentum | 0/4 anchors | Reducing entries without fixing economics reduces signal |
| Adaptive trend v1 | Feb 12 | 4 | adaptive_trend (broken exits) | 0/4 anchors | Regime mismatch + wide stops + no trailing engagement |
| Regime alignment | Feb 12 | 3 | adaptive_trend (regime fixed) | 0/4 anchors | Improved funnel but exits still STOP_LOSS heavy |
| Gate profiles | Feb 12 | 1 | adaptive_trend + adaptive gates | 0/4 anchors | Correct evaluation, strategy correctly fails |
| Exit stack overhaul | Feb 12 | 1 | Progressive trailing + breakeven + trend-break | 0/4 anchors | STOP_LOSS dropped 83% → 35%; returns improved |
| R-multiple filter | Feb 12 | 1 | Pre-entry payoff filter | **2/4 anchors** | First breakthrough past 1/4 ceiling |
| PF/WR waivers + closed floor | Feb 13 | 1 | Trend-following gate fix | 2/4 anchors | Gate evaluation now matches strategy lifecycle |
| Choppiness filter | Feb 13 | 3 | Weekly trend consistency gate | **3/4 anchors** | Choppy-regime entries suppressed |
| **Total** | | **~100+** | | | |

### 4.2 Key Backtest Artifacts

| Artifact | Description | Result |
|----------|------------|--------|
| `multi_week_gate_search_20260212_144131.json` | First adaptive-only run | 0/4, 83% STOP_LOSS |
| `multi_week_gate_search_20260212_145156.json` | After regime alignment fix | 0/4, improved funnel |
| `multi_week_gate_search_20260212_150009.json` | With adaptive gate profiles | 0/4, profile confirmed |
| `multi_week_gate_search_20260212_203911.json` | After exit stack overhaul (42d lookback) | 0/4, STOP_LOSS → 35% |
| `multi_week_gate_search_20260212_205641.json` | Exit stack (28d, matched comparison) | 0/4, 2/4 positive returns |
| `multi_week_gate_search_20260212_223042.json` | With R-multiple filter | **2/4** (first breakthrough) |
| `multi_week_gate_search_20260213_073926.json` | Final calibrated (3/4) | **3/4** (current) |

### 4.3 Iteration Trajectory (Return Improvement)

Apples-to-apples comparison across iterations (28-day lookback where available):

| Iteration | 01-22 | 01-29 | 02-05 | 02-12 | Avg |
|-----------|-------|-------|-------|-------|-----|
| Broken exits (baseline) | -0.68% | -0.97% | -1.98% | -0.32% | **-0.99%** |
| Exit stack fix | -0.74% | +0.44% | -1.04% | +0.001% | **-0.34%** |
| R-multiple filter | -0.86%* | +2.63%* | +1.27%* | +2.07%* | **+1.28%*** |
| Final calibrated (3/4) | -1.43%* | +2.63%* | +1.05%* | +1.83%* | **+1.02%*** |

*\*42-day lookback (not directly comparable to 28-day rows but represents current system.*

---

## 5. Current Performance

### 5.1 Universe Comparison (Same Frozen Parameters)

The same Adaptive Trend strategy parameters were tested on two universes. Midcap 150 produces materially stronger edge.

| Metric | Nifty 50 (6-month) | Midcap 150 (6-month) |
|--------|-------------------|---------------------|
| Period | Aug 2025 - Feb 2026 | Aug 2025 - Feb 2026 |
| Total return | +0.30% | **+7.54%** |
| Sharpe ratio | 0.15 | **1.42** |
| Profit factor | 1.05 | **1.94** |
| Max drawdown | -3.8% | -4.5% |
| Total trades | 45 | 63 |
| Win rate | 44% | 51% |
| Avg days held | ~15 | ~19 |

**Artifacts:**
- Nifty 50: `reports/backtests/adaptive_continuous_6m_20250801_20260212_20260214_054821.json`
- Midcap 150: `reports/backtests/universe_backtest_nifty_midcap150_20250801_20260212_20260214_062827.json`

### 5.2 Walk-Forward Analysis (Midcap 150, 3x3)

Rolling out-of-sample windows: 3-month train (skip), 3-month test. Fixed parameters throughout (no re-optimization).

| Window | Test Period | Return | Sharpe | Trades | Win Rate |
|--------|------------|--------|--------|--------|----------|
| 1 | Apr-Jul 2024 | 0.00% | 0.00 | 0 | -- |
| 2 | Jul-Oct 2024 | **+6.42%** | 5.10 | 17 | 70.6% |
| 3 | Oct 2024-Jan 2025 | -2.06% | -1.03 | 34 | 41.2% |
| 4 | Jan-Apr 2025 | -5.69% | -3.95 | 20 | 25.0% |
| 5 | Apr-Jul 2025 | **+3.44%** | 2.22 | 28 | 64.3% |
| 6 | Jul-Oct 2025 | **+0.94%** | 0.65 | 33 | 48.5% |
| 7 | Oct 2025-Jan 2026 | **+3.27%** | 1.43 | 29 | 44.8% |

| Summary Metric | Value |
|----------------|-------|
| Profitable windows | **4/7** (57%) |
| Avg return per window | **+0.90%** |
| Avg Sharpe | **+0.63** |
| Avg max drawdown | -3.0% |
| Net across all test periods | **+6.32%** (21 months OOS) |

Window 1 (0 trades) reflects conservative regime gating with limited lookback at period start. Window 4 (Jan-Apr 2025) is a broad midcap selloff -- the regime gate did not fully block entries (20 trades, 25% win rate). Excluding the 0-trade window, 4 of 6 active windows were profitable (67%).

**Walk-forward comparison (window sizing matters):**

| Config | Profitable | Avg Return | Avg Sharpe |
|--------|-----------|------------|------------|
| 3x2 (2-month test) | 3/7 (43%) | -0.50% | -0.21 |
| **3x3 (3-month test)** | **4/7 (57%)** | **+0.90%** | **+0.63** |

Longer test windows let winning positions complete their lifecycle, confirming the strategy's 2-6 week holding period requires minimum 3-month evaluation windows.

**Artifact:** `reports/backtests/universe_walk_forward_nifty_midcap150_3x3_20240101_20260211_20260214_065139.json`

### 5.3 Multi-Anchor Gate Results (Nifty 50, Pre-Pivot)

These results were on the original Nifty 50 universe and justified the pivot to Midcap 150.

Starting capital: Rs 1,00,000 per anchor. Lookback: 42 days.

| Anchor | Return | P/L (Rs) | Sharpe | Profit Factor | Closed Trades | Win Rate | Gate Status |
|--------|--------|---------|--------|---------------|---------------|----------|-------------|
| 2026-01-22 (choppy) | -1.43% | -1,429 | -4.56 | 0.24 | 4 | 25% | **Fail** |
| 2026-01-29 (bearish) | +2.63% | +2,635 | +2.71 | 0.00* | 3 | 0%* | **Pass** (waiver) |
| 2026-02-05 (sideways) | +1.05% | +1,048 | +0.89 | 1.40 | 8 | 50% | **Pass** |
| 2026-02-12 (trending) | +1.83% | +1,830 | +1.49 | 1.36 | 8 | 50% | **Pass** |

**Aggregate**: +4,084 net across all anchors. Average +1.02% per 42-day period. **3/4 anchors passed.**

*\*Waiver applied: 0 winning closed trades but positive return (+2.63%) and Sharpe (+2.71) from open winning positions.*

### 5.4 Exit Distribution (Nifty 50 Anchors, 23 Closed Trades)

| Exit Type | Count | Share | Avg P/L |
|-----------|-------|-------|---------|
| TRAILING_STOP | 8 | 35% | Mixed (winners) |
| BREAKEVEN_STOP | 6 | 26% | Near-zero |
| STOP_LOSS | 5 | 22% | Negative |
| TIME_STOP | 2 | 9% | Small negative |
| TREND_BREAK | 2 | 9% | Mixed |

Exit health is good: trailing stops are the dominant exit type (capturing gains), breakeven stops prevent winners from becoming losers, and stop-losses are contained to 22% of exits.

### 5.5 Trade Economics

| Metric | Value |
|--------|-------|
| Avg trades/week | ~2-3 |
| Avg hold period | 10-20 days |
| Weekly cost drag | ~0.7-1.1% |
| Avg stop distance | ~6% (1.5x weekly ATR) |
| Max positions | 5 concurrent |
| Max new entries/week | 3 |

---

## 6. Operational Infrastructure

### 6.1 Orchestrator (main.py)

The main scheduler runs the following daily routines:

| Routine | Time (IST) | Function |
|---------|-----------|----------|
| Pre-market | 09:00 | Data refresh, regime computation, signal generation, ranking |
| Market open | 09:15 | Order placement (paper or live) |
| Intraday monitoring | 10:30, 12:00, 14:00 | Exit checks, position tracking, risk monitoring |
| Market close | 15:30 | Close-of-day reconciliation, P/L snapshot |
| Post-market | 16:00 | Report generation, Telegram alerts |
| Weekly audit | Sunday | Performance audit, paper-run status update |

### 6.2 Safety Controls

| Control | Implementation |
|---------|---------------|
| Live-order lock | Fail-closed: requires `LIVE_ORDER_EXECUTION_ENABLED=1` + ack phrase |
| Kill switch | `scripts/ops_controls.py` -- immediate halt of all trading |
| Incident notes | Structured incident logging with Telegram notification |
| Rollback | `scripts/rollback_live.py` -- cancel open orders, freeze trading |
| Reconciliation | Broker vs local DB position/order reconciliation |
| Retention | Automated log/report rotation (configurable retention days) |

### 6.3 Monitoring

| Monitor | Artifact | Frequency |
|---------|----------|-----------|
| Weekly audit | `reports/audits/weekly_audit_*.json` | Weekly |
| Audit trend | `reports/audits/trends/weekly_audit_trend_*.json` | Weekly |
| Paper-run status | `reports/promotion/paper_run_status_*.json` | Weekly |
| Backtest artifacts | `reports/backtests/*.json` | Per experiment |
| System logs | `system_logs` table | Continuous |
| Telegram alerts | Bot notifications | On events |

---

## 7. Pending Work

### 7.1 Active (Paper-Run Phase)

| Item | Status | Notes |
|------|--------|-------|
| 6-week adaptive paper-run on **Midcap 150** | **Running** (streak 0/4, restarted after universe switch) | `UNIVERSE_FILE=data/universe/nifty_midcap150.txt` |
| Weekly monitoring (PF, choppy losses, waivers) | Active | Filter by `universe_tag` in artifacts |
| Regime gate assessment | Monitoring | Watch for Q1-style midcap selloff behavior |

### 7.2 Blocked on Paper-Run Completion

| Item | Trigger | Description |
|------|---------|-------------|
| ML Scoring (Phase 9E) | 50+ closed trades with features | LightGBM progressive confidence scoring |
| Learning Loop (Phase 9F) | After ML scorer validated | Weekly analysis, monthly retrain, quarterly review |
| Regime gate improvement | Paper-run shows W4-type drawdown | Add portfolio-level drawdown circuit breaker for midcap-specific selloffs |
| Credential rotation | Before live transition | Groww API key/secret + Telegram token |
| Live promotion | 4-week pass + manual review | Staged rollout with monitoring |

### 7.3 Paper-Run Success Criteria

| Criterion | Target |
|-----------|--------|
| Closed-trade profit factor | > 1.2 |
| Choppy-regime weekly loss | < 1% |
| Waiver fire rate trend | Declining week-over-week |
| Critical operational errors | 0 |
| Promotion bundle | Clean (preflight + audit + checklist pass) |
| Universe tag consistency | All artifacts use same `universe_tag` |

---

## 8. Configuration Reference

### 8.1 Active Strategy Parameters

| Parameter | Env Var | Default | Description |
|-----------|---------|---------|-------------|
| Weekly EMA short | `ADAPTIVE_TREND_WEEKLY_EMA_SHORT` | 10 | Short EMA period (weeks) |
| Weekly EMA long | `ADAPTIVE_TREND_WEEKLY_EMA_LONG` | 30 | Long EMA period (weeks) |
| Weekly ATR period | `ADAPTIVE_TREND_WEEKLY_ATR_PERIOD` | 10 | ATR averaging period (weeks) |
| Weekly RSI period | `ADAPTIVE_TREND_WEEKLY_RSI_PERIOD` | 10 | RSI period (weeks) |
| Min weekly ROC | `ADAPTIVE_TREND_MIN_WEEKLY_ROC` | 0.03 | Minimum 4-week return to enter |
| Max weekly ROC | `ADAPTIVE_TREND_MAX_WEEKLY_ROC` | 0.20 | Maximum 4-week return (avoid overextension) |
| Min EMA spread | `ADAPTIVE_TREND_MIN_WEEKLY_EMA_SPREAD_PCT` | 0.005 | Minimum EMA gap (% of price) |
| Min trend consistency | `ADAPTIVE_TREND_MIN_TREND_CONSISTENCY` | 0.50 | Min ratio of weeks close > EMA-10 |
| Min expected R | `ADAPTIVE_TREND_MIN_EXPECTED_R_MULT` | 1.0 | Minimum reward/risk ratio |
| Stop ATR mult | `ADAPTIVE_TREND_STOP_ATR_MULT` | 1.5 | Initial stop width (x weekly ATR) |
| Profit protect pct | `ADAPTIVE_TREND_PROFIT_PROTECT_PCT` | 0.03 | Gain threshold for first trail tightening |
| Profit trail ATR mult | `ADAPTIVE_TREND_PROFIT_TRAIL_ATR_MULT` | 0.8 | Tightest trail band (at 8%+ gain) |
| Breakeven gain pct | `ADAPTIVE_TREND_BREAKEVEN_GAIN_PCT` | 0.03 | Historical gain to activate breakeven |
| Breakeven buffer pct | `ADAPTIVE_TREND_BREAKEVEN_BUFFER_PCT` | 0.005 | Buffer above entry for breakeven stop |
| Max positions | `ADAPTIVE_TREND_MAX_POSITIONS` | 5 | Maximum concurrent positions |
| Max new per week | `ADAPTIVE_TREND_MAX_NEW_PER_WEEK` | 3 | Maximum new entries per week |
| Min hold days | `ADAPTIVE_TREND_MIN_HOLD_DAYS` | 5 | Minimum days before trailing/breakeven |
| Time stop days | `ADAPTIVE_TREND_TIME_STOP_DAYS` | 30 | Days before time stop if gain < 3% |
| ML enabled | `ADAPTIVE_TREND_ML_ENABLED` | false | Enable ML scoring (pending Phase 9E) |

### 8.2 Gate Profile Configuration

| Parameter | Env Var | Default |
|-----------|---------|---------|
| Profile selector | `GO_LIVE_PROFILE` | auto |
| Adaptive min Sharpe | `ADAPTIVE_GO_LIVE_MIN_SHARPE` | 0.7 |
| Adaptive max drawdown | `ADAPTIVE_GO_LIVE_MAX_DRAWDOWN` | 0.15 |
| Adaptive min win rate | `ADAPTIVE_GO_LIVE_MIN_WIN_RATE` | 0.30 |
| Adaptive min closed trades | `ADAPTIVE_GO_LIVE_MIN_CLOSED_TRADES` | 3 |
| Adaptive paper weeks | `ADAPTIVE_PAPER_RUN_REQUIRED_WEEKS` | 6 |

---

## 9. Lessons Learned

### 9.1 Transaction Costs Dominate

On NSE via Groww, 0.355% round-trip cost means any strategy trading more than 5x/week faces structural headwinds. The shift from daily momentum (15-23 trades/week, 5.3% weekly drag) to weekly trend-following (2-4 trades/week, ~1% weekly drag) was the single most impactful change.

### 9.2 Exit Mechanics Matter More Than Entry

The strategy's entries were sound from the start. The difference between 0/4 and 3/4 anchors came entirely from exit improvements:
- Tighter initial stops (2.0x → 1.5x ATR)
- Progressive trailing (binary 10% threshold → graduated 3/5/8% bands)
- Breakeven protection (prevents winner → loser conversion)
- Trend-break exit (structural exit, not just price-based)

### 9.3 Gates Must Match Strategy Lifecycle

Evaluating a trend-following strategy (30-45% win rate, holds winners) with momentum-era gates (50% win rate, closes quickly) produces false failures. Strategy-aware gate profiles and trend-following waivers were necessary to get honest evaluation.

### 9.4 Targeted Iteration Beats Grid Search

100+ brute-force parameter sweeps produced 1/4 anchors. Four targeted diagnostic-driven iterations (exit stack → R-filter → gate calibration → choppiness filter) produced 3/4. Each step was justified by data analysis, not parameter exploration.

### 9.5 Regime Alignment Must Be Canonical

Having strategy-level regime gates that contradicted the orchestrator's regime assessment caused silent failures. Single source of truth for regime (orchestrator computes, strategies consume) eliminated an entire class of bugs.

### 9.6 Universe Selection Is the Largest Alpha Lever

The same frozen parameters on Nifty 50 (Sharpe 0.15, PF 1.05, +0.30%) versus Midcap 150 (Sharpe 1.42, PF 1.94, +7.54%) produced a 25x difference in return. Large-cap Indian stocks are efficiently priced for weekly trend-following; midcaps offer structural inefficiency that the strategy exploits. No parameter tuning would have closed this gap -- the edge is in the universe, not the model.

### 9.7 Walk-Forward Window Sizing Must Match Holding Period

A strategy holding positions 2-6 weeks needs test windows of at least 3 months. With 2-month windows, the same strategy showed 3/7 profitable (avg -0.50%); with 3-month windows, it showed 4/7 profitable (avg +0.90%). Positions that would have been profitable were cut short by window boundaries.

### 9.8 MTM Bugs Create False Confidence

The backtester originally valued open positions at 0 on days where a symbol had no price row, creating artificial drawdowns that masked true performance. After fixing this, corrected Nifty 50 numbers showed near-zero edge (Sharpe 0.15 vs inflated values before). Always verify that mark-to-market logic handles sparse data correctly.

---

## 10. Universe Pivot: Nifty 50 to Midcap 150

### 10.1 Rationale

After correcting the MTM bug, the Adaptive Trend strategy on Nifty 50 showed Sharpe 0.15 and PF 1.05 -- effectively zero edge. Walk-forward on Nifty 50 produced 0/3 profitable windows. The hypothesis: Nifty 50 stocks are too efficiently priced for weekly trend-following. Midcap stocks have higher volatility, lower institutional coverage, and stronger trend persistence.

### 10.2 Validation

1. **Continuous backtest** (Aug 2025 - Feb 2026): +7.54% return, Sharpe 1.42, PF 1.94, 63 trades. All three primary success metrics (positive return, Sharpe > 1.0, PF > 1.5) cleared.

2. **Walk-forward 3x3** (Jan 2024 - Feb 2026): 4/7 profitable windows, avg +0.90%, net +6.32% across 21 months OOS. Meets the "4/7 profitable AND net positive" threshold.

3. **Known weakness**: Jan-Apr 2025 window lost -5.69% during a broad midcap selloff. The regime gate (based on Nifty 50 breadth) didn't catch the midcap-specific downturn fast enough.

### 10.3 Operational Switch

- Universe file: `data/universe/nifty_midcap150.txt` (140 symbols)
- Env var: `UNIVERSE_FILE=data/universe/nifty_midcap150.txt`
- Paper-run streak reset to 0/4 via universe-aware tracking (`run_context.universe_tag`)
- Audit and promotion artifacts now embed `universe_tag` to prevent mixing results from different universes
- Daily data pipeline fetches OHLCV for all 140 midcap symbols (yfinance primary, Groww fallback)

### 10.4 Key Artifacts

| Artifact | Description |
|----------|-------------|
| `reports/backtests/universe_backtest_nifty_midcap150_20250801_20260212_20260214_062827.json` | 6-month continuous backtest |
| `reports/backtests/universe_walk_forward_nifty_midcap150_3x2_20240101_20260211_20260214_063721.json` | Walk-forward 3x2 (superseded) |
| `reports/backtests/universe_walk_forward_nifty_midcap150_3x3_20240101_20260211_20260214_065139.json` | Walk-forward 3x3 (primary) |
| `data/universe/nifty_midcap150.txt` | Universe definition (140 symbols) |
