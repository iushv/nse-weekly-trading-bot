# Windows Migration + Setup Runbook

This runbook covers moving `new-trading-bot` from your current machine to a Windows PC and bringing paper mode online safely.

## 1) Choose transfer method

### Option A: Git (recommended)

On source machine:

```bash
cd /path/to/new-trading-bot
git add .
git commit -m "windows migration snapshot"
git push
```

On Windows:

```powershell
cd C:\
git clone <your-repo-url> new-trading-bot
cd .\new-trading-bot
```

### Option B: Zip transfer (no Git)

On source machine:

```bash
cd /path/to
zip -r new-trading-bot.zip new-trading-bot -x "new-trading-bot/.venv/*" "new-trading-bot/.pytest_cache/*" "new-trading-bot/.mypy_cache/*" "new-trading-bot/.ruff_cache/*" "new-trading-bot/__pycache__/*"
```

Copy `new-trading-bot.zip` to Windows and extract to `C:\new-trading-bot`.

## 2) Prepare Windows runtime

```powershell
cd C:\new-trading-bot
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe -c "from trading_bot.data.storage.database import db; db.init_db()"
```

### One-click alternative (recommended)

```powershell
cd C:\new-trading-bot
powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap_windows.ps1 -TaskName TradingBotPaper
```

This bootstrap script:
- creates `.venv` if missing,
- installs requirements,
- creates `.env` from `.env.example` if needed,
- enforces paper-safe defaults (`ENVIRONMENT=paper`, live order lock off),
- initializes DB schema,
- installs and starts the Task Scheduler job.

## 3) Configure safe paper mode

In `.env`, confirm:
- `ENVIRONMENT=paper`
- `LIVE_ORDER_EXECUTION_ENABLED=0`
- `LIVE_ORDER_FORCE_ACK=` (empty)

## 4) Optional continuity copy (for same paper-run history)

Copy these from source machine to Windows project root:
- `trading_bot.db`
- `control/runtime_state.json`
- `reports/` (optional, for historical artifacts)

Do not copy `.venv` across OS.

## 5) Install auto-start + auto-restart

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install_startup_task.ps1 -TaskName TradingBotPaper
powershell -ExecutionPolicy Bypass -File .\scripts\windows\manage_startup_task.ps1 -Action start -TaskName TradingBotPaper
powershell -ExecutionPolicy Bypass -File .\scripts\windows\manage_startup_task.ps1 -Action status -TaskName TradingBotPaper
```

Skip task creation in bootstrap (if you only want env/deps/db):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap_windows.ps1 -SkipTaskInstall
```

## 6) Verify health

- Runner log: `logs\windows_runner.log`
- Heartbeat: `control\heartbeat.json`
- Runtime state: `control\runtime_state.json`

Expected: runner launches `main.py --mode paper` and restarts automatically after process crash/reboot.

## 7) Credential hygiene

- Rotate API/Telegram tokens before migration if previously exposed.
- Keep `.env` out of version control.
- Use paper-mode credentials until live promotion gates are passed.
