-- 0004: market data for the cost of capital (M2): daily prices from Yahoo Finance and the
-- 10-year Treasury yield from FRED. Used for beta, market weights and the risk-free rate only.

-- One row per download. A refresh replaces a symbol's rows (providers revise adjusted history),
-- so a run records the fetch it used, and its hash says exactly which numbers it saw.
CREATE TABLE market_fetches (
    fetch_id        INTEGER PRIMARY KEY,
    source          TEXT NOT NULL CHECK (source IN ('yahoo', 'fred')),
    symbol          TEXT NOT NULL,           -- ticker (e.g. AAPL, ^GSPC) or series (DGS10)
    fetched_at      TEXT NOT NULL,           -- UTC, ISO 8601
    first_date      DATE NOT NULL,
    last_date       DATE NOT NULL,
    row_count       INTEGER NOT NULL,
    content_sha256  TEXT NOT NULL
);
CREATE INDEX ix_market_fetches_symbol ON market_fetches (source, symbol, fetch_id);

-- close is adjusted for splits only (as Yahoo serves it), adj_close for splits and dividends.
-- split_ratio is the split taking effect that day (4.0 for 4-for-1), NULL when there is none:
-- with it, a close can be put back on the share basis of any date.
CREATE TABLE prices (
    ticker       TEXT NOT NULL,
    date         DATE NOT NULL,
    close        REAL NOT NULL,
    adj_close    REAL NOT NULL,
    volume       INTEGER,
    split_ratio  REAL CHECK (split_ratio IS NULL OR split_ratio > 0),
    fetch_id     INTEGER NOT NULL REFERENCES market_fetches (fetch_id),
    PRIMARY KEY (ticker, date)
);

-- value is in percent, as published (4.25 = 4.25%).
CREATE TABLE yields (
    series    TEXT NOT NULL,
    date      DATE NOT NULL,
    value     REAL NOT NULL,
    fetch_id  INTEGER NOT NULL REFERENCES market_fetches (fetch_id),
    PRIMARY KEY (series, date)
);
