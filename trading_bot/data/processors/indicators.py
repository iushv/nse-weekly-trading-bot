from __future__ import annotations

import pandas as pd


def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["SMA_20"] = out["close"].rolling(20).mean()
    out["SMA_50"] = out["close"].rolling(50).mean()
    out["ROC_20"] = out["close"].pct_change(20)
    out["RSI_14"] = calculate_rsi(out["close"], 14)
    out["ATR_14"] = calculate_atr(out, 14)
    return out


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()
