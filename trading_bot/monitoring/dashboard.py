from __future__ import annotations

import pandas as pd
import streamlit as st

from trading_bot.data.storage.database import db

st.set_page_config(page_title="Trading Bot Dashboard", layout="wide")
st.title("Trading Bot Dashboard")


def load_portfolio_data() -> pd.DataFrame:
    query = "SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT 90"
    return pd.read_sql(query, db.engine)


def load_open_positions() -> pd.DataFrame:
    query = "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY entry_date DESC"
    return pd.read_sql(query, db.engine)


portfolio_df = load_portfolio_data()
positions_df = load_open_positions()

if not portfolio_df.empty:
    latest = portfolio_df.iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Portfolio", f"₹{latest['total_value']:,.0f}")
    c2.metric("Cash", f"₹{latest['cash']:,.0f}")
    c3.metric("Open Positions", int(latest['num_positions']))

st.subheader("Open Positions")
st.dataframe(positions_df, use_container_width=True)
