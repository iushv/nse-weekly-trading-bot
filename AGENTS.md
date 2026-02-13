# Repository Guidelines

## Project Scope
This project is a fresh implementation of an automated trading bot. The goal is to build a modular, testable system that supports historical backtesting first, then paper trading, and only later real broker execution behind strict risk gates.

## Project Structure & Module Organization
Use this initial layout:

```text
new-trading-bot/
├── AGENTS.md
├── README.md
├── requirements.txt
├── config/
├── data/
├── logs/
├── scripts/
├── trading_bot/
│   ├── core/
│   ├── strategy/
│   ├── backtest/
│   ├── brokers/
│   └── risk/
└── tests/
```

Keep strategy logic in `trading_bot/strategy/`, execution interfaces in `trading_bot/brokers/`, and guardrails (position sizing, stop logic, drawdown controls) in `trading_bot/risk/`.

## Build, Test, and Development Commands
- `python3 -m venv .venv && source .venv/bin/activate`: create local environment.
- `pip install -r requirements.txt`: install dependencies.
- `pytest -q`: run all tests.
- `python -m trading_bot.backtest.run`: run baseline backtest.
- `python -m trading_bot.paper.run`: run paper trading loop (no live orders).

## Coding Style & Naming Conventions
- Python 3.11+ with 4-space indentation.
- `snake_case` for functions/variables/files, `PascalCase` for classes.
- Keep modules focused; avoid scripts that mix data loading, signal generation, and order execution.
- Prefer type hints on public functions and dataclass-based config models.

## Testing Guidelines
- Framework: `pytest`.
- Test files: `tests/test_*.py`.
- Add unit tests for indicators, signal rules, and risk checks before integration tests.
- Minimum target before paper launch: critical-path tests passing for entry/exit, sizing, PnL, and max drawdown constraints.

## Commit & Pull Request Guidelines
- Commit format: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- Keep commits scoped to one concern (e.g., “feat: add EMA crossover strategy”).
- PRs must include:
  - Summary of behavior changes
  - Risk impact (if any)
  - Test evidence (`pytest` output or backtest report)
  - Rollback notes for execution-related changes

## Implementation Plan (Phased)
1. Foundation: repo skeleton, config loader, logging, market data adapter.
2. Backtesting: event loop, fills/cost model, metrics report.
3. Strategy v1: one baseline strategy with parameterized settings.
4. Risk Engine: position caps, stop-loss, daily loss limiter, kill switch.
5. Paper Trading: broker simulator + live market feed integration.
6. Production Readiness: monitoring, alerts, incident playbooks, staged rollout.
