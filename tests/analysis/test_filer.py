"""Who filed a filing, when it is not the company's own CIK (backlog #586).

Since #573 Exxon's 10-Q and 10-K filed from 2026-08-03 come from its successor, ExxonMobil
Holdings Corp, and are read into the old CIK's history. Every filing the engine returns (the
#140 shape: a part's filing, a source's filing, a refusal's filings, the evidence filings) now
carries `filer`: the successor's CIK and name for such a filing, else None."""

import json
from dataclasses import asdict
from datetime import date

import pytest

from domains.analysis.math_engine import refusal_filings
from domains.analysis.reported import _Filings, reported_period, successor_filer
from domains.analysis.runs import run_baseline
from domains.analysis.sources import run_sources
from domains.fundamentals.universe import PHASE1_UNIVERSE, UniverseCompany
from tests.analysis.conftest import AS_OF, CHOICES

XOM_CIK = "0000034088"
EXXON_HOLDINGS = {
    "cik": "0002115436",
    "name": "ExxonMobil Holdings Corp",
    "successor": True,
    "since": "2026-08-03",
}
TST_CIK = "0000000123"
CUT = date(2020, 1, 1)  # the test company's made-up reorganisation
TST_10Q_2019Q3 = "0000000123-19-000014"  # filed 2019-10-30, before the cut
TST_10K_2019 = "0000000123-20-000015"  # filed 2020-02-15, after it
TST_10Q_2020Q1 = "0000000123-20-000016"  # filed 2020-04-30
PERIODS = ("FY2019", "FY2019Q3", "FY2020Q1")
SUCCESSOR = {
    "cik": "0000000999",
    "name": "Test Holdings Corp",
    "successor": True,
    "since": "2020-01-01",
}


@pytest.fixture
def linked_tst():
    """Test Corp as a linked company whose filings from 2020-01-01 are its successor's, in the
    shared universe list for one test (the list is the module's; restored afterwards)."""
    row = UniverseCompany(
        "TST", TST_CIK, "Test Corp before its made-up reorganisation.", CUT,
        "holding_company_reorganisation", SUCCESSOR["cik"], SUCCESSOR["name"], True,
    )  # fmt: skip
    PHASE1_UNIVERSE.append(row)
    try:
        yield row
    finally:
        PHASE1_UNIVERSE.remove(row)


def test_exxon_filings_from_the_cut_name_the_successor():
    assert successor_filer(XOM_CIK, date(2026, 8, 3)) == EXXON_HOLDINGS  # the joint Q2 10-Q
    assert successor_filer(XOM_CIK, date(2026, 11, 2)) == EXXON_HOLDINGS  # the Q3 10-Q


def test_exxon_filings_before_the_cut_and_other_companies_name_no_filer():
    assert successor_filer(XOM_CIK, date(2026, 8, 2)) is None
    assert successor_filer(XOM_CIK, date(2026, 5, 1)) is None
    assert successor_filer("0000320193", date(2026, 11, 2)) is None  # Apple: never linked
    assert successor_filer(XOM_CIK, None) is None  # an accession Warren never read


def test_an_unlinked_successor_names_no_filer(unlinked_xom):
    """Without the link the successor's filings are not read, so none is the successor's."""
    assert successor_filer(XOM_CIK, date(2026, 11, 2)) is None


def test_the_filing_shape_carries_the_filer(company, linked_tst):
    filings = _Filings(company, TST_CIK)
    assert filings.get(TST_10Q_2019Q3).filer is None
    assert filings.get(TST_10K_2019).filer == SUCCESSOR
    assert filings.get(TST_10Q_2020Q1).filer == SUCCESSOR
    assert filings.get("0000000123-99-999999").filer is None  # unknown: no date, no filer
    shaped = asdict(filings.get(TST_10K_2019))
    assert set(shaped) == {"accession_no", "form", "filed_at", "url", "filer"}
    # the link stays under the company's own CIK, where EDGAR serves the successor's filings too
    assert shaped["url"] == "https://www.sec.gov/Archives/edgar/data/123/000000012320000015/"


def test_an_unlinked_company_keeps_a_null_filer(company):
    filings = _Filings(company, TST_CIK)
    assert filings.get(TST_10Q_2020Q1).filer is None


def test_a_refusal_names_the_filer_and_survives_json(company, linked_tst):
    out = refusal_filings(company, TST_CIK, [TST_10Q_2019Q3, TST_10Q_2020Q1])
    assert [f["filer"] for f in out] == [None, SUCCESSOR]
    assert json.loads(json.dumps(out)) == out


def test_a_reported_period_names_the_filer_of_each_figure(company, linked_tst):
    """The answer behind brief Q1 and Q2: each line's newest filing says who filed it, and
    nothing else in the answer changes."""
    linked = {p: reported_period(company, "TST", p, AS_OF).to_dict() for p in PERIODS}
    seen = set()
    for answer in linked.values():
        for line in answer["lines"] + answer["prior_lines"]:
            for version in (line["latest"], line["first_reported"]):
                for filing in [version["filing"], *version["inputs"]]:
                    if filing is not None:
                        after = filing["filed_at"] >= CUT.isoformat()
                        assert filing["filer"] == (SUCCESSOR if after else None)
                        seen.add(after)
    assert seen == {True, False}  # both kinds were checked
    PHASE1_UNIVERSE.remove(linked_tst)
    try:
        plain = {p: reported_period(company, "TST", p, AS_OF).to_dict() for p in PERIODS}
    finally:
        PHASE1_UNIVERSE.append(linked_tst)

    def without_filer(value):
        if isinstance(value, dict):
            return {k: without_filer(v) for k, v in value.items() if k != "filer"}
        if isinstance(value, list):
            return [without_filer(v) for v in value]
        return value

    assert without_filer(linked) == without_filer(plain)


def test_a_run_s_sources_name_the_filer(company, linked_tst):
    """Run sources (brief Q3, Q5) read the same filings: the Q1 2020 10-Q behind the seed is the
    successor's, an older filing behind a past quarter is not."""
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = run_sources(company, run_id).to_dict()
    seen = {}
    for row in answer["rows"]:
        for source in row["sources"]:
            if source.get("kind") != "filing":
                continue
            for filing in [source["filing"], *source["input_filings"]]:
                if filing is not None:
                    seen[filing["accession_no"]] = filing["filer"]
    assert seen[TST_10Q_2020Q1] == SUCCESSOR
    assert any(filer is None for filer in seen.values())
    assert all(
        (filer == SUCCESSOR) == (accession >= "0000000123-20-") for accession, filer in seen.items()
    )
