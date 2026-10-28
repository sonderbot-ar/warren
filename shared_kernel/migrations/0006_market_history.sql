-- 0006: keep every market download (M2.1). A refresh used to replace a symbol's rows, so a run
-- built from an older download could no longer be rebuilt from data. Rows are now keyed by their
-- fetch: a refresh adds a fetch, queries read the latest one unless a run pins its own.

CREATE TABLE prices_new (
    ticker       TEXT NOT NULL,
    date         DATE NOT NULL,
    close        REAL NOT NULL,
    adj_close    REAL NOT NULL,
    volume       INTEGER,
    split_ratio  REAL CHECK (split_ratio IS NULL OR split_ratio > 0),
    fetch_id     INTEGER NOT NULL REFERENCES market_fetches (fetch_id),
    PRIMARY KEY (ticker, fetch_id, date)
);
INSERT INTO prices_new SELECT ticker, date, close, adj_close, volume, split_ratio, fetch_id
FROM prices;
DROP TABLE prices;
ALTER TABLE prices_new RENAME TO prices;

CREATE TABLE yields_new (
    series    TEXT NOT NULL,
    date      DATE NOT NULL,
    value     REAL NOT NULL,
    fetch_id  INTEGER NOT NULL REFERENCES market_fetches (fetch_id),
    PRIMARY KEY (series, fetch_id, date)
);
INSERT INTO yields_new SELECT series, date, value, fetch_id FROM yields;
DROP TABLE yields;
ALTER TABLE yields_new RENAME TO yields;
