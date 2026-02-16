from __future__ import annotations

import json
import time
from datetime import date, datetime, time as dt_time, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import io
import zipfile

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
        if self.market_data_provider not in {"auto", "yfinance", "groww", "bhavcopy"}:
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
        self.midcap_cache_path = self.cache_dir / "nifty_midcap150_symbols.json"
        self._groww_init_attempted = False
        self._bhavcopy_cache: dict[str, pd.DataFrame] = {}  # date_str -> full day df

    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        return symbol.replace(".NS", "").strip().upper()

    @staticmethod
    def _normalize_yfinance_symbol(symbol: str) -> str:
        s = str(symbol or "").strip()
        if not s:
            return s
        if s.startswith("^"):
            return s
        if s.endswith(".NS") or "." in s:
            return s
        return f"{s}.NS"

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

    def _load_cached_symbols(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            symbols = payload.get("symbols", [])
            if isinstance(symbols, list) and symbols:
                logger.info(f"Loaded {len(symbols)} symbols from local cache: {path}")
                return symbols
        except Exception as exc:
            logger.warning(f"Failed to read Nifty cache: {exc}")
        return []

    def _save_cached_symbols(self, path: Path, symbols: list[str]) -> None:
        try:
            payload = {"updated_at": datetime.utcnow().isoformat() + "Z", "symbols": symbols}
            path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Failed to write Nifty cache: {exc}")

    def get_nifty_500_list(self) -> list[str]:
        try:
            url = "https://www1.nseindia.com/content/indices/ind_nifty500list.csv"
            response = self._request_with_retries(url=url)
            df = pd.read_csv(StringIO(response.text))
            symbols = [f"{sym}.NS" for sym in df["Symbol"].dropna().tolist()]
            self.nifty_500_symbols = symbols
            self._save_cached_symbols(self.nifty_cache_path, symbols)
            logger.info(f"Loaded {len(symbols)} Nifty 500 symbols")
            return symbols
        except Exception as exc:
            logger.warning(f"Error fetching Nifty 500 list: {exc}. Checking local cache/fallback.")
            cached = self._load_cached_symbols(self.nifty_cache_path)
            if cached:
                self.nifty_500_symbols = cached
                return cached
            return self._get_fallback_symbols()
    def get_nifty_midcap_150_list(self) -> list[str]:
        """Fetch Nifty Midcap 150 constituent list (Yahoo symbols, ".NS" suffix)."""
        try:
            url = "https://www1.nseindia.com/content/indices/ind_niftymidcap150list.csv"
            response = self._request_with_retries(url=url)
            df = pd.read_csv(StringIO(response.text))
            col = None
            for candidate in ("Symbol", "SYMBOL", "symbol"):
                if candidate in df.columns:
                    col = candidate
                    break
            if col is None:
                # Fall back to first column if NSE changes headers.
                col = str(df.columns[0])
            symbols = [f"{sym}.NS" for sym in df[col].dropna().astype(str).tolist()]
            symbols = [s for s in symbols if s and s != "nan.NS"]
            self._save_cached_symbols(self.midcap_cache_path, symbols)
            logger.info(f"Loaded {len(symbols)} Nifty Midcap 150 symbols")
            return symbols
        except Exception as exc:
            logger.warning(f"Error fetching Midcap 150 list: {exc}. Checking local cache/fallback.")
            cached = self._load_cached_symbols(self.midcap_cache_path)
            if cached:
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
                yf_symbol = self._normalize_yfinance_symbol(symbol)
                ticker = yf.Ticker(yf_symbol)
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
            yf_symbol = self._normalize_yfinance_symbol(symbol)
            df = yf.download(
                yf_symbol,
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

    def _fetch_bhavcopy_day(self, trading_date: date) -> pd.DataFrame | None:
        """Download NSE UDiFF bhavcopy for a single trading day. Returns EQ-series DataFrame."""
        date_str = trading_date.strftime("%Y%m%d")
        if date_str in self._bhavcopy_cache:
            return self._bhavcopy_cache[date_str]

        url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://www.nseindia.com/",
        }
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 404:
                return None  # holiday / weekend
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            df = pd.read_csv(z.open(z.namelist()[0]))
            eq = df[df["SctySrs"] == "EQ"][["TckrSymb", "TradDt", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"]].copy()
            eq.columns = ["Symbol", "Date", "Open", "High", "Low", "Close", "Volume"]
            eq["Date"] = pd.to_datetime(eq["Date"])
            self._bhavcopy_cache[date_str] = eq
            return eq
        except Exception as exc:
            logger.debug(f"Bhavcopy fetch failed for {trading_date}: {exc}")
            return None

    def _fetch_historical_data_bhavcopy(
        self, symbol: str, start_date: str | datetime | date, end_date: datetime
    ) -> pd.DataFrame | None:
        """Fetch OHLCV from NSE UDiFF bhavcopy files (day-by-day). No auth required."""
        clean = self._clean_symbol(symbol)
        start_dt = pd.to_datetime(start_date).date()
        end_dt = pd.to_datetime(end_date).date()

        rows: list[dict] = []
        cursor = start_dt
        while cursor <= end_dt:
            # Skip weekends
            if cursor.weekday() < 5:
                day_df = self._fetch_bhavcopy_day(cursor)
                if day_df is not None:
                    row = day_df[day_df["Symbol"] == clean]
                    if not row.empty:
                        r = row.iloc[0]
                        rows.append({
                            "Date": r["Date"],
                            "Open": float(r["Open"]),
                            "High": float(r["High"]),
                            "Low": float(r["Low"]),
                            "Close": float(r["Close"]),
                            "Volume": float(r["Volume"]),
                        })
            cursor += timedelta(days=1)

        if not rows:
            logger.warning(f"No bhavcopy data found for {clean} ({start_dt} -> {end_dt})")
            return None

        df = pd.DataFrame(rows).drop_duplicates(subset=["Date"]).sort_values("Date").set_index("Date")
        df["Adj Close"] = df["Close"]
        df["Returns"] = df["Close"].pct_change()
        df["ATR"] = self._calculate_atr(df)
        return df

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

        if provider == "bhavcopy":
            bhav_df = self._fetch_historical_data_bhavcopy(symbol, start_date, end_date)
            if bhav_df is not None and not bhav_df.empty:
                return bhav_df
            return None

        if provider == "groww":
            groww_df = self._fetch_historical_data_groww(symbol, start_date, end_date)
            if groww_df is not None and not groww_df.empty:
                return groww_df
            # Fall through to bhavcopy then yfinance

        if provider == "yfinance":
            return self._fetch_historical_data_yfinance(symbol, start_date, end_date)

        # auto: bhavcopy first (most reliable for NSE), then yfinance
        bhav_df = self._fetch_historical_data_bhavcopy(symbol, start_date, end_date)
        if bhav_df is not None and not bhav_df.empty:
            return bhav_df

        yf_df = self._fetch_historical_data_yfinance(symbol, start_date, end_date)
        if yf_df is not None and not yf_df.empty:
            return yf_df

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
                    yf_symbol = self._normalize_yfinance_symbol(symbol)
                    ticker = yf.Ticker(yf_symbol)
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
    def _batch_download_yfinance(
        self,
        symbols: list[str],
        *,
        start_date: datetime | date,
        end_date: datetime,
    ) -> dict[str, pd.DataFrame]:
        """Best-effort batch OHLCV fetch via yfinance.

        Returns mapping of original input symbol -> dataframe.
        """
        if not symbols:
            return {}

        # Map to yfinance tickers and back.
        yf_map: dict[str, str] = {}
        yf_symbols: list[str] = []
        for sym in symbols:
            yf_sym = self._normalize_yfinance_symbol(sym)
            if not yf_sym:
                continue
            yf_map[yf_sym] = sym
            yf_symbols.append(yf_sym)

        if not yf_symbols:
            return {}

        try:
            df = yf.download(
                yf_symbols,
                start=start_date,
                end=end_date,
                interval="1d",
                group_by="ticker",
                progress=False,
                threads=False,
                auto_adjust=False,
            )
        except Exception as exc:
            logger.warning(f"Batch yfinance download failed for {len(yf_symbols)} tickers: {exc}")
            return {}

        if df is None or getattr(df, 'empty', True):
            return {}

        out: dict[str, pd.DataFrame] = {}

        if not isinstance(df.columns, pd.MultiIndex):
            # Single ticker download (or yfinance flattened output)
            only = yf_symbols[0]
            out[yf_map.get(only, only)] = df
            return out

        # MultiIndex output, could be (Ticker, Field) or (Field, Ticker)
        lvl0 = set(str(x) for x in df.columns.get_level_values(0).unique())
        field_names = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        ticker_first = not field_names.issubset(lvl0)

        for yf_sym in yf_symbols:
            try:
                if ticker_first:
                    if yf_sym not in df.columns.get_level_values(0):
                        continue
                    sub = df[yf_sym].copy()
                else:
                    if yf_sym not in df.columns.get_level_values(1):
                        continue
                    sub = df.xs(yf_sym, level=1, axis=1).copy()
            except Exception:
                continue

            if sub is None or getattr(sub, 'empty', True):
                continue
            out[yf_map.get(yf_sym, yf_sym)] = sub

        return out

    def update_daily_data(self, symbols: list[str]) -> None:
        today = datetime.now().date()
        fetch_start = today - timedelta(days=3)
        freshness_threshold = today - timedelta(days=1)

        stale_symbols: list[str] = []
        skipped_fresh = 0
        for symbol in symbols:
            latest_date = None
            try:
                latest_date = self._get_latest_price_date(symbol)
            except Exception:
                latest_date = None
            if latest_date is not None and latest_date >= freshness_threshold:
                skipped_fresh += 1
            else:
                stale_symbols.append(symbol)

        if not stale_symbols:
            logger.info(
                "Daily data update summary: symbols={} updated={} skipped_fresh={} failed={}",
                len(symbols),
                0,
                skipped_fresh,
                0,
            )
            return

        updated_symbols = 0
        failed_symbols = 0

        provider = self.market_data_provider
        batch_threshold = 25
        remaining = list(stale_symbols)

        # Batch yfinance download to reduce rate limiting for large universes.
        if provider in {"auto", "yfinance"} and len(remaining) >= batch_threshold:
            batch = self._batch_download_yfinance(remaining, start_date=fetch_start, end_date=datetime.now())
            for sym, df in batch.items():
                try:
                    if df is not None and not df.empty:
                        db.insert_price_data(df, sym)
                        updated_symbols += 1
                        if sym in remaining:
                            remaining.remove(sym)
                except Exception as exc:
                    logger.warning(f"Batch insert failed for {sym}: {exc}")

        # Per-symbol fallback for any not covered by batch fetch.
        for symbol in remaining:
            try:
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
            "Daily data update summary: symbols={} updated={} skipped_fresh={} failed={}",
            len(symbols),
            updated_symbols,
            skipped_fresh,
            failed_symbols,
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
