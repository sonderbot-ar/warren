"""Point-in-time fact queries: what a company had reported as of a given date.

For each canonical item and period, the value is the newest version (public on the as-of date) of
the highest-priority tag that reports the period, skipping a version tagged with the wrong sign
(backlog #280, `_sign_flips`) and a part a filing tagged as the whole (backlog #322,
`_parts_as_whole`). In first_reported mode it is the earliest filing, and the
highest-priority tag within it. `restated` means the value differs from first_reported.

Quarterly results add the quarters companies never report on their own (Q4, and standalone Q2/Q3
for cash-flow items reported only year-to-date). They are derived at query time from the inputs
selected for that as-of date, so a derived value is never built from a number not yet public.
"""

import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from domains.fundamentals.schemas import Fact, OwnTagCheck
from domains.fundamentals.universe import warn_if_beyond_history

Mode = Literal["latest", "first_reported"]
Frequency = Literal["reported", "quarterly", "annual"]

# Only additive flows can be derived by subtraction. Weighted-average shares are averages:
# FY minus nine months of an average means nothing, so those quarters stay unreported.
DERIVABLE_UNITS = {"USD"}

QUERY = """
SELECT f.*, c.canonical_name, c.priority
FROM financial_facts f JOIN concepts c USING (xbrl_concept)
WHERE f.cik = ? AND f.filed_at <= ? AND c.canonical_name IN ({placeholders})
"""


def _as_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _best_in_filing(rows: list[sqlite3.Row]) -> sqlite3.Row:
    return min(rows, key=lambda r: r["priority"])


def _to_fact(row: sqlite3.Row, restated: bool) -> Fact:
    return Fact(
        canonical_name=row["canonical_name"],
        xbrl_concept=row["xbrl_concept"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        fiscal_year=row["fiscal_year"],
        fiscal_period=row["fiscal_period"],
        value=row["value"],
        unit=row["unit"],
        accession_no=row["accession_no"],
        filed_at=row["filed_at"],
        restated=restated,
    )


def _rows_by_period(
    conn: sqlite3.Connection,
    cik: str,
    canonical_names: list[str],
    as_of: date | str,
    keep_parts: bool = False,
) -> dict[tuple, dict[str, list[sqlite3.Row]]]:
    """(name, start, end) -> accession -> rows (one per tag that filing used), public on as_of.

    A part a filing tagged as the whole is left out (`_parts_as_whole`, backlog #322), so every
    selection, derivation and check reads the same rows; `keep_parts` keeps it."""
    known = {r[0] for r in conn.execute("SELECT DISTINCT canonical_name FROM concepts")}
    unknown = sorted(set(canonical_names) - known)
    if unknown:
        raise ValueError(f"Not in the concept map: {unknown}")
    periods: dict[tuple, dict[str, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    if not canonical_names:
        return periods

    warn_if_beyond_history(cik, _as_date(as_of))
    sql = QUERY.format(placeholders=", ".join("?" * len(canonical_names)))
    params = [cik, _as_date(as_of).isoformat(), *canonical_names]
    for row in conn.execute(sql, params):
        key = (row["canonical_name"], row["period_start"] or "", row["period_end"])
        periods[key][row["accession_no"]].append(row)
    if not keep_parts:
        for filings in periods.values():
            for accession, rows in filings.items():
                filings[accession] = _parts_as_whole(rows)[0]
    return periods


# A filing's best-ranked tag for a period is a part tagged as the whole when the same filing gives
# the same item and period under another mapped tag, with the same sign, at more than this many
# times its size: P&G's 2014 10-K tagged one segment's revenue (28,400 million for FY2012) as
# `Revenues` beside the company's 82,006 under `SalesRevenueNet` (backlog #322). A whole is never
# smaller than its part, and two lines of one item (net sales and total revenues) never differ by
# half, so the larger figure is the item.
PART_AS_WHOLE_RATIO = 2.0


def _parts_as_whole(rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    """One filing's rows for one period: (kept, skipped), skipping its best-ranked row while
    another row it filed is the same sign and more than `PART_AS_WHOLE_RATIO` times as large."""
    kept, skipped = list(rows), []
    while len(kept) > 1:
        best = _best_in_filing(kept)
        if not any(
            _sign(r["value"]) == _sign(best["value"]) != 0
            and abs(r["value"]) > PART_AS_WHOLE_RATIO * abs(best["value"])
            for r in kept
            if r is not best
        ):
            break
        kept.remove(best)
        skipped.append(best)
    return kept, skipped


def _filing_order(filings: dict[str, list[sqlite3.Row]]) -> list[str]:
    return sorted(filings, key=lambda accn: (filings[accn][0]["filed_at"], accn))


def get_reported_facts(
    conn: sqlite3.Connection,
    cik: str,
    canonical_names: list[str],
    as_of: date | str,
    mode: Mode = "latest",
) -> list[Fact]:
    """Every reported period for the requested items, exactly as known on `as_of` (inclusive)."""
    if mode not in ("latest", "first_reported"):
        raise ValueError(f"Unknown mode: {mode!r}")
    return _facts(_rows_by_period(conn, cik, canonical_names, as_of), mode)


def _facts(periods: dict[tuple, dict[str, list[sqlite3.Row]]], mode: Mode) -> list[Fact]:
    usual = _UsualSigns(periods) if mode == "latest" else None
    facts = []
    for key in sorted(periods):
        filings = periods[key]
        first = _best_in_filing(filings[_filing_order(filings)[0]])
        if usual is None:
            facts.append(_to_fact(first, restated=False))
        else:
            rows = [row for rows in filings.values() for row in rows]
            latest = _latest_of_best_tag(rows, usual.of(key))
            facts.append(_to_fact(latest, restated=latest["value"] != first["value"]))
    return facts


# Two versions of one period are a sign flip when their signs differ and their sizes are within
# this share of each other (WMT's FY2008 tax: 7,145 million, then -7,133 in a later 10-K: 0.2%).
# A real restatement that changes the sign almost never keeps the size, so it is left alone
# (MSFT's FY2016 domestic pretax income: -325, then 5,125 after a recast).
SIGN_FLIP_TOLERANCE = 0.01


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


class _UsualSigns:
    """The sign an item usually takes for this company: the majority sign of every period's newest
    best-tag value (public on the as-of date), leaving out the period being judged. It breaks a tie
    between two versions of one period that flip sign (`_sign_flips`)."""

    def __init__(self, periods: dict[tuple, dict[str, list[sqlite3.Row]]]) -> None:
        self.own: dict[tuple, int] = {}
        self.total: dict[str, int] = defaultdict(int)
        for key, filings in periods.items():
            rows = [row for rows in filings.values() for row in rows]
            sign = _sign(_best_tag_rows(rows)[-1]["value"])
            self.own[key] = sign
            self.total[key[0]] += sign

    def of(self, key: tuple) -> int:
        return _sign(self.total[key[0]] - self.own.get(key, 0))


def _best_tag_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Rows of the highest-priority tag that reports this period, oldest filing first."""
    best = min(r["priority"] for r in rows)
    return sorted(
        (r for r in rows if r["priority"] == best), key=lambda r: (r["filed_at"], r["accession_no"])
    )


def _sign_flips(rows: list[sqlite3.Row], usual: int) -> set[str]:
    """Filings whose version of the period (one tag) is a sign-tagging error (backlog #280).

    Only versions caught in a flip count: a version is a suspect when another version has the
    opposite sign and nearly the same size (`SIGN_FLIP_TOLERANCE`). Among the suspects, the wrong
    side is the sign fewer of the period's versions take (WMT's FY2009 tax: 7,139, -7,156, 7,156);
    on a tie, the side against the item's usual sign for the company (WMT's FY2008 tax: 7,145
    then -7,133, and tax is positive in almost every other WMT period; CAT's 2009 cost of
    revenue: -12,779 then 12,779). With no usual sign either, nothing is skipped. Only versions
    public on the as-of date are seen, so a flip is caught only once a second version is out."""
    flipped = {
        r["accession_no"]
        for r in rows
        for u in rows
        if _sign(r["value"]) * _sign(u["value"]) < 0
        and abs(abs(r["value"]) - abs(u["value"])) <= SIGN_FLIP_TOLERANCE * abs(u["value"])
    }
    if not flipped:
        return set()
    balance = sum(_sign(r["value"]) for r in rows)
    wrong = -_sign(balance) if balance else -usual
    if not wrong:
        return set()
    return {
        r["accession_no"]
        for r in rows
        if r["accession_no"] in flipped and _sign(r["value"]) == wrong
    }


def _latest_of_best_tag(rows: list[sqlite3.Row], usual: int = 0) -> sqlite3.Row:
    """The newest version of the highest-priority tag that reports this period.

    Ranking the tag before the filing stops definition drift: later filings often repeat an old
    period under a broader or narrower tag (e.g. cash including restricted cash, on the cash-flow
    statement), which is a different measure, not a restatement. A restatement filed under a
    higher-ranked tag still wins, because that tag is preferred. A version that is a sign-tagging
    error (`_sign_flips`) is skipped, so the newest version with the right sign is used.
    """
    best = _best_tag_rows(rows)
    flips = _sign_flips(best, usual)
    return [r for r in best if r["accession_no"] not in flips][-1]


def newest_filing_disagreements(
    conn: sqlite3.Connection, cik: str, canonical_names: list[str], as_of: date | str
) -> list[tuple[Fact, Fact]]:
    """Periods where the newest filing's value differs from the selected one: (selected, newest).

    Under best-tag-first selection this happens when the newest filing reports a period only under
    a lower-ranked tag. Usually that is a different measure (definition drift, correctly ignored),
    but it can be a restatement filed only under that tag, which the selection rule would miss.
    """
    pairs = []
    periods = _rows_by_period(conn, cik, canonical_names, as_of)
    usual = _UsualSigns(periods)
    for key in sorted(periods):
        filings = periods[key]
        rows = [row for rows in filings.values() for row in rows]
        selected = _latest_of_best_tag(rows, usual.of(key))
        newest = _best_in_filing(filings[_filing_order(filings)[-1]])
        if newest["accession_no"] in _sign_flips(_best_tag_rows(rows), usual.of(key)):
            continue  # a sign-tagging error, listed by `skipped_sign_flips`, not tag drift
        if newest["value"] != selected["value"]:
            pairs.append((_to_fact(selected, restated=False), _to_fact(newest, restated=False)))
    return pairs


def skipped_sign_flips(
    conn: sqlite3.Connection, cik: str, canonical_names: list[str], as_of: date | str
) -> list[tuple[Fact, Fact]]:
    """Versions skipped as sign-tagging errors (backlog #280): (selected, skipped), one pair per
    skipped filing, as known on `as_of`."""
    pairs = []
    periods = _rows_by_period(conn, cik, canonical_names, as_of)
    usual = _UsualSigns(periods)
    for key in sorted(periods):
        rows = [row for rows in periods[key].values() for row in rows]
        best = _best_tag_rows(rows)
        flips = _sign_flips(best, usual.of(key))
        if flips:
            selected = _to_fact(_latest_of_best_tag(rows, usual.of(key)), restated=False)
            pairs += [(selected, _to_fact(r, False)) for r in best if r["accession_no"] in flips]
    return pairs


def skipped_parts_as_whole(
    conn: sqlite3.Connection, cik: str, canonical_names: list[str], as_of: date | str
) -> list[tuple[Fact, Fact]]:
    """Rows skipped as a part tagged as the whole (backlog #322): (selected, skipped), one pair per
    skipped filing whose tag ranks at or above the selected one's, as known on `as_of`."""
    pairs = []
    raw = _rows_by_period(conn, cik, canonical_names, as_of, keep_parts=True)
    periods = _rows_by_period(conn, cik, canonical_names, as_of)
    usual = _UsualSigns(periods)
    for key in sorted(raw):
        skipped = [r for rows in raw[key].values() for r in _parts_as_whole(rows)[1]]
        if not skipped:
            continue
        rows = [row for rows in periods[key].values() for row in rows]
        chosen = _latest_of_best_tag(rows, usual.of(key))
        selected = _to_fact(chosen, restated=False)
        pairs += [
            (selected, _to_fact(r, False)) for r in skipped if r["priority"] <= chosen["priority"]
        ]
    return pairs


# A change of meaning shows on at least this many periods: a filing that gives a tag a new
# meaning recasts every comparative it shows (a 10-K's two or three years, a 10-Q's quarter and
# year to date), while one recast period alone is more often a restatement (JNJ's cash at
# 2023-01-01, cut for Kenvue in the 2023-10-27 10-Q, kept whole only under the restricted-cash
# tag). Backlog #295.
MEANING_CHANGE_MIN_PERIODS = 2
MEANING_CHANGE_MOVE = 0.005  # the tag's value moves by more than this share of its old value
MEANING_CHANGE_MATCH = 0.001  # and another tag in the same filing holds the old value within this


@dataclass(frozen=True)
class MeaningChange:
    """A tag that changed meaning for one company (backlog #295): from `filed_at`, filings give
    the tag a new value for periods filed before, while repeating the old value under
    `other_concept`. Exxon's `Revenues` moved from sales (FY2018 279,332) to total revenues and
    other income (290,212) in its 2019-11-06 10-Q and 2020-02-26 10-K; `RevenueFromContract...`
    still holds 279,332. Not a restatement: the old figure is still reported, under another tag.
    """

    canonical_name: str
    xbrl_concept: str
    other_concept: str
    accession_no: str  # the first filing that shows it
    form: str
    filed_at: date
    periods: list[tuple[date | None, date, float, float]]  # (start, end, old, new), by end


def tag_meaning_changes(
    conn: sqlite3.Connection, cik: str, canonical_names: list[str], as_of: date | str
) -> list[MeaningChange]:
    """Each (item, tag) whose meaning changed in filings public on `as_of`, by item.

    A period's version under the filing's best tag moves by more than `MEANING_CHANGE_MOVE` from
    the same tag's previous version, and the same filing gives another tag of the item the
    previous value (within `MEANING_CHANGE_MATCH`). Counted when `MEANING_CHANGE_MIN_PERIODS`
    periods show it; dated by the first filing that does. Values are not changed (a note only).
    """
    found: dict[tuple[str, str, str], list[tuple[sqlite3.Row, float]]] = defaultdict(list)
    for (name, _start, _end), filings in sorted(
        _rows_by_period(conn, cik, canonical_names, as_of).items()
    ):
        previous: dict[str, float] = {}
        for accn in _filing_order(filings):
            rows = filings[accn]
            best = _best_in_filing(rows)
            tag, old = best["xbrl_concept"], previous.get(best["xbrl_concept"])
            if old and abs(best["value"] / old - 1) > MEANING_CHANGE_MOVE:
                for row in rows:
                    if row is not best and abs(row["value"] / old - 1) <= MEANING_CHANGE_MATCH:
                        found[(name, tag, row["xbrl_concept"])].append((best, old))
                        break
            previous.update({r["xbrl_concept"]: r["value"] for r in rows})
    out = []
    for (name, tag, other), hits in sorted(found.items()):
        if len(hits) < MEANING_CHANGE_MIN_PERIODS:
            continue
        first = min((row for row, _ in hits), key=lambda r: (r["filed_at"], r["accession_no"]))
        periods = sorted(
            (
                (
                    date.fromisoformat(r["period_start"]) if r["period_start"] else None,
                    date.fromisoformat(r["period_end"]),
                    old,
                    r["value"],
                )
                for r, old in hits
            ),
            key=lambda p: (p[1], p[0] or p[1]),
        )
        out.append(
            MeaningChange(
                name,
                tag,
                other,
                first["accession_no"],
                first["form"],
                date.fromisoformat(first["filed_at"]),
                periods,
            )
        )
    return out


Meaning = Literal["old", "new", "mixed"]


def meaning_state(
    fact: Fact, changes: list[MeaningChange], filed_at: Mapping[str, date] | None = None
) -> tuple[Meaning, MeaningChange | None]:
    """Which meaning of a changed tag `fact` carries (backlog #295, #297), with the change.

    "new": same item, its tag (a derived quarter's tags include it) and its newest input filed
    on or after the change. "mixed": a derived quarter whose newest input is on or after the
    change while another input was filed before it (Exxon FY2017Q4 plain, 72,513 = 244,363 new
    − 171,850 old); needs `filed_at`, each input accession's filing date, and without it a
    derived quarter is judged on its newest input alone. "old": anything else, with the change
    when the fact's tag is one that changed later, else None. When one tag shows more than one
    change (two "other tags"), the earliest filed dates the fact (then the accession number).
    """
    tags = set(fact.xbrl_concept.split(" − "))
    matching = sorted(
        (c for c in changes if c.canonical_name == fact.canonical_name and c.xbrl_concept in tags),
        key=lambda c: (c.filed_at, c.accession_no),
    )
    if not matching:
        return "old", None
    change = matching[0]
    if fact.filed_at < change.filed_at:
        return "old", change
    if fact.derived and filed_at is not None:
        dates = [filed_at[a] for a in fact.inputs if a in filed_at]
        if dates and min(dates) < change.filed_at:
            return "mixed", change
    return "new", change


State = Literal["old", "new", "mixed", "other"]


def state_for_change(
    fact: Fact,
    change: MeaningChange,
    changes: list[MeaningChange],
    filed_at: Mapping[str, date] | None = None,
) -> State:
    """`fact`'s meaning against one `change` (backlog #297): its `meaning_state` when that change
    dates it; "old" when filed under the changed tag before the change or under the tag that
    keeps the earlier meaning; "other" under any other tag (nothing is known of its meaning)."""
    state, dated_by = meaning_state(fact, changes, filed_at)
    if dated_by is change:
        return state
    if set(fact.xbrl_concept.split(" − ")) & {change.xbrl_concept, change.other_concept}:
        return "old"
    return "other"


def dating_changes(
    facts: Iterable[Fact],
    changes: list[MeaningChange],
    filed_at: Mapping[str, date] | None = None,
) -> list[MeaningChange]:
    """The changes that date at least one of `facts` (`meaning_state`), each once, ordered by
    filing date, then accession, tag and other tag."""
    seen: dict[tuple, MeaningChange] = {}
    for fact in facts:
        _state, c = meaning_state(fact, changes, filed_at)
        if c is not None:
            seen.setdefault((c.filed_at, c.accession_no, c.xbrl_concept, c.other_concept), c)
    return [seen[k] for k in sorted(seen)]


def mixes_meanings(states: Iterable[State]) -> bool:
    """Figures read together that are not like for like across a change (backlog #297): any is
    a mix of both meanings, or at least one carries the new meaning and at least one does not."""
    kinds = set(states)
    return "mixed" in kinds or ("new" in kinds and len(kinds) > 1)


def filing_dates(
    conn: sqlite3.Connection, cik: str, as_of: date | str | None = None
) -> dict[str, date]:
    """The filing date of every accession of one company (one query), for `meaning_state`;
    with `as_of`, only accessions filed by then."""
    dates = {
        r["accession_no"]: date.fromisoformat(r["filed_at"])
        for r in conn.execute(
            "SELECT accession_no, MIN(filed_at) AS filed_at "
            "FROM financial_facts WHERE cik = ? GROUP BY accession_no",
            (cik,),
        )
        if r["filed_at"]
    }
    if as_of is None:
        return dates
    as_of = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    return {a: d for a, d in dates.items() if d <= as_of}


def meaning_of(
    fact: Fact, changes: list[MeaningChange], filed_at: Mapping[str, date] | None = None
) -> MeaningChange | None:
    """The change whose new meaning `fact` carries throughout (`meaning_state` "new"). None: the
    old meaning, a mix of both (only told apart with `filed_at`), or a tag that never changed."""
    state, change = meaning_state(fact, changes, filed_at)
    return change if state == "new" else None


# -- backlog #297 item 13: a filing that changed old figures with no other tag keeping them ------

RECAST_MOVE = MEANING_CHANGE_MOVE  # a version moves by more than this share of the one before


@dataclass(frozen=True)
class Recast:
    """A filing that gave periods filed before a new value for an item, and no longer reports the
    old value under any tag (backlog #297 item 13): a recast or a correction, as opposed to a tag
    that changed meaning (`MeaningChange`, where another tag keeps the old value). Exxon's 10-K of
    2018-02-28 cut FY2015 revenue from 259,488 to 239,854 and FY2016 from 218,608 to 200,628;
    Microsoft's 10-K of 2018-08-03 raised FY2016 and FY2017 for ASC 606. The engine does not
    know why the figures moved."""

    canonical_name: str
    accession_no: str
    form: str
    filed_at: date
    periods: list[tuple[date | None, date, float, float]]  # (start, end, old, new), by end

    def largest_move(self, min_days: int = 0, max_days: int | None = None) -> float | None:
        """The largest change, as a share of the old value (signed), among periods at least
        `min_days` and at most `max_days` long (years only with 300, quarters only with 80 and
        100; None when no period fits)."""
        moves = [
            new / old - 1
            for start, end, old, new in self.periods
            if start is not None
            and (end - start).days >= min_days
            and (max_days is None or (end - start).days <= max_days)
        ]
        return max(moves, key=abs) if moves else None


def item_recasts(
    conn: sqlite3.Connection, cik: str, canonical_name: str, as_of: date | str
) -> list[Recast]:
    """Every filing public on `as_of` that recast `canonical_name`, oldest first.

    For each period, filings in order: a filing's version is the last row of its best-ranked
    tag; it is a recast of the period when it moves by more than `RECAST_MOVE` from the figure
    `latest` mode showed from the earlier filings (`_latest_of_best_tag` over their rows, so a
    filing in between that used only a lower-ranked tag is not what it is compared with, backlog
    #325), keeps its sign, and no row of the filing (any tag) still holds the previous
    value within `MEANING_CHANGE_MATCH` (if one does, the old figure is still reported: a tag
    that changed meaning, or a second tag, not a recast). A period is listed only when the
    recast's tag is the tag `latest` mode shows for it: a filing that gives a period under a
    lower-ranked tag than the one shown (Walmart's 10-Ks tag quarters as net sales, its 10-Qs as
    total revenues) did not change the figure a reader sees (analyst, design review).
    Values are not changed (a note only).
    """
    periods_rows = _rows_by_period(conn, cik, [canonical_name], as_of)
    usual = _UsualSigns(periods_rows)
    hits: dict[str, list[tuple[sqlite3.Row, float]]] = defaultdict(list)
    for key, filings in sorted(periods_rows.items()):
        every = [r for rows in filings.values() for r in rows]
        shown = _latest_of_best_tag(every, usual.of(key))["xbrl_concept"]
        earlier: list[sqlite3.Row] = []
        for accn in _filing_order(filings):
            rows = filings[accn]
            # the figure `latest` mode showed from the filings before this one (backlog #325):
            # a filing that gave the period only under a lower-ranked tag did not change it
            previous = _latest_of_best_tag(earlier, usual.of(key))["value"] if earlier else None
            version = _best_tag_rows(rows)[-1]["value"]
            if (
                previous
                and _sign(version) == _sign(previous)
                and abs(version / previous - 1) > RECAST_MOVE
                and not any(abs(r["value"] / previous - 1) <= MEANING_CHANGE_MATCH for r in rows)
                and _best_tag_rows(rows)[-1]["xbrl_concept"] == shown
            ):
                hits[accn].append((_best_tag_rows(rows)[-1], previous))
            earlier.extend(rows)
    out = []
    for accn, found in hits.items():
        first = found[0][0]
        periods = sorted(
            (
                (
                    date.fromisoformat(r["period_start"]) if r["period_start"] else None,
                    date.fromisoformat(r["period_end"]),
                    old,
                    r["value"],
                )
                for r, old in found
            ),
            key=lambda p: (p[1], p[0] or p[1]),
        )
        out.append(
            Recast(
                canonical_name,
                accn,
                first["form"],
                date.fromisoformat(first["filed_at"]),
                periods,
            )
        )
    return sorted(out, key=lambda r: (r.filed_at, r.accession_no))


def version_dates(
    conn: sqlite3.Connection, cik: str, canonical_name: str, as_of: date | str
) -> dict[tuple[date | None, date, str], list[date]]:
    """(start, end, tag) -> the filing dates of every filing public on `as_of` that reported the
    period under that tag of `canonical_name`, oldest first."""
    out: dict[tuple[date | None, date, str], set[date]] = defaultdict(set)
    for (_name, start, end), filings in _rows_by_period(conn, cik, [canonical_name], as_of).items():
        for rows in filings.values():
            for r in rows:
                key = (date.fromisoformat(start) if start else None, date.fromisoformat(end))
                out[(*key, r["xbrl_concept"])].add(date.fromisoformat(r["filed_at"]))
    return {k: sorted(v) for k, v in out.items()}


Side = Literal["before", "after", "mixed"]


def side_of_recast(
    fact: Fact,
    recast: Recast,
    versions: Mapping[tuple[date | None, date, str], list[date]],
    filed_at: Mapping[str, date],
) -> Side:
    """Which side of `recast` a fact's figure sits on (backlog #297 item 13). A reported fact:
    "after" when its period was reported under the fact's own tag in the recast's filing or any
    filing on or after it (refiled, recast, or first reported then), "before" when every such
    filing came earlier. A derived quarter: by the filing dates of its inputs, "mixed" when
    they fall on both sides.

    A period filed again unchanged on or after the recast is "after" on purpose (backlog #331,
    kept after review): a change of accounting principle is applied to every prior period
    presented (ASC 250-10-45-5), so a figure a filing presents unmoved beside recast ones is
    presumed on the new basis, untouched by the change. Calling such periods "before" added 23
    notes on 14 real series, most on figures first reported after the change took effect
    (Coca-Cola's FY2019Q2, Procter & Gamble's FY2014Q2; see
    docs/designs/backlog-331-refiled-unchanged.md)."""
    if fact.derived:
        dates = [filed_at[a] for a in fact.inputs if a in filed_at] or [fact.filed_at]
        later = [d >= recast.filed_at for d in dates]
        return "after" if all(later) else "before" if not any(later) else "mixed"
    dates = versions.get((fact.period_start, fact.period_end, fact.xbrl_concept), [fact.filed_at])
    return "after" if dates[-1] >= recast.filed_at else "before"


@dataclass(frozen=True)
class AnnualComparison:
    """A 10-K's current fiscal year against the prior year, both as reported in that filing."""

    fiscal_year: int
    current: Fact
    prior: Fact

    @property
    def growth(self) -> float:
        return self.current.value / self.prior.value - 1


def same_filing_annual_comparisons(
    conn: sqlite3.Connection, cik: str, canonical_name: str, as_of: date | str
) -> list[AnnualComparison]:
    """Year-on-year pairs from each annual report, newest fiscal year first.

    Both years come from one filing (its best tag for each), so each pair sits on one restatement
    basis: growth isn't distorted by a restated year next to an unrestated one. An amended 10-K
    replaces the original for its fiscal year.
    """
    by_filing: dict[str, dict[tuple, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for (_name, start, end), filings in _rows_by_period(conn, cik, [canonical_name], as_of).items():
        for accn, rows in filings.items():
            if rows[0]["form"].startswith("10-K") and rows[0]["fiscal_period"] == "FY" and start:
                by_filing[accn][(start, end)].extend(rows)

    newest: dict[int, tuple[str, AnnualComparison]] = {}
    for accn, periods in by_filing.items():
        rows = sorted((_best_in_filing(r) for r in periods.values()), key=lambda r: r["period_end"])
        if len(rows) < 2 or rows[-1]["fiscal_year"] != rows[-2]["fiscal_year"] + 1:
            continue
        pair = AnnualComparison(
            rows[-1]["fiscal_year"], _to_fact(rows[-1], False), _to_fact(rows[-2], False)
        )
        filed = (rows[-1]["filed_at"], accn)
        if pair.fiscal_year not in newest or filed > newest[pair.fiscal_year][0]:
            newest[pair.fiscal_year] = (filed, pair)
    return [newest[y][1] for y in sorted(newest, reverse=True)]


# -- quarterly and annual views ---------------------------------------------------------------


def _derive(minuend: Fact, subtrahends: list[Fact], fiscal_period: str) -> Fact:
    """minuend − sum(subtrahends), e.g. Q4 = FY − M9. Public only once every input is."""
    inputs = [minuend, *subtrahends]
    restated = [f.restated for f in inputs]
    tags = list(dict.fromkeys(f.xbrl_concept for f in inputs))
    return Fact(
        canonical_name=minuend.canonical_name,
        xbrl_concept=" − ".join(tags),
        period_start=max(f.period_end for f in subtrahends) + timedelta(days=1),
        period_end=minuend.period_end,
        fiscal_year=minuend.fiscal_year,
        fiscal_period=fiscal_period,
        value=minuend.value - sum(f.value for f in subtrahends),
        unit=minuend.unit,
        filed_at=max(f.filed_at for f in inputs),
        restated=any(restated),
        derived=True,
        inputs=list(dict.fromkeys(a for f in inputs for a in (f.inputs or [f.accession_no]))),
        mixed_vintage=any(restated) and not all(restated),
    )


# Which periods make a quarter, in the order they are tried: minuend, then what is subtracted.
DERIVATIONS = {
    "Q2": [("H1", ["Q1"])],
    "Q3": [("M9", ["H1"]), ("M9", ["Q1", "Q2"])],
    "Q4": [("FY", ["M9"]), ("FY", ["Q1", "Q2", "Q3"])],
}

Ranks = dict[tuple[str, str], int]  # (item, tag) -> the concept map's priority, 1 first


def _ranks(conn: sqlite3.Connection, canonical_names: list[str]) -> Ranks:
    if not canonical_names:
        return {}
    sql = "SELECT canonical_name, xbrl_concept, priority FROM concepts WHERE canonical_name IN ({})"
    rows = conn.execute(sql.format(", ".join("?" * len(canonical_names))), canonical_names)
    return {(r[0], r[1]): r[2] for r in rows}


@dataclass(frozen=True)
class _YearTag:
    """What `_on_year_tag` found for one reported quarter: move it (`kept` None), or keep it on
    its own tag because that tag disagrees with its year (`kept`, backlog #336)."""

    minuend: Fact
    subtracted: list[Fact]
    kept: OwnTagCheck | None = None


def _on_year_tag(
    year: dict[str, Fact],
    period: str,
    ranks: Ranks,
    tagged: dict[tuple, list[dict[str, Fact]]] | None = None,
) -> _YearTag | None:
    """The inputs to derive a reported quarter from instead, when its filing gave it only under a
    tag ranked below the one tag its year and the periods before it share (backlog #324).

    Walmart's 10-Ks of 2011 and 2012 tag the fourth quarter only as net sales (SalesRevenueNet),
    while the year and every 10-Q use total revenues (Revenues): the year less the nine months
    keeps the quarter on the line of the others. Only reported inputs count, tried in the order
    the derivation itself uses (`DERIVATIONS`); None when the first complete set mixes tags or
    its tag does not rank above the quarter's.

    With `tagged` (every filing's value under each tag), the quarter's own tag is checked too
    (backlog #329, `_own_tag_check`): when the same subtraction on the quarter's tag does not
    come within `RECAST_MOVE` of the reported quarter, the quarter or an input was revised on
    that tag (the check cannot tell which), so the two tags no longer sit on one basis and the
    reported quarter is kept: the result carries `kept` (backlog #336), so the line can say
    why."""
    own = year[period]
    for minuend, subtracted in DERIVATIONS[period]:
        if minuend in year and all(p in year for p in subtracted):
            inputs = [year[minuend], *(year[p] for p in subtracted)]
            tags = {f.xbrl_concept for f in inputs}
            if len(tags) != 1:
                return None
            item = own.canonical_name
            rank = ranks.get((item, next(iter(tags))))
            own_rank = ranks.get((item, own.xbrl_concept))
            if rank is None or own_rank is None or rank >= own_rank:
                return None
            kept = _own_tag_check(own, inputs, tagged) if tagged is not None else None
            return _YearTag(inputs[0], inputs[1:], kept)
    return None


def _own_tag_check(
    own: Fact, inputs: list[Fact], tagged: dict[tuple, list[dict[str, Fact]]]
) -> OwnTagCheck | None:
    """None when the derivation on the quarter's own tag matches the reported quarter, or cannot
    be checked; otherwise what disagreed (backlog #329, #336).

    Two pairings are tried. First each input is read from the filing that gave it (#329). In
    latest mode those can be different years' filings (Walmart's FY2010Q4: the year from the
    10-K of 2012-03-27, the nine months from the 10-Q of 2009-12-08, the quarter from the 10-K of
    2011-03-30), so a recast of the own tag in between could fail it although the quarter is
    right. So, second, each input the quarter's own filing also gives under its tag is read from
    there instead, the others still from their own filings (backlog #336): the quarter and its
    year side by side in one filing share a basis. The check passes when either pairing agrees.
    With any input missing from its own filing under the quarter's tag, there is no check."""
    first = _narrow_inputs(own, inputs, tagged, prefer=None)
    if first is None:
        return None
    if _agrees(own, first):
        return None
    second = _narrow_inputs(own, inputs, tagged, prefer=own.accession_no)
    if second is not None and _agrees(own, second):
        return None
    derived = inputs[0].value - sum(f.value for f in inputs[1:])
    on_own_tag = first[0].value - sum(f.value for f in first[1:])
    on_own_filing = second[0].value - sum(f.value for f in second[1:]) if second else None
    return OwnTagCheck(
        year_tag=inputs[0].xbrl_concept,
        on_year_tag=derived,
        on_own_tag=on_own_tag,
        inputs=[f.accession_no for f in first],
        minuend=inputs[0].fiscal_period,
        # both figures when they differ, so a reader can tell whether the quarter or an input
        # moved (analyst, #336)
        on_own_filing=on_own_filing if on_own_filing != on_own_tag else None,
    )


def _narrow_inputs(
    own: Fact,
    inputs: list[Fact],
    tagged: dict[tuple, list[dict[str, Fact]]],
    prefer: str | None,
) -> list[Fact] | None:
    """Each input under the quarter's own tag, from the filing that gave it, or from `prefer`
    (an accession) when that filing gives it too; None when an input's own filing lacks the tag."""
    narrow = []
    for fact in inputs:
        key = (fact.canonical_name, fact.period_start, fact.period_end)
        filings = [rows for rows in tagged.get(key, []) if own.xbrl_concept in rows]
        same = [
            rows[own.xbrl_concept]
            for rows in filings
            if any(f.accession_no == fact.accession_no for f in rows.values())
        ]
        if not same:
            return None
        preferred = [
            rows[own.xbrl_concept]
            for rows in filings
            if prefer is not None and any(f.accession_no == prefer for f in rows.values())
        ]
        narrow.append((preferred or same)[-1])
    return narrow


def _agrees(own: Fact, narrow: list[Fact]) -> bool:
    derived = narrow[0].value - sum(f.value for f in narrow[1:])
    # A share of the quarter, but never of less than a quarter of the minuend (the year for Q4,
    # the six or nine months for Q2 and Q3): a quarter near zero (tax, other income) would
    # otherwise fail on rounding alone (analyst, #329).
    scale = max(abs(own.value), abs(narrow[0].value) / 4)
    return abs(derived - own.value) <= RECAST_MOVE * scale


def _quarters_for_flow(
    year: dict[str, Fact],
    earliest: bool = False,
    basis: "_Basis | None" = None,
    ranks: Ranks | None = None,
    tagged: dict[tuple, list[dict[str, Fact]]] | None = None,
) -> list[Fact]:
    """Standalone Q1-Q4 for one fiscal year of a duration item, reported where possible.

    With `earliest` (first_reported mode), a quarter reported on its own only in a later filing
    (e.g. a Q4 recast in the next 10-K) gives way to its derivation if that was public first.
    With `basis` (latest mode, backlog #264), a derivation from restated inputs is put on one
    basis (`_Basis.place`). With `ranks`, a quarter its filing gave only under a narrower tag than
    its year's is derived on the year's tag instead (backlog #324, `_on_year_tag`), unless
    `tagged` shows the quarter's own tag no longer agrees with its year (backlog #329).
    """
    q = {p: year[p] for p in ("Q1", "Q2", "Q3", "Q4") if p in year}

    def place(period: str, minuend: str, subtrahends: list[Fact]) -> None:
        derived = _derive(year[minuend], subtrahends, period)
        if basis is not None:
            derived = basis.place(derived, year[minuend], subtrahends)
        if period not in q or (earliest and derived.filed_at < q[period].filed_at):
            q[period] = derived

    if year and next(iter(year.values())).unit in DERIVABLE_UNITS:
        if (earliest or "Q2" not in q) and {"H1", "Q1"} <= year.keys():
            place("Q2", "H1", [q["Q1"]])
        if (earliest or "Q3" not in q) and "M9" in year:
            if "H1" in year:
                place("Q3", "M9", [year["H1"]])
            elif {"Q1", "Q2"} <= q.keys():
                place("Q3", "M9", [q["Q1"], q["Q2"]])
        if (earliest or "Q4" not in q) and "FY" in year:
            if "M9" in year:
                place("Q4", "FY", [year["M9"]])
            elif {"Q1", "Q2", "Q3"} <= q.keys():
                place("Q4", "FY", [q["Q1"], q["Q2"], q["Q3"]])
        for period in ("Q2", "Q3", "Q4") if ranks else ():
            if period not in year or q.get(period) is not year[period]:
                continue  # not reported, or already derived
            on_year_tag = _on_year_tag(year, period, ranks, tagged)
            if on_year_tag is not None and on_year_tag.kept is not None:
                q[period] = year[period].model_copy(update={"kept_on_own_tag": on_year_tag.kept})
            elif on_year_tag is not None:
                minuend, subtracted = on_year_tag.minuend, on_year_tag.subtracted
                derived = _derive(minuend, subtracted, period)
                if basis is not None:
                    derived = basis.place(derived, minuend, subtracted)
                q[period] = derived.model_copy(update={"narrower_tag": year[period].xbrl_concept})
    return [q[p] for p in ("Q1", "Q2", "Q3", "Q4") if p in q]


def _one_per_period(facts: list[Fact]) -> list[Fact]:
    """One fact per (item, fiscal year, fiscal period); unplaced facts are dropped.

    Two dated facts can share a label: an amended filing's cover page repeats shares outstanding
    under a later date, and rarely two balance-sheet dates fall in one period. The later one wins.
    """
    best: dict[tuple, Fact] = {}
    for fact in facts:
        if fact.fiscal_year is None:
            continue  # periods that couldn't be placed in the fiscal calendar
        key = (fact.canonical_name, fact.fiscal_year, fact.fiscal_period, fact.period_start is None)
        if key not in best or fact.period_end > best[key].period_end:
            best[key] = fact
    return list(best.values())


def _flow_years(facts: list[Fact]) -> tuple[list[Fact], dict[tuple, dict[str, Fact]]]:
    """Balance-sheet facts (the Q4 balance is the year-end one), and duration facts by
    (item, fiscal year) and fiscal period."""
    years: dict[tuple, dict[str, Fact]] = defaultdict(dict)
    instants = []
    for fact in _one_per_period(facts):
        if fact.period_start is None:
            if fact.fiscal_period == "FY":
                fact = fact.model_copy(update={"fiscal_period": "Q4"})
            instants.append(fact)
        else:
            years[(fact.canonical_name, fact.fiscal_year)][fact.fiscal_period] = fact
    return instants, years


@dataclass(frozen=True)
class _Basis:
    """Puts a derived quarter on one basis (backlog #264).

    A derivation is year (or half, or nine months) minus the periods before it, each input its
    newest version. When no input was ever restated, all are as first filed: one basis, kept.
    When some were, the newest versions can come from filings on different bases: the year from
    the old 10-K and the nine months recast in a later 10-Q (JNJ FY2022Q4 after Kenvue), or the
    year recast twice and the nine months once (KO's FY2017 operating income). Then the minuend
    is taken as the first filing at or after the newest subtracted input's vintage gave it (the
    10-K that follows the recast 10-Q, on that 10-Q's basis; an input's vintage is the first
    filing of its value, `_vintage`); a version with the opposite sign to the newest is a tagging
    error a later filing corrected, and is skipped. If no such filing is public yet,
    the quarter is derived from every input as first filed (the old year with the old nine
    months), which shares one basis and was public earlier, unless the year as first filed has the
    wrong sign (then the plain derivation is kept). Either way it is flagged
    `one_basis` when its value differs from the plain derivation."""

    versions: dict[tuple, list[Fact]]  # (item, start, end) -> each filing's best tag, oldest first
    first: dict[str, Fact]  # this item-year's quarters as first reported, by fiscal period
    # (item, start, end) -> each filing's value under every tag it used, oldest filing first
    tagged: dict[tuple, list[dict[str, Fact]]] = field(default_factory=dict)

    def place(self, derived: Fact, minuend: Fact, subtrahends: list[Fact]) -> Fact:
        if not derived.restated:
            return derived
        newest = max(self._vintage(f) for f in subtrahends)
        versions = self._paired_tag(minuend, subtrahends)
        # a version of the opposite sign to the newest is a tagging error a later filing
        # corrected (WMT's FY2009 and FY2010 tax, negative in one 10-K), not a basis: skipped
        later = [v for v in versions if v.filed_at >= newest and v.value * minuend.value >= 0]
        if later:
            paired = _derive(later[0], subtrahends, derived.fiscal_period)
        elif versions and versions[0].value * minuend.value < 0:
            return derived  # the year as first filed has the wrong sign: no fallback
        else:
            paired = self.first.get(derived.fiscal_period)
            if paired is None or not paired.derived:
                return derived  # no first-filed derivation of this quarter: kept as it is
        if paired.value == derived.value:
            return derived
        return paired.model_copy(update={"one_basis": True})

    def _of(self, fact: Fact) -> list[Fact]:
        return self.versions.get((fact.canonical_name, fact.period_start, fact.period_end), [])

    def _paired_tag(self, minuend: Fact, subtrahends: list[Fact]) -> list[Fact]:
        """Each filing's version of the minuend, under the tag the subtracted periods use when
        that filing gives it (backlog #290): a filing whose best tag differs from the nine
        months' tag is a change of tag, not of basis. Apple's 2017 10-K gives FY2017 D&A as
        10,157 (the cash-flow tag the 10-Qs use) and 8,200 (a tag ranked higher, depreciation
        alone); the year less the nine months is 2,484, not 527."""
        tags = {f.xbrl_concept for f in subtrahends if not f.derived}
        best = self._of(minuend)
        if len(tags) != 1 or any(f.derived for f in subtrahends):
            return best
        (tag,) = tags
        key = (minuend.canonical_name, minuend.period_start, minuend.period_end)
        by_filing = self.tagged.get(key, [])
        if len(by_filing) != len(best):
            return best
        return [rows.get(tag, b) for rows, b in zip(by_filing, best, strict=True)]

    def _vintage(self, fact: Fact) -> date:
        """When a subtracted input's value was first filed: a later 10-Q that only repeats last
        year's nine months doesn't move its basis (PG's FY2013 tax: 2,812 in both 10-Qs, the year
        recast for Pet Care in between). A derived input: when its last input was filed."""
        if fact.derived:
            return fact.filed_at
        same = [v.filed_at for v in self._of(fact) if v.value == fact.value]
        return min(same, default=fact.filed_at)


def _versions(periods: dict[tuple, dict[str, list[sqlite3.Row]]]) -> dict[tuple, list[Fact]]:
    """Every filing's version (its best tag) of each duration period, oldest filing first."""
    out = {}
    for (_name, start, _end), filings in periods.items():
        if start:
            facts = [_to_fact(_best_in_filing(filings[a]), False) for a in _filing_order(filings)]
            out[(facts[0].canonical_name, facts[0].period_start, facts[0].period_end)] = facts
    return out


def _tagged(periods: dict[tuple, dict[str, list[sqlite3.Row]]]) -> dict[tuple, list[dict]]:
    """Every filing's value of each duration period under each tag it used, oldest filing first
    (backlog #290), keyed as `_versions`."""
    out = {}
    for (_name, start, _end), filings in periods.items():
        if start:
            by_filing = [
                {r["xbrl_concept"]: _to_fact(r, False) for r in filings[a]}
                for a in _filing_order(filings)
            ]
            fact = next(iter(by_filing[0].values()))
            out[(fact.canonical_name, fact.period_start, fact.period_end)] = by_filing
    return out


def _quarterly(
    facts: list[Fact],
    earliest: bool = False,
    first_reported: list[Fact] | None = None,
    versions: dict[tuple, list[Fact]] | None = None,
    tagged: dict[tuple, list[dict[str, Fact]]] | None = None,
    ranks: Ranks | None = None,
) -> list[Fact]:
    """Standalone quarters. With `first_reported` (the same query's facts as first reported) and
    `versions`, a derived quarter is put on one basis (`_Basis`). With `ranks`, a quarter reported
    under a narrower tag than its year's is derived on the year's tag (backlog #324)."""
    quarters, years = _flow_years(facts)
    first_years = _flow_years(first_reported)[1] if first_reported is not None else None
    for key, year in years.items():
        basis = None
        if first_years is not None:
            first_year = first_years.get(key, {})
            first_quarters = _quarters_for_flow(first_year, ranks=ranks, tagged=tagged)
            first = {q.fiscal_period: q for q in first_quarters}
            basis = _Basis(versions or {}, first, tagged or {})
        quarters.extend(_quarters_for_flow(year, earliest, basis, ranks, tagged))
    return sorted(quarters, key=lambda f: (f.canonical_name, f.period_end))


def get_facts(
    conn: sqlite3.Connection,
    cik: str,
    canonical_names: list[str],
    as_of: date | str,
    mode: Mode = "latest",
    frequency: Frequency = "reported",
    one_basis: bool = False,
) -> list[Fact]:
    """Point-in-time facts.

    frequency="reported": every period as filed (Q1-Q4, H1, M9, FY).
    frequency="annual":   fiscal years only (FY durations and year-end balances).
    frequency="quarterly": standalone quarters Q1-Q4, deriving the ones not reported. In
                           first_reported mode each quarter is the version public first.
                           With `one_basis` (latest mode), a quarter derived from restated
                           inputs is put on one basis (backlog #264; `_Basis`, `Fact.one_basis`).
                           A quarter its filing gave only under a narrower tag than its year's
                           is derived on the year's tag (backlog #324, `Fact.narrower_tag`).
    """
    if one_basis and (mode != "latest" or frequency != "quarterly"):
        raise ValueError("one_basis applies to latest quarterly facts only")
    if mode not in ("latest", "first_reported"):
        raise ValueError(f"Unknown mode: {mode!r}")
    periods = _rows_by_period(conn, cik, canonical_names, as_of)
    facts = _facts(periods, mode)
    if frequency == "reported":
        return facts
    if frequency == "annual":
        annual = _one_per_period([f for f in facts if f.fiscal_period == "FY"])
        return sorted(annual, key=lambda f: (f.canonical_name, f.period_end))
    if frequency == "quarterly":
        ranks = _ranks(conn, canonical_names)
        tagged = _tagged(periods)
        if not one_basis:
            earliest = mode == "first_reported"
            return _quarterly(facts, earliest=earliest, tagged=tagged, ranks=ranks)
        first = _facts(periods, "first_reported")
        return _quarterly(
            facts,
            first_reported=first,
            versions=_versions(periods),
            tagged=tagged,
            ranks=ranks,
        )
    raise ValueError(f"Unknown frequency: {frequency!r}")
