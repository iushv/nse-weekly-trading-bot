# Market Indices
INDICES = {
    "NIFTY50": "^NSEI",
    "NIFTY_BANK": "^NSEBANK",
    "NIFTY_IT": "NIFTYIT.NS",
    "NIFTY_AUTO": "NIFTYAUTO.NS",
}

# Sectors
SECTORS = [
    "BANKING",
    "IT",
    "AUTO",
    "PHARMA",
    "FMCG",
    "METAL",
    "REALTY",
    "ENERGY",
    "INFRA",
]

# Quality Filters
MIN_MARKET_CAP = 5000  # Crores
MIN_AVG_VOLUME = 100000  # Shares
MIN_PRICE = 50  # INR

# Indicator Parameters
INDICATORS = {
    "RSI_PERIOD": 14,
    "RSI_OVERSOLD": 30,
    "RSI_OVERBOUGHT": 60,
    "SMA_SHORT": 20,
    "SMA_MEDIUM": 50,
    "SMA_LONG": 200,
    "ATR_PERIOD": 14,
    "VOLUME_MA": 20,
}

# Circuit Filters (NSE)
CIRCUIT_LIMITS = {
    "NORMAL": 0.20,
    "MEDIUM": 0.10,
    "TIGHT": 0.05,
}
