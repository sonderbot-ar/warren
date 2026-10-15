-- 0002: fundamentals data layer (M1, Structure Guide Decision 2).
-- Dates are ISO-8601 text (YYYY-MM-DD), which sorts and compares correctly as text.

CREATE TABLE companies (
    cik             TEXT PRIMARY KEY,               -- zero-padded to 10 digits, e.g. '0000320193'
    ticker          TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    sic             TEXT,
    fiscal_year_end TEXT,                           -- MMDD as SEC reports it, e.g. '0926'
    aliases_json    TEXT NOT NULL DEFAULT '[]',     -- current and former names, for news matching (M5)
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Controlled vocabulary: the only XBRL concepts Warren stores, and their canonical names.
-- Synced from domains/fundamentals/concept_map.csv.
CREATE TABLE concepts (
    canonical_name TEXT NOT NULL,                   -- Warren's name, e.g. 'revenue'
    xbrl_concept   TEXT NOT NULL UNIQUE,            -- e.g. 'us-gaap:Revenues'; one tag maps to one name
    priority       INTEGER NOT NULL CHECK (priority >= 1),  -- 1 = preferred within a filing
    unit           TEXT NOT NULL,                   -- USD, shares, USD/shares
    period_type    TEXT NOT NULL CHECK (period_type IN ('duration', 'instant')),
    definition     TEXT NOT NULL,                   -- one precise sentence, for humans and prompts
    PRIMARY KEY (canonical_name, xbrl_concept),
    UNIQUE (canonical_name, priority)
);

-- Every filing's version of every mapped fact. Nothing derived is stored here.
CREATE TABLE financial_facts (
    fact_id        INTEGER PRIMARY KEY,
    cik            TEXT NOT NULL REFERENCES companies (cik),
    xbrl_concept   TEXT NOT NULL REFERENCES concepts (xbrl_concept),
    period_start   TEXT,                            -- NULL for balance-sheet (instant) items
    period_end     TEXT NOT NULL,
    -- Labels come from the company's filing calendar, not from the JSON's fy/fp (which describe
    -- the filing). Durations: Q1-Q4 (3 months), H1 (6-month YTD), M9 (9-month YTD), FY.
    -- Instants: Q1-Q3 and FY (year-end balance). NULL when the period can't be placed.
    fiscal_year    INTEGER,
    fiscal_period  TEXT CHECK (fiscal_period IN ('Q1', 'Q2', 'Q3', 'Q4', 'H1', 'M9', 'FY')),
    value          REAL NOT NULL,
    unit           TEXT NOT NULL,
    form           TEXT NOT NULL CHECK (form IN ('10-K', '10-Q', '10-K/A', '10-Q/A')),
    accession_no   TEXT NOT NULL,                   -- filing id, e.g. '0000320193-25-000079'
    filed_at       TEXT NOT NULL,                   -- the date the fact became public
    CHECK (period_start IS NULL OR period_start <= period_end)
);

-- One row per fact per filing. COALESCE because NULL period_start values never collide in a
-- plain UNIQUE constraint, which would let duplicate balance-sheet facts in.
CREATE UNIQUE INDEX ux_financial_facts_version ON financial_facts (
    cik, xbrl_concept, unit, COALESCE(period_start, ''), period_end, accession_no
);
CREATE INDEX ix_financial_facts_lookup ON financial_facts (cik, xbrl_concept, period_end);
CREATE INDEX ix_financial_facts_filed_at ON financial_facts (filed_at);
