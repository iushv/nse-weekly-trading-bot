from __future__ import annotations

import argparse

from trading_bot.data.collectors.market_data import MarketDataCollector
from trading_bot.data.storage.database import db


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill market data")
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--universe",
        choices=["nifty500", "midcap150", "fallback"],
        default="nifty500",
        help="Universe to backfill when --symbols is not provided.",
    )
    parser.add_argument(
        "--provider",
        choices=["auto", "yfinance", "groww", "bhavcopy"],
        default=None,
        help="Historical data provider override.",
    )
    parser.add_argument(
        "--use-fallback-universe",
        action="store_true",
        help="Use built-in fallback symbols instead of NSE constituent fetch.",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols to backfill (e.g., RELIANCE.NS,TCS.NS).",
    )
    args = parser.parse_args()

    db.init_db()
    collector = MarketDataCollector(market_data_provider=args.provider)

    if args.symbols.strip():
        symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    elif args.use_fallback_universe or args.universe == "fallback":
        symbols = collector._get_fallback_symbols()
    elif args.universe == "midcap150":
        symbols = collector.get_nifty_midcap_150_list()
    else:
        symbols = collector.get_nifty_500_list()

    symbols = symbols[: args.limit]
    print(f"Backfilling {len(symbols)} symbols using provider={collector.market_data_provider}")
    collector.backfill_historical_data(symbols, start_date=args.start_date)


if __name__ == "__main__":
    main()
