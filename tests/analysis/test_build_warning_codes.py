"""Each build warning is a code with raw-valued params and its English text (backlog #172)."""

import warnings

import pytest

from domains.analysis import math_engine
from domains.analysis.coded import RUN_NOTE_CODES
from domains.analysis.math_engine import build_inputs
from domains.fundamentals.universe import CoverageWarning
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
        "note": "moved",
    }

    def warn(cik, as_of):
        warnings.warn(CoverageWarning("TST is beyond its history", **fields), stacklevel=2)

    monkeypatch.setattr("domains.fundamentals.facts.warn_if_beyond_history", warn)
    note = only(build(company), "beyond_history")  # two queries warn; one note
    assert note.params == fields
    assert note.text == "TST is beyond its history"


def test_a_plain_warning_is_a_data_warning_without_params(company, monkeypatch):
    def warn(cik, as_of):
        warnings.warn("something odd", stacklevel=2)

    monkeypatch.setattr("domains.fundamentals.facts.warn_if_beyond_history", warn)
    note = only(build(company), "data_warning")
    assert note.params == {} and note.text == "something odd"


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
