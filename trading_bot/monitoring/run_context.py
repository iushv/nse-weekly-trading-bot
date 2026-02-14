from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from trading_bot.config.settings import Config


def _read_universe_file(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").splitlines()
    symbols = [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]
    return [s.replace(".NS", "").upper() for s in symbols]


def build_run_context() -> dict[str, Any]:
    universe_file = os.getenv("UNIVERSE_FILE", "").strip()
    trading_universe = (Config.TRADING_UNIVERSE or os.getenv("TRADING_UNIVERSE", "")).strip().lower()

    symbols: list[str] = []
    if universe_file:
        try:
            symbols = _read_universe_file(Path(universe_file))
        except Exception:
            symbols = []

    universe_size = len(symbols) if symbols else None
    universe_hash = None
    if symbols:
        joined = "\n".join(sorted(symbols)).encode("utf-8")
        universe_hash = hashlib.sha1(joined).hexdigest()

    if universe_file:
        tag = f"file:{Path(universe_file).name}:{universe_size or 0}:{(universe_hash or '')[:10]}"
    elif trading_universe:
        tag = f"universe:{trading_universe}"
    else:
        tag = "default"

    return {
        "strategy_profile": Config.STRATEGY_PROFILE,
        "trading_universe": trading_universe or None,
        "universe_file": universe_file or None,
        "universe_size": universe_size,
        "universe_hash": universe_hash,
        "universe_tag": tag,
    }
