"""Reported figures and named ratios (backlog #140), on Test Corp, whose ratios are known by
construction (tests/analysis/conftest.py): operating margin 20%, tax 25% of pretax, D&A 5% and
capex 6% of revenue, revenue +10% a year; debt 20 + 180, cash 60. There is no Q4 10-Q, so every
fiscal Q4 is derived from the 10-K year less the three 10-Q quarters."""

import json
from datetime import date

import pytest

from domains.analysis import __main__ as cli
from domains.analysis.reported import (
    LENGTH_NOTE_DAYS,
    Period,
    ReportedError,
    filing_url,
    parse_period,
    reported_period,
)
from tests.analysis.conftest import AS_OF, revenue

Q1_2020_10Q = "0000000123-20-000016"  # filed 2020-04-30, holds Q1 2019 as its comparative
FY2019_10K = "0000000123-20-000015"  # filed 2020-02-15


def test_parse_period():
    assert parse_period("FY2025Q4") == Period(2025, "Q4")
    assert parse_period("fy2024") == Period(2024, "FY")
    assert Period(2024, "FY").label == "FY2024"
    for bad in ("2025Q4", "FY2025Q5", "FY25", "latest"):
        with pytest.raises(ReportedError, match="FY2025Q4"):
            parse_period(bad)


def test_a_fiscal_year_gives_the_engine_ratios(company):
    r = reported_period(company, "TST", "FY2019", AS_OF)
    assert (r.period, r.period_start, r.period_end) == (
        "FY2019",
        date(2019, 1, 1),
        date(2019, 12, 31),
    )
    assert r.company_name == "Test Corp" and r.fiscal_year_end == "1231"
    rev = r.line("revenue")
    assert rev.value == pytest.approx(sum(revenue(2019, q) for q in (1, 2, 3, 4)))
    assert rev.latest.filing.accession_no == FY2019_10K
    assert rev.latest.filing.form == "10-K"
    assert rev.latest.filing.url == filing_url("0000000123", FY2019_10K)
    assert not rev.derived and not rev.changed
    assert r.ratio("operating_margin").value == pytest.approx(0.20)
    assert r.ratio("effective_tax_rate").value == pytest.approx(0.25)
    assert r.ratio("da_share").value == pytest.approx(0.05)
    assert r.ratio("capex_share").value == pytest.approx(0.06)
    assert r.ratio("revenue_growth_yoy").value == pytest.approx(0.10)
    assert r.ratio("effective_tax_rate").notes == []  # the interim note is for quarters only
    assert r.as_reported_note.code == "as_reported"


def test_a_derived_fourth_quarter_names_its_filings(company):
    r = reported_period(company, "TST", "FY2019Q4", AS_OF)
    rev = r.line("revenue")
    assert rev.derived and rev.latest.filing is None
    assert rev.value == pytest.approx(revenue(2019, 4))
    forms = {i.form for i in rev.latest.inputs}
    assert forms == {"10-K", "10-Q"}
    assert FY2019_10K in {i.accession_no for i in rev.latest.inputs}
    assert r.ratio("revenue_growth_yoy").value == pytest.approx(0.10)
    assert r.ratio("operating_margin").value == pytest.approx(0.20)
    assert [n.code for n in r.ratio("effective_tax_rate").notes] == ["interim_tax_rate"]
    # the balance at a Q4 is the year-end one, from the 10-K
    assert r.line("cash").period_end == date(2019, 12, 31)


def test_net_debt_follows_the_valuation_rule(company):
    r = reported_period(company, "TST", "FY2019Q3", AS_OF)
    net_debt = r.ratio("net_debt")
    assert net_debt.value == pytest.approx(20 + 180 - 60)
    assert net_debt.unit == "USD"
    codes = {n.code: n.params for n in net_debt.notes}
    assert "finance_lease_liabilities" in codes["counted_as_zero"]["items"]
    assert "net_cash" not in codes
    assert {u["line"] for u in net_debt.uses} == {"debt_current", "debt_noncurrent", "cash"}


def test_items_not_reported_give_a_coded_gap(company):
    r = reported_period(company, "TST", "FY2019", AS_OF)
    gross = r.ratio("gross_margin")
    assert gross.value is None
    assert (gross.missing.code, gross.missing.params) == (
        "not_reported",
        {"items": ["cost_of_revenue"]},
    )
    assert r.line("cost_of_revenue") is None  # a line the period doesn't report is left out


def test_net_margin_is_net_income_to_the_parent_over_revenue(company):
    for period in ("FY2019", "FY2019Q4", "FY2019Q2"):  # a year, a derived Q4, a 10-Q quarter
        r = reported_period(company, "TST", period, AS_OF)
        margin = r.ratio("net_margin")
        expected = r.line("net_income").value / r.line("revenue").value
        assert margin.value == pytest.approx(expected)
        assert margin.formula_id == "net_income_to_parent_over_revenue"
        assert margin.notes == [] and margin.missing is None
        assert [u["line"] for u in margin.uses] == ["net_income", "revenue"]
    year = reported_period(company, "TST", "FY2019", AS_OF)
    assert year.line("net_income").latest.xbrl_concept == "us-gaap:NetIncomeLoss"
    # by construction: 0.75 × (20% of revenue − 8 of interest)
    rev = year.line("revenue").value
    assert year.ratio("net_margin").value == pytest.approx(0.75 * (0.2 * rev - 8) / rev)


def test_net_margin_without_net_income_is_a_coded_gap(make_company):
    conn = make_company(lambda tag, row: None if tag == "NetIncomeLoss" else row)
    margin = reported_period(conn, "TST", "FY2019", AS_OF).ratio("net_margin")
    assert margin.value is None
    assert (margin.missing.code, margin.missing.params) == (
        "not_reported",
        {"items": ["net_income"]},
    )


def _with_discontinued(amount, tag="IncomeLossFromDiscontinuedOperationsNetOfTax", net=None):
    """FY2019 (the 10-K's own year) gains a discontinued line; net income moves by it, or to
    `net` when given."""

    def edit(t, row):
        fy2019 = row.get("start") == "2019-01-01" and row["end"] == "2019-12-31"
        if t != "NetIncomeLoss" or not fy2019:
            return row
        value = row["val"] + amount if net is None else net
        return [("NetIncomeLoss", {**row, "val": value}), (tag, {**row, "val": amount})]

    return edit


def test_discontinued_operations_get_a_note_with_their_share(make_company):
    conn = make_company(_with_discontinued(50))
    r = reported_period(conn, "TST", "FY2019", AS_OF)
    margin = r.ratio("net_margin")
    net = r.line("net_income").value
    assert margin.value == pytest.approx(net / r.line("revenue").value)  # stays in, as reported
    (note,) = margin.notes
    assert note.code == "includes_discontinued_operations"
    assert note.params == {
        "amount": 50,
        "currency": "USD",
        "share_of_net_income": pytest.approx(50 / net),
    }
    assert [u["line"] for u in margin.uses] == ["net_income", "discontinued_operations", "revenue"]
    assert r.line("discontinued_operations").value == 50


def test_the_parents_share_of_discontinued_operations_ranks_first(make_company):
    parent = "IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity"

    def both(t, row):
        pairs = _with_discontinued(50)(t, row)
        if isinstance(pairs, list):
            pairs.append((parent, {**row, "val": 40}))
        return pairs

    r = reported_period(make_company(both), "TST", "FY2019", AS_OF)
    assert r.line("discontinued_operations").latest.xbrl_concept == f"us-gaap:{parent}"
    assert r.ratio("net_margin").notes[0].params["amount"] == 40


@pytest.mark.parametrize(
    ("amount", "net"),
    [(-30, None), (50, -20), (500, 300)],  # a loss; net loss overall; more than all of net income
)
def test_no_share_when_it_would_not_be_a_share(make_company, amount, net):
    r = reported_period(make_company(_with_discontinued(amount, net=net)), "TST", "FY2019", AS_OF)
    margin = r.ratio("net_margin")
    (note,) = margin.notes
    assert note.code == "includes_discontinued_operations"
    assert "share_of_net_income" not in note.params
    assert note.params["amount"] == amount
    if net is not None and net < 0:
        assert margin.value < 0  # a loss gives a negative margin, not a gap


def test_zero_discontinued_operations_give_no_note(make_company):
    r = reported_period(make_company(_with_discontinued(0)), "TST", "FY2019", AS_OF)
    assert r.ratio("net_margin").notes == []


def test_latest_quarter_is_point_in_time(company):
    before = reported_period(company, "TST", "latest-quarter", date(2020, 4, 29))
    assert before.period == "FY2019Q4"
    on_the_day = reported_period(company, "TST", "latest-quarter", date(2020, 4, 30))
    assert on_the_day.period == "FY2020Q1"
    with pytest.raises(ReportedError, match="FY2020Q1: revenue not reported"):
        reported_period(company, "TST", "FY2020Q1", date(2020, 4, 29))
    assert reported_period(company, "TST", "latest-year", AS_OF).period == "FY2019"
    with pytest.raises(ReportedError, match="not been ingested"):
        reported_period(company, "NOPE", "FY2019", AS_OF)


def _restate_q1_2019(tag, row):
    if row["accn"] == Q1_2020_10Q and row["end"] == "2019-03-31" and tag == "Revenues":
        return {**row, "val": row["val"] + 5}
    return row


def test_a_restated_comparative_shows_both_versions(make_company):
    conn = make_company(_restate_q1_2019)
    first = revenue(2019, 1)
    before = reported_period(conn, "TST", "FY2019Q1", date(2020, 4, 29)).line("revenue")
    assert not before.changed and before.value == pytest.approx(first)
    r = reported_period(conn, "TST", "FY2019Q1", AS_OF)
    rev = r.line("revenue")
    assert rev.changed
    assert rev.value == pytest.approx(first + 5)
    assert rev.first_reported.value == pytest.approx(first)
    assert rev.latest.filing.accession_no == Q1_2020_10Q
    assert rev.first_reported.filed_at < rev.latest.filed_at
    margin_notes = {n.code: n.params for n in r.ratio("operating_margin").notes}
    assert margin_notes["uses_changed_line"]["items"] == ["revenue"]
    growth_notes = {n.code: n.params for n in r.ratio("revenue_growth_yoy").notes}
    assert growth_notes["uses_changed_line"]["periods"] == ["FY2019Q1"]


def test_disagreement_rows_sit_on_their_own_period(company):
    # the Q1 2020 10-Q repeats Q1 2019 only under a lower-ranked revenue tag, with another value
    company.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES (?, ?, ?, ?, ?, ?, ?, "
        "'USD', '10-Q', ?, '2020-04-30')",
        (
            "0000000123",
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "2019-01-01",
            "2019-03-31",
            2019,
            "Q1",
            revenue(2019, 1) + 7,
            "0000000123-20-000099",
        ),
    )
    hit = reported_period(company, "TST", "FY2019Q1", AS_OF)
    assert [(d.name, d.period_end) for d in hit.disagreements] == [("revenue", date(2019, 3, 31))]
    assert hit.disagreements[0].newest.value == pytest.approx(revenue(2019, 1) + 7)
    assert reported_period(company, "TST", "FY2019Q2", AS_OF).disagreements == []
    # a derived Q4 is built from the year's quarters, so it lists the row too
    assert len(reported_period(company, "TST", "FY2019Q4", AS_OF).disagreements) == 1


def test_operating_margin_through_the_pretax_fallback_says_so(make_company):
    conn = make_company(lambda tag, row: None if tag == "OperatingIncomeLoss" else row)
    margin = reported_period(conn, "TST", "FY2019", AS_OF).ratio("operating_margin")
    assert margin.formula_id == "pretax_plus_interest_over_revenue"
    assert margin.value == pytest.approx(0.20)  # pretax + interest = operating income here
    assert [n.code for n in margin.notes] == ["ebit_from_pretax_plus_interest"]
    assert {u["line"] for u in margin.uses} == {"pretax_income", "interest_expense", "revenue"}


def test_a_loss_before_tax_has_no_tax_rate(make_company):
    pretax = "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"  # the fixture tag starts so

    def loss(tag, row):
        if (
            tag.startswith(pretax)
            and row["end"] == "2019-12-31"
            and row.get("start") == "2019-01-01"
        ):
            return {**row, "val": -10}
        return row

    tax = reported_period(make_company(loss), "TST", "FY2019", AS_OF).ratio("effective_tax_rate")
    assert tax.value is None
    assert tax.missing.code == "base_not_positive"


def test_growth_flags_periods_a_week_apart_in_length(company):
    # a 14-week quarter: 97 days against 90, exactly LENGTH_NOTE_DAYS longer
    company.execute(
        "UPDATE financial_facts SET period_start = '2018-12-25' WHERE period_start = '2019-01-01' "
        "AND period_end = '2019-03-31'"
    )
    growth = reported_period(company, "TST", "FY2019Q1", AS_OF).ratio("revenue_growth_yoy")
    notes = {n.code: n.params for n in growth.notes}
    assert notes["period_length_differs"] == {"days": 97, "prior_days": 90}
    assert 97 - 90 == LENGTH_NOTE_DAYS
    plain = reported_period(company, "TST", "FY2019Q2", AS_OF).ratio("revenue_growth_yoy")
    assert plain.notes == []


def test_the_first_year_has_no_growth(company):
    r = reported_period(company, "TST", "FY2014", AS_OF)  # the 10-K of 2016 holds 2014
    assert r.prior_lines == []
    growth = r.ratio("revenue_growth_yoy")
    assert growth.value is None and growth.missing.code == "not_reported"


def test_to_dict_is_plain_json(company):
    r = reported_period(company, "TST", "FY2019Q4", AS_OF)
    data = json.loads(json.dumps(r.to_dict()))
    assert data["period_end"] == "2019-12-31"
    assert data["lines"][0]["latest"]["filed_at"] >= "2016"
    ratio = next(x for x in data["ratios"] if x["name"] == "operating_margin")
    assert ratio["value"] == pytest.approx(0.20)  # a fraction, unrounded
    assert set(data) >= {"ticker", "cik", "company_name", "lines", "ratios", "warnings"}


def _cli(company, monkeypatch, capsys, *args):
    class Same:
        def __enter__(self):
            return company

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "get_db_connection", lambda: Same())
    code = cli.main(["reported", "--ticker", "TST", "--as-of", AS_OF.isoformat(), *args])
    return code, capsys.readouterr().out


def test_cli_text_and_json(company, monkeypatch, capsys):
    code, out = _cli(company, monkeypatch, capsys, "--period", "FY2019Q4")
    assert code == 0
    assert "FY2019Q4 (2019-10-01 to 2019-12-31)" in out
    assert "derived from 10-K" in out and "operating_margin" in out and "20.0%" in out

    code, out = _cli(
        company, monkeypatch, capsys, "--period", "FY2018", "--period", "FY2019", "--json"
    )
    assert code == 0
    data = json.loads(out)
    assert [d["period"] for d in data] == ["FY2018", "FY2019"]


def test_cli_refuses_an_unknown_period(company, monkeypatch, capsys):
    code, out = _cli(company, monkeypatch, capsys, "--period", "2019Q4")
    assert code == 1
    assert "FAILED: unknown period" in out and "latest-quarter" in out


def test_net_debt_carries_a_balance_tagged_only_at_year_end(make_company):
    # current debt tagged only in the 10-K: the Q3 balance takes the year-end one, and says so
    conn = make_company(
        lambda tag, row: None if tag == "LongTermDebtCurrent" and row["form"] == "10-Q" else row
    )
    r = reported_period(conn, "TST", "FY2019Q3", AS_OF)
    net_debt = r.ratio("net_debt")
    assert net_debt.value == pytest.approx(20 + 180 - 60)
    notes = {n.code: n.params for n in net_debt.notes}
    assert notes["carried_forward"] == {"items": {"debt_current": "2018-12-31"}}
    assert r.line("debt_current") is None  # not a line of this period


def test_a_line_used_twice_is_listed_once(company):
    # under the third pretax rule (net income + tax) the tax line is in both terms of the rate
    from domains.analysis.reported import _uses

    r = reported_period(company, "TST", "FY2019", AS_OF)
    tax = next(x for x in r.lines if x.name == "income_tax_expense")
    fact = type("F", (), {"canonical_name": tax.name})
    assert _uses([fact, fact], Period(2019, "FY")) == [
        {"line": "income_tax_expense", "period": "FY2019"}
    ]


# -- backlog #290: a quarter on one basis, as a run reads it ----------------------------------


def test_a_quarter_put_on_one_basis_shows_the_plain_derivation_beside(make_company):
    """The #264 fixture: the 2019 10-Qs recast 2018's quarters 20% lower, the FY2018 10-K is the
    only year. As of 2019-12-31 the reported view shows FY2018Q4 as a run reads it, the year less
    the quarters as first reported, and the plain derivation (old year less recast quarters)
    beside it with a coded reason."""
    from domains.analysis.math_engine import build_inputs
    from tests.analysis.test_math_engine import CHOICES, by_key, recast_2018_quarters

    conn = make_company(recast_2018_quarters)
    as_of = date(2019, 12, 31)
    r = reported_period(conn, "TST", "FY2018Q4", as_of)
    rev = r.line("revenue")
    plain = sum(revenue(2018, q) for q in (1, 2, 3, 4)) - 0.8 * sum(
        revenue(2018, q) for q in (1, 2, 3)
    )
    assert rev.value == pytest.approx(revenue(2018, 4))
    assert rev.one_basis
    assert rev.plain.value == pytest.approx(plain)
    assert rev.basis_note.code == "one_basis"
    assert rev.basis_note.params == {
        "item": "revenue",
        "period": "FY2018Q4",
        "value": rev.value,
        "plain_value": rev.plain.value,
        "basis": "first_filed",
    }
    # the figure a run reads for the same quarter on the same date
    run = build_inputs(conn, "TST", as_of, choices=CHOICES, today=AS_OF)
    assert by_key(run)[("history:revenue", "FY2018Q4")].value == pytest.approx(rev.value)
    # ratios use it and say so; a line not put on one basis has no plain value
    for name in ("operating_margin", "revenue_growth_yoy"):
        notes = {n.code: n.params for n in r.ratio(name).notes}
        assert notes["uses_one_basis_line"] == {"items": ["revenue"], "periods": ["FY2018Q4"]}
    ebit = r.line("operating_income")
    assert (ebit.one_basis, ebit.plain, ebit.basis_note) == (False, None, None)


def test_a_reported_quarter_and_a_year_are_never_put_on_one_basis(make_company):
    from tests.analysis.test_math_engine import recast_2018_quarters

    conn = make_company(recast_2018_quarters)
    as_of = date(2019, 12, 31)
    q1 = reported_period(conn, "TST", "FY2018Q1", as_of).line("revenue")
    assert (q1.one_basis, q1.plain, q1.changed) == (False, None, True)  # recast, as reported
    year = reported_period(conn, "TST", "FY2018", as_of).line("revenue")
    assert (year.one_basis, year.plain) == (False, None)
    margin = reported_period(conn, "TST", "FY2018", as_of).ratio("operating_margin")
    assert "uses_one_basis_line" not in {n.code for n in margin.notes}


def test_the_terminal_and_json_show_the_plain_derivation(make_company):
    from tests.analysis.test_math_engine import recast_2018_quarters

    conn = make_company(recast_2018_quarters)
    r = reported_period(conn, "TST", "FY2018Q4", date(2019, 12, 31))
    text = cli.render_reported(r)
    assert "on one basis; plain derivation" in text
    line = next(x for x in json.loads(json.dumps(r.to_dict()))["lines"] if x["name"] == "revenue")
    assert (line["one_basis"], line["basis_note"]["code"]) == (True, "one_basis")
    assert line["plain"]["inputs"]  # the filings the plain derivation came from


# -- backlog #295: growth across a tag that changed meaning -----------------------------------

CONTRACT = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _redefine_revenues(tag, row):
    """From the Q3 2019 10-Q (filed 2019-10-30), `Revenues` also counts other income (4% more),
    for the comparatives too; the old figures stay under the contract-revenue tag, as Exxon's
    did from its 2019-11-06 10-Q."""
    if tag != "Revenues" or row["filed"] < "2019-10-30":
        return row
    return [(tag, {**row, "val": row["val"] * 1.04}), (CONTRACT, row)]


def test_growth_across_a_tag_that_changed_meaning_says_so(make_company):
    conn = make_company(_redefine_revenues)
    r = reported_period(conn, "TST", "FY2019Q1", AS_OF)
    assert r.line("revenue").latest.xbrl_concept == "us-gaap:Revenues"
    growth = r.ratio("revenue_growth_yoy")
    assert growth.value == pytest.approx(1.04 * revenue(2019, 1) / revenue(2018, 1) - 1)
    notes = {n.code: n for n in growth.notes}
    note = notes["tag_changed_meaning"]
    assert note.params == {
        "item": "revenue",
        "tag": "us-gaap:Revenues",
        "other_tag": f"us-gaap:{CONTRACT}",
        "changed_on": "2019-10-30",
        "form": "10-Q",
        "accession_no": note.params["accession_no"],
        "new_meaning": "FY2019Q1",
        "old_meaning": "FY2018Q1",
    }
    assert "measure different lines" in note.text and "not like for like" in note.text


@pytest.mark.parametrize("period", ["FY2019Q3", "FY2019Q2", "FY2019"])
def test_growth_on_one_meaning_has_no_note(make_company, period):
    """Q3 against Q3 and the year against the year come from one filing on the new meaning; Q2
    against Q2 are both on the old one."""
    conn = make_company(_redefine_revenues)
    growth = reported_period(conn, "TST", period, AS_OF).ratio("revenue_growth_yoy")
    assert "tag_changed_meaning" not in {n.code for n in growth.notes}


def test_a_change_of_meaning_needs_two_periods_public(make_company):
    """FY2018Q3 is on the new meaning from the Q3 2019 10-Q, FY2017Q3 on the old. On 2019-12-31
    that 10-Q's one comparative is all that shows the change: no note yet. The FY2019 10-K adds
    two years, and the note dates the change by the 10-Q."""
    conn = make_company(_redefine_revenues)

    def codes(as_of):
        growth = reported_period(conn, "TST", "FY2018Q3", as_of).ratio("revenue_growth_yoy")
        return {n.code: n.params for n in growth.notes}

    assert "tag_changed_meaning" not in codes(date(2019, 12, 31))
    later = codes(AS_OF)["tag_changed_meaning"]
    assert (later["new_meaning"], later["old_meaning"]) == ("FY2018Q3", "FY2017Q3")
    assert later["changed_on"] == "2019-10-30"
