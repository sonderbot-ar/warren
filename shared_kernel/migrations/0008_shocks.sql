-- 0008: shocks and Monte Carlo simulations (M4, Decisions 4 and 6). A simulation points at the
-- baseline run it shocks (whose rows already reproduce to the cent), at its shocks in order (the
-- order fixes which column of random draws each shock takes) and at its seed, so it can be run
-- again and checked to the cent.

CREATE TABLE shocks (
    shock_id      TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs (run_id),
    event_id      TEXT,                               -- NULL for a manual shock
    driver        TEXT NOT NULL CHECK (driver IN
                      ('revenue_growth', 'operating_margin', 'capex_intensity', 'risk_premium')),
    low           REAL NOT NULL,                      -- p10; percentage points (bp for risk premium)
    base          REAL NOT NULL,                      -- p50
    high          REAL NOT NULL,                      -- p90
    start_period  INTEGER NOT NULL,                   -- first affected forecast quarter, 1 = first
    horizon       INTEGER NOT NULL,                   -- quarters
    decay         REAL NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('user', 'computed', 'llm_proposed')),
    rationale     TEXT NOT NULL,
    CHECK (low <= base AND base <= high),
    CHECK (decay > 0 AND decay <= 1)
);

CREATE TABLE simulations (
    sim_id         TEXT PRIMARY KEY,                  -- e.g. AAPL_2024-03-31_1_sim1
    run_id         TEXT NOT NULL REFERENCES runs (run_id),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    seed           INTEGER NOT NULL,
    n_samples      INTEGER NOT NULL,
    code_version   TEXT NOT NULL,
    shocks_sha256  TEXT NOT NULL,
    currency       TEXT NOT NULL,                     -- of every money output (Decision 11)
    notes          TEXT
);

CREATE TABLE simulation_shocks (
    sim_id    TEXT NOT NULL REFERENCES simulations (sim_id),
    shock_id  TEXT NOT NULL REFERENCES shocks (shock_id),
    position  INTEGER NOT NULL,
    PRIMARY KEY (sim_id, position)
);

-- money in the simulation's currency; the band covers the shocks' size only, not the baseline's error
CREATE TABLE simulation_outputs (
    sim_id    TEXT NOT NULL REFERENCES simulations (sim_id),
    name      TEXT NOT NULL,
    period    TEXT NOT NULL,
    baseline  REAL NOT NULL,
    p10       REAL NOT NULL,
    p50       REAL NOT NULL,
    p90       REAL NOT NULL,
    mean      REAL NOT NULL,
    PRIMARY KEY (sim_id, name, period)
);
