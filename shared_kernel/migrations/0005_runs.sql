-- 0005: DCF runs (M2). A run stores every assumption it used (including the base values taken
-- from filings) and every number it produced, so it can be valued again from its rows alone and
-- checked to the cent. The data it was built from is named by id and content hash.

CREATE TABLE runs (
    run_id              TEXT PRIMARY KEY,           -- e.g. AAPL_2024-03-31_1
    cik                 TEXT NOT NULL REFERENCES companies (cik),
    ticker              TEXT NOT NULL,
    as_of               DATE NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    seed                INTEGER,                    -- Monte Carlo seed (M4); NULL for a baseline
    code_version        TEXT NOT NULL,              -- git commit, '+dirty' if uncommitted changes
    ingest_run_id       INTEGER NOT NULL REFERENCES ingest_runs (run_id),
    concept_map_sha256  TEXT NOT NULL,
    price_fetch_sha256  TEXT NOT NULL,              -- the company's prices
    index_fetch_sha256  TEXT NOT NULL,              -- the market index (beta, equity risk premium)
    yield_fetch_sha256  TEXT NOT NULL,              -- the risk-free series
    notes               TEXT                        -- warnings, one per line
);
CREATE INDEX ix_runs_ticker ON runs (ticker, as_of);

-- value is NULL only for a user's choice of method (e.g. erp_method), whose choice is in method.
CREATE TABLE assumptions (
    run_id  TEXT NOT NULL REFERENCES runs (run_id),
    name    TEXT NOT NULL,
    period  TEXT NOT NULL,                          -- e.g. FY2024Q3, Y4, or '-' for one value
    value   REAL,
    source  TEXT NOT NULL CHECK (source IN ('computed', 'user', 'llm_proposed')),
    method  TEXT NOT NULL,
    PRIMARY KEY (run_id, name, period)
);

CREATE TABLE run_outputs (
    run_id  TEXT NOT NULL REFERENCES runs (run_id),
    name    TEXT NOT NULL,
    period  TEXT NOT NULL,
    value   REAL NOT NULL,
    PRIMARY KEY (run_id, name, period)
);
