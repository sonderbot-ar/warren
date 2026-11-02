"""The M8 backtest batch: every case, five variants, on the run the AI's shocks were sized on.

For each case the batch takes the current proposal sets (`propose.current_set`, named and
masked), checks they sit on one stored run, and scores that run's baseline, the naive forecast,
the guidance shocks where they exist (M4) and both sets of the AI's shocks (M6). The batch's
notes record what is needed to score it again: the guidance file's hash, the actuals' as-of date
and the set ids per case. `reproduce_batch` re-scores a stored batch from stored data only and
checks every row to the cent. Design: docs/designs/m8-backtest.md.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from domains.analysis.montecarlo import DEFAULT_SAMPLES, reproduce_simulation
from domains.analysis.runs import code_version
from domains.evaluation.cases import Case
from domains.evaluation.guidance import Guide
from domains.evaluation.harness import (
    COLUMNS,
    SHOCKED,
    EvaluationError,
    case_seed,
    evaluate_case,
    insert_rows,
    new_batch,
    record_failure,
    scoring_errors,
)
from domains.llm import propose, review

LLM_VARIANTS = {"named": "llm_named", "masked": "llm_masked"}
MONEY = 0.005  # forecasts and bands, in currency units: to the cent
RATIO = 1e-9  # errors, which are ratios
MONEY_COLUMNS = ("forecast", "actual", "actual_revenue", "comparative", "prior_year_known",
                 "p10", "p50", "p90")  # fmt: skip


def current_sets(conn: sqlite3.Connection, case: Case) -> tuple[str, dict[str, int]]:
    """The run and the current set id per variant for a case; refused when a set is missing or
    the two sit on different runs."""
    sets = {v: propose.current_set(conn, case.case_id, v) for v in LLM_VARIANTS}
    missing = [v for v, s in sets.items() if s is None]
    if missing:
        raise EvaluationError(f"{case.case_id}: no current {' or '.join(missing)} proposal set")
    runs = {s["run_id"] for s in sets.values()}
    if len(runs) != 1:
        raise EvaluationError(
            f"{case.case_id}: the named and masked sets sit on runs {sorted(runs)}"
        )
    return runs.pop(), {v: s["set_id"] for v, s in sets.items()}


def _shock_sets(conn: sqlite3.Connection, set_ids: dict[str, int]) -> dict:
    return {LLM_VARIANTS[v]: review.approved_shocks(conn, i) for v, i in set_ids.items()}


def run_backtest(
    conn: sqlite3.Connection,
    cases: list[Case],
    cases_sha256: str,
    guides: list[Guide] | None = None,
    guidance_sha256: str | None = None,
    actuals_as_of: date | None = None,
    today: date | None = None,
    n_samples: int = DEFAULT_SAMPLES,
) -> str:
    """Score every case in all five variants; the batch id. Failures are stored with a reason."""
    today = today or date.today()
    actuals_as_of = actuals_as_of or today
    plans, failures = {}, {}
    for case in cases:
        try:
            plans[case.case_id] = current_sets(conn, case)
        except EvaluationError as e:
            failures[case.case_id] = str(e)
    notes = {
        "kind": "backtest",
        "guidance_sha256": guidance_sha256,
        "actuals_as_of": actuals_as_of.isoformat(),
        "n_samples": n_samples,
        "sets": {c: s for c, (_, s) in plans.items()},
    }
    batch_id = new_batch(conn, cases, cases_sha256, json.dumps(notes, sort_keys=True), today)
    for case in cases:
        if case.case_id in failures:
            record_failure(conn, batch_id, case.case_id, failures[case.case_id])
            continue
        run_id, set_ids = plans[case.case_id]
        try:
            _, rows = evaluate_case(
                conn, case, actuals_as_of=actuals_as_of, today=today,
                guides=[g for g in guides or [] if g.case_id == case.case_id],
                n_samples=n_samples, run_id=run_id, shock_sets=_shock_sets(conn, set_ids),
            )  # fmt: skip
        except scoring_errors() as e:
            record_failure(conn, batch_id, case.case_id, str(e))
            continue
        insert_rows(conn, batch_id, rows)
    return batch_id


def batch_notes(conn: sqlite3.Connection, batch_id: str) -> dict:
    row = conn.execute("SELECT notes FROM eval_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if row is None:
        raise EvaluationError(f"no batch {batch_id}")
    try:
        notes = json.loads(row["notes"] or "")
    except json.JSONDecodeError:
        notes = None
    if not isinstance(notes, dict) or notes.get("kind") != "backtest":
        raise EvaluationError(f"{batch_id} is not a backtest batch")
    return notes


@dataclass
class BatchReproduction:
    batch_id: str
    code_then: str
    code_now: str
    rows_checked: int = 0
    simulations_checked: int = 0
    mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _differs(a, b, tolerance: float) -> bool:
    if a is None or b is None:
        return a is not b
    if isinstance(a, str) or isinstance(b, str):
        return a != b
    return abs(a - b) > tolerance


def reproduce_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    cases: list[Case],
    guides: list[Guide] | None = None,
    guidance_sha256: str | None = None,
) -> BatchReproduction:
    """Score a stored backtest batch again from stored data and compare every row.

    The runs and simulations are the stored ones; each simulation is also re-run from its
    shocks and seed. The sets must still be each case's current sets, and the guidance file
    must have the hash the batch recorded."""
    notes = batch_notes(conn, batch_id)
    then = conn.execute("SELECT code_version FROM eval_batches WHERE batch_id = ?", (batch_id,))
    out = BatchReproduction(batch_id, then.fetchone()["code_version"], code_version())
    if notes["guidance_sha256"] != guidance_sha256:
        out.mismatches.append(
            f"guidance file hash {guidance_sha256}, batch ran {notes['guidance_sha256']}"
        )
        return out
    stored: dict[tuple, dict] = {}
    for r in conn.execute("SELECT * FROM eval_results WHERE batch_id = ?", (batch_id,)):
        stored[(r["case_id"], r["variant"], r["item"], r["period"])] = dict(r)
    by_case = {c.case_id: c for c in cases}
    actuals_as_of = date.fromisoformat(notes["actuals_as_of"])
    sims: set[str] = set()
    for case_id, set_ids in sorted(notes["sets"].items()):
        case = by_case.get(case_id)
        if case is None:
            out.mismatches.append(f"{case_id}: not in today's case file")
            continue
        if not any(k[0] == case_id for k in stored):
            continue  # the case failed in the batch and has no rows to compare
        try:
            run_now, sets_now = current_sets(conn, case)
        except EvaluationError as e:
            out.mismatches.append(str(e))
            continue
        if sets_now != set_ids:
            out.mismatches.append(f"{case_id}: current sets {sets_now}, batch scored {set_ids}")
            continue
        try:
            _, rows = evaluate_case(
                conn, case, actuals_as_of=actuals_as_of,
                guides=[g for g in guides or [] if g.case_id == case_id],
                n_samples=notes["n_samples"], run_id=run_now,
                shock_sets=_shock_sets(conn, set_ids), stored_only=True,
            )  # fmt: skip
        except scoring_errors() as e:
            out.mismatches.append(f"{case_id}: {e}")
            continue
        now = {(r["case_id"], r["variant"], r["item"], r["period"]): r for r in rows}
        mine = {k for k in stored if k[0] == case_id}
        if set(now) != mine:
            out.mismatches.append(f"{case_id}: rows {sorted(set(now) ^ mine)} differ")
        for key in sorted(set(now) & mine):
            a, b = stored[key], now[key]
            for col in COLUMNS:
                tol = MONEY if col in MONEY_COLUMNS else RATIO
                if _differs(a[col], b.get(col), tol):
                    out.mismatches.append(
                        f"{' '.join(key)} {col}: stored {a[col]}, now {b.get(col)}"
                    )
            out.rows_checked += 1
        seed = case_seed(case_id)
        for (sim_id,) in conn.execute(
            "SELECT sim_id FROM simulations WHERE run_id = ? AND seed = ? AND n_samples = ?",
            (run_now, seed, notes["n_samples"]),
        ).fetchall():
            sims.add(sim_id)
    for sim_id in sorted(sims):
        check = reproduce_simulation(conn, sim_id)
        out.mismatches.extend(f"{sim_id}: {m}" for m in check.mismatches)
        out.simulations_checked += 1
    return out


__all__ = ["LLM_VARIANTS", "SHOCKED", "current_sets", "reproduce_batch", "run_backtest"]
