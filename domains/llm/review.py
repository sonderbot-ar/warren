"""Review of proposed shocks (M6): approve, edit or reject, then store the approved as M4 shocks.

Eval cases are reviewed with `auto`: a person reviewing a 2020 event today knows what happened
next, so each proposal is recorded `auto_approved` with reviewer `none`, and the bounds in
`scales` stand where a person would. The manual path is for live use. An edited shock is stored
with `source='user'`; the proposal keeps the model's classes and code's numbers. Review is
idempotent: a proposal that already has a status is never reviewed again.
"""

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from domains.analysis.shocks import Shock

Decision = tuple[Literal["approve", "edit", "reject"], dict | str | None]
EDITABLE = ("low", "base", "high", "start_period", "horizon", "decay")


def _shock(row: sqlite3.Row, source: str, rationale: str, **changes) -> Shock:
    fields = {"low": row["low"], "base": row["base"], "high": row["high"],
              "start_period": row["start_quarter"], "horizon": row["horizon"],
              "decay": row["decay"]} | changes  # fmt: skip
    return Shock(
        shock_id=f"llm:{row['proposal_id']}", event_id=json.loads(row["evidence_json"])[0],
        driver=row["driver"], source=source, rationale=rationale,
        basis="level" if row["driver"] == "revenue_growth" else "growth", **fields,
    )  # fmt: skip


def rationale(row: sqlite3.Row) -> str:
    """The model's words, the classes and σ, and the evidence, in one line."""
    unit = "bp" if row["driver"] == "risk_premium" else "points"
    what = "revenue level" if row["driver"] == "revenue_growth" else row["driver"]
    move = "rise" if row["direction"] == "up" else "cut"
    half = ", halving in about 2 quarters" if row["duration"] == "fading" else ""
    flags = "; ".join(f for f in (row["sigma_flag"], "clipped" if row["clipped"] else None) if f)
    return (
        f"{row['rationale']} [{row['size']} {move} in {what}, {row['duration']}{half}, from "
        f"Q{row['start_quarter']}; σ {row['sigma']:.2f} {unit}{'; ' + flags if flags else ''}; "
        f"events {', '.join(json.loads(row['evidence_json']))}]"
    )


def _store(conn: sqlite3.Connection, row: sqlite3.Row, run_id: str, shock: Shock) -> None:
    conn.execute(
        "INSERT INTO shocks (shock_id, run_id, event_id, driver, low, base, high, start_period, "
        "horizon, decay, source, rationale, basis) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (shock.shock_id, run_id, shock.event_id, shock.driver, shock.low, shock.base, shock.high,
         shock.start_period, shock.horizon, shock.decay, shock.source, shock.rationale,
         shock.basis),
    )  # fmt: skip
    conn.execute(
        "INSERT INTO proposal_shocks (proposal_id, shock_id) VALUES (?, ?)",
        (row["proposal_id"], shock.shock_id),
    )


def review_set(
    conn: sqlite3.Connection,
    set_id: int,
    auto: bool = False,
    ask: Callable[[sqlite3.Row, Shock], Decision] | None = None,
    reviewer: str = "none",
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, int]:
    """Review every unreviewed proposal of a set; counts by the status given."""
    if not auto and ask is None:
        raise ValueError("a manual review needs a way to ask")
    run_id = conn.execute("SELECT run_id FROM proposal_sets WHERE set_id = ?", (set_id,))
    run_id = run_id.fetchone()["run_id"]
    counts: dict[str, int] = {}
    rows = conn.execute(
        "SELECT * FROM shock_proposals WHERE set_id = ? AND status = 'proposed' "
        "ORDER BY proposal_id",
        (set_id,),
    ).fetchall()
    for row in rows:
        proposed = _shock(row, "llm_proposed", rationale(row))
        action, detail = ("approve", None) if auto else ask(row, proposed)
        with conn:
            if action == "approve":
                status = "auto_approved" if auto else "approved"
                _store(conn, row, run_id, proposed)
                note = None
            elif action == "edit":
                changes = {k: v for k, v in (detail or {}).items() if k in EDITABLE}
                if not changes:
                    raise ValueError(f"an edit changes one of {', '.join(EDITABLE)}")
                edited = _shock(row, "user", f"edited by {reviewer}: {rationale(row)}", **changes)
                _store(conn, row, run_id, edited)
                status, note = "edited", json.dumps(changes, sort_keys=True)
            elif action == "reject":
                status, note = "rejected", str(detail or "")
            else:
                raise ValueError(f"unknown review action {action!r}")
            conn.execute(
                "UPDATE shock_proposals SET status = ?, reviewer = ?, review_note = ?, "
                "reviewed_at = ? WHERE proposal_id = ?",
                (
                    status,
                    "none" if auto else reviewer,
                    note,
                    now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    row["proposal_id"],
                ),  # fmt: skip
            )
        counts[status] = counts.get(status, 0) + 1
    return counts


def approved_shocks(conn: sqlite3.Connection, set_id: int) -> list[Shock]:
    """The set's stored shocks (approved, auto-approved or edited), in proposal order."""
    rows = conn.execute(
        "SELECT s.* FROM shock_proposals p JOIN proposal_shocks ps USING (proposal_id) "
        "JOIN shocks s USING (shock_id) WHERE p.set_id = ? ORDER BY p.proposal_id",
        (set_id,),
    ).fetchall()
    fields = ("shock_id event_id driver low base high start_period horizon decay source rationale "
              "basis").split()  # fmt: skip
    return [Shock(**{k: r[k] for k in fields}) for r in rows]
