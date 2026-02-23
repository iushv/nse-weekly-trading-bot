# Paper Run Acceptance Checklist

## Objective
Enforce a continuous paper run before live capital deployment, using the active gate profile thresholds.

## Weekly Evidence (Required)
- Weekly audit artifact in `reports/audits/weekly_audit_*.json`.
- Promotion bundle in `reports/promotion/promotion_*/`.
- No unresolved critical incidents for the week.

## Metrics Gates
- Sharpe ratio >= active profile threshold.
- Absolute max drawdown <= active profile threshold.
- Win rate >= active profile threshold.
- Profit factor >= active profile threshold (if enabled in profile).
- Closed trades >= active profile minimum.
- Critical error count <= active profile maximum.

Note:
- Baseline and adaptive profiles have different thresholds.
- Canonical values and current profile status are tracked in `IMPLEMENTATION_PLAN.md`.

## Automated Check
Run:

```bash
python scripts/paper_run_tracker.py \
  --require-promotion-bundle \
  --pretty
```

Pass condition: `ready_for_live=true` and `trailing_streak >= required_weeks` for the resolved profile.

## Manual Review Items
- Strategy behavior aligns with expected risk profile.
- Reconciliation mismatches are investigated and closed.
- Alerting latency is acceptable.
- Retention/archive jobs are healthy.

## Approval Record
- Date:
- Trading Owner:
- Ops Owner:
- Reviewer:
- Decision: `APPROVED | HOLD | REJECTED`
- Notes:
