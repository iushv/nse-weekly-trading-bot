# Paper Run Acceptance Checklist

## Objective
Enforce a minimum 4-week continuous paper run before live capital deployment.

## Weekly Evidence (Required)
- Weekly audit artifact in `reports/audits/weekly_audit_*.json`.
- Promotion bundle in `reports/promotion/promotion_*/`.
- No unresolved critical incidents for the week.

## Metrics Gates
- Sharpe ratio >= configured threshold (`GO_LIVE_MIN_SHARPE`).
- Absolute max drawdown <= configured threshold (`GO_LIVE_MAX_DRAWDOWN`).
- Win rate >= configured threshold (`GO_LIVE_MIN_WIN_RATE`).
- Closed trades >= configured minimum (`GO_LIVE_MIN_CLOSED_TRADES`).
- Critical error count <= configured maximum (`GO_LIVE_MAX_CRITICAL_ERRORS`).

## Automated Check
Run:

```bash
python scripts/paper_run_tracker.py \
  --required-weeks 4 \
  --require-promotion-bundle \
  --pretty
```

Pass condition: `ready_for_live=true` and `trailing_streak >= 4`.

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
