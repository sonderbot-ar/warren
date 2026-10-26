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
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from domains.fundamentals.concepts import concept_map_sha256, load_concept_map
from domains.fundamentals.facts import DERIVABLE_UNITS, get_facts, newest_filing_disagreements
from domains.fundamentals.schemas import Fact
from domains.fundamentals.universe import FISCAL_YEARS

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
    as_of = as_of or date.today()
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
