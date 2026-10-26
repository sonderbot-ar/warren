-- 0003: data provenance and a guard against impossible facts (M1.1).

-- A period can't end after the filing that reports it. One EDGAR data error (WMT) was stored by
-- M1; remove it, and make the database refuse such rows from now on.
DELETE FROM financial_facts WHERE period_end > filed_at;

CREATE TRIGGER financial_facts_period_not_after_filing
BEFORE INSERT ON financial_facts
WHEN NEW.period_end > NEW.filed_at
BEGIN
    SELECT RAISE(ABORT, 'financial_facts: period_end is after filed_at');
END;

-- One row per ingest: which data and which concept map produced the stored facts, so any later
-- analysis can say exactly what it was built from.
CREATE TABLE ingest_runs (
    run_id                 INTEGER PRIMARY KEY,
    cik                    TEXT NOT NULL REFERENCES companies (cik),
    ingested_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    companyfacts_sha256    TEXT NOT NULL,   -- hash of the company-facts content that was loaded
    companyfacts_fetched_at TEXT,           -- when it was downloaded from EDGAR (NULL if unknown)
    concept_map_sha256     TEXT NOT NULL,   -- hash of concept_map.csv at ingest time
    facts_kept             INTEGER NOT NULL,
    facts_new              INTEGER NOT NULL
);
CREATE INDEX ix_ingest_runs_cik ON ingest_runs (cik, ingested_at);
