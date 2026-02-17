from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup
from loguru import logger

from trading_bot.data.storage.database import db


class AlternativeDataScraper:
    def __init__(self, headless: bool = True) -> None:
        self.session = requests.Session()
        # Chrome Desktop headers (tested and working with NSE)
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            }
        )
        self.headless = headless

    def _get(self, url: str, headers: dict | None = None, timeout: int = 15, retries: int = 3) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = self.session.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                return response
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    sleep_for = 1.5 * attempt
                    logger.warning(f"Request failed ({attempt}/{retries}) for {url}: {exc}. Retrying in {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                else:
                    logger.error(f"Request failed after {retries} attempts for {url}: {exc}")
        raise RuntimeError(f"Failed to fetch {url}") from last_exc

    def _bootstrap_nse_session(self) -> None:
        # NSE APIs frequently require a home-page request for cookies.
        try:
            self._get("https://www.nseindia.com/", timeout=10, retries=2)
        except Exception:
            # Keep flow resilient; API call may still work in some runs.
            pass

    def scrape_moneycontrol_trending(self) -> list[dict]:
        try:
            url = "https://www.moneycontrol.com/stocks/marketstats/nsegainer/index.php"
            response = self._get(url, timeout=15)
            soup = BeautifulSoup(response.content, "html.parser")
            table = soup.find("table", {"class": "tbldata14"})
            if table is None:
                return []

            rows = table.find_all("tr")[1:]
            out: list[dict] = []
            for row in rows[:20]:
                cols = row.find_all("td")
                if len(cols) < 3:
                    continue
                symbol = cols[0].text.strip().upper()
                change_text = cols[2].text.strip().replace("%", "")
                try:
                    change_pct = float(change_text)
                except ValueError:
                    continue
                out.append(
                    {
                        "symbol": symbol,
                        "date": str(datetime.now().date()),
                        "signal_type": "trending_gainer",
                        "value": change_pct,
                        "source": "moneycontrol",
                        "metadata": "{}",
                    }
                )
            return out
        except Exception as exc:
            logger.error(f"Moneycontrol scrape failed: {exc}")
            return []

    def scrape_sector_performance(self) -> list[dict]:
        try:
            url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/",
            }
            self._bootstrap_nse_session()
            response = self._get(url, headers=headers, timeout=15)
            data = response.json()
            output: list[dict] = []
            for item in data.get("data", []):
                try:
                    change = float(item.get("pChange", 0.0))
                except (TypeError, ValueError):
                    change = 0.0
                output.append(
                    {
                        "symbol": item.get("symbol"),
                        "date": str(datetime.now().date()),
                        "signal_type": "sector_momentum",
                        "value": change,
                        "source": "nse",
                        "metadata": str({"volume": item.get("totalTradedVolume")}),
                    }
                )
            return output
        except Exception as exc:
            logger.error(f"NSE sector scrape failed: {exc}")
            return []

    def scrape_news_mentions(self, symbol: str) -> dict | None:
        try:
            url = f"https://economictimes.indiatimes.com/topic/{symbol}"
            response = self._get(url, timeout=15)
            soup = BeautifulSoup(response.content, "html.parser")
            articles = soup.find_all("div", {"class": "eachStory"})
            return {
                "symbol": symbol,
                "date": str(datetime.now().date()),
                "signal_type": "news_mentions",
                "value": float(len(articles)),
                "source": "economic_times",
                "metadata": "{}",
            }
        except Exception as exc:
            logger.error(f"News scrape failed for {symbol}: {exc}")
            return None

    def scrape_fii_dii_data(self) -> list[dict]:
        """Scrape FII/DII net flows from NSE API."""
        try:
            url = "https://www.nseindia.com/api/fiidiiTradeReact"
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/report-detail/eq_security",
            }
            self._bootstrap_nse_session()
            response = self._get(url, headers=headers, timeout=15)
            data = response.json()

            rows: list[dict] = []
            if isinstance(data, list):
                for item in data:
                    buy = float(item.get("buy", 0) or 0)
                    sell = float(item.get("sell", 0) or 0)
                    rows.append(
                        {
                            "symbol": "FII_DII",
                            "date": str(datetime.now().date()),
                            "signal_type": "fii_dii_flow",
                            "value": buy - sell,
                            "source": "nse",
                            "metadata": str(item),
                        }
                    )
            return rows
        except Exception as exc:
            logger.error(f"FII/DII scrape failed: {exc}")
            return []

    def save_to_db(self, data_list: list[dict]) -> None:
        if not data_list:
            return
        frame = pd.DataFrame(data_list)
        frame.to_sql("alternative_signals", db.engine, if_exists="append", index=False)
        logger.info(f"Saved {len(data_list)} alternative signals")

    def close(self) -> None:
        return None


scraper = AlternativeDataScraper(headless=True)
