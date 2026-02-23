from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timedelta
from trading_bot.data.collectors.market_data import MarketDataCollector

c = MarketDataCollector(market_data_provider='bhavcopy')
start = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')

for sym in ['RELIANCE', 'TMCV', 'VBL', 'HDFCBANK', 'AEGISVOPAK']:
    df = c.fetch_historical_data(sym, start_date=start)
    if df is not None and not df.empty:
        last_close = df['Close'].iloc[-1]
        print(f'{sym}: {len(df)} rows, last close={last_close:.2f}')
    else:
        print(f'{sym}: FAILED')
