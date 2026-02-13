# Windows Long-Run Setup (Paper Mode)

This setup runs the bot continuously on a personal Windows PC with auto-start and auto-restart.

## 1) One-time setup (PowerShell as Administrator)

```powershell
cd C:\path\to\new-trading-bot
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python.exe -c "from trading_bot.data.storage.database import db; db.init_db()"
```

One-step setup + autorun install:

```powershell
cd C:\path\to\new-trading-bot
powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap_windows.ps1 -TaskName TradingBotPaper
```

Edit `.env` and keep these safe defaults:
- `ENVIRONMENT=paper`
- `LIVE_ORDER_EXECUTION_ENABLED=0`
- `LIVE_ORDER_FORCE_ACK=` (empty)

## 2) Install startup task

```powershell
cd C:\path\to\new-trading-bot
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install_startup_task.ps1 -TaskName TradingBotPaper
```

Optional (also run at machine startup, not only user login):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install_startup_task.ps1 -TaskName TradingBotPaper -IncludeStartupTrigger
```

## 3) Manage task

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\manage_startup_task.ps1 -Action status -TaskName TradingBotPaper
powershell -ExecutionPolicy Bypass -File .\scripts\windows\manage_startup_task.ps1 -Action start -TaskName TradingBotPaper
powershell -ExecutionPolicy Bypass -File .\scripts\windows\manage_startup_task.ps1 -Action stop -TaskName TradingBotPaper
```

## 4) Logs and health

- Runner log: `logs\windows_runner.log`
- Bot heartbeat: `control\heartbeat.json`
- Runtime state: `control\runtime_state.json`

The runner script hard-enforces paper safety each launch:
- `ENVIRONMENT=paper`
- `LIVE_ORDER_EXECUTION_ENABLED=0`
- `LIVE_ORDER_FORCE_ACK=`

## Notes

- Keep the PC awake and network connected during market windows.
- If the PC reboots or process crashes, Task Scheduler restarts it.
- Built-in bot auto-resume recovers missed routines within configured windows (`AUTO_RESUME_*` in `.env`).
