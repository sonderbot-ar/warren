"""Coca-Cola's cost of debt leaves out the gain or loss on paying debt off early (backlog #610):
it records the figure inside its interest expense line and files it, so the year's interest is
the expense less a loss (plus a gain). Two filings put the year before's figure under their own
year; those facts, listed in misdated_facts.csv, are left out."""

from datetime import date
from pathlib import Path

import pytest

from domains.analysis import math_engine as me
from domains.analysis import misdated_facts as mf
from domains.analysis.math_engine import History, cost_of_debt_year
from domains.fundamentals.schemas import Fact
from tests.analysis.test_capitalised_interest import exxon
from tests.analysis.test_capitalised_interest import fact as exxon_fact
from tests.analysis.test_lease_interest import microsoft, walmart

TAGS = {
    "interest_expense": "InterestExpense",
    "interest_paid": "InterestPaidNet",
    "debt_extinguishment_in_interest": "GainsLossesOnExtinguishmentOfDebt",
    "debt_noncurrent": "LongTermDebtNoncurrent",
    "debt_current": "LongTermDebtCurrent",
}
INSTANT = {"debt_noncurrent", "debt_current"}
# Coca-Cola's FY2021 10-K, which first filed FY2021's figures
FY2021_10K = "0000021344-22-000009"


def fact(item, value, year, accession=None):
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{TAGS[item]}",
        period_end=date(year, 12, 31),
        period_start=None if item in INSTANT else date(year, 1, 1),
        value=value * 1e6,
        unit="USD",
        accession_no=accession or f"0000021344-{(year + 1) % 100:02d}-000009",
        filed_at=date(year + 1, 2, 22),
        fiscal_year=year,
        fiscal_period="FY",
    )


def coca_cola(year=2021, interest=1_597, extinguishment=-559, accession=None, item=None):
    """Coca-Cola-like figures (millions): debt whose average is 42,777M, interest expense 1,597M
    in FY2021 holding 559M of charges on debt paid off early (FY2021 10-K, Note 10)."""
    annual = {
        ("debt_noncurrent", year - 1): fact("debt_noncurrent", 40_125, year - 1),
        ("debt_current", year - 1): fact("debt_current", 2_183, year - 1),
        ("debt_noncurrent", year): fact("debt_noncurrent", 38_116, year),
        ("debt_current", year): fact("debt_current", 5_130, year),
        (item or "interest_expense", year): fact(item or "interest_expense", interest, year),
    }
    if extinguishment is not None:
        annual[("debt_extinguishment_in_interest", year)] = fact(
            "debt_extinguishment_in_interest", extinguishment, year, accession
        )
    return History(quarterly={}, annual=annual, instants={})


def test_coca_cola_fy2021_leaves_out_the_charges():
    kd, interest, (start, _), (end, _) = cost_of_debt_year(coca_cola(), 2021)
    average = (start + end) / 2
    assert average == pytest.approx(42_777e6)
    assert interest.value == pytest.approx(1_038e6)  # 1,597 - 559
    assert kd == pytest.approx(1_038 / 42_777)  # 2.43%, not 3.73%
    assert [f.canonical_name for f in interest.facts] == [
        "interest_expense",
        "debt_extinguishment_in_interest",
    ]
    assert interest.method.startswith("interest_expense")
    assert " - gain or loss on early extinguishment of debt (recorded in interest expense" in (
        interest.method
    )
    assert "left out" not in interest.method
    assert not interest.fallback


def test_a_gain_is_added_back():
    """FY2018: a net gain of 27M lowered the interest expense; the debt's interest is higher."""
    _, interest, _, _ = cost_of_debt_year(coca_cola(2018, 950, 27), 2018)
    assert interest.value == pytest.approx(977e6)


def test_a_year_without_the_line_keeps_its_interest():
    _, interest, _, _ = cost_of_debt_year(coca_cola(extinguishment=None), 2021)
    assert interest.value == pytest.approx(1_597e6)
    assert [f.canonical_name for f in interest.facts] == ["interest_expense"]


@pytest.mark.parametrize(
    ("year", "interest", "value", "accession"),
    [
        (2016, 733, -320, "0000021344-17-000009"),
        (2019, 946, 27, "0000021344-21-000008"),
    ],
)
def test_a_misdated_fact_is_left_out(year, interest, value, accession):
    """The FY2016 10-K tagged 2015's charge under 2016, the FY2020 10-K 2018's gain under 2019."""
    history = coca_cola(year, interest, value, accession)
    ext = history.annual[("debt_extinguishment_in_interest", year)]
    _, resolved, _, _ = cost_of_debt_year(history, year)
    assert resolved.value == pytest.approx(interest * 1e6)
    assert [f.canonical_name for f in resolved.facts] == ["interest_expense"]
    assert resolved.method.endswith(
        "(gain or loss on early extinguishment of debt left out, the filing put another year's "
        f"figure under this year, misdated_facts.csv: {me.trace(ext)})"
    )


def test_only_the_listed_year_and_filing_are_left_out():
    """The same filing's figure for another year, or another filing's for the listed year,
    counts."""
    _, other_year, _, _ = cost_of_debt_year(
        coca_cola(2021, 1_597, -559, "0000021344-17-000009"), 2021
    )
    assert other_year.value == pytest.approx(1_038e6)
    _, other_filing, _, _ = cost_of_debt_year(coca_cola(2016, 733, -320, FY2021_10K), 2016)
    assert other_filing.value == pytest.approx(413e6)


@pytest.mark.parametrize("value", [-1_597, -2_000])
def test_a_figure_that_would_leave_no_interest_is_left_out(value):
    history = coca_cola(extinguishment=value)
    ext = history.annual[("debt_extinguishment_in_interest", 2021)]
    _, interest, _, _ = cost_of_debt_year(history, 2021)
    assert interest.value == pytest.approx(1_597e6)
    assert interest.method.endswith(
        f"(gain or loss on early extinguishment of debt left out, it would leave no interest: "
        f"{me.trace(ext)})"
    )


def test_never_on_cash_interest():
    """The cash fallback (`InterestPaidNet`) holds no extinguishment charge."""
    _, interest, _, _ = cost_of_debt_year(coca_cola(item="interest_paid"), 2021)
    assert interest.fallback
    assert interest.value == pytest.approx(1_597e6)


def test_taken_out_before_the_capitalised_and_non_debt_parts():
    """Exxon-like figures with an extinguishment figure: each part is applied once, in order."""
    history = exxon()
    history.annual[("debt_extinguishment_in_interest", 2025)] = exxon_fact(
        "debt_extinguishment_in_interest", -100e6, 2025, tag="GainsLossesOnExtinguishmentOfDebt"
    )
    _, interest, _, _ = cost_of_debt_year(history, 2025)
    assert interest.value == pytest.approx((603 - 100 - 300 + 1_534) * 1e6)
    assert interest.method.index("early extinguishment") < interest.method.index("not on debt")


def test_the_other_companies_are_unchanged():
    assert cost_of_debt_year(exxon(), 2025)[1].value == pytest.approx(1_837e6)
    assert cost_of_debt_year(walmart(), 2026)[1].value == pytest.approx(2_318e6 + 383e6)
    assert cost_of_debt_year(microsoft(), 2026)[1].value == pytest.approx(4_047e6)


def test_microsofts_cash_path_never_reads_it():
    history = microsoft()
    history.annual[("debt_extinguishment_in_interest", 2026)] = exxon_fact(
        "debt_extinguishment_in_interest", -999e6, 2026, tag="GainsLossesOnExtinguishmentOfDebt"
    )
    assert cost_of_debt_year(history, 2026)[1].value == pytest.approx(4_047e6)


# The data file


def test_the_shipped_file_loads():
    rows = mf.load_misdated_facts()
    assert [
        (r.ticker, r.canonical_name, r.fiscal_year, r.accession_no, r.stated_fiscal_year)
        for r in rows
    ] == [
        ("KO", "debt_extinguishment_in_interest", 2016, "0000021344-17-000009", 2015),
        ("KO", "debt_extinguishment_in_interest", 2019, "0000021344-21-000008", 2018),
    ]
    # the stated year is the one each row's quoted words give (backlog #613)
    assert all(f"December 31, {r.stated_fiscal_year}" in r.evidence for r in rows)
    row = mf.misdated_fact("debt_extinguishment_in_interest", 2019, "0000021344-21-000008")
    assert row is rows[1] or row == rows[1]
    assert mf.misdated_fact("debt_extinguishment_in_interest", 2018, "0000021344-21-000008") is None
    assert mf.is_misdated("debt_extinguishment_in_interest", 2019, "0000021344-21-000008")
    assert not mf.is_misdated("debt_extinguishment_in_interest", 2018, "0000021344-21-000008")
    assert not mf.is_misdated("interest_expense", 2019, "0000021344-21-000008")


def write(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "misdated_facts.csv"
    path.write_text("\n".join([",".join(mf.COLUMNS), *rows]) + "\n", encoding="utf-8")
    return path


GOOD = (
    "KO,debt_extinguishment_in_interest,2019,0000021344-21-000008,2018,"
    '"0000021344-21-000008 says 2018"'
)


def test_a_good_row_loads(tmp_path):
    assert len(mf.load_misdated_facts(write(tmp_path, GOOD))) == 1


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (GOOD.replace("KO,", "ZZZ,", 1), "'ZZZ' is not in universe.csv"),
        (GOOD.replace("debt_extinguishment_in_interest", "revenue"), "item 'revenue' is not"),
        (GOOD.replace(",2019,", ",FY19,"), "fiscal_year must be a whole number"),
        (
            'KO,debt_extinguishment_in_interest,2019,21344-21-8,2018,"21344-21-8"',
            "'21344-21-8' is not an SEC accession number",
        ),
        (
            'KO,debt_extinguishment_in_interest,2019,0000021344-21-000008,2018,"no filing named"',
            "the evidence must quote the filing it names",
        ),
        ("KO,debt_extinguishment_in_interest,2019", "wrong number of fields"),
        (GOOD.replace(",2018,", ",FY18,"), "stated_fiscal_year must be a whole number"),
        (GOOD.replace(",2018,", ",,"), "stated_fiscal_year must be a whole number"),
        (GOOD.replace(",2018,", ",2019,"), "stated_fiscal_year must differ from fiscal_year"),
        (GOOD.replace("says 2018", "says so"), "the evidence must quote the year it states"),
    ],
)
def test_a_bad_row_is_refused(tmp_path, row, message):
    with pytest.raises(mf.MisdatedFactsError, match=message):
        mf.load_misdated_facts(write(tmp_path, row))


def test_every_problem_is_reported_at_once_and_a_repeat_is_refused(tmp_path):
    bad = GOOD.replace("KO,", "ZZZ,", 1).replace(",2019,", ",FY19,")
    with pytest.raises(mf.MisdatedFactsError) as err:
        mf.load_misdated_facts(write(tmp_path, bad, GOOD, GOOD))
    text = str(err.value)
    assert "line 2: 'ZZZ'" in text and "line 2: fiscal_year" in text
    assert "line 4: repeats an earlier row" in text


def test_wrong_columns_are_refused(tmp_path):
    path = tmp_path / "misdated_facts.csv"
    path.write_text("ticker,year\nKO,2019\n", encoding="utf-8")
    with pytest.raises(mf.MisdatedFactsError, match="expected columns"):
        mf.load_misdated_facts(path)


def test_the_file_is_part_of_the_reading_rules(tmp_path):
    """A new row changes what a run reads, so it changes the fingerprint and needs a version."""
    from domains.analysis import reading_rules as rr

    assert "domains/analysis/misdated_facts.csv" in rr.RULES_DATA
    root = tmp_path / "repo"
    for module in (*rr.rules_modules(), *rr.RULES_DATA):
        (root / module).parent.mkdir(parents=True, exist_ok=True)
        (root / module).write_bytes((rr.REPO_ROOT / module).read_bytes())
    before = rr.rules_fingerprint(root=root)
    assert before == rr.rules_fingerprint()
    data = root / rr.RULES_DATA[0]
    data.write_bytes(data.read_bytes() + GOOD.replace("2019", "2018", 1).encode() + b"\n")
    assert rr.rules_fingerprint(root=root) != before
