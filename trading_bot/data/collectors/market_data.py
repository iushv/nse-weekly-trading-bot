from __future__ import annotations

import json
import time
from datetime import date, datetime, time as dt_time, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from loguru import logger
from sqlalchemy import text

from trading_bot.config.constants import MIN_AVG_VOLUME, MIN_MARKET_CAP
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import db
from trading_bot.execution.broker_interface import GROWW_DEFAULT_BASE_URL, GrowwHttpClient


class MarketDataCollector:
    def __init__(self, market_data_provider: str | None = None) -> None:
        self.nifty_500_symbols: list[str] = []
        self.market_data_provider = (
            (market_data_provider or Config.MARKET_DATA_PROVIDER or "auto").strip().lower()
        )
        if self.market_data_provider not in {"auto", "yfinance", "groww"}:
            logger.warning(f"Unknown MARKET_DATA_PROVIDER={self.market_data_provider}; using auto")
            self.market_data_provider = "auto"
        self.groww_exchange = Config.GROWW_HISTORICAL_EXCHANGE
        self.groww_segment = Config.GROWW_HISTORICAL_SEGMENT
        self.groww_interval = Config.GROWW_HISTORICAL_INTERVAL
        self.groww_chunk_days = max(1, int(Config.GROWW_HISTORICAL_CHUNK_DAYS))
        self.groww_client: GrowwHttpClient | None = None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self.cache_dir = Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.nifty_cache_path = self.cache_dir / "nifty500_symbols.json"
        self._groww_init_attempted = False

    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        return symbol.replace(".NS", "").strip().upper()

    def _init_groww_client(self) -> None:
        self._groww_init_attempted = True
        if self.market_data_provider not in {"auto", "groww"}:
            return
        if not Config.GROWW_API_KEY:
            logger.info("Groww historical data disabled: GROWW_API_KEY is missing")
            return
        try:
            client = GrowwHttpClient(
                api_key=Config.GROWW_API_KEY,
                api_secret=Config.GROWW_API_SECRET,
                token_mode=Config.GROWW_TOKEN_MODE,
                base_url=Config.BROKER_BASE_URL or GROWW_DEFAULT_BASE_URL,
                access_token=Config.GROWW_ACCESS_TOKEN,
                totp=Config.GROWW_TOTP,
                app_id=Config.GROWW_APP_ID,
            )
            client.authenticate()
            self.groww_client = client
            logger.info("Groww historical data client authenticated")
        except Exception as exc:
            self.groww_client = None
            logger.warning(f"Groww historical data unavailable: {exc}")

    def _ensure_groww_client(self) -> None:
        if self.groww_client is None and not self._groww_init_attempted:
            self._init_groww_client()

    @staticmethod
    def _parse_candle_timestamp(value: Any) -> pd.Timestamp | None:
        try:
            if isinstance(value, (int, float)):
                # Groww may return epoch seconds/milliseconds depending on endpoint/version.
                if float(value) > 1_000_000_000_000:
                    ts = pd.to_datetime(value, unit="ms", utc=True)
                else:
                    ts = pd.to_datetime(value, unit="s", utc=True)
            else:
                ts = pd.to_datetime(str(value), utc=True)
            return ts.tz_convert(None)
        except Exception:
            return None

    @staticmethod
    def _format_groww_time(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _get_latest_price_date(self, symbol: str) -> date | None:
        clean_symbol = self._clean_symbol(symbol)
        query = text("SELECT MAX(date) AS latest_date FROM price_data WHERE symbol = :symbol")
        with db.engine.connect() as conn:
            latest = conn.execute(query, {"symbol": clean_symbol}).scalar()
        if latest is None:
            return None
        try:
            return pd.to_datetime(latest).date()
        except Exception:
            return None

    def _request_with_retries(
        self,
        url: str,
        headers: dict | None = None,
        timeout: int = 15,
        retries: int = 3,
        backoff_seconds: float = 1.5,
    ) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = self.session.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                return response
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    sleep_for = backoff_seconds * attempt
                    logger.warning(f"Request failed ({attempt}/{retries}) for {url}: {exc}. Retrying in {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                else:
                    logger.error(f"Request failed after {retries} attempts for {url}: {exc}")
        raise RuntimeError(f"Failed to fetch {url}") from last_exc

    def _load_cached_nifty_symbols(self) -> list[str]:
        if not self.nifty_cache_path.exists():
            return []
        try:
            payload = json.loads(self.nifty_cache_path.read_text(encoding="utf-8"))
            symbols = payload.get("symbols", [])
            if isinstance(symbols, list) and symbols:
                logger.info(f"Loaded {len(symbols)} symbols from local cache")
                return symbols
        except Exception as exc:
            logger.warning(f"Failed to read Nifty cache: {exc}")
        return []

    def _save_cached_nifty_symbols(self, symbols: list[str]) -> None:
        try:
            payload = {"updated_at": datetime.utcnow().isoformat() + "Z", "symbols": symbols}
            self.nifty_cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to write Nifty cache: {exc}")

    def get_nifty_500_list(self) -> list[str]:
        try:
            url = "https://www1.nseindia.com/content/indices/ind_nifty500list.csv"
            response = self._request_with_retries(url=url)
            df = pd.read_csv(StringIO(response.text))
            symbols = [f"{sym}.NS" for sym in df["Symbol"].dropna().tolist()]
            self.nifty_500_symbols = symbols
            self._save_cached_nifty_symbols(symbols)
            logger.info(f"Loaded {len(symbols)} Nifty 500 symbols")
            return symbols
        except Exception as exc:
            logger.warning(f"Error fetching Nifty 500 list: {exc}. Checking local cache/fallback.")
            cached = self._load_cached_nifty_symbols()
            if cached:
                self.nifty_500_symbols = cached
                return cached
            return self._get_fallback_symbols()

    def _get_fallback_symbols(self) -> list[str]:
        return [
            "RELIANCE.NS",
            "TCS.NS",
            "HDFCBANK.NS",
            "INFY.NS",
            "ICICIBANK.NS",
            "HINDUNILVR.NS",
            "ITC.NS",
            "SBIN.NS",
            "BHARTIARTL.NS",
            "KOTAKBANK.NS",
            "LT.NS",
            "AXISBANK.NS",
            "ASIANPAINT.NS",
            "MARUTI.NS",
            "SUNPHARMA.NS",
            "TITAN.NS",
            "ULTRACEMCO.NS",
            "WIPRO.NS",
            "BAJFINANCE.NS",
            "BAJAJFINSV.NS",
            "NESTLEIND.NS",
            "POWERGRID.NS",
            "NTPC.NS",
            "ONGC.NS",
            "COALINDIA.NS",
            "JSWSTEEL.NS",
            "TATASTEEL.NS",
            "HINDALCO.NS",
            "ADANIENT.NS",
            "ADANIPORTS.NS",
            "M&M.NS",
            "TATAMOTORS.NS",
            "EICHERMOT.NS",
            "HEROMOTOCO.NS",
            "DRREDDY.NS",
            "DIVISLAB.NS",
            "CIPLA.NS",
            "APOLLOHOSP.NS",
            "BRITANNIA.NS",
            "DABUR.NS",
            "GODREJCP.NS",
            "HCLTECH.NS",
            "TECHM.NS",
            "LTIM.NS",
            "INDUSINDBK.NS",
            "PNB.NS",
            "BANKBARODA.NS",
            "PIDILITIND.NS",
            "SIEMENS.NS",
            "ABB.NS",
            "BEL.NS",
            "HAL.NS",
            "DLF.NS",
            "LODHA.NS",
            "BPCL.NS",
            "IOC.NS",
            "GAIL.NS",
            "HDFCLIFE.NS",
            "SBILIFE.NS",
            "ICICIPRULI.NS",
            "BAJAJ-AUTO.NS",
            "SHRIRAMFIN.NS",
            "TRENT.NS",
            "ZYDUSLIFE.NS",
            "VEDL.NS",
            "CANBK.NS",
            "MOTHERSON.NS",
            "AMBUJACEM.NS",
            "GRASIM.NS",
        ]

    def _fetch_historical_data_yfinance(
        self, symbol: str, start_date: str | datetime | date, end_date: datetime
    ) -> pd.DataFrame | None:
        for attempt in range(1, 4):
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start_date, end=end_date)
                if df.empty:
                    raise RuntimeError("Empty dataframe from yfinance ticker.history")

                df["Returns"] = df["Close"].pct_change()
                df["ATR"] = self._calculate_atr(df)
                return df
            except Exception as exc:
                if attempt < 3:
                    sleep_for = attempt
                    logger.warning(f"Error fetching {symbol} ({attempt}/3): {exc}. Retrying in {sleep_for}s")
                    time.sleep(sleep_for)
                else:
                    logger.warning(f"Primary yfinance fetch failed for {symbol}: {exc}. Trying download fallback.")

        try:
            df = yf.download(
                symbol,
                start=start_date,
                end=end_date,
                interval="1d",
                progress=False,
                threads=False,
                auto_adjust=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.empty:
                logger.warning(f"No data for {symbol} after yfinance fallback attempts")
                return None
            df["Returns"] = df["Close"].pct_change()
            df["ATR"] = self._calculate_atr(df)
            return df
        except Exception as exc:
            logger.warning(f"Error fetching {symbol} via yfinance fallback download: {exc}")
            return None

    def _fetch_historical_data_groww(
        self, symbol: str, start_date: str | datetime | date, end_date: datetime
    ) -> pd.DataFrame | None:
        self._ensure_groww_client()
        if self.groww_client is None:
            return None

        start_ts = pd.to_datetime(start_date, errors="coerce")
        end_ts = pd.to_datetime(end_date, errors="coerce")
        if pd.isna(start_ts) or pd.isna(end_ts):
            return None

        start_day = start_ts.date()
        end_day = end_ts.date()
        if end_day < start_day:
            return None

        groww_symbol = f"{self.groww_exchange}-{self._clean_symbol(symbol)}"
        rows: list[dict[str, Any]] = []
        cursor = start_day
        while cursor <= end_day:
            chunk_end = min(cursor + timedelta(days=self.groww_chunk_days - 1), end_day)
            try:
                candles = self.groww_client.get_historical_candles(
                    exchange=self.groww_exchange,
                    segment=self.groww_segment,
                    groww_symbol=groww_symbol,
                    start_time=self._format_groww_time(datetime.combine(cursor, dt_time(9, 15))),
                    end_time=self._format_groww_time(datetime.combine(chunk_end, dt_time(15, 30))),
                    candle_interval=self.groww_interval,
                )
            except Exception as exc:
                logger.warning(f"Groww candle fetch failed for {groww_symbol} {cursor}->{chunk_end}: {exc}")
                candles = []

            for candle in candles:
                if not isinstance(candle, list) or len(candle) < 6:
                    continue
                ts = self._parse_candle_timestamp(candle[0])
                if ts is None:
                    continue
                try:
                    rows.append(
                        {
                            "Date": ts,
                            "Open": float(candle[1]),
                            "High": float(candle[2]),
                            "Low": float(candle[3]),
                            "Close": float(candle[4]),
                            "Volume": float(candle[5]),
                        }
                    )
                except (TypeError, ValueError):
                    continue
            cursor = chunk_end + timedelta(days=1)

        if not rows:
            logger.warning(f"No Groww candles returned for {groww_symbol}")
            return None

        df = pd.DataFrame(rows).drop_duplicates(subset=["Date"]).sort_values("Date")
        df = df.set_index("Date")
        df["Adj Close"] = df["Close"]
        df["Returns"] = df["Close"].pct_change()
        df["ATR"] = self._calculate_atr(df)
        return df

    def fetch_historical_data(
        self, symbol: str, start_date: str | datetime | date, end_date: datetime | None = None
    ) -> pd.DataFrame | None:
        if end_date is None:
            end_date = datetime.now()

        provider = self.market_data_provider
        if provider == "groww":
            groww_df = self._fetch_historical_data_groww(symbol, start_date, end_date)
            if groww_df is not None and not groww_df.empty:
                return groww_df
            return self._fetch_historical_data_yfinance(symbol, start_date, end_date)

        if provider == "yfinance":
            return self._fetch_historical_data_yfinance(symbol, start_date, end_date)

        yf_df = self._fetch_historical_data_yfinance(symbol, start_date, end_date)
        if yf_df is not None and not yf_df.empty:
            return yf_df

        groww_df = self._fetch_historical_data_groww(symbol, start_date, end_date)
        if groww_df is not None and not groww_df.empty:
            return groww_df

        logger.error(f"No historical data source succeeded for {symbol}")
        return None

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.rolling(period).mean()

    def filter_liquid_stocks(self, symbols: list[str]) -> list[str]:
        filtered: list[str] = []
        for symbol in symbols:
            for attempt in range(1, 3):
                try:
                    ticker = yf.Ticker(symbol)
                    info = ticker.info
                    market_cap = info.get("marketCap", 0) / 10000000  # crores
                    avg_volume = info.get("averageVolume", 0)
                    if market_cap >= MIN_MARKET_CAP and avg_volume >= MIN_AVG_VOLUME:
                        filtered.append(symbol)
                    break
                except Exception as exc:
                    if attempt == 2:
                        logger.debug(f"Skipping {symbol}: {exc}")
                    else:
                        time.sleep(0.5)

        if not filtered:
            # Keep paper/live workflows moving if upstream metadata lookups fail.
            fallback = [sym for sym in symbols if isinstance(sym, str) and sym.strip()]
            fallback = fallback[: min(len(fallback), 100)]
            if not fallback:
                fallback = self._get_fallback_symbols()
            logger.warning(f"Liquidity filter returned 0 symbols; using fallback universe size={len(fallback)}")
            return fallback

        logger.info(f"Filtered to {len(filtered)} liquid stocks")
        return filtered

    def update_daily_data(self, symbols: list[str]) -> None:
        today = datetime.now().date()
        fetch_start = today - timedelta(days=3)
        freshness_threshold = today - timedelta(days=3)
        skipped_fresh = 0
        updated_symbols = 0
        failed_symbols = 0
        for symbol in symbols:
            try:
                latest_date = self._get_latest_price_date(symbol)
                if latest_date is not None and latest_date >= freshness_threshold:
                    skipped_fresh += 1
                    continue

                df = self.fetch_historical_data(symbol, start_date=fetch_start)
                if df is not None and not df.empty:
                    db.insert_price_data(df, symbol)
                    updated_symbols += 1
                else:
                    failed_symbols += 1
            except Exception as exc:
                logger.error(f"Failed to update {symbol}: {exc}")
                failed_symbols += 1
        logger.info(
            "Daily data update summary: "
            f"symbols={len(symbols)} updated={updated_symbols} "
            f"skipped_fresh={skipped_fresh} failed={failed_symbols}"
        )

    def backfill_historical_data(self, symbols: list[str], start_date: str = "2020-01-01") -> None:
        logger.info(f"Starting backfill from {start_date}")
        for idx, symbol in enumerate(symbols, start=1):
            try:
                df = self.fetch_historical_data(symbol, start_date=start_date)
                if df is not None and not df.empty:
                    db.insert_price_data(df, symbol)
                    logger.info(f"[{idx}/{len(symbols)}] Backfilled {symbol}")
            except Exception as exc:
                logger.error(f"Backfill failed for {symbol}: {exc}")
