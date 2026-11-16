"""Each build warning is a code with raw-valued params and its English text (backlog #172)."""

import warnings
from datetime import date

import pytest

from domains.analysis import math_engine
from domains.analysis.coded import RUN_NOTE_CODES
from domains.analysis.math_engine import build_inputs
from domains.fundamentals.universe import CoverageWarning
from shared_kernel.data_warnings import DataWarning
from tests.analysis.conftest import AS_OF, CHOICES

COVER = "dei:EntityCommonStockSharesOutstanding"


def build(conn):
    return build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def notes(result, code):
    return [n for n in result.notes if n.code == code]


def only(result, code):
    found = notes(result, code)
    assert len(found) == 1, [n.code for n in result.notes]
    assert result.warnings.count(found[0].text) == 1
    return found[0]


def edited(tag_to_change, change=None, when=lambda row: True):
    """An edit that drops (change None) or rescales matching rows of one tag."""

    def edit(tag, row):
        if tag != tag_to_change or not when(row):
            return row
        return None if change is None else {**row, "val": change(row["val"])}

    return edit


def without_q1_2020(tag, row):
    return None if row["filed"] == "2020-04-30" else row


def test_fundamentals_stale(make_company):
    result = build(make_company(without_q1_2020))  # the last quarter is then Q4 2019
    note = only(result, "fundamentals_stale")
    assert note.params == {
        "last_quarter_end": "2019-12-31",
        "days": 182,
        "threshold_days": 135,
    }
    assert note.text == (
        "Fundamentals may be stale: the last reported quarter ended 2019-12-31, "
        "182 days before the as-of date (check that the newest filings are ingested)."
    )


def filed_before(day):
    """Keep only the filings made before `day`."""
    return lambda tag, row: row if row["filed"] < day else None


def build_on(conn, as_of):
    return build_inputs(conn, "TST", date.fromisoformat(as_of), choices=CHOICES, today=None)


@pytest.mark.parametrize(
    ("as_of", "warns"),
    [
        ("2020-02-15", False),  # 138 days after Q3 2019: the 10-K is not due yet (CAT 2024)
        ("2020-03-09", False),  # 161 days: on the line, not over it
        ("2020-03-10", True),  # 162 days
    ],
)
def test_after_a_third_quarter_the_line_is_the_10k_deadline(make_company, as_of, warns):
    conn = make_company(filed_before("2019-11-01"))  # the last quarter is Q3 2019
    found = notes(build_on(conn, as_of), "fundamentals_stale")
    assert bool(found) == warns
    if warns:
        assert found[0].params == {
            "last_quarter_end": "2019-09-30",
            "days": 162,
            "threshold_days": 161,
        }


def test_after_a_second_quarter_the_line_stays_the_10q_deadline(make_company):
    conn = make_company(filed_before("2019-08-01"))  # the last quarter is Q2 2019
    found = notes(build_on(conn, "2019-11-13"), "fundamentals_stale")  # 136 days
    assert [n.params for n in found] == [
        {"last_quarter_end": "2019-06-30", "days": 136, "threshold_days": 135}
    ]


def without_fy2019_revenue(tag, row):
    """Filings before 2020-03-01, so the FY2019 10-K is in, but without its full-year 2019
    revenue: Q4 2019 = year − Q1 − Q2 − Q3 then has no year to start from."""
    if row["filed"] >= "2020-03-01":
        return None
    full_year = row.get("start") == "2019-01-01" and row["end"] == "2019-12-31"
    return None if tag == "Revenues" and full_year else row


@pytest.mark.parametrize("as_of", ["2020-03-09", "2020-03-10"])
def test_a_10k_without_a_derivable_fourth_quarter_says_the_newer_report_was_not_read(
    make_company, as_of
):
    """Backlog #352 (was #349's pin): the 10-K is in but its fourth quarter can't be derived, so
    the newest quarter is still Q3. The run says the newer report wasn't read, at any age, and
    not that filings may be missing, whose advice (ingest) would be wrong."""
    conn = make_company(without_fy2019_revenue)
    in_10k = conn.execute(
        "SELECT COUNT(*) FROM financial_facts WHERE form = '10-K' AND period_end = '2019-12-31'"
    ).fetchone()[0]
    assert in_10k  # the 10-K's figures are in the database
    result = build_on(conn, as_of)
    # the run rolls forward from Q3 2019: the fourth quarter was not derived
    roll = result.sources[("roll_years", math_engine.SINGLE)]
    assert roll == [{"kind": "derived", "inputs": [{"name": "revenue_seed", "period": "FY2019Q3"}]}]
    assert not notes(result, "fundamentals_stale")
    note = only(result, "newer_report_not_read")
    days = (date.fromisoformat(as_of) - date(2019, 9, 30)).days
    assert note.params == {
        "last_quarter_end": "2019-09-30",
        "newer_period_end": "2019-12-31",
        "newer_annual": True,
        "newer_accession_no": "0000000123-20-000015",
        "days": days,
    }
    assert note.text == (
        "The newest quarter with revenue ended 2019-09-30, but figures from the annual report "
        "for the year ended 2019-12-31 are loaded: that period's revenue could not be read or "
        "derived, so the run starts at least one report behind (check that filing's revenue "
        "line)."
    )


def test_the_note_names_a_filing_that_gave_the_newer_figure(make_company):
    conn = make_company(without_fy2019_revenue)
    note = only(build_on(conn, "2020-03-09"), "newer_report_not_read")
    filed = conn.execute(
        "SELECT DISTINCT accession_no FROM financial_facts WHERE period_end = '2019-12-31' "
        "AND period_start = '2019-01-01'"
    ).fetchall()
    assert [note.params["newer_accession_no"]] == [r[0] for r in filed]


@pytest.mark.parametrize(("as_of", "stale"), [("2020-05-14", False), ("2020-05-15", True)])
def test_a_report_missing_after_the_unread_one_is_still_stale(make_company, as_of, stale):
    """Two faults (analyst): the 10-K's revenue unread, and the Q1 10-Q, due 40 days after
    March, not in. The stale line then keys on the newer period, the year that ended
    2019-12-31, after which the next report is a 10-Q: 135 days."""
    result = build_on(make_company(without_fy2019_revenue), as_of)
    assert notes(result, "newer_report_not_read")
    found = notes(result, "fundamentals_stale")
    assert bool(found) == stale
    if stale:
        assert found[0].params == {
            "last_quarter_end": "2019-12-31",
            "days": 135 + 1,
            "threshold_days": 135,
        }


def without_q1_2020_revenue(tag, row):
    """The Q1 2020 10-Q is in, but without its revenue."""
    q1 = row["filed"] == "2020-04-30" and row.get("start") == "2020-01-01"
    return None if tag == "Revenues" and q1 else row


def test_a_10q_whose_revenue_was_not_read(make_company):
    result = build(make_company(without_q1_2020_revenue))
    note = only(result, "newer_report_not_read")
    assert note.params["last_quarter_end"] == "2019-12-31"
    assert note.params["newer_period_end"] == "2020-03-31"
    assert note.params["newer_annual"] is False
    assert "from a report for the period ended 2020-03-31" in note.text
    assert not notes(result, "fundamentals_stale")  # 91 days after March: the 10-Q is in


def test_a_balance_dated_after_the_quarter_is_not_a_newer_report(company):
    """The cover page's share count is dated after its quarter; it must not count."""
    assert not notes(build(company), "newer_report_not_read")


def test_a_late_report_is_stale_not_unread(make_company):
    result = build(make_company(without_q1_2020))
    assert not notes(result, "newer_report_not_read")
    assert notes(result, "fundamentals_stale")


def test_the_lines_are_built_from_the_sec_deadlines():
    assert math_engine.STALE_AFTER.days == 135
    assert math_engine.STALE_AFTER_Q3.days == 161


def test_fresh_fundamentals_are_not_stale(company):
    assert not notes(build(company), "fundamentals_stale")


def test_balance_carried_forward(make_company):
    edit = edited("LongTermDebtNoncurrent", None, lambda row: row["end"] == "2020-03-31")
    note = only(build(make_company(edit)), "balance_carried_forward")
    assert note.params["balance_date"] == "2020-03-31"
    assert len(note.params["items"]) == 1
    item = note.params["items"][0]
    assert item["period_end"] == "2019-12-31"
    assert note.text == (
        f"Carried forward to the 2020-03-31 balance sheet: {item['item']} (2019-12-31)"
    )


def test_balance_counted_zero(company):
    note = only(build(company), "balance_counted_zero")
    items = note.params["items"]
    assert note.params["balance_date"] == "2020-03-31"
    assert items == sorted(items) and "short_term_borrowings/commercial_paper" in items
    assert note.text == (
        "Counted as zero (not reported within a year of the 2020-03-31 balance sheet): "
        + ", ".join(items)
    )


def test_balance_date_differs(make_company):
    edit = edited("AssetsCurrent", None, lambda row: row["end"] == "2020-03-31")
    result = build(make_company(edit))
    note = only(result, "balance_date_differs")
    assert note.params == {"balance_date": "2019-12-31", "last_quarter_end": "2020-03-31"}
    assert note.text == (
        "Balance sheet date 2019-12-31 differs from the last quarter end 2020-03-31"
    )
    assert not notes(result, "balance_carried_forward")


def test_shares_cover_differs(company):
    company.execute(
        "UPDATE financial_facts SET value = 150 WHERE xbrl_concept = ?",
        (COVER,),
    )
    note = only(build(company), "shares_cover_differs")
    assert note.params == {
        "cover_shares_adjusted": 150,
        "diluted_shares_adjusted": 100,
        "tolerance": 0.10,
    }
    assert note.text == (
        "Cover-page shares (150) differ from diluted shares (100) by more than 10%"
    )


def test_cost_of_debt_out_of_bounds(make_company):
    result = build(make_company(edited("InterestExpense", lambda v: v * 5)))
    note = only(result, "cost_of_debt_out_of_bounds")
    assert note.params["cost_of_debt"] == pytest.approx(0.20)
    assert (note.params["low"], note.params["high"]) == (0.0, 0.15)
    assert note.text == f"Cost of debt {note.params['cost_of_debt']:.2%} is outside (0.0, 0.15)"


def test_tax_rate_clipped(make_company):
    result = build(make_company(edited("IncomeTaxExpenseBenefit", lambda v: v * 3)))
    note = only(result, "tax_rate_clipped")
    assert note.params["tax_rate"] == pytest.approx(0.75)
    assert note.params["clipped_to"] == 0.5
    assert (note.params["low"], note.params["high"]) == (0.0, 0.5)
    assert note.text == "Effective tax rate 75.0% clipped to 50%"


def test_concept_map_changed(company, monkeypatch):
    assert not notes(build(company), "concept_map_changed")
    monkeypatch.setattr(math_engine, "concept_map_sha256", lambda: "0" * 64)
    note = only(build(company), "concept_map_changed")
    assert note.params == {}
    assert note.text == "concept_map.csv changed since the last ingest: re-run ingest"


def test_beyond_history_is_one_note_with_its_fields(company, monkeypatch):
    fields = {
        "ticker": "TST",
        "cik": "0000000123",
        "as_of": "2020-06-30",
        "history_ends": "2020-01-01",
        "reason": "holding_company_reorganisation",
        "successor_cik": "0000000456",
        "successor_name": "TST Holdings",
        "note": "moved",
    }

    def warn(cik, as_of):
        warnings.warn(CoverageWarning("TST is beyond its history", **fields), stacklevel=2)

    monkeypatch.setattr("domains.fundamentals.facts.warn_if_beyond_history", warn)
    note = only(build(company), "beyond_history")  # two queries warn; one note
    assert note.params == fields
    assert note.text == "TST is beyond its history"


def test_a_library_warning_is_not_a_note_and_goes_back_to_the_log(company, monkeypatch):
    # backlog #196: before, any warning became a `data_warning` note; only Warren's own now do
    def warn(cik, as_of):
        warnings.warn("something odd", DeprecationWarning, stacklevel=2)

    monkeypatch.setattr("domains.fundamentals.facts.warn_if_beyond_history", warn)
    with pytest.warns(DeprecationWarning, match="something odd"):
        result = build(company)
    assert not notes(result, "data_warning")
    assert "something odd" not in result.warnings


def test_a_plain_user_warning_is_not_a_note_either(company, monkeypatch):
    def warn(cik, as_of):
        warnings.warn("odd", stacklevel=2)

    monkeypatch.setattr("domains.fundamentals.facts.warn_if_beyond_history", warn)
    with pytest.warns(UserWarning, match="odd"):
        result = build(company)
    assert not notes(result, "data_warning")


def test_a_warren_data_warning_without_its_own_code_is_a_data_warning(company, monkeypatch):
    def warn(cik, as_of):
        warnings.warn(DataWarning("something odd in the data"), stacklevel=2)

    monkeypatch.setattr("domains.fundamentals.facts.warn_if_beyond_history", warn)
    note = only(build(company), "data_warning")
    assert note.params == {} and note.text == "something odd in the data"


def test_every_code_the_fixtures_produce_is_a_run_note_code(company, make_company):
    results = [
        build(company),
        build(make_company(without_q1_2020)),
        build(make_company(edited("InterestExpense", lambda v: v * 5))),
        build(make_company(edited("IncomeTaxExpenseBenefit", lambda v: v * 3))),
        build(make_company(edited("AssetsCurrent", None, lambda r: r["end"] == "2020-03-31"))),
    ]
    codes = {n.code for r in results for n in r.notes}
    assert {"balance_counted_zero", "fundamentals_stale", "tax_rate_clipped"} <= codes
    assert codes <= RUN_NOTE_CODES
