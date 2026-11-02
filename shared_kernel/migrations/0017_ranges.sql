-- 0017: honest ranges (M9). New tables only; no stored row changes.
--
-- forecast_origins: one baseline run per company on the 1st of each month (an "origin"), or the
-- reason it could not be built. baseline_errors: how far each of its forecast quarters was from
-- the actual as first reported, with the date that actual was filed (an error is usable on date D
-- only if actual_filed_at <= D). range_builds and range_results: the ranges built from those
-- errors and how they scored. Design: docs/designs/m9-honest-ranges.md.

CREATE TABLE forecast_origins (
    origin_id       TEXT PRIMARY KEY,                -- <TICKER>_<as-of>
    ticker          TEXT NOT NULL,
    as_of           TEXT NOT NULL,                   -- YYYY-MM-DD
    run_id          TEXT REFERENCES runs (run_id),   -- NULL when status = 'failed'
    code_version    TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    reason          TEXT,
    UNIQUE (ticker, as_of)
);

CREATE TABLE baseline_errors (
    origin_id       TEXT NOT NULL REFERENCES forecast_origins (origin_id),
    ticker          TEXT NOT NULL,
    origin_date     TEXT NOT NULL,
    horizon         INTEGER NOT NULL CHECK (horizon BETWEEN 1 AND 4),
    period          TEXT NOT NULL,                   -- fiscal quarter, e.g. FY2020Q2
    period_end      TEXT,                            -- of the actual quarter
    item            TEXT NOT NULL CHECK (item IN ('revenue', 'ebit')),
    forecast        REAL NOT NULL,
    actual          REAL,
    actual_revenue  REAL,
    actual_filed_at TEXT,                            -- the latest filing among the actual's inputs
    error           REAL,                            -- revenue: ln(actual/forecast); EBIT: margin points
    status          TEXT NOT NULL CHECK (status IN ('ok', 'missing', 'excluded')),
    reason          TEXT,
    PRIMARY KEY (origin_id, horizon, item)
);

CREATE INDEX baseline_errors_known ON baseline_errors (horizon, item, actual_filed_at);

CREATE TABLE range_builds (
    build_id        TEXT PRIMARY KEY,                -- ranges_<date>_<n>
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    code_version    TEXT NOT NULL,
    actuals_as_of   TEXT NOT NULL,
    errors_sha256   TEXT NOT NULL,                   -- of the ok error rows the build read
    eval_batch_id   TEXT REFERENCES eval_batches (batch_id),
    notes           TEXT
);

CREATE TABLE range_results (
    build_id        TEXT NOT NULL REFERENCES range_builds (build_id),
    subject_kind    TEXT NOT NULL CHECK (subject_kind IN ('origin', 'case')),
    subject_id      TEXT NOT NULL,                   -- origin_id or case_id
    run_id          TEXT NOT NULL REFERENCES runs (run_id),
    as_of           TEXT NOT NULL,
    variant         TEXT NOT NULL CHECK (variant IN ('baseline', 'with_shocks', 'llm_named',
                                                     'llm_masked')),
    pool            TEXT NOT NULL CHECK (pool IN ('pooled', 'own')),
    item            TEXT NOT NULL CHECK (item IN ('revenue', 'ebit')),
    period          TEXT NOT NULL,
    period_end      TEXT,
    horizon         INTEGER NOT NULL CHECK (horizon BETWEEN 1 AND 4),
    forecast        REAL NOT NULL,                   -- the baseline, or the shocked p50
    n_errors        INTEGER NOT NULL,
    n_quarters      INTEGER NOT NULL,                -- distinct actual quarters behind the errors
    p10             REAL,
    p50             REAL,
    p90             REAL,
    actual          REAL,
    actual_revenue  REAL,
    seed            INTEGER,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'no_history', 'missing')),
    PRIMARY KEY (build_id, subject_kind, subject_id, variant, pool, item, period)
);
