from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any


def _parse_hhmm(value: str, *, arg_name: str) -> dt_time:
    try:
        hour_s, minute_s = value.split(":")
        hour = int(hour_s)
        minute = int(minute_s)
        return dt_time(hour=hour, minute=minute)
    except Exception as exc:  # pragma: no cover - trivial guard
        raise argparse.ArgumentTypeError(f"Invalid {arg_name} value '{value}', expected HH:MM") from exc


def _latest_trading_day(anchor: date) -> date:
    current = anchor
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _json_load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_universe_symbols(path: Path) -> list[str]:
    if not path.exists():
        return []
    symbols: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        symbols.append(s.replace(".NS", "").upper())
    return sorted(set(symbols))


@dataclass
class MonitorConfig:
    log_dir: Path
    heartbeat_file: Path
    runtime_state_file: Path
    db_path: Path
    universe_file: Path
    poll_seconds: int = 60
    stale_heartbeat_seconds: int = 180
    market_close_time: dt_time = dt_time(15, 30)
    coverage_check_start_time: dt_time = dt_time(15, 45)
    end_time: dt_time = dt_time(16, 10)
    provider: str = "bhavcopy"
    autofix_data: bool = True
    alert_all_warnings: bool = False
    once: bool = False


@dataclass
class MonitorState:
    booted: bool = False
    file_offsets: dict[str, int] = field(default_factory=dict)
    throttled: dict[str, datetime] = field(default_factory=dict)
    coverage_checked_for: set[str] = field(default_factory=set)
    coverage_fixed_for: set[str] = field(default_factory=set)


class RuntimeMonitor:
    line_level_re = re.compile(r"\|\s*(INFO|WARNING|ERROR|CRITICAL|DEBUG)\s*\|")

    def __init__(self, cfg: MonitorConfig) -> None:
        self.cfg = cfg
        self.state = MonitorState()
        self.output_dir = Path("reports/monitoring")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.event_path = self.output_dir / f"runtime_monitor_{stamp}.jsonl"
        self.text_log_path = self.output_dir / f"runtime_monitor_{stamp}.log"
        self.universe = _read_universe_symbols(cfg.universe_file)

    def _emit(self, level: str, kind: str, message: str, details: dict[str, Any] | None = None, *, throttle_key: str | None = None, throttle_seconds: int = 300) -> None:
        now = datetime.now()
        if throttle_key:
            last = self.state.throttled.get(throttle_key)
            if last and (now - last).total_seconds() < throttle_seconds:
                return
            self.state.throttled[throttle_key] = now

        payload: dict[str, Any] = {
            "ts": _safe_iso_now(),
            "level": level.upper(),
            "kind": kind,
            "message": message,
        }
        if details:
            payload["details"] = details

        line = json.dumps(payload, ensure_ascii=True)
        self.event_path.write_text(
            (self.event_path.read_text(encoding="utf-8") + line + "\n") if self.event_path.exists() else line + "\n",
            encoding="utf-8",
        )
        print(line, flush=True)
        with self.text_log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{payload['ts']}] {payload['level']} {kind}: {message}\n")

    def _latest_log_file(self) -> Path | None:
        if not self.cfg.log_dir.exists():
            return None
        files = sorted(self.cfg.log_dir.glob("trading_bot_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        return files[0]

    def _consume_log_updates(self) -> None:
        log_file = self._latest_log_file()
        if log_file is None:
            self._emit("WARNING", "log_missing", "No trading_bot log file found", throttle_key="log_missing")
            return

        key = str(log_file)
        if key not in self.state.file_offsets:
            # On first attach, start from EOF and only monitor new lines.
            self.state.file_offsets[key] = log_file.stat().st_size
            return

        start = self.state.file_offsets.get(key, 0)
        size = log_file.stat().st_size
        if size < start:
            start = 0
        if size == start:
            return

        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(start)
            new_lines = handle.readlines()
            self.state.file_offsets[key] = handle.tell()

        for raw in new_lines:
            line = raw.rstrip("\n")
            level_match = self.line_level_re.search(line)
            level = level_match.group(1) if level_match else ""

            if "Traceback (most recent call last):" in line:
                self._emit("ERROR", "traceback", line, throttle_key="traceback", throttle_seconds=30)
                continue

            if level in {"ERROR", "CRITICAL"}:
                self._emit("ERROR", "log_error", line, throttle_key=f"err::{line}", throttle_seconds=600)
                continue

            # Keep warning noise controlled while still surfacing likely incidents.
            if level == "WARNING":
                if self.cfg.alert_all_warnings:
                    self._emit("WARNING", "log_warning", line, throttle_key=f"warn_all::{line}", throttle_seconds=120)
                else:
                    warn_keywords = (
                        "Scheduler loop error",
                        "Data coverage gap",
                        "Data repair incomplete",
                        "pre_market_blocked_incomplete_data",
                        "market_close_data_incomplete",
                        "Request failed after",
                    )
                    if any(token in line for token in warn_keywords):
                        self._emit("WARNING", "log_warning", line, throttle_key=f"warn::{line}", throttle_seconds=600)

    def _check_heartbeat(self) -> None:
        if not self.cfg.heartbeat_file.exists():
            self._emit("ERROR", "heartbeat_missing", "Heartbeat file is missing", throttle_key="heartbeat_missing")
            return
        payload = _json_load(self.cfg.heartbeat_file)
        ts_raw = payload.get("timestamp")
        if not ts_raw:
            self._emit("ERROR", "heartbeat_invalid", "Heartbeat missing timestamp", throttle_key="heartbeat_invalid")
            return
        try:
            ts = datetime.fromisoformat(str(ts_raw))
        except Exception:
            self._emit("ERROR", "heartbeat_invalid", f"Heartbeat timestamp not parseable: {ts_raw}", throttle_key="heartbeat_invalid")
            return
        age = (datetime.now() - ts).total_seconds()
        stage = str(payload.get("stage", "unknown"))
        if age > float(self.cfg.stale_heartbeat_seconds):
            self._emit(
                "ERROR",
                "heartbeat_stale",
                f"Heartbeat stale ({age:.0f}s), last stage={stage}",
                {"age_seconds": round(age, 1), "stage": stage},
                throttle_key="heartbeat_stale",
                throttle_seconds=max(120, self.cfg.stale_heartbeat_seconds),
            )

    def _check_routines(self) -> None:
        if not self.cfg.runtime_state_file.exists():
            self._emit("ERROR", "runtime_state_missing", "runtime_state.json is missing", throttle_key="runtime_state_missing")
            return
        state = _json_load(self.cfg.runtime_state_file)
        routines = state.get("routines", {})
        if not isinstance(routines, dict):
            self._emit("ERROR", "runtime_state_invalid", "runtime_state.json routines payload is invalid", throttle_key="runtime_state_invalid")
            return

        now = datetime.now()
        today = now.date().isoformat()

        def done(name: str) -> bool:
            payload = routines.get(name, {})
            return isinstance(payload, dict) and str(payload.get("date", "")) == today

        pre_deadline = datetime.combine(now.date(), dt_time(8, 25))
        open_deadline = datetime.combine(now.date(), dt_time(9, 35))
        close_deadline = datetime.combine(now.date(), dt_time(15, 45))
        repair_deadline = datetime.combine(now.date(), dt_time(20, 15))

        if now >= pre_deadline and not done("pre_market"):
            self._emit("ERROR", "routine_missed", "pre_market not marked complete by 08:25", throttle_key="routine_pre_market")
        if now >= open_deadline and not done("market_open"):
            self._emit("ERROR", "routine_missed", "market_open not marked complete by 09:35", throttle_key="routine_market_open")
        if now >= close_deadline and not done("market_close"):
            self._emit("ERROR", "routine_missed", "market_close not marked complete by 15:45", throttle_key="routine_market_close")
        if now >= repair_deadline and not done("eod_data_repair"):
            self._emit("WARNING", "routine_pending", "eod_data_repair not marked complete by 20:15", throttle_key="routine_eod_repair")

    def _missing_universe_for_date(self, target_date: date) -> list[str]:
        if not self.universe:
            return []
        if not self.cfg.db_path.exists():
            return list(self.universe)
        placeholders = ",".join(["?"] * len(self.universe))
        with sqlite3.connect(str(self.cfg.db_path)) as conn:
            query = (
                "SELECT DISTINCT symbol FROM price_data "
                "WHERE date = ? AND close IS NOT NULL AND symbol IN (" + placeholders + ")"
            )
            rows = conn.execute(query, [str(target_date), *self.universe]).fetchall()
        available = {str(row[0]).upper() for row in rows}
        return [symbol for symbol in self.universe if symbol not in available]

    def _attempt_autofix(self, target_date: date, missing: list[str]) -> list[str]:
        if not missing:
            return []
        try:
            from trading_bot.data.collectors.market_data import MarketDataCollector
        except Exception as exc:
            self._emit("ERROR", "autofix_import_failed", f"Cannot import MarketDataCollector: {exc}", throttle_key="autofix_import")
            return missing

        try:
            collector = MarketDataCollector(market_data_provider=self.cfg.provider)
            collector.update_daily_data(missing, required_latest_date=target_date)
        except Exception as exc:
            self._emit("ERROR", "autofix_failed", f"Data autofix failed: {exc}", throttle_key="autofix_failed")
            return missing
        return self._missing_universe_for_date(target_date)

    def _check_data_coverage_after_close(self) -> None:
        now = datetime.now()
        start_at = datetime.combine(now.date(), self.cfg.coverage_check_start_time)
        if now < start_at:
            return

        target = _latest_trading_day(now.date())
        key = str(target)
        if key in self.state.coverage_checked_for and key in self.state.coverage_fixed_for:
            return

        missing = self._missing_universe_for_date(target)
        self.state.coverage_checked_for.add(key)
        if not missing:
            self.state.coverage_fixed_for.add(key)
            self._emit(
                "INFO",
                "coverage_ok",
                f"Universe coverage complete for {target}",
                {"symbols": len(self.universe), "missing": 0},
                throttle_key=f"coverage_ok::{target}",
                throttle_seconds=3600,
            )
            return

        self._emit(
            "WARNING",
            "coverage_gap",
            f"Universe coverage gap for {target}: missing={len(missing)}",
            {"target_date": str(target), "missing_symbols": len(missing), "sample": missing[:20]},
            throttle_key=f"coverage_gap::{target}",
            throttle_seconds=900,
        )

        if not self.cfg.autofix_data:
            return

        remaining = self._attempt_autofix(target, missing)
        if not remaining:
            self.state.coverage_fixed_for.add(key)
            self._emit(
                "INFO",
                "coverage_autofix_ok",
                f"Data autofix completed for {target}",
                {"target_date": str(target), "repaired_symbols": len(missing)},
                throttle_key=f"coverage_autofix_ok::{target}",
                throttle_seconds=3600,
            )
        else:
            self._emit(
                "ERROR",
                "coverage_autofix_partial",
                f"Data autofix incomplete for {target}: remaining={len(remaining)}",
                {"target_date": str(target), "remaining_symbols": len(remaining), "sample": remaining[:20]},
                throttle_key=f"coverage_autofix_partial::{target}",
                throttle_seconds=900,
            )

    def _run_cycle(self) -> None:
        self._check_heartbeat()
        self._check_routines()
        self._consume_log_updates()
        self._check_data_coverage_after_close()

    def run(self) -> int:
        self._emit(
            "INFO",
            "monitor_start",
            "Runtime monitor started",
            {
                "poll_seconds": self.cfg.poll_seconds,
                "end_time": self.cfg.end_time.strftime("%H:%M"),
                "autofix_data": self.cfg.autofix_data,
                "alert_all_warnings": self.cfg.alert_all_warnings,
                "universe_symbols": len(self.universe),
                "provider": self.cfg.provider,
            },
        )
        while True:
            now = datetime.now()
            cutoff = datetime.combine(now.date(), self.cfg.end_time)
            self._run_cycle()
            if self.cfg.once:
                break
            if now >= cutoff:
                self._emit("INFO", "monitor_stop", "Reached configured end_time; stopping monitor")
                break
            time.sleep(max(5, self.cfg.poll_seconds))
        return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor paper-run health until market close.")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--stale-heartbeat-seconds", type=int, default=180)
    parser.add_argument("--market-close-time", default="15:30")
    parser.add_argument("--coverage-check-start-time", default="15:45")
    parser.add_argument("--end-time", default="16:10")
    parser.add_argument("--provider", default=os.getenv("MARKET_DATA_PROVIDER", "bhavcopy"))
    parser.add_argument("--no-autofix-data", action="store_true")
    parser.add_argument("--alert-all-warnings", action="store_true")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--heartbeat-file", default="control/heartbeat.json")
    parser.add_argument("--runtime-state-file", default="control/runtime_state.json")
    parser.add_argument("--db-path", default="trading_bot.db")
    parser.add_argument(
        "--universe-file",
        default=os.getenv("UNIVERSE_FILE", "data/universe/nifty_midcap150.txt"),
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    cfg = MonitorConfig(
        log_dir=Path(args.log_dir),
        heartbeat_file=Path(args.heartbeat_file),
        runtime_state_file=Path(args.runtime_state_file),
        db_path=Path(args.db_path),
        universe_file=Path(args.universe_file),
        poll_seconds=max(5, int(args.poll_seconds)),
        stale_heartbeat_seconds=max(30, int(args.stale_heartbeat_seconds)),
        market_close_time=_parse_hhmm(args.market_close_time, arg_name="market-close-time"),
        coverage_check_start_time=_parse_hhmm(args.coverage_check_start_time, arg_name="coverage-check-start-time"),
        end_time=_parse_hhmm(args.end_time, arg_name="end-time"),
        provider=str(args.provider).strip().lower(),
        autofix_data=not bool(args.no_autofix_data),
        alert_all_warnings=bool(args.alert_all_warnings),
        once=bool(args.once),
    )
    monitor = RuntimeMonitor(cfg)
    return monitor.run()


if __name__ == "__main__":
    raise SystemExit(main())
