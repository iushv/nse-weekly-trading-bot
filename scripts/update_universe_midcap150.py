from __future__ import annotations

import argparse
from pathlib import Path

from trading_bot.data.collectors.market_data import MarketDataCollector


def _clean(sym: str) -> str:
    return sym.replace(".NS", "").strip().upper()


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch and write Nifty Midcap 150 universe file")
    p.add_argument(
        "--out",
        default="data/universe/nifty_midcap150.txt",
        help="Output path (one symbol per line, without .NS).",
    )
    args = p.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    collector = MarketDataCollector(market_data_provider="auto")
    symbols = collector.get_nifty_midcap_150_list()
    cleaned = [_clean(s) for s in symbols]
    cleaned = [s for s in cleaned if s]

    out_path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
    print(f"Wrote {len(cleaned)} symbols to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
