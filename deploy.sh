#!/bin/bash
set -euo pipefail

echo "================================"
echo "Trading Bot Deployment Script"
echo "================================"

python3 --version

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p logs reports data/storage

python3 -c "from trading_bot.data.storage.database import db; db.init_db(); print('DB initialized')"
python3 -c "from trading_bot.config.settings import Config; Config.validate(); print('Config validated')"
python3 -c "from trading_bot.reporting.telegram_bot import TelegramReporter; TelegramReporter().send_alert('INFO','Deployment check complete')"

echo "================================"
echo "Deployment complete"
echo "================================"
