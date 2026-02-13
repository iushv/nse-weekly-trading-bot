# Live Rollout Runbook

## Scope
This runbook defines how to move from paper mode to live mode with staged capital, strict rollback controls, and clear ownership.

## Roles
- Trading Owner: approves stage changes and daily go/no-go.
- Ops Owner: monitors automation, runs rollback commands, writes incident notes.
- Reviewer: validates weekly audit and promotion bundle integrity.

## Entry Criteria (Before Stage 1)
- `python scripts/preflight_check.py --include-broker --fail-on-broker --pretty` passes.
- `python scripts/promotion_checklist.py --include-broker --fail-on-broker --pretty` passes.
- `python scripts/paper_run_tracker.py --required-weeks 4 --require-promotion-bundle --pretty` reports ready.
- Kill switch and rollback commands verified in dry run.

## Capital Stages
1. Stage 1 (Pilot): 25% of target capital for 2 weeks.
2. Stage 2 (Scale): 50% of target capital for next 2 weeks if no critical incidents.
3. Stage 3 (Target): 100% target capital only after stable Stage 2 metrics.

## Daily Operations
- Pre-open: run preflight and verify latest heartbeat (`control/heartbeat.json`).
- Market hours: monitor Telegram alerts and reconciliation logs.
- Close: confirm portfolio snapshot and daily report delivery.

## Weekly Governance
- Run and archive:
  - `python scripts/weekly_performance_audit.py --export-json --pretty`
  - `python scripts/weekly_audit_trend.py --export-json --pretty`
  - `python scripts/promotion_checklist.py --include-broker --fail-on-broker --pretty`
- Review drift alerts and failed gates before any stage promotion.

## Incident and Rollback
- Trigger kill switch:
  - `python scripts/ops_controls.py kill-switch on --reason "incident"`
- Create incident note:
  - `python scripts/ops_controls.py incident-note --title "Broker/API Incident" --severity high --details "..."`
- Rollback open orders (guarded):
  - `python scripts/rollback_live.py --enable-kill-switch --cancel-open-orders --force YES_ROLLBACK --dry-run --pretty`
- For real cancellation, remove `--dry-run` after explicit owner approval.

## Communication Template
- Severity: `INFO|WARNING|ERROR`
- Summary: one line impact statement.
- Actions: kill switch state, rollback status, next update ETA.
- Owner: person responsible for the next action.
