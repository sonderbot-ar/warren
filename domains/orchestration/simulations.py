"""A run's simulations with the news variant each stands for (backlog #201).

The app holds a run id; the shocked range (`run_ranges(..., sim_id=S)`) needs a simulation id.
`run_simulations(conn, run_id)` lists every simulation stored on the run, masked first (M8's
headline variant; the first of each variant is its `primary`, see `_rank`), each with:

- its variant, traced through stored rows only: a simulation's shocks are stored as
  `<sim_id>:<shock id>` (`montecarlo.save_simulation`); an AI shock's own id is the one in
  `proposal_shocks`, whose proposal belongs to a `proposal_sets` row with its `variant`. `none`
  when no shock traces to a set (manual or guidance shocks), `both` when shocks trace to sets of
  both variants (no writer does this today);
- the pipelines that filed it, from the last checkpoint of every pipeline on the run (done or
  not: a pipeline that failed after its simulation step still made one), with the variant each
  filed it under; a variant that differs from the trace is a note;
- its value per share p10, p50, p90; and, with `check=True`, whether it reproduces to the cent
  (about a second per 10,000 samples: for a button, never a page view; `mismatches` are English
  for the log, the app shows only `reproduces`).

Notes are codes with parameters (as run warnings are, backlog #172), so the app can word them.
Nothing is stored.
"""

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field, replace

from domains.analysis.coded import SIMULATION_NOTE_CODES, Coded
from domains.analysis.montecarlo import reproduce_simulation
from domains.orchestration import graph
from shared_kernel.config import DATA_DIR, REPORTS_DIR

VARIANT_ORDER = ("masked", "named", "both", "none")
EVAL_VARIANT = {"llm_masked": "masked", "llm_named": "named", "with_shocks": "none"}
FOLDERS = graph.Folders(reports=REPORTS_DIR / "pipeline", telemetry=DATA_DIR / "telemetry")


class SimulationListError(LookupError):
    """The run is not stored."""


@dataclass(frozen=True)
class ProposalSet:
    set_id: int
    variant: str
    case_id: str
    model: str
    run_id: str  # the baseline its shocks were sized on


@dataclass(frozen=True)
class PipelineLink:
    pipeline_id: str
    status: str
    variants: list[str]  # the variants the pipeline filed this simulation under


@dataclass
class Simulation:
    sim_id: str
    created_at: str
    seed: int
    n_samples: int
    code_version: str
    currency: str
    variant: str
    shocks: int
    sources: list[str]
    proposal_sets: list[ProposalSet]
    pipelines: list[PipelineLink]
    backtests: list[str]  # eval batches that scored it (M8): same run, seed and variant
    value_per_share: dict | None
    primary: bool = False
    reproduces: bool | None = None
    mismatches: list[str] = field(default_factory=list)  # English, for the log only
    notes: list[Coded] = field(default_factory=list)


@dataclass(frozen=True)
class RunProposalSet:
    """An AI proposal set sized on this run, and what became of it: why a variant may have no
    simulation (the model saw no impact, every proposal was rejected, or the call failed)."""

    set_id: int
    variant: str
    case_id: str
    status: str  # ok or failed
    no_impact: bool | None
    proposals: dict  # review status → count
    sim_ids: list[str]
    latest: bool  # the newest set for its case and variant on this run (older ones were redone)


@dataclass
class RunSimulations:
    run_id: str
    ticker: str
    as_of: str
    checked: bool
    pipeline_id: str | None
    simulations: list[Simulation]
    proposal_sets: list[RunProposalSet]

    def to_dict(self) -> dict:
        return asdict(self)


def _number(sim_id: str) -> int:
    m = re.search(r"_sim(\d+)$", sim_id)
    return int(m.group(1)) if m else 0


NOTE_TEXT = {
    "shock_not_traced": "AI shock {shock_id} traces to no proposal set",
    "sized_elsewhere": "proposal set {set_id} was sized on run {run_id}, not this one",
    "pipeline_variant_differs": (
        "pipeline {pipeline_id} filed this simulation as {filed}; its shocks say {traced}"
    ),
}


def _note(code: str, **params) -> Coded:
    assert code in SIMULATION_NOTE_CODES, code
    return Coded(code, params, NOTE_TEXT[code].format(**params))


def _rank(sim: "Simulation") -> tuple:
    """Masked first; inside a variant, one a finished pipeline filed, then one a backtest scored,
    then any other pipeline's, then the rest; newest first inside each (the primary is the first
    of its variant)."""
    done = any(p.status == "done" for p in sim.pipelines)
    tier = 0 if done else 1 if sim.backtests else 2 if sim.pipelines else 3
    return VARIANT_ORDER.index(sim.variant), tier, -_number(sim.sim_id), sim.sim_id


def _variant(variants: set[str]) -> str:
    if not variants:
        return "none"
    return variants.pop() if len(variants) == 1 else "both"


def _traced(conn: sqlite3.Connection, sim_id: str) -> tuple[list, list[ProposalSet], list[Coded]]:
    """(shock rows, the proposal sets they trace to, notes) for one simulation."""
    prefix = f"{sim_id}:"
    rows = conn.execute(
        "SELECT s.shock_id, s.source, s.driver, s.event_id "
        "FROM simulation_shocks ss JOIN shocks s USING (shock_id) "
        "WHERE ss.sim_id = ? ORDER BY ss.position",
        (sim_id,),
    ).fetchall()
    sets: dict[int, ProposalSet] = {}
    notes = []
    for r in rows:
        own = r["shock_id"].removeprefix(prefix)
        found = conn.execute(
            "SELECT ps.set_id, ps.variant, ps.case_id, ps.model, ps.run_id, "
            "p.driver, p.evidence_json FROM proposal_shocks x "
            "JOIN shock_proposals p USING (proposal_id) "
            "JOIN proposal_sets ps ON ps.set_id = p.set_id WHERE x.shock_id = ?",
            (own,),
        ).fetchall()
        # the id alone could be any string a person typed: the driver and the first piece of
        # evidence must be the proposal's too (review._shock)
        found = [
            f
            for f in found
            if f["driver"] == r["driver"] and json.loads(f["evidence_json"])[0] == r["event_id"]
        ]
        for f in found:
            sets[f["set_id"]] = ProposalSet(
                f["set_id"], f["variant"], f["case_id"], f["model"], f["run_id"]
            )
        if not found and (r["source"] == "llm_proposed" or own.startswith("llm:")):
            notes.append(_note("shock_not_traced", shock_id=own))
    return rows, [sets[k] for k in sorted(sets)], notes


def _pipelines(
    conn: sqlite3.Connection, run_id: str, folders: graph.Folders
) -> dict[str, list[PipelineLink]]:
    """sim_id → the pipelines on this run whose last checkpoint names it."""
    out: dict[str, dict[str, PipelineLink]] = {}
    for p in conn.execute(
        "SELECT pipeline_id, status FROM pipeline_runs WHERE run_id = ? ORDER BY pipeline_id",
        (run_id,),
    ).fetchall():
        sims = graph.state_values(conn, folders, p["pipeline_id"]).get("sim") or {}
        for variant in sorted(sims, key=VARIANT_ORDER.index):
            summary = sims[variant]
            if summary is None:
                continue
            sim_id = summary["sim_id"] if isinstance(summary, dict) else summary.sim_id
            link = out.setdefault(sim_id, {}).setdefault(
                p["pipeline_id"], PipelineLink(p["pipeline_id"], p["status"], [])
            )
            link.variants.append(variant)
    return {k: list(v.values()) for k, v in out.items()}


def _backtests(conn: sqlite3.Connection, run_id: str) -> dict[tuple[int, str], list[str]]:
    """(seed, variant) → the eval batches that scored a simulation on this run."""
    out: dict[tuple[int, str], list[str]] = {}
    for r in conn.execute(
        "SELECT DISTINCT seed, variant, batch_id FROM eval_results WHERE run_id = ? "
        "AND seed IS NOT NULL ORDER BY batch_id",
        (run_id,),
    ):
        if r["variant"] in EVAL_VARIANT:
            out.setdefault((r["seed"], EVAL_VARIANT[r["variant"]]), []).append(r["batch_id"])
    return out


def _run_sets(conn: sqlite3.Connection, run_id: str, sims: list) -> list[RunProposalSet]:
    out = []
    for r in conn.execute(
        "SELECT set_id, variant, case_id, status, no_impact FROM proposal_sets WHERE run_id = ? "
        "ORDER BY set_id",
        (run_id,),
    ).fetchall():
        counts = {
            x["status"]: x["n"]
            for x in conn.execute(
                "SELECT status, COUNT(*) AS n FROM shock_proposals WHERE set_id = ? "
                "GROUP BY status ORDER BY status",
                (r["set_id"],),
            )
        }
        out.append(
            RunProposalSet(
                set_id=r["set_id"],
                variant=r["variant"],
                case_id=r["case_id"],
                status=r["status"],
                no_impact=None if r["no_impact"] is None else bool(r["no_impact"]),
                proposals=counts,
                latest=False,
                sim_ids=[
                    s.sim_id for s in sims if r["set_id"] in {p.set_id for p in s.proposal_sets}
                ],
            )
        )
    newest: dict[tuple[str, str], int] = {}
    for x in out:
        newest[(x.case_id, x.variant)] = max(newest.get((x.case_id, x.variant), 0), x.set_id)
    return [replace(x, latest=newest[(x.case_id, x.variant)] == x.set_id) for x in out]


def run_simulations(
    conn: sqlite3.Connection,
    run_id: str,
    check: bool = False,
    pipeline_id: str | None = None,
    folders: graph.Folders = FOLDERS,
) -> RunSimulations:
    """Every simulation stored on a run, masked first; see the module docstring. With
    `pipeline_id`, only the simulations that pipeline filed (the app's screen for one pipeline
    run); an unknown pipeline, or one on another run, is an error."""
    if pipeline_id is not None:
        p = conn.execute(
            "SELECT run_id FROM pipeline_runs WHERE pipeline_id = ?", (pipeline_id,)
        ).fetchone()
        if p is None or p["run_id"] != run_id:
            raise SimulationListError(f"No pipeline {pipeline_id} on run {run_id}")
    run = conn.execute("SELECT ticker, as_of FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise SimulationListError(f"No run {run_id}")
    by_pipeline = _pipelines(conn, run_id, folders)
    by_backtest = _backtests(conn, run_id)
    out = []
    for s in conn.execute("SELECT * FROM simulations WHERE run_id = ?", (run_id,)).fetchall():
        sim_id = s["sim_id"]
        rows, sets, notes = _traced(conn, sim_id)
        variant = _variant({x.variant for x in sets})
        for x in sets:
            if x.run_id != run_id:
                notes.append(_note("sized_elsewhere", set_id=x.set_id, run_id=x.run_id))
        links = by_pipeline.get(sim_id, [])
        if pipeline_id is not None and pipeline_id not in {x.pipeline_id for x in links}:
            continue
        for link in links:
            for filed in link.variants:
                if filed != variant:
                    notes.append(
                        _note("pipeline_variant_differs", pipeline_id=link.pipeline_id,
                              filed=filed, traced=variant)
                    )  # fmt: skip
        vps = conn.execute(
            "SELECT p10, p50, p90 FROM simulation_outputs WHERE sim_id = ? "
            "AND name = 'value_per_share'",
            (sim_id,),
        ).fetchone()
        sim = Simulation(
            sim_id=sim_id,
            created_at=s["created_at"],
            seed=s["seed"],
            n_samples=s["n_samples"],
            code_version=s["code_version"],
            currency=s["currency"],
            variant=variant,
            shocks=len(rows),
            sources=sorted({r["source"] for r in rows}),
            proposal_sets=sets,
            pipelines=links,
            backtests=by_backtest.get((s["seed"], variant), []),
            value_per_share=dict(vps) if vps is not None else None,
            notes=notes,
        )
        if check:
            r = reproduce_simulation(conn, sim_id)
            sim.reproduces, sim.mismatches = r.ok, list(r.mismatches)
        out.append(sim)
    out.sort(key=_rank)
    seen = set()
    for sim in out:
        sim.primary = sim.variant not in seen
        seen.add(sim.variant)
    sets = _run_sets(conn, run_id, out)
    if pipeline_id is not None:
        state = graph.state_values(conn, folders, pipeline_id)
        mine = set((state.get("proposal_set") or {}).values())
        sets = [x for x in sets if x.set_id in mine]
    return RunSimulations(run_id, run["ticker"], str(run["as_of"]), check, pipeline_id, out, sets)
