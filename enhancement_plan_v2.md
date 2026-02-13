# Trading Bot Enhancement Plan v2
## Consolidated Path to Anchor Robustness

**Date**: 2026-02-12  
**Status**: Robustness bottleneck remains at **1/4 anchor passes**  
**Objective**: Move from unstable 1/4 to stable 2/4, then 3/4, before any live progression

---

## 1. Confirmed Current State

### What is working
- Project architecture, orchestration, reporting, and promotion tracking are functional.
- Strategy stack already includes momentum and defensive variants.
- Canonical validation scripts and JSON artifacts are consistently available.

### What is blocked
- Bearish and choppy anchors still fail core gates.
- Improvements from parameter/strategy sweeps have not produced stable robustness lift.
- Primary weak metrics remain Sharpe and win-rate on non-trending anchors.

### Canonical tooling (do not fork)
- `scripts/structural_gate_sweep.py`
- `scripts/multi_week_gate_search.py`
- `scripts/weekly_performance_audit.py`
- `scripts/paper_run_tracker.py`

---

## 2. Delta from Original `ENHANCEMENT_PLAN.md`

### Confirmed accurate diagnosis
- Overtrading and transaction-cost drag are material.
- Trend-only behavior is fragile across regime shifts.
- Strategy participation must be regime-aware.

### Corrections required
- Regime logic is not missing; it is fragmented across layers and needs consolidation.
- Throughput and ranking controls already exist; this is tuning and normalization work.
- Defensive strategies are present; work now is routing quality and consistency.
- Exit behavior needs equal priority with entry logic.

---

## 3. Architecture Decisions for v2

### 3.1 Canonical regime contract
Use one canonical regime object in orchestration and pass it into strategy signal generation.

Required keys:
- `regime_label`
- `is_favorable`
- `breadth_ratio`
- `trend_up`
- `annualized_volatility`
- `confidence`

### 3.2 Routing precedence
When regime is unfavorable:
- block new momentum entries,
- allow only configured defensive strategies,
- apply explicit de-risk behavior for open positions.

### 3.3 Scoring contract
Signal ranking must support non-momentum strategies without metadata penalties.

---

## 4. Prioritized Workstreams

### Priority A: Regime Consolidation
- A.1 Consolidate regime computation at bot level.
- A.2 Remove/limit conflicting independent regime decisions across strategies.
- A.3 Define transition behavior (`favorable -> unfavorable`, `unfavorable -> favorable`) for pending and open positions.

### Priority B: Tune Existing Throughput Funnel
- B.1 Calibrate existing knobs (`MAX_SIGNALS_PER_DAY`, `MIN_EXPECTED_EDGE_PCT`, defensive caps).
- B.2 Add funnel attribution metrics at each gate.
- B.3 Enforce participation floor to avoid false passes from under-trading.

### Priority C: Cross-Strategy Score Normalization
- C.1 Implement strategy-aware score features.
- C.2 Normalize per-strategy scores before global ranking.
- C.3 Log selected-count distribution by strategy family.

### Priority D: Exit Logic Audit and Upgrade
- D.1 Add exit reason analytics per anchor and strategy.
- D.2 Evaluate adaptive and regime-aware de-risk exits.
- D.3 Validate loss compression in bear/choppy anchors without damaging trend-week edge.

### Priority E: Universe Quality Hardening
- E.1 Define explicit liquidity/turnover filters.
- E.2 Add gap/instability filters where justified.
- E.3 Validate impact on robustness, not only best-week returns.

---

## 5. Canonical Validation Workflow

For each candidate:
1. Run structural sweep.
2. Run multi-week gate search.
3. Run weekly audit export.
4. Check promotion tracker status and streak.
5. Archive outputs in `reports/backtests/` and `reports/promotion/`.

No candidate is accepted without full pipeline completion.

---

## 6. Experiment Ledger Requirements

Each experiment row must include:
- `experiment_id`
- full overrides
- anchors passed (`x/4`)
- per-anchor Sharpe, win-rate, trades, return, drawdown
- funnel counts (`raw`, `regime_ok`, `edge_ok`, `ranked`, `sized`, `risk_ok`)
- per-strategy selected counts
- exit reason breakdown
- decision (`adopt` or `reject`)
- rejection reason
- repeat run id / reproducibility status

### Guardrails
- Reject single-anchor gains that degrade others materially.
- Reject low-trade passes caused by inactivity.
- Keep cost semantics identical across backtest/risk/execution.
- Require repeatability before baseline adoption.

---

## 7. 7-Day Execution Plan (Realistic Cadence)

### Day 1
- Regime consolidation refactor and routing precedence only.

### Day 2-3
- Throughput calibration and cross-strategy scoring normalization.
- Run bounded experiments through canonical validation workflow.

### Day 4-5
- Exit logic audit and targeted exit-policy experiments.

### Day 6
- Full candidate validation run and ledger completion.

### Day 7
- Reproducibility rerun and go/no-go checkpoint.

---

## 8. Success Gates

### Stage 1
- Stable movement from 1/4 to **2/4** anchors.
- Reduced loss severity on remaining failed anchors.
- Minimum participation maintained (no inactivity pass).

### Stage 2
- Reach **3/4** with acceptable downside constraints.

### Stage 3 (pre-live)
- Required paper-run consistency/streak achieved.
- No live mode progression before paper criteria are met.

---

## 9. Stop/Pivot Rule

If robustness remains at or below 1/4 after bounded experiments, stop incremental tuning and pivot to a materially different participation framework.

---

## 10. Test Scenarios to Enforce

- Regime conflict scenario: bot says defensive while strategy says favorable.
- Cross-strategy ranking with missing momentum-style metadata.
- Low-trade false pass scenario.
- Exit reason concentration in choppy/bear anchors.
- Repeatability scenario with same config over repeated runs.

---

## 11. Implementation Hygiene

- Keep `main.py` as orchestration source of truth.
- Keep `order_manager.py` execution-only (transport layer).
- Keep `IMPLEMENTATION_PLAN.md` synchronized with accepted/rejected experiments and numeric outcomes.
