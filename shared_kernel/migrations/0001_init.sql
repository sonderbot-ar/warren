-- 0001: migration bookkeeping only. Domain tables arrive with their milestones (M1 onward).
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
