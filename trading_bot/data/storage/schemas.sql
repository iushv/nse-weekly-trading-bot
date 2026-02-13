CREATE TABLE IF NOT EXISTS price_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    adj_close REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_price_symbol_date ON price_data(symbol, date);

CREATE TABLE IF NOT EXISTS alternative_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    date TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    value REAL,
    source TEXT,
    metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alt_symbol_date ON alternative_signals(symbol, date);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_price REAL,
    entry_date TEXT,
    exit_price REAL,
    exit_date TEXT,
    stop_loss REAL,
    target REAL,
    pnl REAL,
    pnl_percent REAL,
    status TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    total_value REAL,
    cash REAL,
    positions_value REAL,
    num_positions INTEGER,
    daily_pnl REAL,
    daily_pnl_percent REAL,
    total_pnl REAL,
    total_pnl_percent REAL,
    max_drawdown REAL,
    sharpe_ratio REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategy_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    date TEXT NOT NULL,
    trades_count INTEGER,
    wins INTEGER,
    losses INTEGER,
    win_rate REAL,
    avg_win REAL,
    avg_loss REAL,
    pnl REAL,
    sharpe REAL,
    UNIQUE(strategy, date)
);

CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    level TEXT,
    module TEXT,
    message TEXT,
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON system_logs(timestamp);

CREATE TABLE IF NOT EXISTS trade_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL,
    stop_loss REAL,
    target REAL,
    quantity INTEGER,
    confidence REAL,
    ml_score REAL,
    market_regime_label TEXT,
    market_regime_confidence REAL,
    market_breadth_ratio REAL,
    market_trend_up INTEGER,
    market_annualized_volatility REAL,
    weekly_ema_short REAL,
    weekly_ema_long REAL,
    weekly_atr REAL,
    weekly_rsi REAL,
    weekly_roc REAL,
    daily_sma20 REAL,
    daily_rsi REAL,
    volume_ratio REAL,
    sector TEXT,
    liquidity_score REAL,
    exit_date TEXT,
    exit_price REAL,
    pnl REAL,
    pnl_percent REAL,
    days_held INTEGER,
    exit_reason TEXT,
    mfe REAL,
    mae REAL,
    outcome_label INTEGER,
    metadata_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trade_features_symbol_entry ON trade_features(symbol, entry_date);
CREATE INDEX IF NOT EXISTS idx_trade_features_strategy_entry ON trade_features(strategy, entry_date);
CREATE INDEX IF NOT EXISTS idx_trade_features_outcome ON trade_features(outcome_label);
CREATE INDEX IF NOT EXISTS idx_trade_features_exit_reason ON trade_features(exit_reason);
