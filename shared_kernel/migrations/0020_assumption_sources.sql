-- 0020: a structured source for every assumption row of a run (backlog #175). Beside the
-- English method text, each row gets an ordered list of typed sources: an EDGAR fact, a
-- downloaded market series, the owner's choice, other rows of the run, a fixed rule, or (on a
-- what-if) the student's change. `detail` holds the kind's fields as one JSON object. Runs stored
-- before this version have no rows here; nothing else changes.

CREATE TABLE assumption_sources (
    run_id    TEXT NOT NULL,
    name      TEXT NOT NULL,
    period    TEXT NOT NULL,
    position  INTEGER NOT NULL CHECK (position >= 0),
    kind      TEXT NOT NULL CHECK (
        kind IN ('filing', 'market', 'owner_choice', 'derived', 'rule', 'what_if')
    ),
    detail    TEXT NOT NULL CHECK (json_valid(detail)),
    PRIMARY KEY (run_id, name, period, position),
    FOREIGN KEY (run_id, name, period) REFERENCES assumptions (run_id, name, period)
        ON DELETE CASCADE  -- a source belongs to its row
);
