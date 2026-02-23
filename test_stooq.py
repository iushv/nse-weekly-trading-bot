import pandas_datareader.data as web
from datetime import date

# Stooq uses symbol.IN format for NSE stocks
df = web.DataReader('TATAMOTORS.IN', 'stooq', start='2026-02-01', end='2026-02-13')
print(f'Rows: {len(df)}')
print(df[['Open','High','Low','Close','Volume']].head(5))
