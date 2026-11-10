-- 0022: each filing's own period, with the fiscal year and period the filing gives it (the
-- SEC's `fy` and `fp` tags) beside Warren's label from the filing calendar (backlog #310).
-- One row per 10-K, 10-Q or amendment; facts join it on accession_no. Rebuilt for a company on
-- each ingest, as its labels are. A filing with no us-gaap facts has no own period
-- (period_end NULL); a period the calendar cannot place has no Warren label.

CREATE TABLE filing_labels (
    cik                  TEXT NOT NULL REFERENCES companies (cik),
    accession_no         TEXT NOT NULL,
    form                 TEXT NOT NULL CHECK (form IN ('10-K', '10-Q', '10-K/A', '10-Q/A')),
    filed_at             TEXT NOT NULL,
    period_end           TEXT,
    filed_fiscal_year    INTEGER,
    filed_fiscal_period  TEXT CHECK (filed_fiscal_period IN ('Q1', 'Q2', 'Q3', 'FY')),
    fiscal_year          INTEGER,
    fiscal_period        TEXT CHECK (fiscal_period IN ('Q1', 'Q2', 'Q3', 'FY')),
    PRIMARY KEY (cik, accession_no),
    CHECK (period_end IS NULL OR period_end <= filed_at),
    CHECK ((fiscal_year IS NULL) = (fiscal_period IS NULL))
);
