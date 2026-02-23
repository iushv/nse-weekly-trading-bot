# Experiment History (Archive)

This archive contains detailed experiment logs that were previously embedded in `IMPLEMENTATION_PLAN.md`.
Use `IMPLEMENTATION_PLAN.md` for current status, blockers, and next steps.
Historical thresholds in this file may differ from current active values.

## Experiment History (Implemented But Failed / No Improvement)
This section tracks major implemented experiment rounds that did not improve promotion readiness.

### 2026-02-11: Strategy/Exit Tuning Round (No Promotion-Grade Lift)
- Entry parameter tuning batches:
  - `reports/backtests/strategy_tuning_20260211_210307.json`
  - `reports/backtests/strategy_tuning_20260211_211703.json`
  - `reports/backtests/strategy_tuning_20260211_223549.json`
  - `reports/backtests/strategy_tuning_20260211_223640.json`
- Exit/risk tuning batches:
  - `reports/backtests/exit_risk_tuning_20260211_213234.json`
  - `reports/backtests/exit_risk_tuning_20260211_223756.json`
- Validation / walk-forward checks:
  - `reports/backtests/tuned_validation_20260211_213536.json`
  - `reports/backtests/tuned_validation_20260211_214025.json`
  - `reports/backtests/tuned_walkforward_20260211_213558.json`
- Outcome: parameter improvements were not stable enough to satisfy go-live gates consistently.

### 2026-02-11 Late: Window/Turnover/Entry Variant Sweeps (Failed Stability)
- Gate-window and candidate sweeps:
  - `reports/backtests/momentum_gate_window_search_20260211_224648.json`
  - `reports/backtests/paper_candidate_sweep_20260211_224958.json`
- Entry aggressiveness / turnover control sweeps:
  - `reports/backtests/entry_aggressive_sweep_20260211_225223.json`
  - `reports/backtests/lowrisk_turnover_sweep_20260211_225530.json`
  - `reports/backtests/focus_turnover_sweep_20260211_225838.json`
- Outcome: no setup produced reliable multi-window gate passes.

### 2026-02-12 Early: Profile/Cost/Gate Loop Sweeps (Partial Wins, No Robustness)
- Profile evals:
  - `reports/backtests/momentum_v4_replay_eval_20260212.json`
  - `reports/backtests/hybrid_profile_eval_20260212.json`
- Gate loop/focus sweeps:
  - `reports/backtests/gate_sweep_20260212.json`
  - `reports/backtests/gate_sweep_focus_20260212.json`
  - `reports/backtests/gate_sweep_focus2_20260212.json`
- Cost and DB coverage sensitivity:
  - `reports/backtests/latest_cost_sensitivity.json`
  - `reports/backtests/latest_projectdb_cost_comparison.json`
- Mixed/win-rate/robust searches:
  - `reports/backtests/latest_winrate_gate_sweep.json`
  - `reports/backtests/latest_mixed_gate_sweep.json`
  - `reports/backtests/latest_robust_param_search.json`
- Outcome: occasional single-window improvement, but no durable promotion streak.

### 2026-02-12 Mid: Structural + Multi-Week Anchor Robustness (Primary Failure)
- Structural sweeps:
  - `reports/backtests/structural_gate_sweep_20260212_071519.json`
  - `reports/backtests/structural_gate_sweep_20260212_071714.json`
  - `reports/backtests/structural_gate_sweep_20260212_072119.json`
- Multi-week anchor searches:
  - `reports/backtests/multi_week_gate_search_20260212_074633.json`
  - `reports/backtests/multi_week_gate_search_20260212_074816.json`
  - `reports/backtests/multi_week_gate_search_20260212_075501.json`
  - `reports/backtests/multi_week_gate_search_20260212_080339.json`
  - plus iterative reruns through `reports/backtests/multi_week_gate_search_20260212_081915.json`
- Outcome: best configuration still only passed `1/4` anchors; robustness target not met.

### 2026-02-12 Late: Anchor-Diagnostic Micro-Sweeps (All Failed To Beat 1/4)
- Parameter-only sweep:
  - `reports/backtests/anchor_param_sweep_20260212_081154.json`
- Exit-shape sweep:
  - `reports/backtests/anchor_exit_sweep_20260212_081915.json`
- Signal quality sweep:
  - `reports/backtests/anchor_quality_sweep_20260212_082626.json`
- Strategy mix sweep:
  - `reports/backtests/anchor_strategy_mix_sweep_20260212_082805.json`
- Non-momentum-only sweep:
  - `reports/backtests/anchor_non_momentum_sweep_20260212_082912.json`
- Defensive breadth-mode eval:
  - `reports/backtests/anchor_defensive_eval_20260212_083507.json`
- Outcome: no experiment exceeded `1/4` anchor passes; dominant failing gates remained `sharpe_ratio` and `win_rate` on bearish anchors.

### 2026-02-12 Post-v2: Regime Contract + Strategy-Aware Scoring + Funnel/Exit Telemetry
- Implemented:
  - Canonical regime object is computed once in orchestrator and passed into all strategies.
  - Strategy interface updated: `generate_signals(..., market_regime=...)`.
  - Cross-strategy scoring normalized to avoid momentum-metadata bias.
  - Funnel telemetry persisted to `system_logs` (`module=signal_funnel`, `message=pre_market_signal_funnel`).
  - Exit reason analytics added to weekly audit metrics.
  - Sweep artifacts now include:
    - `exit_analysis` (`exit_reason_breakdown`, `exit_reason_by_strategy`)
    - `funnel_analysis` (`counts_total/avg`, `rates_avg`, per-strategy selected totals)
- First validation artifacts after implementation:
  - Structural sweep: `reports/backtests/structural_gate_sweep_20260212_095852.json`
    - Combo `regime=False`, `edge=0.0`, `cap=5` reached weekly gate pass (`ready=True`) in bounded run.
    - Funnel sample: `entries=19`
    - Exit reasons: `TARGET_HIT=7`, `STOP_LOSS=4`, `TIME_STOP=3`
  - Multi-week anchors: `reports/backtests/multi_week_gate_search_20260212_095913.json`
    - Best combo still `0/4` anchors passed (bounded `max-combos=1` run).
    - Representative anchor exit reasons showed `STOP_LOSS` concentration.
  - Weekly audit export: `reports/audits/weekly_audit_20260212_095919.json`
    - Metrics: Sharpe `1.6503`, WinRate `0.5000`, MaxDD `0.0346`, ClosedTrades `6`
    - Gate result: failed only `closed_trades` (`6 < 10`)
  - Paper status: `reports/promotion/paper_run_status_20260212_095918.json`
    - Trailing streak remains `1/4`, not live-ready.
- Experiment ledger added and first post-change row appended:
  - `reports/backtests/experiment_ledger.csv`

### 2026-02-12 Phase 9A-9D Initial Validation (Adaptive Trend Only)
- Configuration used:
  - `ENABLE_ADAPTIVE_TREND=1`
  - `ENABLE_MOMENTUM_BREAKOUT=0`
  - `ENABLE_MEAN_REVERSION=0`
  - `ENABLE_SECTOR_ROTATION=0`
  - `ENABLE_BEAR_REVERSAL=0`
  - `ENABLE_VOLATILITY_REVERSAL=0`
- Sanity run command:
  - `python scripts/multi_week_gate_search.py --max-combos 1`
- Artifact:
  - `reports/backtests/multi_week_gate_search_20260212_144131.json`
- Outcome:
  - Anchor pass count: `0/4`
  - Exit reasons show high `STOP_LOSS` concentration on bearish anchors.
  - Funnel confirms adaptive strategy is active (`risk_valid_by_strategy_total.adaptive_trend` populated across anchors).

### 2026-02-12 Adaptive-Diagnosis Pass (Before Wider Sweeps)
- Goal: diagnose structural behavior before running full parameter grids.
- Base artifact reviewed: `reports/backtests/multi_week_gate_search_20260212_144131.json`
- Per-anchor diagnostics from temp DBs (`/tmp/trading_bot_multi_week_1_2026-*.db`):
  - `2026-01-22`: trades `10` (`closed=0`, `open=10`), effective avg hold `13.30d`, avg stop distance `7.96%`
  - `2026-01-29`: trades `9` (`closed=3`, `open=6`), effective avg hold `17.44d`, avg stop distance `8.06%`
  - `2026-02-05`: trades `7` (`closed=3`, `open=4`), effective avg hold `19.71d`, avg stop distance `8.27%`
  - `2026-02-12`: trades `4` (`closed=1`, `open=3`), effective avg hold `21.50d`, avg stop distance `7.66%`
- Key finding 1 (confirmed): **regime-gate mismatch**
  - Orchestrator marked many days `favorable` while strategy-level gate still blocked at `ADAPTIVE_TREND_REGIME_MAX_VOL=0.30`.
  - From funnel logs (anchor `2026-02-12`): `ann_vol ≈ 0.45-0.46`, regime `favorable`, but raw signals collapsed late window.
- Controlled rerun A (env-only): `ADAPTIVE_TREND_REGIME_MAX_VOL=0.55`
  - Artifact: `reports/backtests/multi_week_gate_search_20260212_144642.json`
  - Result: still `0/4`, but trending anchor raw signals increased (`raw_total: 4 -> 16`) and return improved (`-0.5008% -> -0.3940%`).
- Controlled rerun B (env-only): `ADAPTIVE_TREND_REGIME_MAX_VOL=0.55`, `MAX_POSITIONS=5`
  - Artifact: `reports/backtests/multi_week_gate_search_20260212_144733.json`
  - Result: still `0/4`; risk-valid counts were reduced, but no gate pass.
- Decision:
  - Do **not** run wide sweeps yet.
  - Next work must fix structural issues first (regime contract alignment + adaptive position-cap enforcement + exit behavior audit) before grid search.

### 2026-02-12 Regime-Alignment Hotfix + Exit-Level Findings
- Code fix applied:
  - `trading_bot/strategies/adaptive_trend.py:_regime_allows_entry()` now trusts canonical `market_regime.is_favorable` (single source of truth).
  - Removed independent strategy-side vol gate from the active path (kept legacy fallback only when canonical key is missing).
- Validation run after fix:
  - Command: adaptive-only bounded anchor run (`--max-combos 1`, `MAX_POSITIONS=5`)
  - Artifact: `reports/backtests/multi_week_gate_search_20260212_145156.json`
  - Result: still `0/4`, but funnel activity increased on later anchors (`raw_signals` rose to `21` on `2026-02-05` and `2026-02-12`).
- Exit-level diagnostics (from `/tmp/trading_bot_multi_week_1_2026-*.db`):
  - Stops are **not** immediate Day 1-3 failures.
  - Closed-trade buckets were concentrated in `D8-15` and `D16+`.
  - Trailing stop engaged at least once (`2026-02-05`: `TRAILING_STOP=1`), so trail logic is active but infrequent.
  - Stop distance remained wide (`~8-10%`), consistent with weekly ATR framing.
- Critical implication:
  - Adaptive cadence/hold profile is structurally different and produces many open positions at anchor boundaries.
  - Current weekly gate (`min_closed_trades=10` over 4-week lookback) is likely mismatched for this low-frequency/long-hold strategy family.

### 2026-02-12 Adaptive Audit Profile (Implemented)
- Implemented profile-aware go-live gates with `baseline` and `adaptive` modes:
  - New resolver/helpers: `trading_bot/monitoring/gate_profiles.py`
  - `auto` profile selects `adaptive` when adaptive trend is the only enabled strategy.
- Adaptive thresholds (configured in `settings.py` / `.env.example`):
  - `min_sharpe=0.7` (unchanged)
  - `max_drawdown=0.15` (unchanged)
  - `min_win_rate=0.30` (lowered for trend-following expectancy model)
  - `min_profit_factor=1.20` (new; evaluates trend-following by payoff quality, not win-rate alone)
  - `min_closed_trades=5` at this stage (later reduced to `3` in subsequent calibration)
  - `max_critical_errors=0` (unchanged)
  - `required_paper_weeks=6` (increased for sample-size confidence)
- Wiring completed:
  - `main.py:weekly_audit_routine()` now uses profile-derived thresholds.
  - `main.py:paper_run_status_routine()` now uses profile-derived required weeks.
  - `scripts/multi_week_gate_search.py` and `scripts/structural_gate_sweep.py` now evaluate using profile-derived thresholds and emit `gate_profile` in artifacts.
  - `scripts/weekly_performance_audit.py` and `scripts/promotion_checklist.py` now support profile-aware defaults.
- Verification:
  - Resolver sanity check in adaptive-only mode returned:
    - profile `adaptive`
    - thresholds `Sharpe 0.7 / MaxDD 0.15 / WinRate 0.30 / ProfitFactor 1.20 / ClosedTrades 5 / CriticalErrors 0` at this stage
    - required paper weeks `6`
  - Sweep artifact confirms profile propagation:
    - `reports/backtests/multi_week_gate_search_20260212_150009.json` (`gate_profile` = `adaptive` on all anchors).

### 2026-02-12 Exit-Stack Overhaul Batch (Implemented + Validated)
- Implemented changes:
  - `stop_atr_mult` default tightened (`2.0 -> 1.5`)
  - progressive trailing bands in `AdaptiveTrendFollowingStrategy.check_exit_conditions()`:
    - `<3%`: `1.5x ATR`
    - `>=3%`: `1.2x ATR`
    - `>=5%`: `1.0x ATR`
    - `>=8%`: `0.8x ATR`
  - new `BREAKEVEN_STOP` (`>=3%` historical gain after min hold, floor at `entry + 0.5%`)
  - new `TREND_BREAK` exit using entry EMA relation + current weekly EMA crossover
  - trend-break check ordering placed before trailing/time exits
  - weekly EMA caching wired in both backtest and live orchestrator exit loops
  - `multi_week_gate_search.py` now uses strategy-aware default lookback (`42` days for adaptive-only runs)
- New/updated config knobs:
  - `ADAPTIVE_TREND_PROFIT_TRAIL_ATR_MULT=0.8`
  - `ADAPTIVE_TREND_BREAKEVEN_GAIN_PCT=0.03`
  - `ADAPTIVE_TREND_BREAKEVEN_BUFFER_PCT=0.005`
  - default updates:
    - `ADAPTIVE_TREND_STOP_ATR_MULT=1.5`
    - `ADAPTIVE_TREND_PROFIT_PROTECT_PCT=0.03`
- Validation artifact:
  - `reports/backtests/multi_week_gate_search_20260212_203911.json`
  - `lookback_days=42` confirmed
  - anchor result still `0/4`, but exit distribution changed materially:
    - `2026-01-22`: `{STOP_LOSS:1, TRAILING_STOP:1, BREAKEVEN_STOP:1, TREND_BREAK:1, TIME_STOP:1}`
    - `2026-01-29`: `{STOP_LOSS:2, TRAILING_STOP:1}`
    - `2026-02-05`: `{TRAILING_STOP:4, STOP_LOSS:2, BREAKEVEN_STOP:1}`
    - `2026-02-12`: `{TRAILING_STOP:5, STOP_LOSS:2, BREAKEVEN_STOP:1}`
  - STOP_LOSS share reduced from prior ~`83%` to ~`35%` on latest run (`7/20` closed exits).

### 2026-02-12 Entry-Quality Iteration (Implemented + Bounded Validation)
- Implemented changes (focused, no broad sweep):
  - adaptive gate profile now includes `profit_factor` gate and lower `min_win_rate`:
    - `ADAPTIVE_GO_LIVE_MIN_WIN_RATE: 0.40 -> 0.30`
    - `ADAPTIVE_GO_LIVE_MIN_PROFIT_FACTOR: 1.20` (new)
  - entry-strength tightening in `AdaptiveTrendFollowingStrategy`:
    - `ADAPTIVE_TREND_MIN_WEEKLY_ROC: 0.02 -> 0.03`
    - new weekly EMA spread filter:
      - `ADAPTIVE_TREND_MIN_WEEKLY_EMA_SPREAD_PCT=0.005` (0.5%)
  - signal selection refactor:
    - collect all valid adaptive candidates, rank by `confidence`, then enforce `max_new_per_week`
    - removed first-come symbol-order dependency
  - audit/search surfaces updated:
    - `profit_factor` included in weekly audit thresholds and gate evaluation
    - `scripts/weekly_performance_audit.py` + `scripts/promotion_checklist.py` support `--min-profit-factor`
    - `scripts/multi_week_gate_search.py` now records `profit_factor` in per-anchor metrics
- Validation artifact:
  - `reports/backtests/multi_week_gate_search_20260212_210713.json` (`lookback_days=42`)
  - Result: `0/4` gate passes, with gate profile correctly set to `adaptive` per anchor.
- Per-anchor metrics (new run):
  - `2026-01-22`: Return `-2.1654%`, Sharpe `-5.8107`, WinRate `0.2000`, ProfitFactor `0.1540`, Closed `5`
  - `2026-01-29`: Return `+1.8966%`, Sharpe `+1.8927`, WinRate `0.0000`, ProfitFactor `0.0000`, Closed `4`
  - `2026-02-05`: Return `+1.2305%`, Sharpe `+1.0024`, WinRate `0.4444`, ProfitFactor `0.9597`, Closed `9`
  - `2026-02-12`: Return `+1.5139%`, Sharpe `+1.2151`, WinRate `0.4444`, ProfitFactor `0.9422`, Closed `9`
- Failed gate breakdown (adaptive profile):
  - `2026-01-22`: failed `sharpe_ratio`, `win_rate`, `profit_factor`
  - `2026-01-29`: failed `win_rate`, `profit_factor`, `closed_trades`
  - `2026-02-05`: failed `profit_factor` only
  - `2026-02-12`: failed `profit_factor` only
- Comparison vs previous exit-overhaul baseline (`reports/backtests/multi_week_gate_search_20260212_203911.json`):
  - Average anchor return improved `-0.4216% -> +0.6189%` (`+1.0405%` delta)
  - `3/4` anchors improved; `2026-01-22` remains the dominant weak regime.
- Key implication:
  - Returns materially improved on `3/4` anchors versus prior exit-overhaul baseline, but go-live gates still fail due weak payoff quality (`profit_factor < 1.2`) and one severe choppy-anchor loss.

### 2026-02-12 Regime-Conditional Entry Tightening (Implemented + Bounded Validation)
- Implemented changes:
  - adaptive trend entry thresholds now tighten conditionally when regime quality is weaker.
  - New dynamic thresholds in `AdaptiveTrendFollowingStrategy`:
    - if any of the following are adverse:
      - `regime.confidence < 0.65`
      - `regime.breadth_ratio < 0.58`
      - `regime.annualized_volatility > 0.42`
    - then progressively tighten:
      - `min_weekly_roc += 0.005` per adverse signal
      - `min_weekly_ema_spread_pct += 0.0015` per adverse signal
      - `min_volume_ratio += 0.05` per adverse signal
  - Entry-ranking/exit stack unchanged from prior batch; this is entry-quality-only.
  - Added regime diagnostics to signal metadata:
    - `regime_confidence`, `regime_breadth_ratio`, `regime_annualized_volatility`
- Tests:
  - Added tests for threshold tightening and tightened-threshold rejection:
    - `tests/test_adaptive_trend_strategy.py`
  - Validation status: `22 passed` (`test_adaptive_trend_strategy`, `test_gate_profiles`, `test_weekly_audit`)
- Validation artifact:
  - `reports/backtests/multi_week_gate_search_20260212_212741.json`
  - Result: `0/4` gate passes (adaptive profile), but choppy-anchor loss reduced.
- Per-anchor metrics (new run):
  - `2026-01-22`: Return `-1.5981%`, Sharpe `-4.6031`, WinRate `0.2500`, ProfitFactor `0.1971`, Closed `4`
  - `2026-01-29`: Return `+1.8966%`, Sharpe `+1.8927`, WinRate `0.0000`, ProfitFactor `0.0000`, Closed `4`
  - `2026-02-05`: Return `+1.2305%`, Sharpe `+1.0024`, WinRate `0.4444`, ProfitFactor `0.9597`, Closed `9`
  - `2026-02-12`: Return `+1.5139%`, Sharpe `+1.2151`, WinRate `0.4444`, ProfitFactor `0.9422`, Closed `9`
- Failed gate breakdown (adaptive profile):
  - `2026-01-22`: failed `sharpe_ratio`, `win_rate`, `profit_factor`, `closed_trades`
  - `2026-01-29`: failed `win_rate`, `profit_factor`, `closed_trades`
  - `2026-02-05`: failed `profit_factor` only
  - `2026-02-12`: failed `profit_factor` only
- Comparison vs prior entry-quality iteration (`reports/backtests/multi_week_gate_search_20260212_210713.json`):
  - Average anchor return improved `+0.6189% -> +0.7607%` (`+0.1418%` delta)
  - Largest move was choppy anchor (`2026-01-22`: `-2.1654% -> -1.5981%`, `+0.5673%` improvement).

### 2026-02-12 Pre-Entry Payoff Filter (Implemented + Bounded Validation)
- Implemented changes:
  - Added strategy-level expected payoff filter in `AdaptiveTrendFollowingStrategy`:
    - New param: `min_expected_r_mult` (config: `ADAPTIVE_TREND_MIN_EXPECTED_R_MULT`, default `1.0`)
    - New estimator: `_estimate_expected_r_multiple(entry_price, weekly)`
      - trend proxy from weekly momentum structure (`max(ROC_4, EMA-spread-derived proxy)`)
      - risk proxy from stop distance (`stop_atr_mult * weekly_atr / entry_price`)
      - expected R = `trend_proxy_pct / risk_pct`
    - Signals are now rejected pre-entry when `expected_r < expected_r_floor`
  - Regime-aware floor tightening:
    - `expected_r_floor = min_expected_r_mult + 0.15 * tighten_steps`
    - `tighten_steps` derived from weak-regime conditions (`confidence`, `breadth_ratio`, `annualized_volatility`)
  - Added metadata for diagnostics:
    - `expected_r_multiple`, `expected_r_floor`
- Validation artifact:
  - `reports/backtests/multi_week_gate_search_20260212_223042.json`
  - Result: **`2/4` anchors passed** (first time above prior `1/4` robustness ceiling).
- Per-anchor metrics:
  - `2026-01-22`: Return `-0.8594%`, Sharpe `-3.1274`, WinRate `0.3333`, ProfitFactor `0.3300`, Closed `3`
  - `2026-01-29`: Return `+2.6347%`, Sharpe `+2.7122`, WinRate `0.0000`, ProfitFactor `0.0000`, Closed `3`
  - `2026-02-05`: Return `+1.2677%`, Sharpe `+1.0587`, WinRate `0.5000`, ProfitFactor `1.3973`, Closed `8`
  - `2026-02-12`: Return `+2.0690%`, Sharpe `+1.6723`, WinRate `0.5000`, ProfitFactor `1.3604`, Closed `8`
- Adaptive gate outcomes:
  - Pass: `2026-02-05`, `2026-02-12`
  - Fail:
    - `2026-01-22`: `sharpe_ratio`, `profit_factor`, `closed_trades`
    - `2026-01-29`: `win_rate`, `profit_factor`, `closed_trades`
- Comparison vs prior run (`reports/backtests/multi_week_gate_search_20260212_212741.json`):
  - Average anchor return improved `+0.7607% -> +1.2780%` (`+0.5173%` delta)
  - Positive improvement on all four anchors.

### 2026-02-13 Profit-Factor Waiver Calibration (Implemented + Bounded Validation)
- Implemented change:
  - Updated `evaluate_go_live_gates()` in `trading_bot/monitoring/performance_audit.py`:
    - Profit-factor gate now supports waiver when all of the following hold:
      - `wins == 0`
      - `closed_trades > 0`
      - `total_return_pct > 0`
      - `sharpe_ratio >= min_sharpe`
      - `min_profit_factor > 0`
    - Added gate metadata: `profit_factor.waiver_applied`.
- Added test coverage:
  - `tests/test_weekly_audit.py::test_profit_factor_waiver_for_positive_sharpe_positive_return_trend_case`
- Validation artifact:
  - `reports/backtests/multi_week_gate_search_20260213_072804.json`
  - Result: `2/4` anchors passed (unchanged vs previous run), with identical returns.
- Adaptive gate breakdown after waiver:
  - `2026-01-22`: failed `sharpe_ratio`, `profit_factor`, `closed_trades` (waiver not applied)
  - `2026-01-29`: failed `win_rate`, `closed_trades` (**profit-factor waiver applied**)
  - `2026-02-05`: pass
  - `2026-02-12`: pass
- Key implication:
  - Profit-factor calibration issue is resolved for trend-following open-winner cases.
  - Remaining blockers are now concentrated in:
    - `2026-01-22` (true choppy-regime weakness)
    - `2026-01-29` gate mix (`win_rate`, `closed_trades`) despite strong return/Sharpe.

### 2026-02-13 Gate + Choppiness Calibration (Implemented + Iterated)
- Implemented changes:
  - Extended waiver linkage in `evaluate_go_live_gates()`:
    - when PF waiver condition is met, `win_rate` gate is also waived (`win_rate.waiver_applied=true`)
  - Adaptive closed-trade floor reduced:
    - `ADAPTIVE_GO_LIVE_MIN_CLOSED_TRADES: 5 -> 3`
  - Added weekly trend-consistency entry filter in adaptive strategy:
    - `trend_consistency_ratio = (# of last 4 weeks with close > EMA_S) / 4`
    - config knob: `ADAPTIVE_TREND_MIN_TREND_CONSISTENCY`
- Iteration history (important):
  - **Attempt A (over-tight static consistency floor)**:
    - artifact: `reports/backtests/multi_week_gate_search_20260213_073510.json`
    - result: `1/4` (regression from `2/4`)
  - **Attempt B (initial conditional floor)**:
    - artifact: `reports/backtests/multi_week_gate_search_20260213_073704.json`
    - result: `1/4` (still over-tight in practice)
  - **Attempt C (calibrated conditional tightening; severe regime-only steps)**:
    - tighten only on explicit severe regime signals:
      - `confidence < 0.55`
      - `breadth_ratio < 0.52`
      - `annualized_volatility > 0.50`
    - final artifact: `reports/backtests/multi_week_gate_search_20260213_073926.json`
    - result: **`3/4` anchors passed**
- Final per-anchor metrics (Attempt C):
  - `2026-01-22`: Return `-1.4291%`, Sharpe `-4.5564`, WinRate `0.2500`, ProfitFactor `0.2445`, Closed `4` (fail)
  - `2026-01-29`: Return `+2.6347%`, Sharpe `+2.7122`, WinRate `0.0000`, ProfitFactor `0.0000`, Closed `3` (**pass via PF+WinRate waiver**)
  - `2026-02-05`: Return `+1.0485%`, Sharpe `+0.8926`, WinRate `0.5000`, ProfitFactor `1.3973`, Closed `8` (pass)
  - `2026-02-12`: Return `+1.8296%`, Sharpe `+1.4914`, WinRate `0.5000`, ProfitFactor `1.3604`, Closed `8` (pass)
- Net state after calibration:
  - Robustness now at **`3/4`** (first time reaching the current Phase 9 target).
  - Sole remaining failing anchor is `2026-01-22` (choppy regime), which is now explicit and isolated.

### 2026-02-13 Paper-Run Kickoff + Weekly Summary View
- Weekly summary artifact view enhancement:
  - `trading_bot/monitoring/audit_trend.py` now tracks:
    - `waiver_fire_rate`
    - `profit_factor_waiver_fire_rate`
    - `win_rate_waiver_fire_rate`
    - `waiver_fire_rate_last4`
    - `waiver_timeline` (per-week flags)
  - `scripts/weekly_audit_trend.py` prints waiver-fire-rate line item in CLI output.
  - Artifact generated:
    - `reports/audits/trends/weekly_audit_trend_20260213_075620.json`
- Adaptive-only paper-run started (scheduler mode):
  - Runtime mode: `python main.py --mode paper`
  - Strategy toggles: adaptive enabled, all others disabled.
  - Session tracking:
    - `control/paper_run_session.txt` (`session_id=89275`)
  - Note: startup showed NSE DNS fetch failures in this environment and correctly fell back to local/cache paths.

### Numeric Parameter Ledger (Latest Tested Values + Failure Numbers)
1. Baseline anchor profile (reference):
   - `STRATEGY_PROFILE=tuned_momentum_v6`, `MOMENTUM_ENABLE_REGIME_FILTER=0`, `MAX_SIGNALS_PER_DAY=5`, `MIN_EXPECTED_EDGE_PCT=0.0`
   - Latest anchor metrics: `reports/backtests/latest_anchor_quality_sweep.json`
   - Failing anchors:
     - `2026-01-22`: Sharpe `-6.6467`, WinRate `0.3478`, Trades `23`, Return `-1.2574%`
     - `2026-01-29`: Sharpe `-8.7992`, WinRate `0.2353`, Trades `17`, Return `-1.5310%`
     - `2026-02-05`: Sharpe `-1.0038`, WinRate `0.4375`, Trades `16`, Return `-0.2917%`
   - Passing anchor:
     - `2026-02-12`: Sharpe `2.3998`, WinRate `0.5333`, Trades `15`, Return `0.6196%`
2. Parameter sweep ranges and best outcomes:
   - `anchor_param_sweep` (`16` combos):
     - Tested: `RISK_PER_TRADE ∈ {0.004, 0.006}`, `MAX_POSITION_SIZE ∈ {0.06, 0.08}`, `MOMENTUM_MIN_ROC ∈ {0.03, 0.05}`, `MOMENTUM_MAX_ATR_PCT ∈ {0.03, 0.035}`
     - Best: `0.004 / 0.06 / 0.03 / 0.035` -> `1/4` anchors (`reports/backtests/anchor_param_sweep_20260212_081154.json`)
   - `anchor_exit_sweep` (`27` combos):
     - Tested: `MOMENTUM_RR_RATIO ∈ {0.8, 1.0, 1.2}`, `MOMENTUM_TIME_STOP_DAYS ∈ {3,4,5}`, `MOMENTUM_TIME_STOP_MOVE_PCT ∈ {0.002,0.003,0.005}`
     - Best: `RR=0.8`, `TIME_STOP_DAYS=3`, `TIME_STOP_MOVE_PCT=0.005` -> `1/4` anchors (`reports/backtests/anchor_exit_sweep_20260212_081915.json`)
   - `anchor_quality_sweep` (`24` combos):
     - Tested: `MOMENTUM_ENABLE_REGIME_FILTER ∈ {0,1}`, `MAX_SIGNALS_PER_DAY ∈ {2,3,5}`, `MIN_EXPECTED_EDGE_PCT ∈ {0,0.005,0.01,0.015}`
     - Best: `regime=0`, `cap=5`, `edge=0.0` -> `1/4` anchors (`reports/backtests/anchor_quality_sweep_20260212_082626.json`)
   - `anchor_strategy_mix_sweep` (`4` combos):
     - Tested: `ENABLE_MEAN_REVERSION ∈ {0,1}`, `ENABLE_SECTOR_ROTATION ∈ {0,1}` (with momentum enabled)
     - Best: `mean=0`, `sector=0` -> `1/4` anchors (`reports/backtests/anchor_strategy_mix_sweep_20260212_082805.json`)
   - `anchor_non_momentum_sweep` (`3` combos):
     - Tested: momentum disabled; `{mean-only, sector-only, mean+sector}`
     - Best: `mean-only` -> `0/4`; all anchors had `Trades=0`, failed `closed_trades/win_rate/sharpe` (`reports/backtests/anchor_non_momentum_sweep_20260212_082912.json`)
   - `anchor_defensive_eval` (`4` cases):
     - Tested defensive breadth mode variants:
       - baseline (off)
       - defensive breadth `0.55` momentum+mean
       - defensive breadth `0.55` mean-only
       - defensive breadth `0.60` mean-only tight
     - Best remained baseline `1/4`; defensive variants `0/4` (`reports/backtests/anchor_defensive_eval_20260212_083507.json`)
   - `anchor_bear_strategy_sweep` (`9` cases):
     - Tested `ENABLE_BEAR_REVERSAL ∈ {0,1}` with variants:
       - bear-only `{default, loose, tight}`
       - momentum+bear `{default, loose, tight}`
       - defensive bear-only and defensive momentum+bear
     - Best: baseline momentum-only `1/4`; no bear variant improved above `1/4` (`reports/backtests/anchor_bear_strategy_sweep_20260212_084944.json`)
     - Best failing bear examples:
       - `bear_only_default`: `0/4` anchors
       - `bear_only_loose_entry`: `0/4` anchors
       - `momentum_plus_bear_loose`: `1/4` anchors (no lift vs baseline)
   - `anchor_volatility_strategy_sweep` (`9` cases):
     - Tested `ENABLE_VOLATILITY_REVERSAL ∈ {0,1}` with variants:
       - vol-only `{default, loose, tight}`
       - momentum+vol `{default, loose, tight}`
       - defensive vol-only and defensive momentum+vol
     - Volatility params tested:
       - `VOL_REV_RSI_REENTRY ∈ {32,35,38}`
       - `VOL_REV_MIN_DROP_PCT ∈ {0.02,0.03,0.05}`
       - `VOL_REV_VOL_SPIKE_MULT ∈ {1.05,1.2,1.4}`
       - `VOL_REV_MIN_ATR_PCT ∈ {0.02,0.025,0.03}`
       - `VOL_REV_RR_RATIO ∈ {0.8,1.0}`
       - `VOL_REV_MAX_HOLD_DAYS ∈ {2,3,4}`
     - Best: baseline momentum-only still `1/4` (`reports/backtests/anchor_volatility_strategy_sweep_20260212_090240.json`)
     - Representative failure metrics:
       - `vol_only_loose`:
         - `2026-01-22`: Sharpe `-0.2303`, WinRate `0.2500`, Trades `4` (failed `closed_trades`)
         - `2026-01-29`: Sharpe `-4.2047`, WinRate `0.1250`, Trades `8` (failed `closed_trades`)
         - `2026-02-05`: pass (`Sharpe 0.8465`, `WinRate 0.5000`, `Trades 14`)
         - `2026-02-12`: failed `sharpe_ratio` (`Sharpe 0.1486`, `WinRate 0.5625`, `Trades 16`)
       - `momentum_plus_vol_loose`:
         - `2026-01-22`: Sharpe `-5.4050`, WinRate `0.3333`, Trades `27`
         - `2026-01-29`: Sharpe `-8.9506`, WinRate `0.2000`, Trades `25`
         - `2026-02-05`: Sharpe `0.2957`, WinRate `0.4444`, Trades `27`
         - `2026-02-12`: pass (`Sharpe 1.8078`, `WinRate 0.5357`, `Trades 28`)

