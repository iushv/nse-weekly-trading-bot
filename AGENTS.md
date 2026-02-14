# Repository Guidelines (new-trading-bot)

This file is the operational guide for coding agents working in this repo. It is intentionally aligned to `CLAUDE.md`
and the current implementation status recorded in `IMPLEMENTATION_PLAN.md`.

## Project Overview

Indian equity swing-trading system targeting NSE stocks. The system supports backtesting, paper trading (production-like
orchestration), and guarded live execution.

Current operating mode:
- **Paper trading** with the **Adaptive Trend Following** strategy.
- **Universe pivot**: Nifty 50 showed near-zero edge; **Nifty Midcap 150 is the active paper-run candidate** (see
  `IMPLEMENTATION_PLAN.md` “Midcap 150 Universe Pivot (Decision)”).

## Quick Commands

```bash
# Environment
source .venv/bin/activate

# Quality (mirrors CI)
ruff check .
mypy --config-file pyproject.toml --ignore-missing-imports trading_bot main.py paper_trading.py
pytest -q

# Paper trading (one cycle)
PYTHONPATH=. python main.py --mode paper --test

# Paper trading (continuous scheduler)
PYTHONPATH=. python main.py --mode paper

# Universe: fetch/write Midcap150 constituents into a deterministic universe file
PYTHONPATH=. python scripts/update_universe_midcap150.py --out data/universe/nifty_midcap150.txt

# Backfill market data for Midcap150
PYTHONPATH=. python scripts/backfill_data.py --universe midcap150 --limit 150 --start-date 2023-01-01

# Continuous backtest restricted to a universe file
PYTHONPATH=. python scripts/run_universe_backtest.py \
  --start 2025-08-01 --end 2026-02-12 \
  --universe-file data/universe/nifty_midcap150.txt

# Rolling OOS window analysis restricted to a universe file
PYTHONPATH=. python scripts/run_universe_walk_forward.py \
  --start 2024-01-01 --end 2026-02-11 \
  --universe-file data/universe/nifty_midcap150.txt \
  --train-months 3 --test-months 3

# Weekly audit + promotion bundle
PYTHONPATH=. python scripts/weekly_performance_audit.py --pretty --export-json
PYTHONPATH=. python scripts/promotion_checklist.py --pretty --allow-not-ready

# Paper-run readiness tracker (universe-aware)
PYTHONPATH=. python scripts/paper_run_tracker.py --require-promotion-bundle --pretty --allow-not-ready

# Preflight (paper + optional broker read-only check)
PYTHONPATH=. python scripts/preflight_check.py --pretty
PYTHONPATH=. python scripts/preflight_check.py --include-broker --fail-on-broker --pretty
```

## Safety Rules (Non-Negotiable)

1. **Paper is the default.** Do not “temporarily” switch to live for debugging.
2. **Live order path is fail-closed.**
   - No broker orders may be placed unless both:
     - `LIVE_ORDER_EXECUTION_ENABLED=1`
     - `LIVE_ORDER_FORCE_ACK=YES_I_UNDERSTAND_LIVE_ORDERS`
   - Do not change these defaults unless an explicit go-live decision has been made and recorded.
3. **Never leak secrets.**
   - `.env` contains broker keys/JWTs and Telegram tokens and must never be committed.
   - Do not print `.env` contents in logs or chat transcripts.
4. **No real trades before go-live.**
   - All “smoke tests” should be read-only unless live has been explicitly armed as above.

## What “Paper-Run” Means Here

Paper-run is not historical replay. It is **a long-running process** that:
- fetches live-ish daily data (provider dependent),
- generates signals,
- simulates fills in paper mode,
- writes trades/snapshots/audit artifacts to disk + SQLite.

Historical replay is `paper_trading.py` (deterministic, backtest-like), and should not be conflated with paper-run.

## Runtime Recovery (Auto-Resume + Resume-Safe State)

Paper-run is designed to survive process restarts and missed schedules (see `IMPLEMENTATION_PLAN.md` “Runtime Reliability
Update”):
- Persistent runtime state: `control/runtime_state.json`
- Restore-on-start:
  - portfolio cash/value from `portfolio_snapshots`
  - open positions from `trades` (`status='OPEN'`)
  - same-day pending signals if restart happened between pre-market and market open
- Recovery windows are env-configurable:
  - `AUTO_RESUME_PREMARKET_START/CUTOFF`
  - `AUTO_RESUME_MARKET_OPEN_START/CUTOFF`
  - `AUTO_RESUME_MARKET_CLOSE_START/CUTOFF`

Agent rule: **do not delete `control/runtime_state.json`** unless you are explicitly resetting a run and you understand
the duplicate-entry implications.

## Windows Long-Running Setup (Personal PC)

Runbooks:
- `docs/WINDOWS_MIGRATION_SETUP.md` (moving the repo + continuity)
- `docs/WINDOWS_AUTORUN.md` (Task Scheduler + auto-restart)

Scripts:
- `scripts/windows/bootstrap_windows.ps1`
- `scripts/windows/install_startup_task.ps1`
- `scripts/windows/manage_startup_task.ps1`
- `scripts/windows/run_paper_bot.ps1`

Agent rule: Windows runner must **force paper-safe defaults** (paper mode, live orders unarmed).

## Universe Selection (Deterministic and Trackable)

Preferred (deterministic/offline):
- Set `UNIVERSE_FILE=data/universe/nifty_midcap150.txt`

Alternative (online fetch during bootstrap only):
- Set `TRADING_UNIVERSE=midcap150`

Universe changes must be treated as a new paper-run regime:
- Promotion streak tracking must be **universe-aware** via `run_context.universe_tag` embedded in audit/promotion
  artifacts (`trading_bot/monitoring/run_context.py`).

## Logs and Artifacts (Where to Look)

Runtime artifacts are intentionally gitignored:
- Logs: `logs/`
- Reports and backtest/audit JSON bundles: `reports/`
- Runtime state and heartbeat: `control/`

If you need “what happened”:
1. Check `logs/` for the orchestrator and data-provider errors.
2. Check `reports/` for the latest backtest/audit/promotion artifacts.
3. Check `control/runtime_state.json` for last routine timestamps + pending signal state.

## Data Update Guidance (Rate-Limit Safe)

- Large universes (Midcap150) use a batched yfinance download path with per-symbol fallback in
  `trading_bot/data/collectors/market_data.py`.
- If daily updates become flaky:
  - prefer a deterministic universe file and avoid online universe refresh during market hours,
  - run `scripts/preflight_check.py` to validate DB/data freshness before assuming strategy issues.

## Coding Conventions

- Use `loguru.logger`, not stdlib `logging`.
- Prefer explicit type hints on public functions.
- Keep changes scoped: avoid mixing strategy logic, risk rules, and broker plumbing in one patch.
- Any backtest/audit should write a JSON artifact under `reports/` (reproducibility).

## Repository Structure (Source of Truth)

```
main.py                          # Orchestrator (TradingBot)
paper_trading.py                 # Deterministic historical replay simulator
trading_bot/
  config/settings.py             # Config (env-driven, class-level defaults)
  strategies/                    # Strategy implementations (adaptive_trend is active)
  backtesting/                   # Backtest engine + walk-forward
  data/collectors/               # Market data providers (yfinance/Groww/NSE)
  data/storage/                  # SQLite schema + DB helpers + feature store
  execution/                     # Broker adapters (mock/groww/http)
  risk/                          # Risk manager + sizing
  monitoring/                    # Audits, promotion gates, run_context tagging
  reporting/                     # Telegram + report formatting
scripts/                         # CLI tools for backfill/audit/ops/backtests
tests/                           # pytest suite
data/universe/                   # Universe files (one symbol per line)

reports/                         # Runtime artifacts (gitignored)
logs/                            # Runtime logs (gitignored)
control/                         # Heartbeat/runtime state (gitignored)
```

## Tests

- Ensure `pytest -q` passes before pushing.
- Add tests when changing:
  - strategy signal generation and exit cascade behavior,
  - backtest engine accounting / mark-to-market,
  - promotion/audit gate logic,
  - auto-resume state persistence.

## Git / PR Hygiene

- Commits: imperative, single-concern.
- Any change touching execution safety must include:
  - what changed,
  - why it is safe in paper mode,
  - why it remains fail-closed in live mode.
