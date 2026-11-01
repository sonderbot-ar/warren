-- foreign_keys: off
-- 0015: the one-command pipeline (M7).
--
-- pipeline_runs: one row per pipeline run, for one ticker and as-of date, from filings to report
-- (domains/orchestration). Its full state after every step is in LangGraph's checkpoint tables
-- (`checkpoints`, `writes`), which the checkpointer creates itself in this same file; this table
-- is the index. seed is chosen once when the pipeline starts, so a step run again after a failure
-- or a resume uses the same seed.
--
-- shock_proposals.reviewed_at: when a review status was set, so a person's review made after the
-- as-of date (with hindsight) is said so in the report.
--
-- proposal_sets: a set's sizes come from its baseline run and from scales.csv, so both join its
-- key (analyst review of M7): before this, a set sized on one baseline was reused for another.
-- SQLite can't change a UNIQUE constraint in place, so the table is rebuilt with foreign keys off;
-- the runner checks every foreign key before commit. Stored sets keep their run_id and get the
-- SHA-256 of scales.csv as it is today (text with LF line endings): the file has not changed
-- since it was added (oct.31.2026, M6 Step 5b), before any set was stored.

CREATE TABLE pipeline_runs (
    pipeline_id     TEXT PRIMARY KEY,                -- <TICKER>_<as-of>_p<N>
    ticker          TEXT NOT NULL,
    as_of           TEXT NOT NULL,                   -- YYYY-MM-DD
    variants        TEXT NOT NULL,                   -- 'named', 'masked' or 'named,masked'
    review          TEXT NOT NULL CHECK (review IN ('auto', 'manual', 'later')),
    seed            INTEGER NOT NULL,
    n_samples       INTEGER NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN ('running', 'waiting_review', 'done', 'failed')),
    run_id          TEXT REFERENCES runs (run_id),   -- the baseline, once built
    report_path     TEXT,
    telemetry_path  TEXT NOT NULL,
    code_version    TEXT NOT NULL,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at     TEXT
);

ALTER TABLE shock_proposals ADD COLUMN reviewed_at TEXT;  -- UTC; NULL before 0015 or unreviewed

CREATE TABLE proposal_sets_new (
    set_id                 INTEGER PRIMARY KEY,
    case_id                TEXT NOT NULL,
    event_run_id           TEXT NOT NULL REFERENCES event_runs (event_run_id),
    variant                TEXT NOT NULL CHECK (variant IN ('named', 'masked')),
    model                  TEXT NOT NULL,
    prompt_sha256          TEXT NOT NULL,
    inputs_sha256          TEXT NOT NULL DEFAULT '',  -- what the set read; '' before 0014
    call_id                INTEGER REFERENCES llm_calls (call_id),
    run_id                 TEXT NOT NULL REFERENCES runs (run_id),  -- the baseline it was sized on
    scales_sha256          TEXT NOT NULL,             -- scales.csv it was sized with
    status                 TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    no_impact              INTEGER CHECK (no_impact IN (0, 1)),
    reason                 TEXT,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (case_id, event_run_id, variant, model, prompt_sha256, inputs_sha256, run_id,
            scales_sha256)
);

INSERT INTO proposal_sets_new (set_id, case_id, event_run_id, variant, model, prompt_sha256,
                               inputs_sha256, call_id, run_id, scales_sha256, status, no_impact,
                               reason, created_at)
SELECT set_id, case_id, event_run_id, variant, model, prompt_sha256, inputs_sha256, call_id,
       run_id, '9581eb13e4eb1f614fc8737a87cdc07be5255cf3fdd0ba5b1140df2d4242664c', status,
       no_impact, reason, created_at
FROM proposal_sets;

DROP TABLE proposal_sets;
ALTER TABLE proposal_sets_new RENAME TO proposal_sets;
