"""Data-quality report: which canonical items each company has, from which tags, and every gap.

A gap is a missing quarter or fiscal year in FY2016-FY2025. It is *explained* when known_gaps.csv
gives a reason (or when it is a weighted-average shares Q4, which can't be derived); anything else
is *unexplained*, and the M1 exit criterion requires none. Only required items are checked:
optional items (fallbacks, and holdings a company may not have) are not part of this report; a run
that uses one records it in its assumptions.
"""

import csv
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path

from domains.fundamentals.concepts import concept_map_sha256, load_concept_map
from domains.fundamentals.facts import (
    DERIVABLE_UNITS,
    MeaningChange,
    get_facts,
    newest_filing_disagreements,
    skipped_parts_as_whole,
    skipped_sign_flips,
    tag_meaning_changes,
)
from domains.fundamentals.schemas import MINUEND_WORDS, Fact
from domains.fundamentals.universe import FISCAL_YEARS
from shared_kernel.calendar import last_ended_day

KNOWN_GAPS_PATH = Path(__file__).parent / "known_gaps.csv"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
PERIODS = ("Q1", "Q2", "Q3", "Q4", "FY")
NON_ADDITIVE_REASON = "Q4 not reported; weighted-average shares can't be derived (not additive)."
# Quarters of a flow should add up to its fiscal year; beyond this they come from different bases.
CONSISTENCY_TOLERANCE = 0.005
AUDIT_EXAMPLES = 4  # periods listed per group in the newest-filing audit


@dataclass(frozen=True)
class KnownGap:
    ticker: str
    canonical_name: str
    fiscal_years: str  # '*', '2019' or '2016-2018'
    periods: str  # '*' or 'Q4' or 'Q1;Q2'
    reason: str

    def covers(self, ticker: str, name: str, fiscal_year: int, period: str) -> bool:
        if self.ticker != ticker or self.canonical_name not in ("*", name):
            return False
        if self.periods != "*" and period not in self.periods.split(";"):
            return False
        if self.fiscal_years == "*":
            return True
        first, _, last = self.fiscal_years.partition("-")
        return int(first) <= fiscal_year <= int(last or first)


def load_known_gaps(path: Path = KNOWN_GAPS_PATH) -> list[KnownGap]:
    gaps = []
    with open(path, newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            if None in row or None in row.values():
                raise ValueError(f"{path.name} line {line}: wrong number of fields (quote commas)")
            gaps.append(KnownGap(**{k: v.strip() for k, v in row.items()}))
    return gaps


@dataclass(frozen=True)
class Gap:
    canonical_name: str
    fiscal_year: int
    period: str
    reason: str | None  # None = unexplained


@dataclass(frozen=True)
class Inconsistency:
    """A flow whose four quarters don't add up to its fiscal year (mixed restatement vintages)."""

    canonical_name: str
    fiscal_year: int
    quarters_total: float
    fiscal_year_value: float
    restated: tuple[str, ...]  # which of Q1-Q4 and FY are restated values


@dataclass
class QualityReport:
    ticker: str
    cik: str
    name: str
    as_of: date
    cells: dict[tuple[str, int, str], Fact] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    tags_by_year: dict[str, dict[int, str]] = field(default_factory=dict)
    restated: Counter = field(default_factory=Counter)
    derived: Counter = field(default_factory=Counter)
    mixed_vintage: list[Fact] = field(default_factory=list)
    canonical_names: list[str] = field(default_factory=list)
    inconsistencies: list[Inconsistency] = field(default_factory=list)
    last_ingest: dict | None = None  # the latest ingest_runs row: what data the facts came from
    concept_map_changed: bool = False  # concept_map.csv edited since that ingest
    gap_links: dict[tuple[str, int, str], str] = field(default_factory=dict)  # [inferred] gaps
    # (selected, newest filing's value) where they differ: the standing tag-change audit
    disagreements: list[tuple[Fact, Fact]] = field(default_factory=list)
    # (selected, skipped) versions skipped as sign-tagging errors (backlog #280)
    sign_flips: list[tuple[Fact, Fact]] = field(default_factory=list)
    # (selected, skipped) parts a filing tagged as the whole (backlog #322)
    parts_as_whole: list[tuple[Fact, Fact]] = field(default_factory=list)
    # tags whose meaning changed in a later filing (backlog #295): flagged, values unchanged
    meaning_changes: list[MeaningChange] = field(default_factory=list)
    # quarters kept on a lower-ranked tag than their year's, as that tag disagrees (backlog #336)
    kept_on_own_tag: list[Fact] = field(default_factory=list)

    @property
    def unexplained(self) -> list[Gap]:
        return [g for g in self.gaps if g.reason is None]

    @property
    def explained(self) -> list[Gap]:
        return [g for g in self.gaps if g.reason is not None]

    def to_markdown(self) -> str:
        years = list(FISCAL_YEARS)
        gap_at = {(g.canonical_name, g.fiscal_year, g.period): g for g in self.gaps}

        def cell(name: str, year: int) -> str:
            out = []
            for period in PERIODS:
                fact = self.cells.get((name, year, period))
                if fact is not None:
                    out.append("d" if fact.derived else "R")
                else:
                    out.append("!" if gap_at[(name, year, period)].reason is None else "e")
            return "`" + "".join(out) + "`"

        lines = [
            f"# Data quality: {self.ticker}",
            "",
            f"{self.name} · CIK {self.cik} · facts as known on {self.as_of.isoformat()} · "
            f"FY{years[0]}–FY{years[-1]}",
            "",
            self._provenance_line(),
            "",
            "## Summary",
            "",
            f"- Canonical items found: {sum(1 for n in self.canonical_names if self._found(n))}"
            f" of {len(self.canonical_names)}",
            f"- **Unexplained gaps: {len(self.unexplained)}** · explained gaps: "
            f"{len(self.explained)}",
            f"- Restated values in use: {sum(self.restated.values())} · derived quarters: "
            f"{sum(self.derived.values())} · derived from mixed restatement vintages: "
            f"{len(self.mixed_vintage)}",
            f"- Fiscal years whose quarters don't add up to the full year: "
            f"{len(self.inconsistencies)} (informational; see below)",
            f"- Periods where the newest filing disagrees with the selected value: "
            f"{len(self.disagreements)} (informational; see below)",
            f"- Versions skipped as sign-tagging errors: {len(self.sign_flips)} (see below)",
            f"- Parts skipped as tagged as the whole: {len(self.parts_as_whole)} (see below)",
            f"- Tags that changed meaning in a later filing: {len(self.meaning_changes)} "
            "(informational; see below)",
            "",
            "## Coverage",
            "",
            "Each cell is Q1 Q2 Q3 Q4 FY: `R` reported, `d` derived, `e` explained gap, "
            "`!` unexplained gap. Required items only.",
            "",
            "| Item | " + " | ".join(f"FY{y}" for y in years) + " |",
            "|---|" + "---|" * len(years),
        ]
        for name in self.canonical_names:
            lines.append(f"| {name} | " + " | ".join(cell(name, y) for y in years) + " |")

        lines += ["", "## Tags used", ""]
        for name in self.canonical_names:
            lines.append(f"- **{name}**: {self._tag_runs(name) or 'none found'}")

        lines += ["", "## Unexplained gaps", ""]
        lines += self._gap_lines(self.unexplained) or ["None."]
        lines += ["", "## Explained gaps", ""]
        lines += self._gap_lines(self.explained, with_reason=True) or ["None."]

        lines += ["", "## Restatements and derivations", ""]
        for name in self.canonical_names:
            if self.restated[name] or self.derived[name]:
                lines.append(
                    f"- {name}: {self.restated[name]} restated, {self.derived[name]} derived"
                )
        for fact in self.mixed_vintage:
            lines.append(
                f"- Mixed vintage: {fact.canonical_name} FY{fact.fiscal_year} "
                f"{fact.fiscal_period} (inputs {', '.join(fact.inputs)})"
            )

        lines += [
            "",
            "## Quarters vs full year",
            "",
            "Flows whose Q1-Q4 differ from the fiscal year by more than "
            f"{CONSISTENCY_TOLERANCE:.1%}. Usually a restated year next to quarters that were never"
            " restated, so growth rates"
            " across these periods compare different bases.",
            "",
        ]
        if not self.inconsistencies:
            lines.append("None.")
        for i in self.inconsistencies:
            share = (i.quarters_total - i.fiscal_year_value) / abs(i.fiscal_year_value)
            lines.append(
                f"- **{i.canonical_name}** FY{i.fiscal_year}: quarters "
                f"{i.quarters_total / 1e6:,.0f}M vs year {i.fiscal_year_value / 1e6:,.0f}M "
                f"({share:+.1%}); "
                f"restated: {', '.join(i.restated) or 'none'}"
            )

        lines += [
            "",
            "## Newest filing disagrees with the selected value",
            "",
            "Periods where the newest filing reports a different value, only under a lower-ranked "
            "tag. Usually a different measure (correctly ignored); a restatement filed only under "
            "that tag would be missed by the selection rule, so check any new group after a "
            "concept-map edit.",
            "",
        ]
        lines += self._disagreement_lines() or ["None."]
        lines += [
            "",
            "## Versions skipped as sign-tagging errors",
            "",
            "A filing's version of a period whose sign is flipped against another version of "
            "nearly the same size, on the side fewer versions take (or, on a tie, against the "
            "item's usual sign for the company). The newest version with the right sign is used.",
            "",
        ]
        lines += [
            f"- **{s.canonical_name}** {s.period_start} to {s.period_end}: used "
            f"{_amount(s)} ({s.accession_no}), skipped {_amount(k)} ({k.accession_no})"
            for s, k in self.sign_flips
        ] or ["None."]

        lines += [
            "",
            "## Parts skipped as tagged as the whole",
            "",
            "A filing's figure under its best-ranked tag of an item, when the same filing gives "
            "the same item and period under another tag, with the same sign, at more than twice "
            "the size: a part (a segment, a line) tagged as the whole. The next tag that filing "
            "used is read instead.",
            "",
        ]
        lines += [
            f"- **{s.canonical_name}** {s.period_start} to {s.period_end}: used "
            f"{_amount(s)} ({s.xbrl_concept}, {s.accession_no}), skipped {_amount(k)} "
            f"({k.xbrl_concept}, {k.accession_no})"
            for s, k in self.parts_as_whole
        ] or ["None."]

        lines += [
            "",
            "## Tags that changed meaning",
            "",
            "A filing gives a tag a new value for periods filed before, and repeats the old value "
            "under another tag of the same item: the two values measure different lines, so the "
            "change is not a restatement. Values are kept as the selection rule gives them; "
            "growth across the change compares two meanings, and the reported view says so on "
            "growth and on the line.",
            "",
        ]
        for m in self.meaning_changes:
            examples = ", ".join(
                f"{end} {old / 1e6:,.0f}M to {new / 1e6:,.0f}M"
                for _start, end, old, new in m.periods[:AUDIT_EXAMPLES]
            )
            more = len(m.periods) - AUDIT_EXAMPLES
            lines.append(
                f"- **{m.canonical_name}**: {m.xbrl_concept.split(':', 1)[1]} from the {m.form} "
                f"filed {m.filed_at} ({m.accession_no}); old values under "
                f"{m.other_concept.split(':', 1)[1]}; {len(m.periods)} periods: {examples}"
                + (f", +{more} more" if more > 0 else "")
            )
        if not self.meaning_changes:
            lines.append("None.")

        lines += [
            "",
            "## Quarters kept on a lower-ranked tag",
            "",
            "A quarter its filing gives only under a tag ranked below the one tag of its year and "
            "the periods before it is normally worked out on the year's tag. When the same "
            "subtraction on the quarter's own tag does not give the quarter (the quarter or an "
            "input was revised on that tag), it is kept as filed: the four quarters then measure "
            "two lines.",
            "",
        ]
        lines += [_kept_line(f) for f in self.kept_on_own_tag] or ["None."]
        return "\n".join(lines) + "\n"

    def _disagreement_lines(self) -> list[str]:
        groups: dict[tuple, list[tuple[Fact, Fact]]] = defaultdict(list)
        for selected, newest in self.disagreements:
            key = (selected.canonical_name, selected.xbrl_concept, newest.xbrl_concept)
            groups[key].append((selected, newest))
        lines = []
        for (name, selected_tag, newest_tag), pairs in groups.items():
            examples = ", ".join(
                f"{s.period_end} {s.value / 1e6:,.0f}M vs {n.value / 1e6:,.0f}M"
                for s, n in pairs[:AUDIT_EXAMPLES]
            )
            more = f", +{len(pairs) - AUDIT_EXAMPLES} more" if len(pairs) > AUDIT_EXAMPLES else ""
            lines.append(
                f"- **{name}** ({len(pairs)}): selected {selected_tag.split(':', 1)[1]}, newest "
                f"filing {newest_tag.split(':', 1)[1]}: {examples}{more}"
            )
        return lines

    def _provenance_line(self) -> str:
        run = self.last_ingest
        if run is None:
            return "Data: no ingest run recorded."
        line = (
            f"Data: company facts `{run['companyfacts_sha256'][:12]}` fetched "
            f"{run['companyfacts_fetched_at'] or 'at an unrecorded time'}; concept map "
            f"`{run['concept_map_sha256'][:12]}`; ingested {run['ingested_at']}."
        )
        if self.concept_map_changed:
            line += " **Warning: concept_map.csv changed since this ingest; re-run ingest.**"
        return line

    def _found(self, name: str) -> bool:
        return any(key[0] == name for key in self.cells)

    def _tag_runs(self, name: str) -> str:
        """'SalesRevenueNet FY2016–FY2017 → Revenues FY2018–FY2025'."""
        runs: list[list] = []
        for year, tag in sorted(self.tags_by_year.get(name, {}).items()):
            if runs and runs[-1][0] == tag and runs[-1][2] == year - 1:
                runs[-1][2] = year
            else:
                runs.append([tag, year, year])
        return " → ".join(
            f"{tag.split(':', 1)[1]} FY{a}" + (f"–FY{b}" if b != a else "") for tag, a, b in runs
        )

    def _gap_lines(self, gaps: list[Gap], with_reason: bool = False) -> list[str]:
        grouped: dict[tuple, list[str]] = defaultdict(list)
        for g in gaps:
            where = f"FY{g.fiscal_year} {g.period}"
            link = self.gap_links.get((g.canonical_name, g.fiscal_year, g.period))
            grouped[(g.canonical_name, g.reason)].append(
                f"{where} ([check]({link}))" if link else where
            )
        lines = []
        for (name, reason), where in grouped.items():
            line = f"- **{name}** ({len(where)}): {', '.join(where)}"
            lines.append(line + (f". *{reason}*" if with_reason else ""))
        return lines


def build_report(
    conn: sqlite3.Connection,
    ticker: str,
    as_of: date | None = None,
    known_gaps: list[KnownGap] | None = None,
) -> QualityReport:
    company = conn.execute("SELECT * FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
    if company is None:
        raise ValueError(f"{ticker} has not been ingested")
    as_of = as_of or last_ended_day(datetime.now(UTC))
    known_gaps = load_known_gaps() if known_gaps is None else known_gaps
    concepts = [c for c in load_concept_map() if c.gate == "required"]
    names = list(dict.fromkeys(c.canonical_name for c in concepts))
    unit_of = {c.canonical_name: c.unit for c in concepts}
    flows = {c.canonical_name for c in concepts if c.period_type == "duration"}

    report = QualityReport(
        ticker=company["ticker"],
        cik=company["cik"],
        name=company["name"],
        as_of=as_of,
        canonical_names=names,
    )
    years = set(FISCAL_YEARS)
    quarterly = get_facts(conn, company["cik"], names, as_of, frequency="quarterly")
    annual = get_facts(conn, company["cik"], names, as_of, frequency="annual")
    for fact in quarterly + annual:
        if fact.fiscal_year in years:
            report.cells[(fact.canonical_name, fact.fiscal_year, fact.fiscal_period)] = fact
    for fact in annual:
        if fact.fiscal_year in years:
            report.tags_by_year.setdefault(fact.canonical_name, {})[fact.fiscal_year] = (
                fact.xbrl_concept
            )

    report.kept_on_own_tag = sorted(
        (f for f in report.cells.values() if f.kept_on_own_tag is not None),
        key=lambda f: (f.canonical_name, f.period_end),
    )
    for (name, _year, _period), fact in report.cells.items():
        if fact.derived:
            report.derived[name] += 1
            if fact.mixed_vintage:
                report.mixed_vintage.append(fact)
        elif fact.restated:
            report.restated[name] += 1

    for name in names:
        for year in FISCAL_YEARS:
            for period in PERIODS:
                if (name, year, period) in report.cells:
                    continue
                reason = next(
                    (g.reason for g in known_gaps if g.covers(report.ticker, name, year, period)),
                    None,
                )
                if (
                    reason is None
                    and period == "Q4"
                    and unit_of[name] not in DERIVABLE_UNITS
                    and (name, year, "FY") in report.cells
                ):
                    reason = NON_ADDITIVE_REASON
                report.gaps.append(Gap(name, year, period, reason))

    for name in names:
        if name not in flows or unit_of[name] not in DERIVABLE_UNITS:
            continue
        for year in FISCAL_YEARS:
            facts = [report.cells.get((name, year, period)) for period in PERIODS]
            if any(f is None for f in facts) or facts[-1].value == 0:
                continue
            total = sum(f.value for f in facts[:-1])
            if abs(total - facts[-1].value) / abs(facts[-1].value) > CONSISTENCY_TOLERANCE:
                restated = tuple(p for p, f in zip(PERIODS, facts, strict=True) if f.restated)
                report.inconsistencies.append(
                    Inconsistency(name, year, total, facts[-1].value, restated)
                )

    report.disagreements = [
        (selected, newest)
        for selected, newest in newest_filing_disagreements(conn, company["cik"], names, as_of)
        if selected.fiscal_year in years
    ]
    # every year, not only the report's: the flips seen so far are all from 2008-2011
    report.sign_flips = skipped_sign_flips(conn, company["cik"], names, as_of)
    report.parts_as_whole = skipped_parts_as_whole(conn, company["cik"], names, as_of)
    report.meaning_changes = _within_years(
        tag_meaning_changes(conn, company["cik"], names, as_of), report.cells
    )

    run = conn.execute(
        "SELECT * FROM ingest_runs WHERE cik = ? ORDER BY run_id DESC LIMIT 1", (company["cik"],)
    ).fetchone()
    if run is not None:
        report.last_ingest = dict(run)
        report.concept_map_changed = run["concept_map_sha256"] != concept_map_sha256()
    for gap in report.explained:
        if gap.reason.startswith("[inferred]"):
            link = _filing_link(conn, company["cik"], gap.fiscal_year, gap.period)
            if link:
                report.gap_links[(gap.canonical_name, gap.fiscal_year, gap.period)] = link
    return report


def _filing_link(conn: sqlite3.Connection, cik: str, fiscal_year: int, period: str) -> str | None:
    """EDGAR folder of the first filing that reported this fiscal period, to check a gap by hand."""
    periods = ("FY", "Q4") if period in ("FY", "Q4") else (period,)
    row = conn.execute(
        "SELECT accession_no FROM financial_facts WHERE cik = ? AND fiscal_year = ? "
        f"AND fiscal_period IN ({', '.join('?' * len(periods))}) AND form IN ('10-K', '10-Q') "
        "ORDER BY filed_at, accession_no LIMIT 1",
        (cik, fiscal_year, *periods),
    ).fetchone()
    if row is None:
        return None
    return f"{EDGAR_ARCHIVES}/{int(cik)}/{row[0].replace('-', '')}/"


def _kept_line(fact: Fact) -> str:
    """One quarter kept on its own lower-ranked tag (backlog #336)."""
    kept = fact.kept_on_own_tag

    def amount(value: float) -> str:
        return _amount(fact.model_copy(update={"value": value}))

    own_filing = (
        f", {amount(kept.on_own_filing)} from the quarter's own filing"
        if kept.on_own_filing is not None
        else ""
    )
    return (
        f"- **{fact.canonical_name}** FY{fact.fiscal_year} {fact.fiscal_period}: "
        f"{fact.xbrl_concept.split(':', 1)[1]} {_amount(fact)} ({fact.accession_no}); on its own "
        f"tag {MINUEND_WORDS.get(kept.minuend, kept.minuend)} less the earlier periods is "
        f"{amount(kept.on_own_tag)} "
        f"({', '.join(kept.inputs)}){own_filing}; on {kept.year_tag.split(':', 1)[1]} it would "
        f"be {amount(kept.on_year_tag)}"
    )


def _amount(fact: Fact) -> str:
    """A fact's value for the report: millions for money, as is for shares or per-share units."""
    if fact.unit == "USD":
        return f"{fact.value / 1e6:,.0f}M"
    return f"{fact.value:,g} {fact.unit}"


def _within_years(changes: list[MeaningChange], cells: dict) -> list[MeaningChange]:
    """Each change cut to the periods that end within the report's fiscal years (backlog #297,
    as `disagreements` are): from the earliest start to the latest end of the report's cells.
    A change with no period left is dropped; its filing date stays the first filing's."""
    if not cells:
        return []
    first = min(f.period_start or f.period_end for f in cells.values())
    last = max(f.period_end for f in cells.values())
    out = []
    for change in changes:
        periods = [p for p in change.periods if first <= p[1] <= last]
        if periods:
            out.append(replace(change, periods=periods))
    return out
