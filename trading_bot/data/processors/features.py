from __future__ import annotations

import pandas as pd


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.sort_values(["symbol", "date"])
    out["ret_1d"] = out.groupby("symbol")["close"].pct_change(1)
    out["ret_5d"] = out.groupby("symbol")["close"].pct_change(5)
    out["ret_20d"] = out.groupby("symbol")["close"].pct_change(20)
    out["vol_20d"] = out.groupby("symbol")["ret_1d"].rolling(20).std().reset_index(level=0, drop=True)
    return out
