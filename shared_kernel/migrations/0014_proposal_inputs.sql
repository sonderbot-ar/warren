-- foreign_keys: off
-- 0014: a proposal set records exactly what it read (M6 Step 8). Before this, a set was keyed by
-- case, event run, variant, model and proposal prompt only, so a stored set was reused after its
-- inputs changed: a new extraction prompt, or a different choice of events. inputs_sha256 is the
-- SHA-256 of the extraction prompt's hash and the sorted classification ids the proposal read
-- (`domains.llm.propose.inputs_sha256`), and joins the key. SQLite can't change a UNIQUE
-- constraint in place, so proposal_sets is rebuilt with foreign keys off; the runner checks every
-- foreign key before commit. Sets from before 0014 get '' (not known) and are never reused.

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
    status                 TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    no_impact              INTEGER CHECK (no_impact IN (0, 1)),
    reason                 TEXT,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (case_id, event_run_id, variant, model, prompt_sha256, inputs_sha256)
);

INSERT INTO proposal_sets_new (set_id, case_id, event_run_id, variant, model, prompt_sha256,
                               call_id, run_id, status, no_impact, reason, created_at)
SELECT set_id, case_id, event_run_id, variant, model, prompt_sha256, call_id, run_id, status,
       no_impact, reason, created_at
FROM proposal_sets;

DROP TABLE proposal_sets;
ALTER TABLE proposal_sets_new RENAME TO proposal_sets;
