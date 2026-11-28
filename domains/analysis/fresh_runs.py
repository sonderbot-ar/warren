"""Fresh runs for dates whose newest stored baseline was read under older rules (backlog #626
item 1, #485).

A stored run is the record of what Warren said on its date: it keeps its own assumption rows and
reproduces from them to the cent, so it is never rebuilt in place. When the reading rules
(`reading_rules.READING_RULES_VERSION`) or the concept map change, the newest run of a date keeps
the old reading, and the app (which shows the newest baseline of a date) says so through
`run_read_differently`. This module finds those dates and builds one new baseline for each under
today's rules, map and owner choices, from the data stored now; the old run stays beside it.

Only the reading is compared: a run built from an older filings download (`ingest_run_id`) or
older market downloads is not called stale here, because its reading rules are today's and a new
download is a data question (the pipeline's reuse check, `orchestration.nodes._same_inputs`,
handles it on a pipeline run).
"""

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from domains.analysis.math_engine import EngineError
from domains.analysis.reading_rules import READING_RULES_VERSION
from domains.analysis.runs import run_baseline
from domains.fundamentals.concepts import concept_map_sha256
from domains.market.store import MarketDataError

# The newest stored baseline of each company and date, as the app picks it: not a what-if (no
# parent), not a simulation (no seed), and with no assumption an LLM proposed.
_NEWEST = """
    SELECT r.run_id, r.ticker, r.as_of, r.reading_rules_version, r.concept_map_sha256
    FROM runs r
    WHERE r.parent_run_id IS NULL AND r.seed IS NULL
      AND NOT EXISTS (SELECT 1 FROM assumptions a
                      WHERE a.run_id = r.run_id AND a.source = 'llm_proposed')
    ORDER BY r.ticker, r.as_of, r.created_at DESC, r.run_id DESC
"""


@dataclass(frozen=True)
class StaleDate:
    ticker: str
    as_of: date
    run_id: str  # the newest stored baseline of the date
    rules_version: int | None  # its reading rules; None: stored before they were recorded
    map_same: bool  # read through today's concept map

    @property
    def reason(self) -> str:
        parts = []
        if self.rules_version != READING_RULES_VERSION:
            shown = "not recorded" if self.rules_version is None else f"v{self.rules_version}"
            parts.append(f"reading rules {shown}, today v{READING_RULES_VERSION}")
        if not self.map_same:
            parts.append("another concept map")
        return "; ".join(parts)


@dataclass(frozen=True)
class Refreshed:
    stale: StaleDate
    run_id: str | None  # the new run; None when the build failed
    error: str | None = None


def stale_dates(conn: sqlite3.Connection, tickers: Iterable[str] | None = None) -> list[StaleDate]:
    """Every company and date whose newest stored baseline was made under other reading rules
    than today's (or none recorded) or through another concept map, sorted by ticker and date."""
    wanted = None if tickers is None else {t.upper() for t in tickers}
    today_map = concept_map_sha256()
    seen: set[tuple[str, str]] = set()
    out = []
    for row in conn.execute(_NEWEST):
        key = (row["ticker"], row["as_of"])
        if key in seen:
            continue
        seen.add(key)  # rows come newest first within a date
        if wanted is not None and row["ticker"] not in wanted:
            continue
        rules = row["reading_rules_version"]
        map_same = row["concept_map_sha256"] == today_map
        if rules == READING_RULES_VERSION and map_same:
            continue
        out.append(
            StaleDate(
                row["ticker"], date.fromisoformat(row["as_of"]), row["run_id"], rules, map_same
            )
        )
    return out


def refresh(
    conn: sqlite3.Connection,
    stale: Iterable[StaleDate],
    build: Callable[[sqlite3.Connection, str, date], str] = run_baseline,
) -> list[Refreshed]:
    """Build one new baseline for each stale date under today's rules; nothing stored is changed.
    A date whose build fails (no market data stored, no base value) is reported, not raised."""
    done = []
    for item in stale:
        try:
            run_id = build(conn, item.ticker, item.as_of)
        except (EngineError, MarketDataError, ValueError) as e:
            done.append(Refreshed(item, None, f"{getattr(e, 'code', None) or 'error'}: {e}"))
            continue
        done.append(Refreshed(item, run_id))
    return done
