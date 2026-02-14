from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime, time as dt_time
from pathlib import Path
from typing import Any

import pandas as pd
import schedule
from loguru import logger
from sqlalchemy import text

from trading_bot.config.settings import Config
from trading_bot.data.collectors.alternative_data import AlternativeDataScraper
from trading_bot.data.collectors.market_data import MarketDataCollector
from trading_bot.data.storage.database import db
from trading_bot.data.storage.feature_store import FeatureStore
from trading_bot.execution.broker_interface import BrokerInterface
from trading_bot.monitoring.audit_artifacts import write_json, write_weekly_audit_artifact
from trading_bot.monitoring.audit_trend import load_weekly_audits, summarize_audit_trend, write_trend_artifact
from trading_bot.monitoring.gate_profiles import build_audit_thresholds, required_paper_weeks, resolve_go_live_profile
from trading_bot.monitoring.logger import setup_logging
from trading_bot.monitoring.paper_run_tracker import (
    compute_paper_run_status,
    load_promotion_records,
    load_weekly_audit_records,
)
from trading_bot.monitoring.performance_audit import run_weekly_audit
from trading_bot.monitoring.retention import rotate_many
from trading_bot.reporting.report_generator import ReportGenerator
from trading_bot.reporting.telegram_bot import TelegramReporter
from trading_bot.risk.position_sizer import size_position, size_position_adaptive
from trading_bot.risk.risk_manager import RiskManager
from trading_bot.strategies.adaptive_trend import AdaptiveTrendFollowingStrategy
from trading_bot.strategies.base_strategy import BaseStrategy, Signal
from trading_bot.strategies.bear_reversal import BearReversalStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.momentum_breakout import MomentumBreakoutStrategy
from trading_bot.strategies.sector_rotation import SectorRotationStrategy
from trading_bot.strategies.volatility_reversal import VolatilityReversalStrategy


class TradingBot:
    def __init__(
        self,
        paper_mode: bool = True,
        dry_run_live: bool = False,
        simulation_mode: bool = False,
        simulation_date: datetime | None = None,
    ) -> None:
        setup_logging()
        os.makedirs("logs", exist_ok=True)
        os.makedirs("reports", exist_ok=True)

        Config.validate()
        db.init_db()

        self.paper_mode = paper_mode
        self.dry_run_live = dry_run_live
        if self.paper_mode and self.dry_run_live:
            raise ValueError("dry_run_live can only be used with live mode")
        self.live_orders_armed = False
        if not self.paper_mode and not self.dry_run_live:
            armed_by_config = bool(Config.LIVE_ORDER_EXECUTION_ENABLED)
            ack_ok = Config.LIVE_ORDER_FORCE_ACK == Config.LIVE_ORDER_ACK_PHRASE
            if armed_by_config and ack_ok:
                self.live_orders_armed = True
            else:
                self.dry_run_live = True
                logger.warning(
                    "Live order execution blocked by safety lock. "
                    "Set LIVE_ORDER_EXECUTION_ENABLED=1 and LIVE_ORDER_FORCE_ACK={} to arm live orders.",
                    Config.LIVE_ORDER_ACK_PHRASE,
                )
        self.simulation_mode = simulation_mode
        self.simulation_date = simulation_date
        self.data_collector = MarketDataCollector()
        self.alt_scraper = AlternativeDataScraper(headless=True)
        self.broker = BrokerInterface()
        self.risk_manager = RiskManager(Config.STARTING_CAPITAL, clock=self._now)
        self.telegram = TelegramReporter()
        self.reporter = ReportGenerator()
        self.feature_store = FeatureStore(db.engine)

        self.strategies: dict[str, BaseStrategy] = {}
        if Config.ENABLE_MOMENTUM_BREAKOUT:
            self.strategies["momentum_breakout"] = MomentumBreakoutStrategy(
                lookback_period=Config.MOMENTUM_LOOKBACK_PERIOD,
                min_history=Config.MOMENTUM_MIN_HISTORY,
                volume_multiplier=Config.MOMENTUM_VOLUME_MULTIPLIER,
                min_roc=Config.MOMENTUM_MIN_ROC,
                max_atr_pct=Config.MOMENTUM_MAX_ATR_PCT,
                stop_atr_mult=Config.MOMENTUM_STOP_ATR_MULT,
                rr_ratio=Config.MOMENTUM_RR_RATIO,
                time_stop_days=Config.MOMENTUM_TIME_STOP_DAYS,
                time_stop_move_pct=Config.MOMENTUM_TIME_STOP_MOVE_PCT,
                enable_regime_filter=Config.MOMENTUM_ENABLE_REGIME_FILTER,
                regime_sma_period=Config.MOMENTUM_REGIME_SMA_PERIOD,
                regime_vol_window=Config.MOMENTUM_REGIME_VOL_WINDOW,
                regime_max_annual_vol=Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL,
            )
        if Config.ENABLE_MEAN_REVERSION:
            self.strategies["mean_reversion"] = MeanReversionStrategy(
                oversold_buffer=Config.MEAN_REV_OVERSOLD_BUFFER,
                trend_tolerance=Config.MEAN_REV_TREND_TOLERANCE,
                bb_entry_mult=Config.MEAN_REV_BB_ENTRY_MULT,
                volume_cap=Config.MEAN_REV_VOLUME_CAP,
                stop_bb_buffer=Config.MEAN_REV_STOP_BB_BUFFER,
                stop_sma_buffer=Config.MEAN_REV_STOP_SMA_BUFFER,
                stop_atr_mult=Config.MEAN_REV_STOP_ATR_MULT,
                target_gain_pct=Config.MEAN_REV_TARGET_GAIN_PCT,
                time_stop_days=Config.MEAN_REV_TIME_STOP_DAYS,
            )
        if Config.ENABLE_SECTOR_ROTATION:
            self.strategies["sector_rotation"] = SectorRotationStrategy()
        if Config.ENABLE_ADAPTIVE_TREND:
            self.strategies["adaptive_trend"] = AdaptiveTrendFollowingStrategy(
                weekly_ema_short=Config.ADAPTIVE_TREND_WEEKLY_EMA_SHORT,
                weekly_ema_long=Config.ADAPTIVE_TREND_WEEKLY_EMA_LONG,
                weekly_atr_period=Config.ADAPTIVE_TREND_WEEKLY_ATR_PERIOD,
                weekly_rsi_period=Config.ADAPTIVE_TREND_WEEKLY_RSI_PERIOD,
                min_weekly_roc=Config.ADAPTIVE_TREND_MIN_WEEKLY_ROC,
                max_weekly_roc=Config.ADAPTIVE_TREND_MAX_WEEKLY_ROC,
                min_weekly_ema_spread_pct=Config.ADAPTIVE_TREND_MIN_WEEKLY_EMA_SPREAD_PCT,
                min_trend_consistency=Config.ADAPTIVE_TREND_MIN_TREND_CONSISTENCY,
                min_expected_r_mult=Config.ADAPTIVE_TREND_MIN_EXPECTED_R_MULT,
                stop_atr_mult=Config.ADAPTIVE_TREND_STOP_ATR_MULT,
                profit_protect_pct=Config.ADAPTIVE_TREND_PROFIT_PROTECT_PCT,
                profit_trail_atr_mult=Config.ADAPTIVE_TREND_PROFIT_TRAIL_ATR_MULT,
                breakeven_gain_pct=Config.ADAPTIVE_TREND_BREAKEVEN_GAIN_PCT,
                breakeven_buffer_pct=Config.ADAPTIVE_TREND_BREAKEVEN_BUFFER_PCT,
                max_positions=Config.ADAPTIVE_TREND_MAX_POSITIONS,
                max_new_per_week=Config.ADAPTIVE_TREND_MAX_NEW_PER_WEEK,
                min_hold_days=Config.ADAPTIVE_TREND_MIN_HOLD_DAYS,
                time_stop_days=Config.ADAPTIVE_TREND_TIME_STOP_DAYS,
                regime_min_breadth=Config.ADAPTIVE_TREND_REGIME_MIN_BREADTH,
                regime_max_vol=Config.ADAPTIVE_TREND_REGIME_MAX_VOL,
            )
        if Config.ENABLE_BEAR_REVERSAL:
            self.strategies["bear_reversal"] = BearReversalStrategy(
                rsi_period=Config.BEAR_REV_RSI_PERIOD,
                rsi_oversold=Config.BEAR_REV_RSI_OVERSOLD,
                rsi_reentry=Config.BEAR_REV_RSI_REENTRY,
                trend_sma_period=Config.BEAR_REV_TREND_SMA_PERIOD,
                trend_below_sma_mult=Config.BEAR_REV_TREND_BELOW_SMA_MULT,
                drop_lookback_days=Config.BEAR_REV_DROP_LOOKBACK_DAYS,
                min_drop_pct=Config.BEAR_REV_MIN_DROP_PCT,
                min_volume_ratio=Config.BEAR_REV_MIN_VOLUME_RATIO,
                stop_atr_mult=Config.BEAR_REV_STOP_ATR_MULT,
                rr_ratio=Config.BEAR_REV_RR_RATIO,
                max_hold_days=Config.BEAR_REV_MAX_HOLD_DAYS,
            )
        if Config.ENABLE_VOLATILITY_REVERSAL:
            self.strategies["volatility_reversal"] = VolatilityReversalStrategy(
                rsi_period=Config.VOL_REV_RSI_PERIOD,
                rsi_reentry=Config.VOL_REV_RSI_REENTRY,
                drop_lookback_days=Config.VOL_REV_DROP_LOOKBACK_DAYS,
                min_drop_pct=Config.VOL_REV_MIN_DROP_PCT,
                vol_spike_mult=Config.VOL_REV_VOL_SPIKE_MULT,
                min_atr_pct=Config.VOL_REV_MIN_ATR_PCT,
                trend_sma_period=Config.VOL_REV_TREND_SMA_PERIOD,
                trend_below_sma_mult=Config.VOL_REV_TREND_BELOW_SMA_MULT,
                stop_atr_mult=Config.VOL_REV_STOP_ATR_MULT,
                rr_ratio=Config.VOL_REV_RR_RATIO,
                max_hold_days=Config.VOL_REV_MAX_HOLD_DAYS,
            )

        self.cash = Config.STARTING_CAPITAL
        self.positions: dict[str, dict[str, Any]] = {}
        self.portfolio_value = Config.STARTING_CAPITAL
        self.pending_signals: list[Signal] = []
        self._intent_day = self._today_str()
        self._executed_intents: set[str] = set()
        self.control_dir = Path("control")
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.kill_switch_path = self.control_dir / "kill_switch.flag"
        self.heartbeat_path = self.control_dir / "heartbeat.json"
        self.runtime_state_path = self.control_dir / "runtime_state.json"
        self._runtime_state: dict[str, Any] = self._load_runtime_state()
        self._last_recovery_check_at = 0.0
        self._restore_portfolio_state_from_db()
        self._restore_open_positions_from_db()

        self.universe = self._initialize_universe()

        if not paper_mode:
            if not self.broker.connect():
                raise RuntimeError("Broker connection failed")
            self._reconcile_with_broker()

        logger.info(
            "Strategy profile={} enabled={} risk_per_trade={:.4f} max_position_size={:.4f}",
            Config.STRATEGY_PROFILE,
            ",".join(self.strategies.keys()) or "none",
            Config.RISK_PER_TRADE,
            Config.MAX_POSITION_SIZE,
        )

        self.telegram.send_alert(
            "SUCCESS",
            (
                f"Trading bot started in {'paper' if self.paper_mode else 'live'} mode "
                f"({'dry-run' if self.dry_run_live else 'orders-enabled'}) with capital ₹{self.cash:,.0f}"
            ),
        )

    def _initialize_universe(self) -> list[str]:
        local_only = self.simulation_mode or os.getenv("USE_LOCAL_UNIVERSE", "0") == "1"
        universe_file = os.getenv("UNIVERSE_FILE", "").strip()
        if universe_file:
            try:
                path = Path(universe_file)
                raw = path.read_text(encoding="utf-8").splitlines()
                symbols = [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]
                symbols = [s.replace(".NS", "").upper() for s in symbols]
                if symbols:
                    logger.info(f"Using UNIVERSE_FILE universe: {len(symbols)} symbols")
                    return symbols
            except Exception as exc:
                logger.warning(f"Failed loading UNIVERSE_FILE={universe_file}: {exc}")

        trading_universe = (Config.TRADING_UNIVERSE or os.getenv("TRADING_UNIVERSE", "")).strip().lower()
        if local_only:
            try:
                local_df = pd.read_sql(
                    "SELECT DISTINCT symbol FROM price_data WHERE symbol IS NOT NULL AND symbol <> '' ORDER BY symbol",
                    db.engine,
                )
                if not local_df.empty:
                    symbols = [str(x).strip() for x in local_df["symbol"].tolist() if str(x).strip()]
                    logger.info(f"Using local DB universe for simulation: {len(symbols)} symbols")
                    return symbols
            except Exception as exc:
                logger.warning(f"Failed loading local universe: {exc}")

        try:
            if trading_universe in {"midcap150", "niftymidcap150"}:
                symbols = self.data_collector.get_nifty_midcap_150_list()
            else:
                symbols = self.data_collector.get_nifty_500_list()
            universe = self.data_collector.filter_liquid_stocks(symbols[:100])
            if universe:
                return universe
        except Exception as exc:
            logger.warning(f"Primary universe bootstrap failed: {exc}")

        local_df = pd.read_sql(
            "SELECT DISTINCT symbol FROM price_data WHERE symbol IS NOT NULL AND symbol <> '' ORDER BY symbol",
            db.engine,
        )
        fallback = [str(x).strip() for x in local_df["symbol"].tolist() if str(x).strip()]
        if fallback:
            logger.warning(f"Falling back to local DB universe: {len(fallback)} symbols")
            return fallback
        return self.data_collector._get_fallback_symbols()

    def _now(self) -> datetime:
        return self.simulation_date or datetime.now()

    def _today_str(self) -> str:
        return str(self._now().date())

    def set_simulation_date(self, dt: datetime) -> None:
        self.simulation_mode = True
        self.simulation_date = dt

    def _roll_intent_day(self) -> None:
        today = self._today_str()
        if today != self._intent_day:
            self._intent_day = today
            self._executed_intents.clear()

    def _intent_key(self, action: str, symbol: str, quantity: int) -> str:
        return f"{self._today_str()}::{action.upper()}::{symbol.upper()}::{quantity}"

    def _is_kill_switch_active(self) -> bool:
        if os.getenv("KILL_SWITCH", "0") == "1":
            return True
        return self.kill_switch_path.exists()

    def _write_heartbeat(self, stage: str) -> None:
        payload = {
            "timestamp": self._now().isoformat(),
            "stage": stage,
            "paper_mode": self.paper_mode,
            "dry_run_live": self.dry_run_live,
            "simulation_mode": self.simulation_mode,
            "portfolio_value": self.portfolio_value,
            "cash": self.cash,
            "positions": len(self.positions),
        }
        self.heartbeat_path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _default_runtime_state() -> dict[str, Any]:
        return {
            "routines": {},
            "pending_signals": {
                "date": None,
                "saved_at": None,
                "consumed": True,
                "signals": [],
            },
        }

    @staticmethod
    def _parse_clock_time(value: str, fallback: dt_time) -> dt_time:
        try:
            return datetime.strptime(value.strip(), "%H:%M").time()
        except Exception:
            return fallback

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): TradingBot._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [TradingBot._json_safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                return str(value)
        return str(value)

    def _load_runtime_state(self) -> dict[str, Any]:
        if not self.runtime_state_path.exists():
            state = self._default_runtime_state()
            self.runtime_state_path.write_text(json.dumps(state), encoding="utf-8")
            return state
        try:
            parsed = json.loads(self.runtime_state_path.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("runtime state root must be dict")
            routines = parsed.get("routines")
            pending = parsed.get("pending_signals")
            if not isinstance(routines, dict):
                parsed["routines"] = {}
            if not isinstance(pending, dict):
                parsed["pending_signals"] = self._default_runtime_state()["pending_signals"]
            return parsed
        except Exception as exc:
            logger.warning(f"Invalid runtime state; resetting file: {exc}")
            state = self._default_runtime_state()
            self.runtime_state_path.write_text(json.dumps(state), encoding="utf-8")
            return state

    def _save_runtime_state(self) -> None:
        clean = self._json_safe(self._runtime_state)
        self.runtime_state_path.write_text(json.dumps(clean), encoding="utf-8")

    def _mark_routine_completed(self, routine_name: str) -> None:
        routines = self._runtime_state.setdefault("routines", {})
        if not isinstance(routines, dict):
            routines = {}
            self._runtime_state["routines"] = routines
        routines[routine_name] = {
            "date": self._today_str(),
            "timestamp": self._now().isoformat(),
        }
        self._save_runtime_state()

    def _routine_completed_today(self, routine_name: str) -> bool:
        routines = self._runtime_state.get("routines", {})
        if not isinstance(routines, dict):
            return False
        payload = routines.get(routine_name, {})
        if not isinstance(payload, dict):
            return False
        return str(payload.get("date", "")) == self._today_str()

    @staticmethod
    def _serialize_signal(signal: Signal) -> dict[str, Any]:
        return {
            "symbol": str(signal.symbol),
            "action": str(signal.action),
            "price": float(signal.price),
            "quantity": int(signal.quantity),
            "stop_loss": float(signal.stop_loss),
            "target": float(signal.target),
            "strategy": str(signal.strategy),
            "confidence": float(signal.confidence),
            "timestamp": signal.timestamp.isoformat(),
            "metadata": TradingBot._json_safe(dict(signal.metadata or {})),
        }

    def _deserialize_signal(self, payload: dict[str, Any]) -> Signal | None:
        try:
            ts_raw = payload.get("timestamp")
            ts = datetime.fromisoformat(str(ts_raw)) if ts_raw else self._now()
            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            return Signal(
                symbol=str(payload["symbol"]),
                action=str(payload.get("action", "BUY")),
                price=float(payload["price"]),
                quantity=int(payload.get("quantity", 0)),
                stop_loss=float(payload["stop_loss"]),
                target=float(payload["target"]),
                strategy=str(payload.get("strategy", "unknown")),
                confidence=float(payload.get("confidence", 0.5)),
                timestamp=ts,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(f"Skipping invalid persisted signal payload: {exc}")
            return None

    def _persist_pending_signals(self, signals: list[Signal]) -> None:
        self._runtime_state["pending_signals"] = {
            "date": self._today_str(),
            "saved_at": self._now().isoformat(),
            "consumed": False,
            "signals": [self._serialize_signal(signal) for signal in signals],
        }
        self._save_runtime_state()

    def _restore_pending_signals(self) -> list[Signal]:
        payload = self._runtime_state.get("pending_signals", {})
        if not isinstance(payload, dict):
            return []
        if str(payload.get("date", "")) != self._today_str():
            return []
        if bool(payload.get("consumed", True)):
            return []
        serialized = payload.get("signals", [])
        if not isinstance(serialized, list):
            return []
        restored: list[Signal] = []
        for item in serialized:
            if not isinstance(item, dict):
                continue
            signal = self._deserialize_signal(item)
            if signal is not None:
                restored.append(signal)
        return restored

    def _mark_pending_signals_consumed(self) -> None:
        payload = self._runtime_state.get("pending_signals")
        if not isinstance(payload, dict):
            return
        if str(payload.get("date", "")) != self._today_str():
            return
        payload["consumed"] = True
        self._runtime_state["pending_signals"] = payload
        self._save_runtime_state()

    def _restore_portfolio_state_from_db(self) -> None:
        try:
            latest = pd.read_sql(
                """
                SELECT total_value, cash
                FROM portfolio_snapshots
                ORDER BY date DESC
                LIMIT 1
                """,
                db.engine,
            )
            if not latest.empty:
                row = latest.iloc[0]
                if pd.notna(row.get("cash")):
                    self.cash = float(row["cash"])
                if pd.notna(row.get("total_value")):
                    self.portfolio_value = float(row["total_value"])
        except Exception as exc:
            logger.warning(f"Portfolio state restore skipped: {exc}")

    def _restore_open_positions_from_db(self) -> None:
        try:
            open_df = pd.read_sql(
                """
                SELECT order_id, symbol, strategy, quantity, entry_price, entry_date, stop_loss, target
                FROM trades
                WHERE status = 'OPEN'
                ORDER BY entry_date ASC
                """,
                db.engine,
            )
        except Exception as exc:
            logger.warning(f"Open positions restore skipped: {exc}")
            return

        restored = 0
        for _, row in open_df.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            if not symbol:
                continue
            if symbol in self.positions:
                continue
            try:
                qty = int(row.get("quantity", 0))
                entry_price = float(row.get("entry_price", 0.0))
                if qty <= 0 or entry_price <= 0:
                    continue
                entry_date_raw = row.get("entry_date")
                try:
                    entry_date = pd.to_datetime(entry_date_raw).to_pydatetime()
                except Exception:
                    entry_date = self._now()
                self.positions[symbol] = {
                    "symbol": symbol,
                    "strategy": str(row.get("strategy", "unknown")),
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "quantity": qty,
                    "stop_loss": float(row.get("stop_loss", entry_price * 0.95)),
                    "target": float(row.get("target", entry_price * 1.08)),
                    "highest_close": entry_price,
                    "lowest_close": entry_price,
                    "weekly_atr": 0.0,
                    "metadata": {},
                    "days_held": max(0, (self._now() - entry_date).days),
                    "order_id": str(row.get("order_id", "")),
                }
                restored += 1
            except Exception:
                continue
        if restored > 0:
            logger.info(f"Restored {restored} open position(s) from local DB state")

    def _in_time_window(self, current: dt_time, start_raw: str, end_raw: str, fallback_start: dt_time, fallback_end: dt_time) -> bool:
        start = self._parse_clock_time(start_raw, fallback_start)
        end = self._parse_clock_time(end_raw, fallback_end)
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def _run_recovery_cycle(self, force: bool = False) -> list[str]:
        if not Config.AUTO_RESUME_ENABLED:
            return []
        if not force:
            min_interval = max(5, int(Config.AUTO_RESUME_INTERVAL_SECONDS))
            now_monotonic = time.monotonic()
            if now_monotonic - self._last_recovery_check_at < min_interval:
                return []
            self._last_recovery_check_at = now_monotonic

        now_dt = self._now()
        if now_dt.weekday() >= 5:
            return []
        now_clock = now_dt.time()
        recovered: list[str] = []

        if self._in_time_window(
            now_clock,
            Config.AUTO_RESUME_PREMARKET_START,
            Config.AUTO_RESUME_PREMARKET_CUTOFF,
            dt_time(8, 0),
            dt_time(10, 0),
        ) and not self._routine_completed_today("pre_market"):
            logger.warning(f"Auto-resume running missed pre-market routine for {self._today_str()}")
            self.pre_market_routine()
            recovered.append("pre_market")

        if self._in_time_window(
            now_clock,
            Config.AUTO_RESUME_MARKET_OPEN_START,
            Config.AUTO_RESUME_MARKET_OPEN_CUTOFF,
            dt_time(9, 15),
            dt_time(11, 30),
        ) and not self._routine_completed_today("market_open"):
            if self._routine_completed_today("pre_market"):
                logger.warning(f"Auto-resume running missed market-open routine for {self._today_str()}")
                self.market_open_routine()
                recovered.append("market_open")

        if self._in_time_window(
            now_clock,
            Config.AUTO_RESUME_MARKET_CLOSE_START,
            Config.AUTO_RESUME_MARKET_CLOSE_CUTOFF,
            dt_time(15, 30),
            dt_time(21, 0),
        ) and not self._routine_completed_today("market_close"):
            logger.warning(f"Auto-resume running missed market-close routine for {self._today_str()}")
            self.market_close_routine()
            recovered.append("market_close")

        return recovered

    def _should_place_live_orders(self) -> bool:
        return (not self.paper_mode) and (not self.dry_run_live) and self.live_orders_armed

    def _insert_system_log(self, level: str, module: str, message: str, metadata: dict[str, Any] | None = None) -> None:
        query = """
            INSERT INTO system_logs (level, module, message, metadata)
            VALUES (:level, :module, :message, :metadata)
        """
        payload = {
            "level": level.upper(),
            "module": module,
            "message": message,
            "metadata": json.dumps(metadata or {}),
        }
        with db.engine.begin() as conn:
            conn.execute(text(query), payload)

    def reconciliation_routine(self) -> dict[str, int | bool]:
        self._write_heartbeat("reconcile_start")
        if self.paper_mode:
            logger.info("Skipping reconciliation in paper mode")
            self._write_heartbeat("reconcile_skipped_paper")
            return {
                "skipped": True,
                "mismatched_open_trades": 0,
                "untracked_broker_positions": 0,
                "auto_closed_trades": 0,
            }

        lookback_days = max(1, int(Config.RECONCILIATION_LOOKBACK_DAYS))
        lookback_anchor = self._now().date().strftime("%Y-%m-%d")
        lookback_start_query = f"date(:anchor, '-{lookback_days} day')"
        trades_query = f"""
            SELECT order_id, symbol, quantity, entry_price, entry_date
            FROM trades
            WHERE status = 'OPEN'
              AND date(entry_date) >= {lookback_start_query}
        """
        open_trades_df = pd.read_sql(trades_query, db.engine, params={"anchor": lookback_anchor})

        broker_positions = self.broker.get_current_positions()
        broker_qty_by_symbol: dict[str, int] = {}
        for pos in broker_positions:
            symbol = str(pos.get("symbol", "")).replace(".NS", "").upper()
            qty_raw = pos.get("quantity", pos.get("net_quantity", 0))
            try:
                qty = int(float(qty_raw))
            except (TypeError, ValueError):
                qty = 0
            if symbol and qty > 0:
                broker_qty_by_symbol[symbol] = qty

        mismatches: list[dict[str, Any]] = []
        db_symbols: set[str] = set()
        for _, row in open_trades_df.iterrows():
            symbol = str(row["symbol"]).replace(".NS", "").upper()
            db_qty = int(row["quantity"])
            broker_qty = broker_qty_by_symbol.get(symbol, 0)
            db_symbols.add(symbol)
            if db_qty != broker_qty:
                mismatches.append(
                    {
                        "order_id": str(row["order_id"]),
                        "symbol": symbol,
                        "db_qty": db_qty,
                        "broker_qty": broker_qty,
                        "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else 0.0,
                    }
                )

        untracked_positions = []
        for symbol, broker_qty in broker_qty_by_symbol.items():
            if symbol not in db_symbols:
                untracked_positions.append({"symbol": symbol, "broker_qty": broker_qty})

        auto_closed = 0
        if Config.RECONCILIATION_ENFORCE_CLOSE:
            for item in mismatches:
                if item["broker_qty"] == 0:
                    symbol = str(item["symbol"])
                    current = self._get_current_price(symbol) or {}
                    exit_price = float(current.get("close", item["entry_price"]))
                    entry_price = float(item["entry_price"])
                    qty = int(item["db_qty"])
                    pnl = (exit_price - entry_price) * qty
                    base = entry_price * qty
                    pnl_percent = (pnl / base) * 100 if base > 0 else 0.0

                    update_query = """
                        UPDATE trades
                        SET status = 'CLOSED',
                            action = 'SELL',
                            exit_price = :exit_price,
                            exit_date = :exit_date,
                            pnl = :pnl,
                            pnl_percent = :pnl_percent,
                            notes = :notes
                        WHERE order_id = :order_id
                          AND status = 'OPEN'
                    """
                    with db.engine.begin() as conn:
                        conn.execute(
                            text(update_query),
                            {
                                "order_id": item["order_id"],
                                "exit_price": exit_price,
                                "exit_date": self._now().isoformat(),
                                "pnl": pnl,
                                "pnl_percent": pnl_percent,
                                "notes": "RECONCILE_AUTO_CLOSE_MISSING_AT_BROKER",
                            },
                        )
                    self.positions.pop(symbol, None)
                    auto_closed += 1

        if mismatches:
            self._insert_system_log(
                "WARNING",
                "reconciliation",
                f"Detected {len(mismatches)} open-trade mismatches",
                {"mismatches": mismatches[:20]},
            )
        if untracked_positions:
            self._insert_system_log(
                "WARNING",
                "reconciliation",
                f"Detected {len(untracked_positions)} broker positions not tracked in local DB",
                {"positions": untracked_positions[:20]},
            )

        summary = {
            "skipped": False,
            "mismatched_open_trades": len(mismatches),
            "untracked_broker_positions": len(untracked_positions),
            "auto_closed_trades": auto_closed,
        }
        logger.info(f"Reconciliation summary: {summary}")
        self._mark_routine_completed("reconciliation")
        self._write_heartbeat("reconcile_complete")
        return summary

    def weekly_audit_routine(self) -> dict[str, Any]:
        self._write_heartbeat("weekly_audit_start")
        try:
            profile = resolve_go_live_profile()
            thresholds = build_audit_thresholds(profile)
            result = run_weekly_audit(db.engine, weeks=4, thresholds=thresholds)
            artifact = write_weekly_audit_artifact(result, output_dir="reports/audits")

            ready = bool(result.get("ready_for_live", False))
            self._insert_system_log(
                "INFO",
                "weekly_audit",
                f"Weekly audit complete. ready_for_live={ready}",
                {
                    "artifact": str(artifact),
                    "gate_profile": profile,
                    "thresholds": {
                        "min_sharpe": thresholds.min_sharpe,
                        "max_drawdown": thresholds.max_drawdown,
                        "min_win_rate": thresholds.min_win_rate,
                        "min_closed_trades": thresholds.min_closed_trades,
                        "max_critical_errors": thresholds.max_critical_errors,
                        "critical_window_days": thresholds.critical_window_days,
                    },
                    "failed_gates": [
                        name
                        for name, gate in result.get("gates", {}).items()
                        if isinstance(gate, dict) and not bool(gate.get("passed"))
                    ],
                },
            )
            self.telegram.send_alert(
                "SUCCESS" if ready else "WARNING",
                (
                    "Weekly audit completed\n"
                    f"Ready for live: {ready}\n"
                    f"Artifact: {artifact}"
                ),
            )
            self._mark_routine_completed("weekly_audit")
            self._write_heartbeat("weekly_audit_complete")
            return result
        except Exception as exc:
            self._insert_system_log("ERROR", "weekly_audit", f"Weekly audit failed: {exc}")
            self.telegram.send_alert("ERROR", f"Weekly audit failed: {exc}")
            self._write_heartbeat("weekly_audit_failed")
            raise

    def weekly_audit_trend_routine(self) -> dict[str, Any]:
        self._write_heartbeat("weekly_audit_trend_start")
        try:
            records = load_weekly_audits("reports/audits")
            summary = summarize_audit_trend(records, lookback=Config.AUDIT_TREND_LOOKBACK)
            artifact = write_trend_artifact(summary, output_dir="reports/audits/trends")
            needs_attention = bool(summary.get("needs_attention", False))
            self._insert_system_log(
                "WARNING" if needs_attention else "INFO",
                "weekly_audit_trend",
                (
                    f"Weekly audit trend generated. needs_attention={needs_attention} "
                    f"records={summary.get('records_considered', 0)}"
                ),
                {"artifact": str(artifact), "drift_alerts": summary.get("drift_alerts", {})},
            )
            if needs_attention:
                self.telegram.send_alert(
                    "WARNING",
                    (
                        "Weekly audit trend detected drift alerts\n"
                        f"Artifact: {artifact}"
                    ),
                )
            self._mark_routine_completed("weekly_audit_trend")
            self._write_heartbeat("weekly_audit_trend_complete")
            return summary
        except Exception as exc:
            self._insert_system_log("ERROR", "weekly_audit_trend", f"Weekly audit trend failed: {exc}")
            self.telegram.send_alert("ERROR", f"Weekly audit trend failed: {exc}")
            self._write_heartbeat("weekly_audit_trend_failed")
            raise

    def retention_rotation_routine(self) -> dict[str, Any]:
        self._write_heartbeat("retention_rotation_start")
        try:
            result = rotate_many(
                Config.RETENTION_SOURCES,
                archive_root=Config.RETENTION_ARCHIVE_ROOT,
                retention_days=Config.RETENTION_DAYS,
                dry_run=False,
            )
            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            artifact = write_json(Path("reports/retention") / f"retention_{stamp}.json", result)
            failed = int(result.get("files_failed", 0))
            self._insert_system_log(
                "WARNING" if failed > 0 else "INFO",
                "retention_rotation",
                (
                    f"Retention rotation completed: rotated={result.get('files_rotated', 0)} "
                    f"failed={failed}"
                ),
                {"artifact": str(artifact), "sources": Config.RETENTION_SOURCES},
            )
            if failed > 0:
                self.telegram.send_alert(
                    "WARNING",
                    (
                        "Retention rotation completed with failures\n"
                        f"Artifact: {artifact}\n"
                        f"Failed files: {failed}"
                    ),
                )
            self._mark_routine_completed("retention_rotation")
            self._write_heartbeat("retention_rotation_complete")
            return result
        except Exception as exc:
            self._insert_system_log("ERROR", "retention_rotation", f"Retention rotation failed: {exc}")
            self.telegram.send_alert("ERROR", f"Retention rotation failed: {exc}")
            self._write_heartbeat("retention_rotation_failed")
            raise

    def paper_run_status_routine(self) -> dict[str, Any]:
        self._write_heartbeat("paper_run_status_start")
        try:
            profile = resolve_go_live_profile()
            required_weeks = required_paper_weeks(profile)
            weekly_records = load_weekly_audit_records("reports/audits")
            promotion_records = load_promotion_records("reports/promotion")
            result = compute_paper_run_status(
                weekly_records=weekly_records,
                promotion_records=promotion_records,
                required_weeks=required_weeks,
                require_promotion_bundle=Config.PAPER_RUN_REQUIRE_PROMOTION_BUNDLE,
            )
            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            artifact = write_json(Path("reports/promotion") / f"paper_run_status_{stamp}.json", result)

            ready = bool(result.get("ready_for_live", False))
            streak = int(result.get("trailing_ready_streak", 0))
            required = int(result.get("required_weeks", 0))

            self._insert_system_log(
                "INFO",
                "paper_run_status",
                f"Paper run status computed: profile={profile} ready_for_live={ready} streak={streak}/{required}",
                {
                    "artifact": str(artifact),
                    "gate_profile": profile,
                    "blocking_reasons": result.get("blocking_reasons", []),
                },
            )

            if not ready:
                reasons = result.get("blocking_reasons", [])
                msg = (
                    "Paper run status updated\n"
                    f"Ready for live: {ready}\n"
                    f"Streak: {streak}/{required}\n"
                    f"Blocking: {', '.join(reasons) if isinstance(reasons, list) else reasons}\n"
                    f"Artifact: {artifact}"
                )
                self.telegram.send_alert("INFO", msg)

            self._mark_routine_completed("paper_run_status")
            self._write_heartbeat("paper_run_status_complete")
            return result
        except Exception as exc:
            self._insert_system_log("ERROR", "paper_run_status", f"Paper run status failed: {exc}")
            self.telegram.send_alert("ERROR", f"Paper run status failed: {exc}")
            self._write_heartbeat("paper_run_status_failed")
            raise

    def _reconcile_with_broker(self) -> None:
        if self.paper_mode:
            return
        try:
            broker_positions = self.broker.get_current_positions()
            for pos in broker_positions:
                symbol = str(pos.get("symbol", "")).replace(".NS", "")
                qty = int(pos.get("quantity", 0))
                if not symbol or qty <= 0:
                    continue
                if symbol in self.positions:
                    continue
                avg_price = float(pos.get("avg_price", pos.get("average_price", 0.0)) or 0.0)
                if avg_price <= 0:
                    continue
                self.positions[symbol] = {
                    "symbol": symbol,
                    "strategy": "Broker Reconciled",
                    "entry_date": self._now(),
                    "entry_price": avg_price,
                    "quantity": qty,
                    "stop_loss": avg_price * 0.95,
                    "target": avg_price * 1.08,
                    "days_held": 0,
                    "order_id": f"RECON_{symbol}_{self._today_str()}",
                }
            logger.info(f"Reconciliation complete: {len(self.positions)} positions in memory")
        except Exception as exc:
            logger.error(f"Broker reconciliation failed: {exc}")

    def pre_market_routine(self) -> None:
        self._roll_intent_day()
        self._write_heartbeat("pre_market_start")
        if self._is_kill_switch_active():
            logger.warning("Kill switch active; skipping pre-market routine")
            return
        logger.info("Running pre-market routine")

        if self.simulation_mode:
            logger.info("Simulation mode: skipping live alternative data scraping")
        else:
            trending = self.alt_scraper.scrape_moneycontrol_trending()
            sectors = self.alt_scraper.scrape_sector_performance()
            self.alt_scraper.save_to_db(trending + sectors)

        market_data = self._load_market_data()
        alt_data = self._load_alternative_data()
        regime = self._compute_market_regime(market_data)

        all_signals = []
        for name, strategy in self.strategies.items():
            strategy_alt_data = alt_data if name == "sector_rotation" else None
            signals = strategy.generate_signals(
                market_data=market_data,
                alternative_data=strategy_alt_data,
                market_regime=regime,
            )
            all_signals.extend(signals)

        in_defensive_mode = bool(
            Config.ADAPTIVE_DEFENSIVE_MODE_ENABLED and not bool(regime.get("is_favorable", True))
        )
        candidate_signals = all_signals
        min_expected_edge_pct = Config.MIN_EXPECTED_EDGE_PCT
        max_daily_signals = max(0, int(Config.MAX_SIGNALS_PER_DAY))

        if in_defensive_mode:
            candidate_signals = [signal for signal in all_signals if self._defensive_allows_signal(signal)]
            min_expected_edge_pct = max(
                Config.MIN_EXPECTED_EDGE_PCT,
                Config.ADAPTIVE_DEFENSIVE_MIN_EXPECTED_EDGE_PCT,
            )
            defensive_cap = max(0, int(Config.ADAPTIVE_DEFENSIVE_MAX_SIGNALS_PER_DAY))
            if defensive_cap > 0:
                max_daily_signals = (
                    min(max_daily_signals, defensive_cap) if max_daily_signals > 0 else defensive_cap
                )
            logger.info(
                "Defensive regime active: breadth={:.2%} threshold={:.2%} raw={} defensive_candidates={} cap={}",
                float(regime.get("breadth_ratio", 0.0)),
                float(regime.get("breadth_threshold", Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH)),
                len(all_signals),
                len(candidate_signals),
                max_daily_signals,
            )

        # Keep only signals with enough expected edge after transaction costs.
        edge_filtered_signals = [
            signal for signal in candidate_signals if self._expected_edge_pct(signal) >= min_expected_edge_pct
        ]
        # Rank by combined signal quality and cap daily throughput.
        ranked_signals = sorted(edge_filtered_signals, key=self._score_signal, reverse=True)
        if max_daily_signals > 0:
            ranked_signals = ranked_signals[:max_daily_signals]

        # Attach current market breadth context to selected signals for downstream analysis.
        for signal in ranked_signals:
            metadata = dict(signal.metadata or {})
            metadata["market_breadth_ratio"] = float(regime.get("breadth_ratio", 0.0))
            metadata["market_breadth_favorable"] = bool(regime.get("is_favorable", True))
            metadata["market_regime_label"] = str(regime.get("regime_label", "unknown"))
            metadata["market_regime_confidence"] = float(regime.get("confidence", 0.5))
            metadata["market_regime_trend_up"] = bool(regime.get("trend_up", True))
            metadata["market_regime_annualized_volatility"] = float(regime.get("annualized_volatility", 0.0))
            signal.metadata = metadata

        raw_by_strategy = self._count_signals_by_strategy(all_signals)
        candidate_by_strategy = self._count_signals_by_strategy(candidate_signals)
        edge_by_strategy = self._count_signals_by_strategy(edge_filtered_signals)
        ranked_by_strategy = self._count_signals_by_strategy(ranked_signals)

        logger.info(
            "Signal funnel: raw={} candidates={} edge_ok={} selected={} min_edge={:.4f}",
            len(all_signals),
            len(candidate_signals),
            len(edge_filtered_signals),
            len(ranked_signals),
            float(min_expected_edge_pct),
        )

        # Size first, then validate on true risk/heat with quantity.
        sized_candidates = []
        virtual_cash = self.cash
        for signal in ranked_signals:
            qty = self._size_signal_position(signal, virtual_cash)
            if qty <= 0:
                continue
            signal.quantity = qty
            sized_candidates.append(signal)
            virtual_cash -= signal.price * signal.quantity * (1 + Config.COST_PER_SIDE)
            if virtual_cash <= 0:
                break

        sized_by_strategy = self._count_signals_by_strategy(sized_candidates)
        sized = self.risk_manager.validate_sized_signals(sized_candidates, self.positions)
        risk_valid_by_strategy = self._count_signals_by_strategy(sized)

        self._insert_system_log(
            "INFO",
            "signal_funnel",
            "pre_market_signal_funnel",
            metadata={
                "simulation_date": self._today_str(),
                "regime": {
                    "label": str(regime.get("regime_label", "unknown")),
                    "is_favorable": bool(regime.get("is_favorable", True)),
                    "breadth_ratio": float(regime.get("breadth_ratio", 0.0)),
                    "trend_up": bool(regime.get("trend_up", True)),
                    "annualized_volatility": float(regime.get("annualized_volatility", 0.0)),
                    "confidence": float(regime.get("confidence", 0.5)),
                },
                "counts": {
                    "raw_signals": len(all_signals),
                    "candidate_signals": len(candidate_signals),
                    "edge_passed": len(edge_filtered_signals),
                    "ranked_selected": len(ranked_signals),
                    "sized_candidates": len(sized_candidates),
                    "risk_valid": len(sized),
                },
                "by_strategy": {
                    "raw": raw_by_strategy,
                    "candidates": candidate_by_strategy,
                    "edge_passed": edge_by_strategy,
                    "ranked_selected": ranked_by_strategy,
                    "sized_candidates": sized_by_strategy,
                    "risk_valid": risk_valid_by_strategy,
                },
                "settings": {
                    "in_defensive_mode": in_defensive_mode,
                    "min_expected_edge_pct": float(min_expected_edge_pct),
                    "max_daily_signals": int(max_daily_signals),
                },
            },
        )

        self.pending_signals = sized
        self._persist_pending_signals(self.pending_signals)
        self.telegram.send_morning_report(
            signals=[self._signal_to_dict(s) for s in sized],
            portfolio_value=self.portfolio_value,
            cash=self.cash,
            positions=list(self.positions.values()),
        )
        self._mark_routine_completed("pre_market")
        self._write_heartbeat("pre_market_complete")

    def _expected_edge_pct(self, signal: Signal) -> float:
        if signal.price <= 0:
            return -1.0
        gross_reward_pct = (signal.target - signal.price) / signal.price
        return float(gross_reward_pct - Config.TOTAL_COST_PER_TRADE)

    def _compute_market_regime(self, market_data: pd.DataFrame) -> dict[str, Any]:
        if market_data.empty:
            return {
                "is_favorable": True,
                "regime_label": "unknown",
                "trend_up": True,
                "annualized_volatility": 0.0,
                "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
                "breadth_ratio": 1.0,
                "breadth_threshold": Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH,
                "confidence": 0.5,
                "eligible_symbols": 0,
                "reason": "empty_market_data",
            }

        vol_window = max(5, int(Config.MOMENTUM_REGIME_VOL_WINDOW))
        proxy_sma_period = max(5, int(Config.MOMENTUM_REGIME_SMA_PERIOD))
        period = max(2, int(Config.ADAPTIVE_DEFENSIVE_BREADTH_SMA_PERIOD))
        frame = market_data[["symbol", "date", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["symbol", "date", "close"])
        if frame.empty:
            return {
                "is_favorable": True,
                "regime_label": "unknown",
                "trend_up": True,
                "annualized_volatility": 0.0,
                "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
                "breadth_ratio": 1.0,
                "breadth_threshold": Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH,
                "confidence": 0.5,
                "eligible_symbols": 0,
                "reason": "no_valid_points",
            }

        frame = frame.sort_values(["symbol", "date"])
        frame["sma"] = frame.groupby("symbol")["close"].transform(lambda series: series.rolling(period).mean())
        latest = frame.dropna(subset=["sma"]).groupby("symbol", as_index=False).tail(1)
        eligible = int(len(latest))
        min_eligible = max(1, int(Config.ADAPTIVE_DEFENSIVE_MIN_ELIGIBLE_SYMBOLS))
        if eligible < min_eligible:
            return {
                "is_favorable": True,
                "regime_label": "warmup",
                "trend_up": True,
                "annualized_volatility": 0.0,
                "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
                "breadth_ratio": 1.0,
                "breadth_threshold": Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH,
                "confidence": 0.5,
                "eligible_symbols": eligible,
                "reason": "insufficient_symbols",
            }

        breadth_ratio = float((latest["close"] > latest["sma"]).mean())
        threshold = float(Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH)
        close_pivot = frame.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
        proxy_returns = close_pivot.pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
        proxy = (1.0 + proxy_returns).cumprod() * 100.0

        min_proxy_points = max(proxy_sma_period, vol_window) + 5
        if len(proxy) < min_proxy_points:
            trend_up = True
            latest_vol = 0.0
            low_vol = True
            reason = "proxy_warmup"
        else:
            proxy_sma = proxy.rolling(proxy_sma_period).mean()
            ann_vol = proxy_returns.rolling(vol_window).std() * (252**0.5)
            latest_close = float(proxy.iloc[-1])
            latest_sma = float(proxy_sma.iloc[-1]) if pd.notna(proxy_sma.iloc[-1]) else latest_close
            latest_vol = float(ann_vol.iloc[-1]) if pd.notna(ann_vol.iloc[-1]) else 0.0
            trend_up = latest_close >= (latest_sma * 0.99)
            low_vol = latest_vol <= float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL)
            reason = "computed"

        is_favorable = bool((breadth_ratio >= threshold) and trend_up and low_vol)
        if is_favorable:
            regime_label = "favorable"
        elif (not trend_up) and (breadth_ratio < (threshold * 0.9)):
            regime_label = "bearish"
        elif low_vol and breadth_ratio >= (threshold * 0.8):
            regime_label = "choppy"
        else:
            regime_label = "defensive"

        vol_limit = max(float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL), 1e-6)
        if latest_vol <= vol_limit:
            vol_score = 1.0
        else:
            vol_score = max(0.0, 1.0 - ((latest_vol - vol_limit) / vol_limit))
        confidence = self._clamp((0.40 * breadth_ratio) + (0.35 * (1.0 if trend_up else 0.0)) + (0.25 * vol_score))

        return {
            "is_favorable": is_favorable,
            "regime_label": regime_label,
            "trend_up": bool(trend_up),
            "annualized_volatility": float(latest_vol),
            "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
            "breadth_ratio": breadth_ratio,
            "breadth_threshold": threshold,
            "confidence": confidence,
            "eligible_symbols": eligible,
            "reason": reason,
        }

    def _compute_market_breadth_regime(self, market_data: pd.DataFrame) -> dict[str, Any]:
        """Backward-compatible wrapper for older callers."""
        return self._compute_market_regime(market_data)

    def _signal_strategy_key(self, signal: Signal) -> str:
        name = str(signal.strategy or "").strip().lower()
        if "adaptive trend" in name:
            return "adaptive_trend"
        if "momentum" in name:
            return "momentum"
        if "mean" in name:
            return "mean_reversion"
        if "sector" in name:
            return "sector_rotation"
        if "bear" in name:
            return "bear_reversal"
        if "volatility" in name:
            return "volatility_reversal"
        return "unknown"

    def _defensive_allows_signal(self, signal: Signal) -> bool:
        key = self._signal_strategy_key(signal)
        if key == "momentum":
            return bool(Config.ADAPTIVE_DEFENSIVE_ALLOW_MOMENTUM)
        if key == "mean_reversion":
            return bool(Config.ADAPTIVE_DEFENSIVE_ALLOW_MEAN_REVERSION)
        if key == "sector_rotation":
            return bool(Config.ADAPTIVE_DEFENSIVE_ALLOW_SECTOR_ROTATION)
        if key == "adaptive_trend":
            return bool(Config.ADAPTIVE_DEFENSIVE_ALLOW_ADAPTIVE_TREND)
        if key == "bear_reversal":
            return bool(Config.ADAPTIVE_DEFENSIVE_ALLOW_BEAR_REVERSAL)
        if key == "volatility_reversal":
            return bool(Config.ADAPTIVE_DEFENSIVE_ALLOW_VOLATILITY_REVERSAL)
        return False

    def _count_signals_by_strategy(self, signals: list[Signal]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for signal in signals:
            key = self._signal_strategy_key(signal)
            counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
        return float(max(lower, min(upper, value)))

    def _strategy_feature_score(self, strategy_key: str, metadata: dict[str, Any]) -> float:
        if strategy_key == "momentum":
            roc = float(metadata.get("roc_20", 0.0))
            volume_ratio = float(metadata.get("volume_ratio", 1.0))
            atr_pct = float(metadata.get("atr_pct", Config.MOMENTUM_MAX_ATR_PCT))
            roc_score = self._clamp(roc / max(Config.MOMENTUM_MIN_ROC, 1e-6), 0.0, 2.0) / 2.0
            volume_score = self._clamp(volume_ratio / max(Config.MOMENTUM_VOLUME_MULTIPLIER, 1e-6), 0.0, 2.0) / 2.0
            atr_score = self._clamp(
                (Config.MOMENTUM_MAX_ATR_PCT - atr_pct) / max(Config.MOMENTUM_MAX_ATR_PCT, 1e-6)
            )
            return float((0.45 * roc_score) + (0.35 * volume_score) + (0.20 * atr_score))

        if strategy_key == "mean_reversion":
            rsi = float(metadata.get("rsi", 50.0))
            oversold_score = self._clamp((50.0 - rsi) / 25.0)
            return float((0.60 * oversold_score) + 0.40)

        if strategy_key == "bear_reversal":
            drop_pct = float(metadata.get("drop_pct", 0.0))
            rsi = float(metadata.get("rsi", 35.0))
            volume_ratio = float(metadata.get("volume_ratio", 1.0))
            drop_score = self._clamp(drop_pct / 0.08)
            rsi_recovery = self._clamp((rsi - 30.0) / 20.0)
            volume_score = self._clamp(volume_ratio / 2.0)
            return float((0.40 * drop_score) + (0.35 * rsi_recovery) + (0.25 * volume_score))

        if strategy_key == "volatility_reversal":
            drop_pct = float(metadata.get("drop_pct", 0.0))
            rsi = float(metadata.get("rsi", 35.0))
            atr_spike = float(metadata.get("atr_spike_ratio", 1.0))
            drop_score = self._clamp(drop_pct / 0.06)
            rsi_recovery = self._clamp((rsi - 30.0) / 20.0)
            atr_spike_score = self._clamp((atr_spike - 1.0) / 1.0)
            return float((0.35 * drop_score) + (0.30 * rsi_recovery) + (0.35 * atr_spike_score))

        if strategy_key == "sector_rotation":
            has_sector = 1.0 if metadata.get("sector") else 0.5
            return float((0.60 * has_sector) + 0.20)

        if strategy_key == "adaptive_trend":
            weekly_roc = float(metadata.get("weekly_roc", 0.0))
            weekly_rsi = float(metadata.get("weekly_rsi", 50.0))
            volume_ratio = float(metadata.get("volume_ratio", 1.0))
            trend_gap = float(metadata.get("weekly_ema_short", 0.0)) - float(metadata.get("weekly_ema_long", 0.0))
            roc_score = self._clamp(weekly_roc / max(Config.ADAPTIVE_TREND_MAX_WEEKLY_ROC, 1e-6))
            rsi_score = self._clamp((weekly_rsi - 40.0) / 35.0)
            volume_score = self._clamp(volume_ratio / 2.0)
            trend_score = 1.0 if trend_gap > 0 else 0.0
            return float((0.35 * roc_score) + (0.25 * rsi_score) + (0.20 * volume_score) + (0.20 * trend_score))

        return 0.5

    def _is_adaptive_signal(self, signal: Signal) -> bool:
        return self._signal_strategy_key(signal) == "adaptive_trend"

    def _get_recent_trade_stats(self, strategy_name: str, lookback: int = 20) -> dict[str, float]:
        query = """
            SELECT pnl FROM trades
            WHERE status = 'CLOSED'
              AND strategy = :strategy
              AND pnl IS NOT NULL
            ORDER BY exit_date DESC
            LIMIT :lookback
        """
        df = pd.read_sql(
            query,
            db.engine,
            params={"strategy": strategy_name, "lookback": max(1, int(lookback))},
        )
        if df.empty:
            return {"win_rate": 0.5, "avg_win_loss_ratio": 1.2}

        wins = df[df["pnl"] > 0]["pnl"]
        losses = df[df["pnl"] < 0]["pnl"]
        win_rate = float(len(wins) / len(df))
        avg_win = float(wins.mean()) if not wins.empty else 0.0
        avg_loss = float(abs(losses.mean())) if not losses.empty else 0.0
        ratio = avg_win / avg_loss if avg_loss > 0 else 1.2
        return {"win_rate": win_rate, "avg_win_loss_ratio": max(ratio, 0.1)}

    def _get_sector_exposure(self, sector: str | None) -> float:
        if not sector:
            return 0.0
        total_value = self.portfolio_value if self.portfolio_value > 0 else (self.cash + 1.0)
        if total_value <= 0:
            return 0.0

        sector_value = 0.0
        for symbol, pos in self.positions.items():
            metadata = pos.get("metadata", {}) if isinstance(pos.get("metadata"), dict) else {}
            if str(metadata.get("sector", "")).upper() != str(sector).upper():
                continue
            current = self._get_current_price(symbol)
            if not current:
                continue
            sector_value += float(pos.get("quantity", 0)) * float(current.get("close", 0.0))

        return max(0.0, min(1.0, sector_value / total_value))

    def _size_signal_position(self, signal: Signal, cash_available: float) -> int:
        if not self._is_adaptive_signal(signal):
            return size_position(signal.price, signal.stop_loss, Config.STARTING_CAPITAL, cash_available)

        stats = self._get_recent_trade_stats(signal.strategy)
        drawdown = max(0.0, (Config.STARTING_CAPITAL - self.portfolio_value) / max(Config.STARTING_CAPITAL, 1.0))
        metadata = signal.metadata or {}
        sector_exposure = self._get_sector_exposure(str(metadata.get("sector")) if metadata.get("sector") else None)

        return size_position_adaptive(
            price=signal.price,
            stop_loss=signal.stop_loss,
            capital=Config.STARTING_CAPITAL,
            cash_available=cash_available,
            confidence=float(signal.confidence),
            win_rate=float(stats.get("win_rate", 0.5)),
            avg_win_loss_ratio=float(stats.get("avg_win_loss_ratio", 1.2)),
            current_drawdown=drawdown,
            sector_exposure=sector_exposure,
        )

    def _score_signal(self, signal: Signal) -> float:
        metadata = signal.metadata or {}
        strategy_key = self._signal_strategy_key(signal)
        regime_favorable = bool(
            metadata.get(
                "market_breadth_favorable",
                metadata.get("regime_favorable", True),
            )
        )
        regime_confidence = float(metadata.get("market_regime_confidence", metadata.get("regime_confidence", 0.5)))

        risk_per_share = max(signal.price - signal.stop_loss, 1e-9)
        reward_to_risk = max(signal.target - signal.price, 0.0) / risk_per_share
        edge_pct = self._expected_edge_pct(signal)
        rr_score = self._clamp(reward_to_risk / 2.0)
        edge_score = self._clamp(edge_pct / 0.02)
        strategy_score = self._strategy_feature_score(strategy_key, metadata)
        confidence_score = self._clamp(float(signal.confidence))

        score = (
            (confidence_score * 0.45)
            + (edge_score * 0.20)
            + (rr_score * 0.15)
            + (strategy_score * 0.15)
            + (self._clamp(regime_confidence) * 0.05)
        )
        if regime_favorable:
            score += 0.03
        return float(score)

    def market_open_routine(self) -> None:
        self._roll_intent_day()
        self._write_heartbeat("market_open_start")
        if self._is_kill_switch_active():
            logger.warning("Kill switch active; skipping market-open routine")
            return
        logger.info("Running market-open routine")
        if not self.risk_manager.check_can_trade():
            logger.warning("Risk limits block trading")
            return

        if not self.pending_signals:
            restored = self._restore_pending_signals()
            if restored:
                self.pending_signals = restored
                logger.info(f"Restored {len(restored)} pending signal(s) from runtime state")

        for signal in self.pending_signals:
            self._execute_entry(signal)
            # Keep broker pacing for live/paper runtime, skip in simulation replays.
            if not self.simulation_mode:
                time.sleep(0.5)
        self.pending_signals = []
        self._mark_pending_signals_consumed()
        self._mark_routine_completed("market_open")
        self._write_heartbeat("market_open_complete")

    def intraday_monitoring(self) -> None:
        self._write_heartbeat("intraday_start")
        if self._is_kill_switch_active():
            logger.warning("Kill switch active; intraday will only evaluate exits")
            self._check_exit_conditions()
            self._update_portfolio_value()
            self._write_heartbeat("intraday_complete_killswitch")
            return
        self._check_exit_conditions()
        self._update_portfolio_value()
        if self.risk_manager.check_emergency_stop(self.portfolio_value):
            self._close_all_positions()
        self._write_heartbeat("intraday_complete")

    def market_close_routine(self) -> None:
        self._write_heartbeat("market_close_start")
        logger.info("Running market-close routine")
        if not self.simulation_mode:
            self.data_collector.update_daily_data(self.universe)
        self._update_portfolio_value()
        self._save_portfolio_snapshot()
        closed_today = self._get_closed_trades_today()
        strategy_perf = self._calculate_strategy_performance()
        portfolio_data = {
            "total_value": self.portfolio_value,
            "cash": self.cash,
            "num_positions": len(self.positions),
            "daily_pnl": self.risk_manager.daily_pnl,
            "daily_pnl_pct": (self.risk_manager.daily_pnl / Config.STARTING_CAPITAL) * 100,
        }
        positions_with_pnl = self._calculate_unrealized_pnl()
        self.telegram.send_daily_pnl_report(
            portfolio_data=portfolio_data,
            positions=positions_with_pnl,
            closed_trades=closed_today,
            strategy_performance=strategy_perf,
        )
        self._mark_routine_completed("market_close")
        self._write_heartbeat("market_close_complete")

    def _execute_entry(self, signal: Signal) -> None:
        if signal.symbol in self.positions:
            logger.warning(f"Skipping entry for {signal.symbol}; position already open")
            return
        intent = self._intent_key("BUY", signal.symbol, int(signal.quantity))
        if intent in self._executed_intents:
            logger.warning(f"Skipping duplicate entry intent {intent}")
            return

        order: dict[str, Any] | None
        if self.paper_mode:
            order = {
                "order_id": f"PAPER_{signal.symbol.replace('.', '_')}_{int(time.time() * 1000)}",
                "status": "COMPLETE",
            }
        elif self.dry_run_live:
            order = {
                "order_id": f"DRYRUN_{signal.symbol.replace('.', '_')}_{int(time.time() * 1000)}",
                "status": "SIMULATED_COMPLETE",
            }
        else:
            order = self.broker.place_market_order(signal.symbol, signal.quantity, "BUY")
            if not order:
                return

        self.positions[signal.symbol] = {
            "symbol": signal.symbol,
            "strategy": signal.strategy,
            "entry_date": self._now(),
            "entry_price": signal.price,
            "quantity": signal.quantity,
            "stop_loss": signal.stop_loss,
            "target": signal.target,
            "highest_close": signal.price,
            "lowest_close": signal.price,
            "weekly_atr": float((signal.metadata or {}).get("weekly_atr", 0.0)),
            "metadata": dict(signal.metadata or {}),
            "days_held": 0,
            "order_id": order["order_id"] if order else "",
        }

        cost = signal.price * signal.quantity * (1 + Config.COST_PER_SIDE)
        self.cash -= cost

        self._save_trade_to_db(self.positions[signal.symbol], status="OPEN")
        try:
            self.feature_store.save_entry_features(
                order_id=str(self.positions[signal.symbol]["order_id"]),
                symbol=str(signal.symbol),
                strategy=str(signal.strategy),
                entry_date=self._now(),
                entry_price=float(signal.price),
                stop_loss=float(signal.stop_loss),
                target=float(signal.target),
                quantity=int(signal.quantity),
                confidence=float(signal.confidence),
                metadata=dict(signal.metadata or {}),
            )
        except Exception as exc:
            logger.warning(f"Feature entry persistence failed for {signal.symbol}: {exc}")
        self.telegram.send_trade_notification(self.positions[signal.symbol], "ENTRY")
        self._executed_intents.add(intent)

    def _execute_exit(self, symbol: str, exit_price: float, reason: str) -> None:
        pos = self.positions[symbol]
        intent = self._intent_key("SELL", symbol, int(pos["quantity"]))
        if intent in self._executed_intents:
            logger.warning(f"Skipping duplicate exit intent {intent}")
            return

        if self._should_place_live_orders():
            order = self.broker.place_market_order(symbol, pos["quantity"], "SELL")
            if not order:
                return

        gross = (exit_price - pos["entry_price"]) * pos["quantity"]
        entry_cost = pos["entry_price"] * pos["quantity"]
        exit_cost = exit_price * pos["quantity"]
        total_cost = (entry_cost + exit_cost) * Config.COST_PER_SIDE
        net_pnl = gross - total_cost

        self.cash += exit_cost * (1 - Config.COST_PER_SIDE)
        self.risk_manager.update_pnl(net_pnl)

        trade = {
            **pos,
            "exit_date": self._now(),
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl": net_pnl,
            "pnl_percent": (net_pnl / entry_cost) * 100 if entry_cost else 0.0,
            "action": "SELL",
        }

        self._save_trade_to_db(trade, status="CLOSED")
        try:
            self.feature_store.update_trade_outcome(
                order_id=str(trade.get("order_id", "")),
                exit_date=self._now(),
                exit_price=float(exit_price),
                pnl=float(net_pnl),
                pnl_percent=float(trade["pnl_percent"]),
                days_held=int(trade.get("days_held", 0)),
                exit_reason=str(reason),
            )
        except Exception as exc:
            logger.warning(f"Feature outcome persistence failed for {symbol}: {exc}")
        self.telegram.send_trade_notification(trade, "EXIT")
        del self.positions[symbol]
        self._executed_intents.add(intent)

    def _check_exit_conditions(self) -> None:
        weekly_ema_cache = self._compute_live_weekly_ema_cache(list(self.positions.keys()))
        for symbol in list(self.positions.keys()):
            position = self.positions[symbol]
            current_data = self._get_current_price(symbol)
            if not current_data:
                continue

            position["days_held"] = (self._now() - position["entry_date"]).days
            current_close = float(current_data["close"])
            position["highest_close"] = max(float(position.get("highest_close", current_close)), current_close)
            position["lowest_close"] = min(float(position.get("lowest_close", current_close)), current_close)
            if symbol in weekly_ema_cache:
                ema_short, ema_long = weekly_ema_cache[symbol]
                position["current_weekly_ema_short"] = ema_short
                position["current_weekly_ema_long"] = ema_long

            strategy = self.strategies.get(position["strategy"].lower().replace(" ", "_"))
            if strategy is None:
                continue

            should_exit, reason = strategy.check_exit_conditions(position, pd.Series(current_data))
            if should_exit:
                self._execute_exit(symbol, float(current_data["close"]), reason or "EXIT")

    def _compute_live_weekly_ema_cache(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        adaptive = self.strategies.get("adaptive_trend")
        if adaptive is None or not symbols:
            return {}
        history = self._load_market_data()
        if history.empty:
            return {}

        short_span = int(getattr(adaptive, "weekly_ema_short", 10))
        long_span = int(getattr(adaptive, "weekly_ema_long", 30))
        clean_symbols = {str(sym).replace(".NS", "") for sym in symbols}
        frame = history.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.replace(".NS", "", regex=False)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame[
            frame["symbol"].isin(clean_symbols)
            & frame["date"].notna()
            & pd.to_numeric(frame["close"], errors="coerce").notna()
        ].sort_values(["symbol", "date"])
        if frame.empty:
            return {}

        cache: dict[str, tuple[float, float]] = {}
        for symbol in clean_symbols:
            sym_frame = frame[frame["symbol"] == symbol]
            if sym_frame.empty:
                continue
            weekly = (
                sym_frame.set_index("date")
                .resample("W-FRI")
                .agg({"close": "last"})
                .dropna()
            )
            if len(weekly) < max(short_span, long_span):
                continue
            ema_short = weekly["close"].ewm(span=short_span, adjust=False).mean().iloc[-1]
            ema_long = weekly["close"].ewm(span=long_span, adjust=False).mean().iloc[-1]
            if pd.notna(ema_short) and pd.notna(ema_long):
                cache[symbol] = (float(ema_short), float(ema_long))
                cache[f"{symbol}.NS"] = (float(ema_short), float(ema_long))
        return cache

    def _get_current_price(self, symbol: str) -> dict | None:
        clean = symbol.replace(".NS", "")
        query = """
            SELECT * FROM price_data
            WHERE symbol = :symbol
            AND date <= date(:anchor)
            ORDER BY date DESC
            LIMIT 1
        """
        df = pd.read_sql(query, db.engine, params={"symbol": clean, "anchor": self._today_str()})
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def _update_portfolio_value(self) -> None:
        positions_value = 0.0
        for symbol, position in self.positions.items():
            row = self._get_current_price(symbol)
            if row:
                positions_value += position["quantity"] * float(row["close"])
        self.portfolio_value = self.cash + positions_value

    def _calculate_unrealized_pnl(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol, pos in self.positions.items():
            current = self._get_current_price(symbol)
            if not current:
                continue
            current_price = float(current["close"])
            unrealized = (current_price - float(pos["entry_price"])) * float(pos["quantity"])
            base = float(pos["entry_price"]) * float(pos["quantity"])
            rows.append(
                {
                    **pos,
                    "current_price": current_price,
                    "unrealized_pnl": unrealized,
                    "unrealized_pnl_pct": (unrealized / base) * 100 if base else 0.0,
                }
            )
        return rows

    def _load_market_data(self) -> pd.DataFrame:
        query = """
            SELECT symbol, date, open, high, low, close, volume
            FROM price_data
            WHERE date >= date(:anchor, '-260 day')
            AND date <= date(:anchor)
            ORDER BY symbol, date
        """
        return pd.read_sql(query, db.engine, params={"anchor": self._today_str()})

    def _load_alternative_data(self) -> pd.DataFrame:
        query = """
            SELECT * FROM alternative_signals
            WHERE date >= date(:anchor, '-7 day')
            AND date <= date(:anchor)
        """
        return pd.read_sql(query, db.engine, params={"anchor": self._today_str()})

    def _signal_to_dict(self, signal) -> dict:
        return {
            "symbol": signal.symbol,
            "strategy": signal.strategy,
            "price": signal.price,
            "quantity": signal.quantity,
            "stop_loss": signal.stop_loss,
            "target": signal.target,
        }

    def _save_trade_to_db(self, trade: dict, status: str) -> None:
        action = trade.get("action", "BUY" if status == "OPEN" else "SELL")
        query = """
            INSERT OR REPLACE INTO trades (
                order_id, symbol, strategy, action, quantity, entry_price, entry_date,
                exit_price, exit_date, stop_loss, target, pnl, pnl_percent, status, notes
            ) VALUES (
                :order_id, :symbol, :strategy, :action, :quantity, :entry_price, :entry_date,
                :exit_price, :exit_date, :stop_loss, :target, :pnl, :pnl_percent, :status, :notes
            )
        """
        payload = {
            "order_id": trade.get("order_id"),
            "symbol": trade.get("symbol", ""),
            "strategy": trade.get("strategy", "unknown"),
            "action": action,
            "quantity": int(trade.get("quantity", 0)),
            "entry_price": trade.get("entry_price"),
            "entry_date": str(trade.get("entry_date")) if trade.get("entry_date") else None,
            "exit_price": trade.get("exit_price"),
            "exit_date": str(trade.get("exit_date")) if trade.get("exit_date") else None,
            "stop_loss": trade.get("stop_loss"),
            "target": trade.get("target"),
            "pnl": trade.get("pnl"),
            "pnl_percent": trade.get("pnl_percent"),
            "status": status,
            "notes": trade.get("exit_reason"),
        }
        with db.engine.begin() as conn:
            conn.execute(text(query), payload)

    def _save_portfolio_snapshot(self) -> None:
        today = self._today_str()
        starting = Config.STARTING_CAPITAL
        total_pnl = self.portfolio_value - starting
        query = """
            INSERT OR REPLACE INTO portfolio_snapshots (
                date, total_value, cash, positions_value, num_positions,
                daily_pnl, daily_pnl_percent, total_pnl, total_pnl_percent
            ) VALUES (
                :date, :total_value, :cash, :positions_value, :num_positions,
                :daily_pnl, :daily_pnl_percent, :total_pnl, :total_pnl_percent
            )
        """
        payload = {
            "date": today,
            "total_value": self.portfolio_value,
            "cash": self.cash,
            "positions_value": self.portfolio_value - self.cash,
            "num_positions": len(self.positions),
            "daily_pnl": self.risk_manager.daily_pnl,
            "daily_pnl_percent": (self.risk_manager.daily_pnl / starting) * 100,
            "total_pnl": total_pnl,
            "total_pnl_percent": (total_pnl / starting) * 100,
        }
        with db.engine.begin() as conn:
            conn.execute(text(query), payload)

    def _get_closed_trades_today(self) -> list[dict[str, Any]]:
        query = """
            SELECT symbol, strategy, pnl, pnl_percent, notes AS exit_reason, exit_date
            FROM trades
            WHERE status = 'CLOSED'
              AND date(exit_date) = date(:today)
            ORDER BY exit_date DESC
        """
        df = pd.read_sql(query, db.engine, params={"today": self._today_str()})
        if df.empty:
            return []
        return df.to_dict("records")

    def _calculate_strategy_performance(self) -> dict[str, dict[str, float]]:
        month_start = self._today_str()[:8] + "01"
        query = """
            SELECT strategy,
                   SUM(CASE WHEN COALESCE(pnl, 0) > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN COALESCE(pnl, 0) <= 0 THEN 1 ELSE 0 END) AS losses,
                   COALESCE(SUM(COALESCE(pnl, 0)), 0) AS pnl
            FROM trades
            WHERE status = 'CLOSED'
              AND date(exit_date) >= date(:month_start)
            GROUP BY strategy
        """
        df = pd.read_sql(query, db.engine, params={"month_start": month_start})
        if df.empty:
            return {}

        result: dict[str, dict[str, float]] = {}
        for _, row in df.iterrows():
            strategy = str(row["strategy"])
            pnl = float(row["pnl"])
            result[strategy] = {
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
                "pnl": pnl,
                "pnl_pct": (pnl / Config.STARTING_CAPITAL) * 100,
            }
        return result

    def _close_all_positions(self) -> None:
        for symbol in list(self.positions.keys()):
            row = self._get_current_price(symbol)
            if row:
                self._execute_exit(symbol, float(row["close"]), "EMERGENCY_STOP")

    def run(self) -> None:
        schedule.every().day.at("08:00").do(self.pre_market_routine)
        schedule.every().day.at("09:15").do(self.market_open_routine)
        schedule.every().day.at("15:30").do(self.market_close_routine)
        for hour in range(9, 16):
            for minute in ["00", "30"]:
                schedule.every().day.at(f"{hour:02d}:{minute}").do(self.intraday_monitoring)
        if not self.paper_mode:
            for t in ["10:05", "12:05", "14:05", "16:05"]:
                schedule.every().day.at(t).do(self.reconciliation_routine)
        schedule.every().sunday.at("18:10").do(self.weekly_audit_routine)
        schedule.every().sunday.at("18:20").do(self.weekly_audit_trend_routine)
        schedule.every().sunday.at("18:25").do(self.paper_run_status_routine)
        schedule.every().sunday.at("18:30").do(self.retention_rotation_routine)

        logger.info("Scheduler started")
        if Config.AUTO_RESUME_ENABLED:
            recovered = self._run_recovery_cycle(force=True)
            if recovered:
                logger.info(f"Startup auto-resume recovered routines: {recovered}")

        while True:
            try:
                schedule.run_pending()
                if Config.AUTO_RESUME_ENABLED:
                    self._run_recovery_cycle()
            except Exception as exc:
                logger.error(f"Scheduler loop error: {exc}")
                self._write_heartbeat("scheduler_loop_error")
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Indian stock swing trading bot")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument(
        "--dry-run-live",
        action="store_true",
        help="Use live dependencies but block broker order placement (simulated fills).",
    )
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.dry_run_live and args.mode != "live":
        parser.error("--dry-run-live requires --mode live")

    bot = TradingBot(
        paper_mode=(args.mode == "paper"),
        dry_run_live=args.dry_run_live,
    )
    if args.test:
        bot.pre_market_routine()
        bot.market_open_routine()
        bot.market_close_routine()
        if args.mode == "live":
            bot.reconciliation_routine()
    else:
        bot.run()


if __name__ == "__main__":
    main()
