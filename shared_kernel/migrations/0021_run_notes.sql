-- 0021: a run's warnings as stable codes with parameters (backlog #172), so the app can show
-- them in any language. One row per line of `runs.notes`, in the same order; `text` is that
-- line, byte for byte (the English fallback), and `params` a JSON object of raw values. Runs
-- stored before this version have no rows here until the backfill matches their text.

CREATE TABLE run_notes (
    run_id    TEXT NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    position  INTEGER NOT NULL CHECK (position >= 0),
    code      TEXT NOT NULL CHECK (code <> ''),
    params    TEXT NOT NULL CHECK (json_valid(params) AND json_type(params) = 'object'),
    text      TEXT NOT NULL,
    PRIMARY KEY (run_id, position)
);
