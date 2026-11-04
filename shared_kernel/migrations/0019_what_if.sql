-- 0019: what-if revaluations (backlog #141). A what-if is a run whose rows are a stored run's
-- rows with named inputs changed; parent_run_id links it to that run and is NULL for every run
-- built from data. No stored row changes.
--
-- Numbered 0019 because M10's 0018 waits on its branch (the shared data snapshot already carries
-- it); the runner applies every version not yet recorded, so 0018 still applies after this one.

ALTER TABLE runs ADD COLUMN parent_run_id TEXT REFERENCES runs (run_id);
CREATE INDEX ix_runs_parent ON runs (parent_run_id);
