from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable, Coroutine

from loguru import logger
from telegram import Bot
from telegram.error import TelegramError

from trading_bot.config.settings import Config


class TelegramReporter:
    def __init__(self) -> None:
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID

    async def send_message(self, message: str, parse_mode: str = "HTML") -> None:
        if not self.token or not self.chat_id:
            logger.info("Telegram not configured; skipping message")
            return
        try:
            async with Bot(token=self.token) as bot:
                await bot.send_message(chat_id=self.chat_id, text=message, parse_mode=parse_mode)
        except TelegramError as exc:
            logger.error(f"Telegram send failed: {exc}")

    def _run_async(self, factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Run async Telegram operations safely from sync call sites."""
        primary_coro = factory()
        try:
            asyncio.run(primary_coro)
            return
        except RuntimeError as exc:
            primary_coro.close()
            # Common cases:
            # - asyncio.run() cannot be called from a running event loop
            # - Event loop is closed
            logger.debug(f"Primary asyncio.run path unavailable: {exc}")
        except Exception as exc:
            primary_coro.close()
            logger.error(f"Telegram async execution failed: {exc}")
            return

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop and running_loop.is_running() and not running_loop.is_closed():
            try:
                running_loop.create_task(factory())
            except Exception as exc:
                logger.error(f"Telegram loop scheduling failed: {exc}")
            return

        temp_loop = asyncio.new_event_loop()
        try:
            temp_loop.run_until_complete(factory())
        except Exception as exc:
            logger.error(f"Telegram fallback loop failed: {exc}")
        finally:
            temp_loop.close()

    def send_message_sync(self, message: str, parse_mode: str = "HTML") -> None:
        self._run_async(lambda: self.send_message(message, parse_mode=parse_mode))

    async def send_photo(self, photo_path: str, caption: str | None = None) -> None:
        if not self.token or not self.chat_id:
            logger.info("Telegram not configured; skipping photo")
            return
        try:
            async with Bot(token=self.token) as bot:
                with open(photo_path, "rb") as photo:
                    await bot.send_photo(chat_id=self.chat_id, photo=photo, caption=caption)
        except Exception as exc:
            logger.error(f"Telegram photo send failed: {exc}")

    def send_photo_sync(self, photo_path: str, caption: str | None = None) -> None:
        self._run_async(lambda: self.send_photo(photo_path, caption=caption))

    def send_alert(self, alert_type: str, message: str) -> None:
        emoji_map = {"ERROR": "🚨", "WARNING": "⚠️", "INFO": "ℹ️", "SUCCESS": "✅"}
        emoji = emoji_map.get(alert_type, "📢")
        self.send_message_sync(f"{emoji} <b>{alert_type}</b>\n\n{message}")

    def send_trade_notification(self, trade: dict[str, Any], action: str) -> None:
        if action == "ENTRY":
            text = (
                "🟢 <b>NEW POSITION</b>\n\n"
                f"Symbol: <b>{trade['symbol']}</b>\n"
                f"Strategy: {trade['strategy']}\n"
                f"Entry: ₹{trade['entry_price']:.2f}\n"
                f"Quantity: {trade['quantity']}\n"
                f"Stop Loss: ₹{trade['stop_loss']:.2f}\n"
                f"Target: ₹{trade['target']:.2f}"
            )
        else:
            pnl = float(trade.get("pnl", 0.0))
            emoji = "🟢" if pnl > 0 else "🔴"
            text = (
                f"{emoji} <b>POSITION CLOSED</b>\n\n"
                f"Symbol: <b>{trade['symbol']}</b>\n"
                f"Exit: ₹{trade['exit_price']:.2f}\n"
                f"P&L: ₹{pnl:,.2f} ({trade.get('pnl_percent', 0.0):.2f}%)"
            )
        self.send_message_sync(text)

    def send_morning_report(self, signals: list[dict], portfolio_value: float, cash: float, positions: list[dict]) -> None:
        message = self._format_morning_report(signals, portfolio_value, cash, positions)
        self.send_message_sync(message)

    def send_daily_pnl_report(
        self,
        portfolio_data: dict[str, Any],
        positions: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        strategy_performance: dict[str, Any],
    ) -> None:
        message = self._format_daily_pnl(portfolio_data, positions, closed_trades, strategy_performance)
        self.send_message_sync(message)

    def send_weekly_summary(self, weekly_data: dict[str, Any]) -> None:
        message = self._format_weekly_summary(weekly_data)
        self.send_message_sync(message)

    def _format_morning_report(
        self,
        signals: list[dict[str, Any]],
        portfolio_value: float,
        cash: float,
        positions: list[dict[str, Any]],
    ) -> str:
        lines = [
            "🌅 <b>MORNING REPORT</b>",
            f"📅 {datetime.now().strftime('%d %b %Y, %A')}",
            "",
            f"💰 Portfolio: ₹{portfolio_value:,.2f}",
            f"💵 Cash: ₹{cash:,.2f}",
            f"📊 Open Positions: {len(positions)}",
            "",
            f"📍 Signals: {len(signals)}",
        ]
        for s in signals[:5]:
            lines.append(f"• <b>{s['symbol']}</b> {s['strategy']} @ ₹{s['price']:.2f}")
        return "\n".join(lines)

    def _format_daily_pnl(
        self,
        portfolio_data: dict[str, Any],
        positions: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        strategy_performance: dict[str, Any],
    ) -> str:
        daily_change = float(portfolio_data.get("daily_pnl", 0.0))
        daily_pct = float(portfolio_data.get("daily_pnl_pct", 0.0))
        emoji = "📈" if daily_change > 0 else "📉"

        lines = [
            f"{emoji} <b>DAILY REPORT</b>",
            f"📅 {datetime.now().strftime('%d %b %Y')}",
            "",
            f"💰 Portfolio Value: ₹{float(portfolio_data.get('total_value', 0.0)):,.2f}",
            f"{'📈' if daily_change > 0 else '📉'} Today: ₹{daily_change:,.2f} ({daily_pct:+.2f}%)",
            f"💵 Cash: ₹{float(portfolio_data.get('cash', 0.0)):,.2f}",
            f"📊 Positions: {int(portfolio_data.get('num_positions', 0))}",
            "",
        ]

        if positions:
            lines.append("📍 <b>OPEN POSITIONS</b>")
            winners = [p for p in positions if float(p.get("unrealized_pnl", 0.0)) > 0]
            losers = [p for p in positions if float(p.get("unrealized_pnl", 0.0)) < 0]
            for p in winners[:3]:
                lines.append(
                    f"🟢 {p['symbol']}: +{float(p.get('unrealized_pnl_pct', 0.0)):.2f}% (₹{float(p.get('unrealized_pnl', 0.0)):,.0f})"
                )
            for p in losers[:3]:
                lines.append(
                    f"🔴 {p['symbol']}: {float(p.get('unrealized_pnl_pct', 0.0)):.2f}% (₹{float(p.get('unrealized_pnl', 0.0)):,.0f})"
                )
            lines.append("")

        if closed_trades:
            lines.append(f"✅ <b>CLOSED TODAY ({len(closed_trades)})</b>")
            for t in closed_trades:
                t_emoji = "🟢" if float(t.get("pnl", 0.0)) > 0 else "🔴"
                lines.append(
                    f"{t_emoji} {t.get('symbol', '')}: ₹{float(t.get('pnl', 0.0)):,.0f} ({float(t.get('pnl_percent', 0.0)):.2f}%)"
                )
            lines.append("")

        if strategy_performance:
            lines.append("⚙️ <b>STRATEGY PERFORMANCE (MTD)</b>")
            for name, perf in strategy_performance.items():
                lines.append(
                    f"• {name}: {float(perf.get('pnl_pct', 0.0)):+.2f}% | {int(perf.get('wins', 0))}W-{int(perf.get('losses', 0))}L"
                )

        return "\n".join(lines)

    def _format_weekly_summary(self, weekly_data: dict[str, Any]) -> str:
        lines = [
            "📊 <b>WEEKLY SUMMARY</b>",
            f"Week ending: {datetime.now().strftime('%d %b %Y')}",
            "",
            f"💰 Starting: ₹{float(weekly_data.get('start_value', 0.0)):,.2f}",
            f"💰 Ending: ₹{float(weekly_data.get('end_value', 0.0)):,.2f}",
            f"{'📈' if float(weekly_data.get('weekly_pnl', 0.0)) > 0 else '📉'} Weekly P&L: ₹{float(weekly_data.get('weekly_pnl', 0.0)):,.2f} ({float(weekly_data.get('weekly_pnl_pct', 0.0)):+.2f}%)",
            "",
            f"📈 Total Trades: {int(weekly_data.get('total_trades', 0))}",
            f"🟢 Wins: {int(weekly_data.get('wins', 0))} ({float(weekly_data.get('win_rate', 0.0)):.1f}%)",
            f"🔴 Losses: {int(weekly_data.get('losses', 0))}",
            f"💎 Best Trade: ₹{float(weekly_data.get('best_trade', 0.0)):,.0f}",
            f"💔 Worst Trade: ₹{float(weekly_data.get('worst_trade', 0.0)):,.0f}",
            "",
            f"📉 Max Drawdown: {float(weekly_data.get('max_drawdown', 0.0)):.2f}%",
            f"📊 Sharpe Ratio: {float(weekly_data.get('sharpe', 0.0)):.2f}",
        ]
        return "\n".join(lines)


telegram_reporter = TelegramReporter()
