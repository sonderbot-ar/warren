-- 0012: the LLM steps (M6, Decisions 1, 6 and 9). Every call to a model is a row, with its model,
-- prompt version and hash, input, output, tokens and latency, so any answer can be traced. The
-- answers point at M5's events, which stay as clustered: one event has a named and a masked
-- variant and may be classified by more than one model.

CREATE TABLE llm_calls (
    call_id         INTEGER PRIMARY KEY,
    batch_id        TEXT NOT NULL,                     -- one command's calls, for its budget
    node            TEXT NOT NULL,                     -- extract_events | check_headlines | ...
    model           TEXT NOT NULL,
    prompt_name     TEXT NOT NULL,
    prompt_version  INTEGER NOT NULL,
    prompt_sha256   TEXT NOT NULL,
    ref             TEXT NOT NULL,                     -- what the call is about, e.g. an event id
    attempt         INTEGER NOT NULL CHECK (attempt >= 1),
    input_json      TEXT NOT NULL,
    output_json     TEXT,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'invalid', 'error')),
    error           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX llm_calls_batch ON llm_calls (batch_id);

CREATE TABLE event_classifications (
    classification_id  INTEGER PRIMARY KEY,
    event_id           TEXT NOT NULL REFERENCES events (event_id),
    variant            TEXT NOT NULL CHECK (variant IN ('named', 'masked')),
    model              TEXT NOT NULL,
    prompt_sha256      TEXT NOT NULL,
    call_id            INTEGER REFERENCES llm_calls (call_id),  -- the accepted attempt
    status             TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    event_type         TEXT,
    model_event_type   TEXT,                           -- the type the model chose, before rules
    materiality        TEXT CHECK (materiality IN ('low', 'medium', 'high')),
    reasons            TEXT,
    summary            TEXT,
    evidence_json      TEXT,
    about_json         TEXT,                           -- {article_id: true | false}
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (event_id, variant, model, prompt_sha256)
);

CREATE TABLE case_llm_status (
    case_id        TEXT NOT NULL,
    event_run_id   TEXT NOT NULL,
    variant        TEXT NOT NULL CHECK (variant IN ('named', 'masked')),
    events_total   INTEGER NOT NULL,
    events_chosen  INTEGER NOT NULL,                   -- 0 is a case with no qualifying events
    PRIMARY KEY (case_id, event_run_id, variant)
);

CREATE TABLE headline_checks (
    article_id     TEXT NOT NULL,
    cik            TEXT NOT NULL,
    variant        TEXT NOT NULL CHECK (variant IN ('named', 'masked')),
    model          TEXT NOT NULL,
    prompt_sha256  TEXT NOT NULL,
    call_id        INTEGER NOT NULL REFERENCES llm_calls (call_id),
    about          INTEGER NOT NULL CHECK (about IN (0, 1)),
    PRIMARY KEY (article_id, cik, variant, model, prompt_sha256)
);

-- one proposal set per case and variant, so one story split across events can't stack shocks
CREATE TABLE proposal_sets (
    set_id         INTEGER PRIMARY KEY,
    case_id        TEXT NOT NULL,
    event_run_id   TEXT NOT NULL REFERENCES event_runs (event_run_id),
    variant        TEXT NOT NULL CHECK (variant IN ('named', 'masked')),
    model          TEXT NOT NULL,
    prompt_sha256  TEXT NOT NULL,
    call_id        INTEGER REFERENCES llm_calls (call_id),
    run_id         TEXT NOT NULL REFERENCES runs (run_id),  -- the baseline it was sized on
    status         TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    no_impact      INTEGER CHECK (no_impact IN (0, 1)),
    reason         TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (case_id, event_run_id, variant, model, prompt_sha256)
);

CREATE TABLE shock_proposals (
    proposal_id    INTEGER PRIMARY KEY,
    set_id         INTEGER NOT NULL REFERENCES proposal_sets (set_id),
    driver         TEXT NOT NULL CHECK (driver IN
                       ('revenue_growth', 'operating_margin', 'capex_intensity', 'risk_premium')),
    direction      TEXT NOT NULL CHECK (direction IN ('up', 'down')),
    size           TEXT NOT NULL CHECK (size IN ('small', 'medium', 'large')),
    duration       TEXT NOT NULL
                   CHECK (duration IN ('one_quarter', 'fading', 'lasting', 'permanent')),
    start_quarter  INTEGER NOT NULL CHECK (start_quarter BETWEEN 1 AND 4),
    rationale      TEXT NOT NULL,                      -- the model's words
    evidence_json  TEXT NOT NULL,
    sigma          REAL NOT NULL,                      -- computed by code, never by the model
    sigma_flag     TEXT,                               -- fallback | floored | capped
    low            REAL NOT NULL,
    base           REAL NOT NULL,
    high           REAL NOT NULL,
    horizon        INTEGER NOT NULL,
    decay          REAL NOT NULL,
    clipped        INTEGER NOT NULL DEFAULT 0 CHECK (clipped IN (0, 1)),
    status         TEXT NOT NULL CHECK (status IN
                       ('proposed', 'auto_approved', 'approved', 'edited', 'rejected')),
    reviewer       TEXT,
    review_note    TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (set_id, driver)
);

-- the M4 shock a reviewed proposal became (revenue proposals are one level shock)
CREATE TABLE proposal_shocks (
    proposal_id  INTEGER NOT NULL REFERENCES shock_proposals (proposal_id),
    shock_id     TEXT NOT NULL REFERENCES shocks (shock_id),
    PRIMARY KEY (proposal_id, shock_id)
);

-- a revenue shock may move the level instead of the growth rate (M6 design, Revenue is a level);
-- every shock stored before 0012 is a growth shock
ALTER TABLE shocks ADD COLUMN basis TEXT NOT NULL DEFAULT 'growth'
    CHECK (basis IN ('growth', 'level'));
