-- 0007: evaluation harness (M3, Decision 7). A batch scores every case's forecast, and a naive
-- seasonal random walk, against the actuals as first reported. One row per forecast, with the
-- metrics as columns; p10/p50/p90/seed stay NULL until the Monte Carlo variants (M4, M8).

CREATE TABLE eval_cases (
    case_id           TEXT PRIMARY KEY,                -- e.g. AAPL_2020-02-17
    ticker            TEXT NOT NULL,
    cik               TEXT NOT NULL REFERENCES companies (cik),
    event_date        DATE NOT NULL,
    event_type        TEXT NOT NULL,
    description       TEXT NOT NULL,
    horizon_quarters  INTEGER NOT NULL CHECK (horizon_quarters BETWEEN 1 AND 4),
    selected_because  TEXT NOT NULL,
    source_url        TEXT,
    scope_change      TEXT                             -- a deal closing inside the horizon
);

CREATE TABLE eval_batches (
    batch_id      TEXT PRIMARY KEY,                    -- e.g. eval_2026-10-30_1
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    code_version  TEXT NOT NULL,
    cases_sha256  TEXT NOT NULL,                       -- the case file the batch ran
    notes         TEXT
);

CREATE TABLE eval_results (
    batch_id            TEXT NOT NULL REFERENCES eval_batches (batch_id),
    case_id             TEXT NOT NULL REFERENCES eval_cases (case_id),
    run_id              TEXT NOT NULL REFERENCES runs (run_id),
    variant             TEXT NOT NULL CHECK (variant IN ('baseline', 'naive_srw', 'with_shocks')),
    item                TEXT NOT NULL CHECK (item IN ('revenue', 'ebit')),
    period              TEXT NOT NULL,                 -- fiscal quarter, e.g. FY2020Q2
    horizon             INTEGER NOT NULL CHECK (horizon BETWEEN 1 AND 4),
    period_end          DATE,                          -- of the actual quarter
    days                INTEGER,                       -- length of the actual quarter
    forecast            REAL NOT NULL,
    actual              REAL,                          -- NULL while status = 'missing'
    actual_revenue      REAL,                          -- scales the EBIT error (margin points)
    comparative         REAL,                          -- prior year, from the actual's filing
    prior_year_known    REAL,                          -- prior year, as known on the case date
    error               REAL,                          -- revenue: APE; EBIT: |error| / revenue
    signed_error        REAL,
    pct_error           REAL,                          -- stored for reference, never summarised
    direction_forecast  INTEGER,                       -- -1, 0 (within ±0.5%), 1
    direction_actual    INTEGER,
    derived             INTEGER NOT NULL DEFAULT 0,    -- actual is a derived Q4
    actual_method       TEXT,
    status              TEXT NOT NULL CHECK (status IN ('ok', 'missing')),
    p10                 REAL,
    p50                 REAL,
    p90                 REAL,
    seed                INTEGER,
    PRIMARY KEY (batch_id, case_id, variant, item, period)
);

CREATE TABLE eval_failures (
    batch_id  TEXT NOT NULL REFERENCES eval_batches (batch_id),
    case_id   TEXT NOT NULL REFERENCES eval_cases (case_id),
    reason    TEXT NOT NULL,
    PRIMARY KEY (batch_id, case_id)
);
