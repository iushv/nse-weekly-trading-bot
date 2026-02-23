# Indian Stock Trading Bot - Implementation Plan (Updated)

## Objective
Build a modular Indian swing-trading system with strategy diversification, strict risk controls, backtesting-first workflow, and guarded transition to live execution.

## Documentation Governance (Single Source of Truth)
This file is the canonical source of truth for:
- current runtime status,
- implementation timeline,
- roadmap and blockers,
- promotion readiness.

All high-level status tracking should be updated here first. Other docs should stay runbook-focused (how-to), not status-focused.

## Update Cadence
1. **Daily**: append runtime-relevant status changes when correctness, data coverage, or execution safety changes.
2. **Weekly (Sunday audit window)**: update promotion readiness, trend metrics, and blocker state.
3. **Per major commit batch**: record what changed, why, and measurable impact (metrics/tests).

## Current Status (as of 2026-02-21)
1. Runtime mode: **Paper** (`main.py --mode paper`)
2. Active strategy stack: **Adaptive Trend only** (`STRATEGY_PROFILE=adaptive`)
3. Universe mode: **Deterministic Midcap150 via `UNIVERSE_FILE`** (151 symbols)
4. Data coverage state: **Daily universe coverage repaired through 2026-02-20**
5. Open positions: **1 (SUNDARMFIN)**, no closed trades in current adaptive paper-run streak
6. Promotion readiness: **Not ready** (insufficient closed-trade sample and week streak)
7. Critical accounting/restart correctness fixes: **Implemented and validated** (see timeline below)
8. Next major phase: **Step 7 tuning gated until full Monday diagnostic logs are collected**

## Timeline: 2026-02-14 to 2026-02-21
### 2026-02-14 to 2026-02-20 (Paper Run + Data Reliability)
- Bhavcopy-based daily pipeline remained primary EOD source.
- Pre-market and EOD data-repair guards were active.
- Universe-level coverage was repaired to full expected symbol count for trade-day readiness.

### 2026-02-21 (P0/P1 Correctness and Reliability Fix Batch)
- Fixed restart cash/accounting inflation:
  - `main.py:_restore_open_positions_from_db()` now reconstructs cash from trade ledger:
    - `STARTING_CAPITAL - sum(entry costs) + sum(closed exit proceeds)`.
- Added one-time historical snapshot repair script:
  - `scripts/repair_portfolio_snapshots.py`
  - dry-run then applied to correct inflated rows.
- Scoped market-data load to configured runtime universe:
  - `main.py:_load_market_data()` now filters by `self.universe`.
- Persisted and restored open-position trailing state:
  - new `trades` columns: `highest_close`, `lowest_close`, `weekly_atr`
  - DB migration safety in `trading_bot/data/storage/database.py`
  - open-position state now persists during intraday updates.
- Added restart reconstruction for risk limits:
  - `RiskManager` now reconstructs daily and weekly realized PnL from closed trades.

### 2026-02-21 (P2 Step 6 Diagnostics)
- Added adaptive-trend signal diagnostics:
  - per-scan rejection counters,
  - per-condition rejection reason breakdown.
- Optimized rejection-path overhead to avoid duplicate entry-condition evaluation.

## Delivery Status Snapshot (as of 2026-02-21)
1. Phase 1-8 platform buildout and safety controls (former items 1-55): **Completed**
2. P0/P1 correctness and restart reliability fixes (former items 56-60): **Completed**
3. P2 step 6 diagnostic instrumentation (former item 61): **Completed**
4. Production rollout controls and paper-run acceptance gating: **In Progress**
5. Anchor validation plus adaptive paper-run evidence collection: **In Progress**
6. ML scoring package (`trading_bot/ml/scorer.py`): **Pending**
7. Automated learning loop (`trading_bot/ml/learning_loop.py`): **Pending**

## Completed Milestones
### Phase 1-2: Foundation + Data Infra
- Project structure created under `trading_bot/` with module boundaries.
- Config system + env validation implemented (`trading_bot/config/settings.py`).
- SQLite schema + DB helper layer implemented (`trading_bot/data/storage/`).
- Market and alternative data collectors integrated with retries and cache fallback.

### Phase 3-4: Strategies + Backtesting
- Implemented `momentum_breakout`, `mean_reversion`, `sector_rotation`.
- Backtest engine and walk-forward analysis implemented with transaction costs.

### Phase 5-7: Risk, Execution, Reporting, Orchestration
- Risk manager with portfolio heat, daily/weekly limits, emergency stop.
- Broker interface supports `mock`, `groww`, and generic `http` providers.
- Telegram reporting and report generation integrated.
- Main scheduler flow implemented (`main.py`) with paper/live modes.

### Phase 8+: Validation and Live Safety
- Tests expanded (integration + contracts + safety): currently passing.
- Groww live smoke script added (`scripts/groww_live_smoke.py`):
  - Read-only auth/funds/positions check
  - Optional guarded order placement
  - Simulated funded BUY->SELL roundtrip with P&L
  - Optional DB persistence of closed roundtrip trades
- Live-order execution now fail-closed by default:
  - New settings: `LIVE_ORDER_EXECUTION_ENABLED` + `LIVE_ORDER_FORCE_ACK`
  - Required ack phrase: `YES_I_UNDERSTAND_LIVE_ORDERS`
  - If not armed, live mode auto-forces dry-run behavior and blocks broker order placement.
  - Smoke script order placement is also blocked unless armed.
- Preflight health script added (`scripts/preflight_check.py`):
  - Environment + database checks
  - Optional broker read-only check
- Weekly performance audit script added (`scripts/weekly_performance_audit.py`):
  - Trailing-window performance metrics from `portfolio_snapshots` + `trades`
  - Threshold gates for Sharpe, drawdown, win-rate, closed-trade count
  - Critical log gate from `system_logs` (ERROR/CRITICAL)
  - Exit code supports CI/automation enforcement
- Telegram reporter hardened for mixed sync/async runtime contexts:
  - Safe async execution fallback without closed-loop crashes
  - Fresh bot session per send to avoid cross-loop pool errors
- Market data update hardened:
  - Skip remote daily refresh when local DB data is already fresh (3-day threshold)
  - Fallback from `Ticker.history` to `yf.download` for transient Yahoo failures
- Baseline backtest summary now exported to:
  - `reports/backtests/latest_backtest_summary.json`

### Phase 9: Adaptive Trend System (Economics Fix + Self-Improvement)

> Full technical spec: [`PHASE9_SPEC.md`](PHASE9_SPEC.md)

**Rationale**: Parameter tuning exhausted (100+ experiments, 1/4 max). Root cause: 15-23 trades/week at 0.355% round-trip = 5.3%+ weekly cost drag. Phase 9 shifts to fewer trades (2-4/week), longer holds (2-6 weeks), and adds self-improving ML.

**Sub-items** (details in `PHASE9_SPEC.md`):
- **9A**: Adaptive Trend strategy (weekly trend + daily entry, trailing stops, hard regime gate)
- **9B**: Feature persistence layer (`trade_features` table, fixes metadata loss gap)
- **9C**: Adaptive position sizing (half-Kelly + confidence + drawdown scaling)
- **9D**: BacktestEngine trailing-stop support (`highest_close`/`lowest_close`)
- **9E**: ML scoring (LightGBM, progressive rules->ensemble->ML-primary)
- **9F**: Automated learning loop (weekly analysis, monthly retrain, quarterly review)
- **9G**: Orchestrator integration (feature wiring in entry/exit, learning scheduler)
- **9H**: Configuration (16 new env vars)
- **9I**: Dependencies (lightgbm, scikit-learn, joblib)
- **9J**: Test suite (12 tests)

## Current Quality Gates (Active Today)
1. `ruff check .` must pass
2. `mypy --config-file pyproject.toml trading_bot main.py paper_trading.py scripts` must pass
3. `pytest -q` must pass
4. `python scripts/preflight_check.py --include-broker --fail-on-broker --pretty` should pass before live runs
5. Live orders must remain unarmed unless explicit go-live decision is made:
   - `LIVE_ORDER_EXECUTION_ENABLED=0` and empty `LIVE_ORDER_FORCE_ACK` in normal development/paper trading.

## Phase 9 Quality Gates (Post-Implementation)
> These gates become active only after Phase 9A-9D are implemented and wired into the codebase.

6. Adaptive trend multi-anchor validation (canonical command):
   ```
   ENABLE_ADAPTIVE_TREND=1 ENABLE_MOMENTUM_BREAKOUT=0 ENABLE_MEAN_REVERSION=0 ENABLE_SECTOR_ROTATION=0 ENABLE_BEAR_REVERSAL=0 ENABLE_VOLATILITY_REVERSAL=0 python scripts/multi_week_gate_search.py
   ```
   Must show improvement over momentum baseline (>1/4 anchors). Use `structural_gate_sweep.py` as secondary single-window diagnostic only.
7. Feature persistence integrity: `SELECT count(*) FROM trade_features WHERE outcome_label IS NOT NULL` must match closed adaptive-trend trade count in `trades` table.

## 2026-02-12 Verification Update
1. Verification checks executed:
   - `ruff check .`: pass
   - `mypy .`: pass
   - `pytest` targeted safety/integration suites: pass
2. Coverage tooling status:
   - `pytest --cov` unavailable in current environment (missing `pytest-cov`, package install blocked by DNS/network resolution limits).
3. Broker connectivity verification:
   - `scripts/groww_live_smoke.py` in read-only mode failed due to DNS resolution to `api.groww.in` (connectivity issue, not order execution).
   - `scripts/preflight_check.py --include-broker --fail-on-broker --pretty`:
     - Passes with `BROKER_PROVIDER=mock`.
     - Degraded with `BROKER_PROVIDER=groww` due to same DNS resolution issue.
4. Post-change regression checks:
   - `structural_gate_sweep` (bounded) still shows known baseline behavior.
   - `multi_week_gate_search` (bounded) remains robustness-blocked (no anchor pass lift yet).


## 2026-02-13 Validation Update
1. Backtest valuation correction:
   - Fixed `BacktestEngine` mark-to-market when a symbol is missing on a trading day (fallback to last known mark instead of zero).
   - Regression test added: `tests/test_backtesting_integration.py::test_backtest_marks_open_positions_when_symbol_missing_for_day`.
2. Full test suite status:
   - `pytest -q`: pass (`89 passed`).
3. Extended continuous adaptive backtest (2025-01-01 to 2026-02-12):
   - Artifact: `reports/backtests/adaptive_continuous_20260213_185x_fix_193638.json`
   - Metrics: return `+0.30%`, Sharpe `0.15`, max drawdown `-6.73%`, total trades `41`, win rate `48.8%`, profit factor `1.05`.
4. Walk-forward robustness check (3m train / 2m test):
   - Artifact: `reports/backtests/adaptive_walk_forward_3x2_fix_20260213_193711.json`
   - Summary: avg return `-0.53%`, consistency `0/3` profitable windows, avg Sharpe `-0.93`.
   - Interpretation: anchor robustness improved, but long-window robustness remains weak; keep paper-run gate conservative until additional edge work.

## Experiment History (Archive)
- Detailed failed/neutral experiment logs were moved to `docs/EXPERIMENT_HISTORY.md` to keep this plan focused on current status.
- Summary: 100+ parameter and structure experiments were exhausted before pivoting to adaptive trend and Midcap150.

## Runtime Reliability Update (Auto-Resume + Recovery)
- Implemented restart-safe runtime recovery for paper/live scheduler in `main.py`.
  - New persistent state file: `control/runtime_state.json`.
  - Persists:
    - last successful routine date/timestamp (`pre_market`, `market_open`, `market_close`, weekly ops),
    - pending signals generated in pre-market (with consumed flag).
- Implemented automatic recovery cycle:
  - On startup and periodically during scheduler loop, the bot now checks for missed routines and runs them within configured windows.
  - Recovery windows are env-configurable:
    - `AUTO_RESUME_PREMARKET_START/CUTOFF`
    - `AUTO_RESUME_MARKET_OPEN_START/CUTOFF`
    - `AUTO_RESUME_MARKET_CLOSE_START/CUTOFF`
  - Default behavior:
    - pre-market recovery: `08:00` to `10:00`
    - market-open recovery: `09:15` to `11:30`
    - market-close recovery: `15:30` to `21:00`
- Added state restoration on restart:
  - Restores latest portfolio cash/value from `portfolio_snapshots`.
  - Restores open positions from `trades` table (`status='OPEN'`) into memory.
  - Prevents duplicate entries when position already open.
- Added pending signal restore:
  - If process restarts before market-open execution, `market_open_routine` reloads same-day pending signals from runtime state and continues.
- Added tests:
  - `tests/test_auto_resume.py`:
    - pending signal persist/restore path,
    - recovery of missed pre-market + market-open,
    - recovery of missed market-close.
- Added Windows long-run operational setup:
  - `scripts/windows/run_paper_bot.ps1` (paper-safe runner with crash restart loop),
  - `scripts/windows/install_startup_task.ps1` (Task Scheduler install),
  - `scripts/windows/manage_startup_task.ps1` (start/stop/status/remove),
  - `scripts/windows/bootstrap_windows.ps1` (one-click Windows setup + paper-safe autorun install),
  - `docs/WINDOWS_AUTORUN.md` runbook.
  - `docs/WINDOWS_MIGRATION_SETUP.md` migration + continuity runbook.

## Remaining Work to Production
1. **Complete one full live-paper diagnostic day (Monday) before threshold tuning.**
   - Required evidence: adaptive scan logs with rejection reason counts and corrected breadth behavior.
2. **Execute Step 7 tuning in isolated commits with backtest deltas per step.**
   - Step 7.1: continuous tighten scoring only.
   - Step 7.2: daily RSI band `40-72` only.
   - Step 7.3: min volume ratio `0.65` only.
   - For each: record before/after `Sharpe`, `Profit Factor`, `trade count`.
3. **Rebuild paper-run streak under corrected accounting.**
   - Portfolio and audit metrics are now corrected; gather fresh weekly artifacts post-fix.
4. **Increase closed-trade sample size to unlock statistically meaningful promotion decisions.**
   - Current blocker remains low trade throughput in weak market regimes.
5. **Keep Phase 9E-9F (ML scoring and learning loop) deferred until signal flow and closed-trade sample are sufficient.**
6. **Proceed to staged live only after promotion gates and manual review are both satisfied.**

## Current Roadblocks
1. **Signal drought under weak breadth conditions.**
   - Even with relaxed market days, entry filters can still reject all candidates.
2. **Insufficient closed trades for promotion confidence.**
   - Open-position mark-to-market can move, but gates rely on realized outcomes.
3. **Upstream NSE endpoint instability remains intermittent.**
   - Data-repair guards mitigate this operationally, but it still adds latency/noise.
4. **Environment/tooling gaps on local machine.**
   - `ruff`/`mypy` modules not installed in the active venv during this patch cycle.

## Immediate Next Iteration
1. Let Monday (`2026-02-23`) complete end-to-end in paper mode with diagnostics enabled.
2. Extract and review adaptive scan diagnostics (rejection breakdown + regime context).
3. Start Step 7 tuning in strict sequence:
   - Commit A: continuous tighten scoring.
   - Commit B: RSI band `40-72`.
   - Commit C: volume ratio `0.65`.
4. After each commit, run:
   - `scripts/run_universe_backtest.py` on Midcap150,
   - and log metric delta table in this document.
5. Keep live order path fail-closed and keep single bot instance policy enforced.

## 2026-02-23 Step 7 Tuning Log (Midcap150 Backtest Window)
- Backtest window: `2025-08-01` to `2026-02-20`
- Universe: `data/universe/nifty_midcap150.txt` (151 symbols)
- One-off runtime repair completed for pre-fix open trade:
  - `SUNDARMFIN` open row updated in `trades` with `weekly_atr=335.25`, `highest_close=5331.0`, `lowest_close=5175.0`
- Observability patch completed:
  - adaptive scan diagnostics now persist in `system_logs` `signal_funnel` metadata under `scan_diagnostics.adaptive_trend`

Artifacts:
- Baseline: `reports/backtests/universe_backtest_nifty_midcap150_20250801_20260220_20260223_053300.json`
- Step 7.1: `reports/backtests/step71_backtest_20250801_20260220.json`
- Step 7.2: `reports/backtests/step72_backtest_20250801_20260220.json`
- Step 7.3: `reports/backtests/step73_backtest_20250801_20260220.json`

| Step | Sharpe | PF (closed) | Trade Count | Delta |
|---|---:|---:|---:|---|
| Baseline | -1.1299 | 0.5222 | 60 | n/a |
| Step 7.1 (continuous tighten scoring + lower tighten increments) | -1.1299 | 0.5222 | 60 | No change vs baseline |
| Step 7.2 (daily RSI band `40-72`) | -0.4765 | 0.7830 | 58 | Sharpe `+0.6534`, PF `+0.2609`, trades `-2` vs Step 7.1 |
| Step 7.3 (base min volume ratio `0.65`) | -0.4549 | 0.7648 | 56 | Sharpe `+0.0216`, PF `-0.0182`, trades `-2` vs Step 7.2 |

Interpretation:
- Step 7.2 delivered the largest uplift on this window.
- Step 7.3 slightly improved Sharpe and drawdown but reduced PF versus Step 7.2.
- Absolute promotion thresholds remain unmet on this window (Sharpe and PF both below target).

## 2026-02-23 Regime-Aware Backtest Wiring (Engine Parity Fix)
- Implemented shared regime utility: `trading_bot/data/processors/regime.py` (`compute_market_regime`).
- `main.py:_compute_market_regime()` now delegates to shared utility (single source of truth).
- `BacktestEngine.run_backtest()` now computes/passes `market_regime` per day by default (`include_regime=True`).
- Added `include_regime` toggle and `regime_summary` output in backtest results.
- Added CLI toggle `--no-regime` in `scripts/run_universe_backtest.py` for A/B validation.

Artifacts (same window as Step 7 log):
- Regime ON: `reports/backtests/regime_aware_backtest_20250801_20260220_20260223_v2.json`
- Regime OFF: `reports/backtests/regime_off_backtest_20250801_20260220_20260223.json`

Observed delta (2025-08-01 to 2026-02-20):
- Regime ON: Sharpe `-3.4573`, PF `0.2538`, trades `47`.
- Regime OFF: Sharpe `-0.4549`, PF `0.7648`, trades `56`.
- Regime summary (ON): favorable `59/138` days (`42.75%`), labels `{favorable:59, choppy:38, bearish:38, defensive:3}`.

Note:
- The Step 7 table above was produced before this engine-parity fix and is effectively a regime-off benchmark.
- All future Step 7 deltas should be recomputed with regime ON to reflect runtime behavior.

Regime-aware Step 7 matrix (config-driven, same window):
- Step 7.1 artifact: `reports/backtests/regime_on_step71_cfg_20250801_20260220_20260223.json`
- Step 7.2 artifact: `reports/backtests/regime_on_step72_cfg_20250801_20260220_20260223.json`
- Step 7.3 artifact: `reports/backtests/regime_on_step73_cfg_20250801_20260220_20260223.json`

| Step | Sharpe | PF (closed) | Trade Count | Delta vs Step 7.1 |
|---|---:|---:|---:|---|
| Step 7.1 (continuous tighten scoring; RSI `45-70`; volume `0.80`) | -2.4069 | 0.3339 | 43 | baseline |
| Step 7.2 (+ RSI `40-72`) | -1.9118 | 0.4069 | 42 | Sharpe `+0.4951`, PF `+0.0730`, trades `-1` |
| Step 7.3 (+ volume `0.65`) | -3.4573 | 0.2538 | 47 | Sharpe `-1.5455`, PF `-0.0800`, trades `+4` |

Interpretation:
- Under regime-aware execution, Step 7.2 improved Sharpe and PF versus Step 7.1.
- Step 7.3 materially degraded performance on this window and should not be promoted without further guardrails.

## 2026-02-23 Binary Regime Gate Removal Trial (Option 1)
- Change applied: adaptive binary gate disabled (`_regime_allows_entry()` no longer blocks entries); regime still feeds tighten-steps.
- Default base volume floor reverted to `ADAPTIVE_MIN_VOLUME_RATIO=0.80` (Step 7.3 rollback).
- Test status after change: `pytest tests -q` -> `101 passed`.

Artifacts:
- No-binary-gate + RSI `40-72` + volume `0.80`:
  - `reports/backtests/regime_on_no_binary_gate_step72default_20250801_20260220_20260223.json`
- No-binary-gate + RSI `40-72` + volume `0.65` (comparison):
  - `reports/backtests/regime_on_no_binary_gate_vol065_20250801_20260220_20260223.json`

Metrics (2025-08-01 to 2026-02-20, include_regime=true):
- With binary gate ON + Step 7.2 (`40-72`, `0.80`): Sharpe `-1.9118`, PF `0.4069`, trades `42`.
- With binary gate OFF + Step 7.2 (`40-72`, `0.80`): Sharpe `-0.2135`, PF `0.8711`, trades `53`.
- With binary gate OFF + volume `0.65`: Sharpe `-0.9559`, PF `0.6106`, trades `62`.

Interpretation:
- Removing the binary regime block materially improved performance on this window while preserving regime-aware threshold tightening.
- Lowering volume floor to `0.65` remains harmful even after removing the binary gate; keep `0.80` as default.

## 2026-02-23 Step 8 Exit Cascade Tuning (Regime-aware, binary gate OFF)
- Objective: improve the Step 7.2 no-binary-gate baseline (`Sharpe -0.2135`, `PF 0.8711`, `53 trades`).
- Code changes shipped:
  - `scripts/run_universe_backtest.py`: `--include-trades` flag + `exit_breakdown` summary in JSON output.
  - `trading_bot/config/settings.py`: added `ADAPTIVE_TREND_TRAIL_TIER2_GAIN`, `ADAPTIVE_TREND_TRAIL_TIER2_MULT`, `ADAPTIVE_TREND_TRAIL_TIER3_GAIN`, `ADAPTIVE_TREND_TRAIL_TIER3_MULT`.
  - `trading_bot/strategies/adaptive_trend.py`: progressive trail tiers are now configurable via constructor/env values.

Artifacts:
- Baseline with trade diagnostics:
  - `reports/backtests/step8_baseline_20250801_20260220_20260223b.json`
- Parameter sweeps:
  - `reports/backtests/step8_82a_breakeven_gain_005_20250801_20260220_20260223b.json`
  - `reports/backtests/step8_82b_breakeven_buffer_002_20250801_20260220_20260223b.json`
  - `reports/backtests/step8_82ab_breakeven_gain005_buffer002_20250801_20260220_20260223b.json`
  - `reports/backtests/step8_82cde_trail_shift_20250801_20260220_20260223b.json`
  - `reports/backtests/step8_82f_time_stop_42_20250801_20260220_20260223b.json`
  - `reports/backtests/step8_best_combo_82a_82f_20250801_20260220_20260223b.json`

Step 8 delta table:

| Step | Sharpe | PF (closed) | Trades | Win % | Avg Hold | Delta vs baseline |
|---|---:|---:|---:|---:|---:|---|
| Baseline | -0.2135 | 0.8711 | 53 | 45.3 | 19.3 | baseline |
| 8.2a (`breakeven_gain_pct=0.05`) | -0.3525 | 0.8126 | 52 | 42.3 | 19.6 | Sharpe `-0.1390`, PF `-0.0585` |
| 8.2b (`breakeven_buffer_pct=0.02`) | -0.7658 | 0.6940 | 59 | 44.1 | 17.3 | Sharpe `-0.5523`, PF `-0.1772` |
| 8.2a+b combined | -0.3269 | 0.8228 | 52 | 44.2 | 19.6 | Sharpe `-0.1134`, PF `-0.0483` |
| 8.2c+d+e (trail tier shift) | -0.6200 | 0.7011 | 55 | 40.0 | 18.6 | Sharpe `-0.4065`, PF `-0.1700` |
| 8.2f (`time_stop_days=42`) | -0.2163 | 0.8729 | 51 | 39.2 | 20.1 | Sharpe `-0.0028`, PF `+0.0017` |
| Best-combo trial (`8.2a+8.2f`) | -1.3273 | 0.5051 | 49 | 36.7 | 22.5 | Sharpe `-1.1138`, PF `-0.3660` |

Interpretation:
- No tested Step 8 parameter change improved Sharpe above the baseline; none achieved positive Sharpe.
- Baseline remains the best Sharpe configuration on this window.
- `8.2f` reduced `TIME_STOP` losses but materially increased `STOP_LOSS` losses.
- `8.2b` and trail-tier shifts were clearly harmful.

## 2026-02-23 Step 9 Execution Framework (PF-first, low-run budget)
- Runtime/backtest parity fixes implemented:
  - `main.py`: adaptive strategy constructor now passes `trail_tier2_*`, `trail_tier3_*`, `max_weekly_atr_pct`, `transaction_cost_pct`.
  - `trading_bot/risk/position_sizer.py`: `MAX_LOSS_PER_TRADE` cap now applies in both `size_position()` and `size_position_adaptive()`.
  - `scripts/run_universe_walk_forward.py`: strategy construction now uses `Config`-driven adaptive parameters (same shape as `run_universe_backtest.py`).
  - `.env.example`: added `MAX_LOSS_PER_TRADE` and `ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT`.

- Test coverage added for parity and sizing:
  - `tests/test_runtime_adaptive_wiring.py`: verifies `TradingBot` passes new adaptive runtime knobs.
  - `tests/test_risk_validation.py`: verifies runtime sizing cap on both standard and adaptive sizing paths.
  - `tests/test_backtesting_integration.py`: verifies runtime sizing and backtest sizing are aligned under `MAX_LOSS_PER_TRADE`.
  - Validation run: `pytest tests -q` => `109 passed`.

- Constrained optimization runner added:
  - New script: `scripts/run_step9_factorial.py`
  - Purpose: enforce a fixed PF-first 12-run cycle (baseline + 8-factorial + retest + holdout + walk-forward) over:
    - `ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT`
    - `MAX_LOSS_PER_TRADE`
    - `ADAPTIVE_TREND_STOP_ATR_MULT`
  - Includes hard rejection gates (`PF`, `Sharpe`, trade-count band, `STOP_LOSS` degradation) and ranked candidate selection.

## Phase 9 File Manifest

> Full file inventory with line estimates and recommended config: [`PHASE9_SPEC.md`](PHASE9_SPEC.md#file-manifest)
>
> 6 new files, 8 modified files. No existing strategies are removed.


## 2026-02-14 Data Source Migration (bhavcopy)

### Problem
yfinance completely broken for NSE `.NS` symbols regardless of version:
- v0.2.33 / v0.2.50: `datetime - str` TypeError, timezone errors, empty body (rate-limit/cookie blocking)
- v1.1.0: 404 `Quote not found for symbol: TATAMOTORS.NS`
- US stocks (AAPL) work fine — Yahoo reachable but NSE symbols blocked

Groww historical API tested: auth works (token refresh confirmed), but `/v1/historical/candles` returns 403 — requires Pro/Premium plan. Standard developer key only covers order + auth endpoints.

Alternatives tested and failed:
- `jugaad-data 0.29`: JSONDecodeError — NSE blocks without JS-rendered cookies
- `pandas-datareader` Stooq: 0 rows — doesn't carry NSE individual stocks
- BSE Bhavcopy (old URL): 404

### Solution: NSE UDiFF Bhavcopy
NSE switched to CM-UDiFF Common Bhavcopy format from July 8, 2024.

URL format: `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`

Returns 3250 rows (2410 EQ-series stocks) per day, 182KB ZIP. No auth required, no rate limiting observed.

### Symbol Demerger Fixes
6 symbols in Midcap 150 universe no longer exist in bhavcopy:

| Old Symbol | New Symbol | Reason |
|---|---|---|
| `AEGISCHEM` | `AEGISVOPAK` | Demerged → Aegis Vopak Terminals (mid-2025) |
| `AMARAJABAT` | `ARE&M` | Renamed to Amara Raja Energy & Mobility |
| `GMRINFRA` | `GMRAIRPORT` | Demerged → GMR Airports (mid-2025) |
| `SAILCORP` | `SAIL` | Invalid symbol, Steel Authority is SAIL |
| `TATAMOTORS` | `TMCV` | Demerged CV business (~late 2025) |
| `VARUNBEV` | `VBL` | Symbol changed to VBL |

Updated files:
- `data/universe/nifty_midcap150.txt`
- `data/cache/nifty_midcap150_symbols.json`

### Code Changes (`trading_bot/data/collectors/market_data.py`)
- Added `_bhavcopy_cache: dict` to cache full day DataFrames in memory
- Added `_fetch_bhavcopy_day(trading_date)`: downloads + extracts ZIP, filters EQ-series, caches
- Added `_fetch_historical_data_bhavcopy(symbol, start_date, end_date)`: day-by-day OHLCV build
- Updated `fetch_historical_data()` priority: `bhavcopy` first for `auto` provider
- Added `"bhavcopy"` to valid provider list
- Config: `MARKET_DATA_PROVIDER=bhavcopy` in `.env`

### Backfill Completed
- Pass 1: 151 symbols backfilled (2024-01-01 → 2026-02-14), 524 rows each
  - `AEGISCHEM`: 105 rows (partial — existed until demerger mid-2025)
  - `GMRINFRA`: 232 rows (partial — existed until demerger)
  - `TATAMOTORS`: 447 rows (partial — demerged late 2025)
  - `AMARAJABAT`, `SAILCORP`, `VARUNBEV`: 0 rows (confirmed dead symbols)
- Pass 2: 6 renamed symbols backfilled
  - `AEGISVOPAK`: 177 rows, `GMRAIRPORT`: 292 rows, `TMCV`: 55 rows
  - `ARE&M`, `SAIL`, `VBL`: 524 rows each
- Database: `trading_bot.db` fully populated, 157 distinct symbols

### Bot Restart
- Started via `python main.py --mode paper`
- Confirmed: `Using UNIVERSE_FILE universe: 151 symbols`, all 3 strategies enabled, scheduler started, no errors
- Task Scheduler update pending (requires admin PowerShell)

---

## Midcap 150 Universe Pivot (Decision)
- Baseline (Nifty 50-ish universe, 6-month continuous): near-zero edge
  - Artifact: `reports/backtests/adaptive_continuous_6m_20250801_20260212_20260214_054821.json`
  - Metrics: return `+0.30%`, Sharpe `0.22`, PF `1.05`, trades `41`, max DD `-6.73%`
- Midcap 150 (same frozen strategy parameters, 6-month continuous): strong edge
  - Metrics observed: return `+7.54%`, Sharpe `1.42`, PF `1.94`, trades `63`, max DD `-4.52%`
- Midcap 150 walk-forward (3m train / 3m test) to match hold period:
  - Artifact: `reports/backtests/universe_walk_forward_nifty_midcap150_3x3_20240101_20260211_20260214_065139.json`
  - Summary: profitable windows `4/7`, avg return `+0.90%` (note: 1 window had 0 trades), avg Sharpe `0.63`
- Decision: treat Midcap 150 as the active paper-run universe candidate.
  - Switch via `UNIVERSE_FILE=data/universe/nifty_midcap150.txt` (or regenerate file with `scripts/update_universe_midcap150.py`).
  - Paper-run streak must be tracked per-universe (implemented via `run_context.universe_tag`).
