"""Monte Carlo over shocks (M4, Decisions 4 and 6): the baseline run, shocked N times.

Each sample draws one magnitude per shock (a split normal whose p10/p50/p90 are the shock's
low/base/high), adds the shocks to the run's driver paths and values the result with the same
arithmetic as the baseline. Only the shocks' size is uncertain here: the baseline's own drivers are
not sampled, so the p10–p90 band is shock-size uncertainty only (M8 adds the rest).

A simulation is stored with its seed and its shocks in order, and reproduces to the cent.
"""

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from domains.analysis import dcf, shocks
from domains.analysis import financial_math as fm
from domains.analysis.dcf import Inputs
from domains.analysis.runs import CENT, code_version, load_assumptions
from domains.analysis.schemas import SINGLE
from domains.analysis.shocks import Shock

DEFAULT_SAMPLES = 10_000
LINES = ("revenue", "ebit", "fcff")
SINGLES = ("enterprise_value_as_of", "equity_value", "value_per_share")
MARGIN_BOUNDS = (-1.0, 1.0)  # an operating margin outside these is not a business


class SimulationError(ValueError):
    """Samples that can't be valued, or impossible drivers: narrow the shocks' ranges."""


@dataclass(frozen=True)
class Band:
    baseline: float
    p10: float
    p50: float
    p90: float
    mean: float


def _check_samples(inp: Inputs, n: int) -> None:
    """Stop the run if any sample has an impossible driver or a rate the terminal value can't use.

    Dropping such samples would bias the percentiles; the user narrows the range instead.
    """
    problems = []
    for name, test in (
        ("operating_margin", lambda v: (v <= MARGIN_BOUNDS[0]) | (v >= MARGIN_BOUNDS[1])),
        ("capex_pct", lambda v: v < 0),
    ):
        bad = np.zeros(n, dtype=bool)
        for v in inp.driver[name]:
            bad |= np.broadcast_to(test(np.asarray(v)), (n,))
        if bad.any():
            problems.append(f"{int(bad.sum())} samples give an impossible {name}")
    one = inp.one
    cost_of_equity = fm.capm_cost_of_equity(one["risk_free"], one["beta"], one["erp"])
    shift = (inp.cost_of_equity_shift or [0.0])[-1]
    last = fm.wacc(
        one["equity_market_value"],
        one["debt"],
        cost_of_equity + np.asarray(shift),
        one["cost_of_debt"],
        one["debt_tax_rate"],
    )
    floor = 0.0 if inp.terminal_method == dcf.VALUE_DRIVER else one["terminal_growth"]
    bad = np.broadcast_to(np.asarray(last) <= floor, (n,))
    if bad.any():
        problems.append(f"{int(bad.sum())} samples put Y5's discount rate at or below {floor:.2%}")
    if problems:
        raise SimulationError(f"of {n} samples: " + "; ".join(problems))


def simulate(
    rows, shock_list: list[Shock], n: int = DEFAULT_SAMPLES, seed: int = 0
) -> dict[tuple[str, str], Band]:
    """p10/p50/p90 and mean of each output over n shocked samples, next to the baseline."""
    if n < 1:
        raise SimulationError("need at least one sample")
    base_inputs = dcf.inputs(rows)
    baseline = dcf.compute(base_inputs)
    rng = np.random.Generator(np.random.PCG64(seed))
    z = rng.standard_normal((n, len(shock_list)))
    magnitudes = [fm.split_normal(s.low, s.base, s.high, z[:, i]) for i, s in enumerate(shock_list)]
    shocked = shocks.apply(base_inputs, shock_list, magnitudes)
    _check_samples(shocked, n)
    valuation = dcf.compute(shocked)

    out = {}

    def band(key, base_value, samples):
        values = np.broadcast_to(np.asarray(samples, dtype=float), (n,))
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        out[key] = Band(float(base_value), float(p10), float(p50), float(p90), float(values.mean()))

    for line in LINES:
        for i, period in enumerate(baseline.periods):
            band((line, period), baseline.lines[line][i], valuation.lines[line][i])
    for name in SINGLES:
        band((name, SINGLE), getattr(baseline, name), getattr(valuation, name))
    return out


# -- shocks from a file ------------------------------------------------------------------------

SHOCK_FIELDS = (
    "shock_id event_id driver low base high start_period horizon decay source rationale".split()
)


def load_shocks(path: Path) -> list[Shock]:
    """Shocks from a CSV with SHOCK_FIELDS as columns; a bad row is an error, never skipped."""
    out = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        missing = set(SHOCK_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise SimulationError(f"{path.name}: missing columns {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            try:
                fields = {k: (row[k] or "").strip() for k in SHOCK_FIELDS}
                out.append(Shock(**fields | {"event_id": fields["event_id"] or None}))
            except ValueError as e:
                raise SimulationError(f"{path.name} line {line}: {e}") from e
    if len({s.shock_id for s in out}) != len(out):
        raise SimulationError(f"{path.name}: duplicate shock_id")
    return out


# -- storage -----------------------------------------------------------------------------------


def _currency(conn: sqlite3.Connection) -> str:
    units = {
        r["unit"]
        for r in conn.execute("SELECT unit FROM concepts WHERE canonical_name = 'revenue'")
    }
    if len(units) != 1:
        raise SimulationError(f"revenue concepts must share one currency, got {sorted(units)}")
    return units.pop()


def save_simulation(
    conn: sqlite3.Connection,
    run_id: str,
    shock_list: list[Shock],
    n: int = DEFAULT_SAMPLES,
    seed: int | None = None,
) -> str:
    """Simulate a stored run under the shocks and store it all in one transaction; its id."""
    if seed is None:
        seed = int(np.random.SeedSequence().entropy % 2**63)
    bands = simulate(load_assumptions(conn, run_id), shock_list, n, seed)
    count = conn.execute("SELECT COUNT(*) FROM simulations WHERE run_id = ?", (run_id,)).fetchone()[
        0
    ]
    sim_id = f"{run_id}_sim{count + 1}"
    with conn:
        conn.execute(
            "INSERT INTO simulations (sim_id, run_id, seed, n_samples, code_version, "
            "shocks_sha256, currency, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sim_id,
                run_id,
                seed,
                n,
                code_version(),
                shocks.shocks_sha256(shock_list),
                _currency(conn),
                "band = shock-size uncertainty only; baseline drivers not sampled",
            ),
        )
        for position, s in enumerate(shock_list):
            shock_id = f"{sim_id}:{s.shock_id}"
            conn.execute(
                "INSERT INTO shocks (shock_id, run_id, event_id, driver, low, base, high, "
                "start_period, horizon, decay, source, rationale) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    shock_id,
                    run_id,
                    s.event_id,
                    s.driver,
                    s.low,
                    s.base,
                    s.high,
                    s.start_period,
                    s.horizon,
                    s.decay,
                    s.source,
                    s.rationale,
                ),
            )
            conn.execute(
                "INSERT INTO simulation_shocks (sim_id, shock_id, position) VALUES (?, ?, ?)",
                (sim_id, shock_id, position),
            )
        conn.executemany(
            "INSERT INTO simulation_outputs (sim_id, name, period, baseline, p10, p50, p90, mean) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (sim_id, name, period, b.baseline, b.p10, b.p50, b.p90, b.mean)
                for (name, period), b in bands.items()
            ],
        )
    return sim_id


def load_simulation_shocks(conn: sqlite3.Connection, sim_id: str) -> list[Shock]:
    rows = conn.execute(
        "SELECT s.* FROM simulation_shocks ss JOIN shocks s USING (shock_id) "
        "WHERE ss.sim_id = ? ORDER BY ss.position",
        (sim_id,),
    ).fetchall()
    prefix = f"{sim_id}:"
    return [
        Shock(**{k: r[k] for k in SHOCK_FIELDS} | {"shock_id": r["shock_id"].removeprefix(prefix)})
        for r in rows
    ]


def load_bands(conn: sqlite3.Connection, sim_id: str) -> dict[tuple[str, str], Band]:
    return {
        (r["name"], r["period"]): Band(r["baseline"], r["p10"], r["p50"], r["p90"], r["mean"])
        for r in conn.execute("SELECT * FROM simulation_outputs WHERE sim_id = ?", (sim_id,))
    }


@dataclass(frozen=True)
class SimReproduction:
    sim_id: str
    outputs_checked: int
    mismatches: list[str]

    @property
    def ok(self) -> bool:
        return not self.mismatches


def reproduce_simulation(conn: sqlite3.Connection, sim_id: str) -> SimReproduction:
    """Run a stored simulation again from its run's rows, its shocks and its seed; compare."""
    sim = conn.execute("SELECT * FROM simulations WHERE sim_id = ?", (sim_id,)).fetchone()
    if sim is None:
        raise SimulationError(f"No simulation {sim_id}")
    shock_list = load_simulation_shocks(conn, sim_id)
    mismatches = []
    if shocks.shocks_sha256(shock_list) != sim["shocks_sha256"]:
        mismatches.append("shocks differ from the ones simulated (hash)")
    stored = load_bands(conn, sim_id)
    now = simulate(load_assumptions(conn, sim["run_id"]), shock_list, sim["n_samples"], sim["seed"])
    if set(stored) != set(now):
        mismatches.append("different outputs")
    for key in sorted(set(stored) & set(now)):
        for field in ("baseline", "p10", "p50", "p90", "mean"):
            a, b = getattr(stored[key], field), getattr(now[key], field)
            if abs(a - b) > CENT:
                mismatches.append(f"{key[0]} {key[1]} {field}: stored {a}, now {b}")
    return SimReproduction(sim_id, len(stored), mismatches)
