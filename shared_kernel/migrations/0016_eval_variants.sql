-- foreign_keys: off
-- 0016: the backtest (M8) scores the AI's shocks as two more variants of eval_results, one per
-- proposal variant of M6: llm_named and llm_masked. SQLite can't change a CHECK in place, so the
-- table is rebuilt with the wider check and every stored row is copied unchanged.

CREATE TABLE eval_results_new (
    batch_id            TEXT NOT NULL REFERENCES eval_batches (batch_id),
    case_id             TEXT NOT NULL REFERENCES eval_cases (case_id),
    run_id              TEXT NOT NULL REFERENCES runs (run_id),
    variant             TEXT NOT NULL CHECK (variant IN ('baseline', 'naive_srw', 'with_shocks',
                                                  'llm_named', 'llm_masked')),
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

INSERT INTO eval_results_new SELECT * FROM eval_results;
DROP TABLE eval_results;
ALTER TABLE eval_results_new RENAME TO eval_results;
