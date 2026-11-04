"""Where each assumption of a run came from, as fields (backlog #175).

Every row a run stores (`assumptions`) gets a list of typed sources beside its English `method`
text, so the student app's *Fuente* tab can link a number to its filing, its market series, the
owner's choice or the other rows it was computed from, without parsing text. Sources describe
rows; they never move a number, so `reproduce` and `rebuild` don't read them.

Kinds:
- `filing`: one EDGAR fact (a reported one with its accession, or one Warren derived, e.g. Q4 =
  year − nine months, with the accessions it used).
- `market`: one downloaded series over a day or a span (Yahoo Finance or FRED); the download is
  the one the run's data snapshot names.
- `owner_choice`: a row of `user_assumptions.csv`.
- `derived`: computed from other rows of the same run.
- `rule`: a value set by a fixed rule with no data behind it (an item not reported, counted as
  zero; no debt, so no cost of debt).
- `what_if`: a row a student changed on a what-if child (backlog #141), with the parent's sources.
"""

import json
import sqlite3
from collections.abc import Iterable
from datetime import date

from domains.analysis.schemas import Assumption
from domains.fundamentals.schemas import Fact

KINDS = ("filing", "market", "owner_choice", "derived", "rule", "what_if")
RULES = {
    "not_reported_zero": "Not reported within a year of the balance sheet: counted as zero.",
    "no_debt": "No debt on the balance sheet: the cost of debt is not used (its weight is 0).",
    "not_in_annual_report_zero": "Not reported in that year's annual report: counted as zero.",
}
PROVIDERS = {"yahoo": "Yahoo Finance", "fred": "FRED"}
MEASURES = ("close", "splits", "weekly_total_return", "annual_total_return", "yield")
NOT_RECORDED = {
    "code": "not_recorded",
    "params": {},
    "text": "This run was stored before sources were recorded; see the method text.",
}


class SourceError(ValueError):
    """A run's sources are incomplete or malformed: a row without one, an unknown kind, or a
    derived input that names no row of the run."""


Key = tuple[str, str]  # (name, period) of an assumption row


def filing(fact: Fact) -> dict:
    """One EDGAR fact, as the point-in-time query returned it."""
    return {
        "kind": "filing",
        "item": fact.canonical_name,
        "concept": fact.xbrl_concept,
        "unit": fact.unit,
        "period_start": fact.period_start.isoformat() if fact.period_start else None,
        "period_end": fact.period_end.isoformat(),
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
        "value": fact.value,
        "filed_at": fact.filed_at.isoformat(),
        "accession_no": fact.accession_no,
        "inputs": list(fact.inputs),
        "derived": fact.derived,
        "restated": fact.restated,
    }


def market(provider: str, series: str, measure: str, start: date, end: date) -> dict:
    """A downloaded series over [start, end] (one day when equal). Which download: the one whose
    hash the run stores for that series (`runs.price_fetch_sha256`, `index_fetch_sha256`,
    `yield_fetch_sha256`), added when the sources are read."""
    if provider not in PROVIDERS:
        raise SourceError(f"unknown market provider {provider!r}")
    if measure not in MEASURES:
        raise SourceError(f"unknown market measure {measure!r}")
    return {
        "kind": "market",
        "provider": provider,
        "series": series,
        "measure": measure,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def owner_choice(name: str, value: str, set_by: str, set_on: str) -> dict:
    return {
        "kind": "owner_choice",
        "choice": name,
        "value": value,
        "set_by": set_by,
        "set_on": set_on,
    }


def derived(*inputs: Key) -> dict:
    """Computed from these rows of the same run."""
    if not inputs:
        raise SourceError("a derived source needs at least one input row")
    return {"kind": "derived", "inputs": [{"name": n, "period": p} for n, p in inputs]}


def rule(code: str) -> dict:
    if code not in RULES:
        raise SourceError(f"unknown rule {code!r}")
    return {"kind": "rule", "code": code}


def what_if(parent_run_id: str, before: float | None, how: str, parent_sources: list) -> dict:
    return {
        "kind": "what_if",
        "parent_run_id": parent_run_id,
        "before": before,
        "how": how,
        "parent_sources": list(parent_sources),
    }


def check(rows: Iterable[Assumption], sources: dict[Key, list[dict]], child: bool = False) -> None:
    """Every row has at least one source of a known kind, every source belongs to a row, every
    derived input names a row of the run, and `what_if` appears only on a what-if child."""
    keys = {(a.name, a.period) for a in rows}
    missing = sorted(keys - sources.keys())
    if missing:
        raise SourceError(f"rows without a source: {missing}")
    extra = sorted(sources.keys() - keys)
    if extra:
        raise SourceError(f"sources for rows the run doesn't store: {extra}")
    for key, items in sources.items():
        if not items:
            raise SourceError(f"{key}: no source")
        for item in items:
            kind = item.get("kind")
            if kind not in KINDS:
                raise SourceError(f"{key}: unknown kind {kind!r}")
            if kind == "what_if" and not child:
                raise SourceError(f"{key}: a what_if source on a run that is not a what-if")
            for inner in [item] + list(item.get("parent_sources", [])):
                if inner.get("kind") != "derived":
                    continue
                for ref in inner["inputs"]:
                    if "run_id" in ref:  # a parent's row, on a what-if child
                        if not child:
                            raise SourceError(f"{key}: an input from another run on a base run")
                        continue
                    if (ref["name"], ref["period"]) not in keys:
                        raise SourceError(f"{key}: derived from {ref}, which the run doesn't store")


def insert(conn: sqlite3.Connection, run_id: str, sources: dict[Key, list[dict]]) -> None:
    """Store a run's sources; the caller holds the write transaction (`runs.write_lock`)."""
    conn.executemany(
        "INSERT INTO assumption_sources (run_id, name, period, position, kind, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                name,
                period,
                i,
                item["kind"],
                json.dumps({k: v for k, v in item.items() if k != "kind"}, sort_keys=True),
            )
            for (name, period), items in sorted(sources.items())
            for i, item in enumerate(items)
        ],
    )


def load(conn: sqlite3.Connection, run_id: str) -> dict[Key, list[dict]]:
    """A run's stored sources by row, in the order they were written; {} for a run made before
    sources were recorded."""
    out: dict[Key, list[dict]] = {}
    for r in conn.execute(
        "SELECT name, period, kind, detail FROM assumption_sources WHERE run_id = ? "
        "ORDER BY name, period, position",
        (run_id,),
    ):
        out.setdefault((r["name"], r["period"]), []).append(
            {"kind": r["kind"], **json.loads(r["detail"])}
        )
    return out


def for_child(
    parent: dict[Key, list[dict]], parent_run_id: str, changed: dict[Key, tuple[float, str]]
) -> dict[Key, list[dict]]:
    """A what-if child's sources from its parent's: a changed row (key -> (before, how)) gets a
    `what_if` source holding the parent's list; a copied row keeps the parent's list, except that
    a derived input the child changed names the parent's row (`run_id`), since the copied value
    was computed from the parent's, not the child's (analyst, #175)."""
    out: dict[Key, list[dict]] = {}
    for key, items in parent.items():
        if key in changed:
            before, how = changed[key]
            out[key] = [what_if(parent_run_id, before, how, items)]
            continue
        copied = []
        for item in items:
            if item["kind"] == "derived":
                item = {
                    "kind": "derived",
                    "inputs": [
                        ref | {"run_id": parent_run_id}
                        if (ref["name"], ref["period"]) in changed
                        else ref
                        for ref in item["inputs"]
                    ],
                }
            copied.append(item)
        out[key] = copied
    return out
