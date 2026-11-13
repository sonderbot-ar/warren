-- 0023: the version of the reading rules a run was made with (backlog #365): the code that turns
-- filed and downloaded data into its assumption rows (domains/analysis/reading_rules.py). Runs
-- stored before this have none (NULL, "not recorded"); a what-if copies its parent's.

ALTER TABLE runs ADD COLUMN reading_rules_version INTEGER
    CHECK (reading_rules_version IS NULL OR reading_rules_version >= 1);
