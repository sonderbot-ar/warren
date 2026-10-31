-- 0013: why a run has no value for an output (backlog #9). A sensitivity such as value per share
-- at ERP − 1 SE can have no value (e.g. WACC at or below terminal growth under the Gordon rule);
-- the output is left out of run_outputs and its reason is stored here, so the report states the
-- real cause and reproduce can check it. reason is a code from financial_math.REASONS, checked
-- by the code on write and read (a CHECK would need a table rebuild for every new code). Runs
-- stored before 0013 have no rows here; their missing outputs are still checked by reproduce.

CREATE TABLE run_output_gaps (
    run_id  TEXT NOT NULL REFERENCES runs (run_id),
    name    TEXT NOT NULL,
    period  TEXT NOT NULL,
    reason  TEXT NOT NULL,                          -- e.g. growth_not_below_rate
    detail  TEXT NOT NULL,                          -- the error's message, for people
    PRIMARY KEY (run_id, name, period)
);
