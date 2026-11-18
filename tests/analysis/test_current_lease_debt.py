"""The current portion of long-term debt is read on the non-current debt's basis (backlog #421):
Exxon tags its current portion with and without finance leases beside a lease-inclusive
non-current tag, and the plain current figure lost the leases due within a year."""

from datetime import date

import pytest

from domains.analysis.math_engine import debt_parts
from domains.fundamentals.concepts import concept_map_in_force
from domains.fundamentals.facts import (
    _get_facts,
    _merge_current,
    _placed,
    _quarterly,
    current_on_noncurrent_basis,
    get_facts,
    rounding_unit,
)
from domains.fundamentals.schemas import Fact
from tests.analysis.conftest import AS_OF
from tests.analysis.test_debt_current_inside import build, by_key

BEFORE_421 = "c621cb3eaf6ecc0fba17d01218f5fcd2a31a653ec2eb0731bcb2bd65d2f977f4"  # #408's map
WITH = "LongTermDebtAndCapitalLeaseObligationsCurrent"


def lease_inclusive(with_leases=24, noncurrent_tag="LongTermDebtAndCapitalLeaseObligations"):
    """Exxon's presentation: the non-current debt only under a lease-inclusive tag, and the
    current portion under both tags (the fixture's plain one is 20)."""

    def edit(tag, row):
        if tag == "LongTermDebtNoncurrent":
            return [(noncurrent_tag, row)]
        if tag == "LongTermDebtCurrent" and with_leases is not None:
            return [(tag, row), (WITH, {**row, "val": with_leases})]
        return row

    return edit


def test_a_lease_inclusive_noncurrent_reads_the_lease_inclusive_current(make_company):
    conn = make_company(lease_inclusive())
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 204  # 24 + 180, not 200
    assert rows[("balance:debt_current", "-")].value == 24
    assert WITH in rows[("balance:debt_current", "-")].method
    nwc = rows[("history:nwc", "FY2019")]
    assert nwc.value == pytest.approx((300 - 60) - (150 - 24))
    assert "FY2019 204" in rows[("cost_of_debt", "-")].method


def test_a_plain_noncurrent_keeps_the_plain_current(make_company):
    # Coca-Cola's presentation before 2024 (and any company counting finance leases on their
    # own line): the lease-inclusive current would count current leases twice
    conn = make_company(lease_inclusive(noncurrent_tag="LongTermDebtNoncurrent"))
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 200
    assert WITH not in rows[("balance:debt_current", "-")].method


@pytest.mark.parametrize("with_leases", [20, 19, 180])
def test_equal_smaller_or_the_noncurrent_again_keeps_the_plain_current(make_company, with_leases):
    # equal: the plain tag already holds any leases (Exxon 2020-2024); smaller: can't hold
    # leases too; equal to the non-current debt: the long-term debt under the wrong tag (Exxon
    # 2010-12-31, 12,227M beside 345M)
    conn = make_company(lease_inclusive(with_leases))
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 200
    assert WITH not in rows[("balance:debt_current", "-")].method


def test_the_lease_inclusive_current_alone_is_read_as_before(make_company):
    # Coca-Cola 2024+: only the lease-inclusive tags
    def only_with_leases(tag, row):
        if tag == "LongTermDebtNoncurrent":
            return [("LongTermDebtAndCapitalLeaseObligations", row)]
        if tag == "LongTermDebtCurrent":
            return [(WITH, {**row, "val": 22})]
        return row

    conn = make_company(only_with_leases)
    rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 202
    assert WITH in rows[("balance:debt_current", "-")].method


def test_a_map_before_421_reads_what_it_read_before(make_company):
    conn = make_company(lease_inclusive())
    with concept_map_in_force(conn, BEFORE_421, "TST"):
        rows = by_key(build(conn))
    assert rows[("debt", "-")].value == 200  # the plain tag ranked first, leases lost


def test_the_merged_fact_is_the_current_portion_and_nothing_else_is_returned(make_company):
    conn = make_company(lease_inclusive())
    facts = get_facts(conn, "0000000123", ["debt_current"], AS_OF, frequency="annual")
    assert {f.canonical_name for f in facts} == {"debt_current"}
    assert {f.xbrl_concept for f in facts} == {f"us-gaap:{WITH}"}
    assert all(f.value == 24 for f in facts)


def fact(item, value, tag):
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{tag}",
        period_end=date(2019, 12, 31),
        value=value,
        unit="USD",
        accession_no="0000034088-20-000016",
        filed_at=date(2020, 2, 26),
    )


def test_xom_2019_year_end():
    # Exxon's 10-K for 2019: current portion 1,617M, with finance leases 1,701M, non-current
    # (lease-inclusive) 26,342M
    plain = fact("debt_current", 1_617e6, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", 1_701e6, WITH)
    noncurrent = fact("debt_noncurrent", 26_342e6, "LongTermDebtAndCapitalLeaseObligations")
    current = current_on_noncurrent_basis(plain, with_leases, noncurrent)
    assert current.value == 1_701e6 and current.canonical_name == "debt_current"
    leases = fact("finance_lease_liabilities", 2_000e6, "FinanceLeaseLiability")
    by_item = {f.canonical_name: f for f in (current, noncurrent, leases)}
    total, _, _, notes = debt_parts(by_item.get)
    assert total == 1_701e6 + 26_342e6  # the lease line is skipped, the current leases kept
    assert "finance leases skipped" in notes
    # the filing's own total of debt due within one year adds up with the lease-inclusive
    # figure: bank loans 316 + commercial paper 18,561 + 1,701 = 20,578 (1,617 gives 20,494)
    assert 316 + 18_561 + current.value / 1e6 == 20_578


def test_a_large_lease_share_of_a_small_current_portion_is_kept():
    # Exxon's current portion was 181M at 2022-12-31: a lease portion near its size is real
    plain = fact("debt_current", 181e6, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", 400e6, WITH)
    noncurrent = fact("debt_noncurrent", 40_559e6, "LongTermDebtAndCapitalLeaseObligations")
    assert current_on_noncurrent_basis(plain, with_leases, noncurrent).value == 400e6


def test_xom_2010_year_end_mistag_is_not_read():
    plain = fact("debt_current", 345e6, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", 12_227e6, WITH)
    noncurrent = fact("debt_noncurrent", 12_227e6, "LongTermDebtAndCapitalLeaseObligations")
    assert current_on_noncurrent_basis(plain, with_leases, noncurrent) is plain


def test_none_without_either():
    assert current_on_noncurrent_basis(None, None, None) is None


# Backlog #427: pairing on the date alone, one fact per fiscal label, a rounded plain figure.

XOM_NONCURRENT = 26_342e6  # any lease-inclusive non-current debt


def choose(plain_value, with_leases_value, noncurrent_value=XOM_NONCURRENT):
    plain = fact("debt_current", plain_value, "LongTermDebtCurrent")
    with_leases = fact("debt_current_with_leases", with_leases_value, WITH)
    noncurrent = fact("debt_noncurrent", noncurrent_value, "LongTermDebtAndCapitalLeaseObligations")
    return current_on_noncurrent_basis(plain, with_leases, noncurrent)


@pytest.mark.parametrize(
    ("value", "unit"),
    [
        (6.2e9, 10**8),  # Exxon's "$6.2 billion" (decimals -8)
        (1.617e9, 10**6),
        (1_000e6 + 617e6, 10**6),  # a float sum is read in whole dollars
        (1.7e9, 10**8),  # precise, but looks rounded: the known limit
        (0, 0),  # no unit, so no margin
        (-5e6, 10**6),
        (1e15, 10**12),  # capped
    ],
)
def test_rounding_unit(value, unit):
    assert rounding_unit(value) == unit


def test_a_precise_lease_inclusive_figure_inside_a_rounded_plain_one_is_taken():
    # "$6.2 billion" stands for 6,150M to 6,250M, so a precise 6,180M with leases agrees with it
    current = choose(6_200e6, 6_180e6)
    assert current.value == 6_180e6 and current.xbrl_concept == f"us-gaap:{WITH}"
    assert current.canonical_name == "debt_current"


@pytest.mark.parametrize(
    ("plain", "with_leases"),
    [
        (6_200e6, 6_140e6),  # 60M below: outside half the 100M unit
        (6_200e6, 6_100e6),  # no more precise than the plain figure (both look rounded to 10^8)
        (1_617e6, 1_616e6),  # a plain figure precise to the million opens no margin
        (20, 19),  # nor one that looks rounded only below ten million (the fixture's 20)
        (0, -5e6),  # a plain zero (AAPL and MSFT file some) opens no margin
    ],
)
def test_outside_the_rounding_keeps_the_plain_figure(plain, with_leases):
    current = choose(plain, with_leases)
    assert current.value == plain and current.xbrl_concept == "us-gaap:LongTermDebtCurrent"


def test_a_precise_plain_figure_ending_in_zeros_looks_rounded():
    # the known limit (design doc): 1,700M exactly looks rounded to 10^8, so 1,660M is taken
    assert choose(1_700e6, 1_660e6).value == 1_660e6


def test_the_mistag_guard_beats_the_rounding_margin():
    # a lease-inclusive figure equal to the non-current debt is never taken, rounded plain or not
    assert choose(6_200e6, 6_180e6, noncurrent_value=6_180e6).value == 6_200e6


def test_a_rounded_plain_figure_alone_is_read_unchanged():
    plain = fact("debt_current", 6_200e6, "LongTermDebtCurrent")
    noncurrent = fact("debt_noncurrent", XOM_NONCURRENT, "LongTermDebtAndCapitalLeaseObligations")
    assert current_on_noncurrent_basis(plain, None, noncurrent) is plain


def relabel_with_leases(conn, years_back=1):
    """File every lease-inclusive current figure under a fiscal year `years_back` earlier, as if
    its filings had placed the same dates on another fiscal calendar."""
    conn.execute(
        "UPDATE financial_facts SET fiscal_year = fiscal_year - ? WHERE xbrl_concept = ?",
        (years_back, f"us-gaap:{WITH}"),
    )
    conn.commit()


@pytest.mark.parametrize("frequency", ["reported", "annual", "quarterly"])
@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_two_fiscal_labels_at_one_date_give_one_current_portion(make_company, mode, frequency):
    conn = make_company(lease_inclusive())
    before = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    relabel_with_leases(conn)
    facts = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    dates = [f.period_end for f in facts]
    assert len(dates) == len(set(dates))  # one current portion per date
    assert all(f.value == 24 for f in facts)  # the lease-inclusive figure, paired with the plain
    # each date keeps the plain figure's fiscal labels, where it sat before the relabel
    assert [(f.period_end, f.fiscal_year, f.fiscal_period) for f in facts] == [
        (f.period_end, f.fiscal_year, f.fiscal_period) for f in before
    ]


def at(item, value, tag, end):
    return Fact(
        canonical_name=item,
        xbrl_concept=f"us-gaap:{tag}",
        period_end=end,
        fiscal_year=2019,
        fiscal_period="FY",
        value=value,
        unit="USD",
        accession_no="0000034088-20-000016",
        filed_at=date(2020, 2, 26),
    )


def test_two_dates_under_one_fiscal_label_give_one_current_portion_by_label():
    # the plain figure at the year end, a lone lease-inclusive one three days earlier under the
    # same label: annual and quarterly reads keep one per label (the later date), as any item
    year_end, earlier = date(2019, 12, 31), date(2019, 12, 28)
    facts = [
        at("debt_current", 1_617e6, "LongTermDebtCurrent", year_end),
        at("debt_current_with_leases", 1_650e6, WITH, earlier),
        at("debt_noncurrent", XOM_NONCURRENT, "LongTermDebtAndCapitalLeaseObligations", year_end),
    ]
    annual = _merge_current(facts, ["debt_current"], "annual")
    assert [(f.period_end, f.value) for f in annual] == [(year_end, 1_617e6)]
    reported = _merge_current(facts, ["debt_current"], "reported")
    assert [f.period_end for f in reported] == [earlier, year_end]  # one per date


# Backlog #430: the two tags are paired on every filed date before the annual and quarterly reads
# place them, so a figure placed under another fiscal period (or none) is not dropped first.


def relabel_period(conn, tag, period, year_ends_only=True):
    """File every `tag` figure at a year end (or every one) under fiscal period `period`, or
    unplaced (`period=None`), as if its filings had placed the date differently."""
    where = " AND period_end LIKE '%-12-31'" if year_ends_only else ""
    if period is None:
        conn.execute(
            "UPDATE financial_facts SET fiscal_year = NULL, fiscal_period = NULL "
            f"WHERE xbrl_concept = ?{where}",
            (f"us-gaap:{tag}",),
        )
    else:
        conn.execute(
            f"UPDATE financial_facts SET fiscal_period = ? WHERE xbrl_concept = ?{where}",
            (period, f"us-gaap:{tag}"),
        )
    conn.commit()


def placed(facts):
    return [(f.period_end, f.fiscal_year, f.fiscal_period, f.value) for f in facts]


@pytest.mark.parametrize("period", ["Q3", None])
@pytest.mark.parametrize("frequency", ["annual", "quarterly"])
@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_a_year_end_lease_figure_under_another_period_is_still_paired(
    make_company, mode, frequency, period
):
    # the lease-inclusive year-end figures filed as Q3 (or unplaced): before #430 the annual read
    # dropped them before the merge (the plain 20 stood alone), and the quarterly read let a
    # mislabelled year end displace the real Q3 figure
    conn = make_company(lease_inclusive())
    before = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    relabel_period(conn, WITH, period)
    facts = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    assert placed(facts) == placed(before)
    assert facts and all(f.value == 24 for f in facts)


@pytest.mark.parametrize("period", ["Q3", None])
@pytest.mark.parametrize("frequency", ["annual", "quarterly"])
@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_a_plain_year_end_under_another_period_takes_the_year_end_label(
    make_company, mode, frequency, period
):
    # the plain figure's labels win as a rule (the single item before #421), but a date the
    # lease-inclusive figure places as a year end, and the plain one under a quarter or nowhere,
    # stays a year end: the annual read would drop it otherwise (main read it from the lease tag)
    conn = make_company(lease_inclusive())
    before = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    relabel_period(conn, "LongTermDebtCurrent", period)
    facts = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    assert placed(facts) == placed(before)
    assert facts and all(f.value == 24 for f in facts)


def test_the_plain_labels_win_otherwise():
    # both placed, neither as a year end only: the plain figure's labels, as #427 set
    plain = at("debt_current", 1_617e6, "LongTermDebtCurrent", date(2019, 12, 31))
    plain = plain.model_copy(update={"fiscal_period": "Q4"})
    with_leases = at("debt_current_with_leases", 1_701e6, WITH, date(2019, 12, 31))
    with_leases = with_leases.model_copy(update={"fiscal_year": 2020, "fiscal_period": "Q1"})
    noncurrent = at(
        "debt_noncurrent",
        XOM_NONCURRENT,
        "LongTermDebtAndCapitalLeaseObligations",
        date(2019, 12, 31),
    )
    current = current_on_noncurrent_basis(plain, with_leases, noncurrent)
    assert (current.value, current.fiscal_year, current.fiscal_period) == (1_701e6, 2019, "Q4")
    # and the plain figure chosen keeps its own labels
    lower = with_leases.model_copy(update={"value": 1_600e6})
    current = current_on_noncurrent_basis(plain, lower, noncurrent)
    assert current is plain


@pytest.mark.parametrize("frequency", ["reported", "annual", "quarterly"])
def test_an_unplaced_plain_figure_alone_reads_as_before(make_company, frequency):
    # Coca-Cola's plain presentation: no lease-inclusive tag, so nothing is paired
    conn = make_company(lease_inclusive(with_leases=None))
    before = get_facts(conn, "0000000123", ["debt_current"], AS_OF, frequency=frequency)
    assert before and all(f.value == 20 for f in before)


def lone_lease_figure(conn, end, value):
    """A lease-inclusive figure filed at `end` with no plain figure there, under FY 2019."""
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "VALUES ('0000000123', ?, NULL, ?, 2019, 'FY', ?, 'USD', '10-K', "
        "'0000000123-20-000099', '2020-02-20')",
        (f"us-gaap:{WITH}", end, value),
    )
    conn.commit()


@pytest.mark.parametrize("mode", ["latest", "first_reported"])
@pytest.mark.parametrize("frequency", ["annual", "quarterly"])
def test_get_facts_keeps_one_current_portion_per_fiscal_label(make_company, mode, frequency):
    # #427's one-per-label rule pinned through get_facts: a lone lease-inclusive figure three days
    # before the year end, under the same label, gives way to the later date
    conn = make_company(lease_inclusive())
    lone_lease_figure(conn, "2019-12-28", 30)
    facts = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    labels = [(f.fiscal_year, f.fiscal_period) for f in facts]
    assert len(labels) == len(set(labels))
    fy2019 = [f for f in facts if f.fiscal_year == 2019 and f.fiscal_period in ("FY", "Q4")]
    assert [(f.period_end, f.value) for f in fy2019] == [(date(2019, 12, 31), 24)]
    reported = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, "reported")
    assert date(2019, 12, 28) in {f.period_end for f in reported}  # one per date there


# Backlog #430 item 3: a run note when the rounding margin chooses the figure.


def rounded_presentation(plain, with_leases):
    """Exxon's presentation with every current portion scaled: a plain figure that looks rounded
    and a lease-inclusive one beside it."""

    def edit(tag, row):
        if tag == "LongTermDebtNoncurrent":
            return [("LongTermDebtAndCapitalLeaseObligations", row)]
        if tag == "LongTermDebtCurrent":
            return [(tag, {**row, "val": plain}), (WITH, {**row, "val": with_leases})]
        return row

    return edit


def test_a_note_when_the_rounding_margin_chooses_the_figure(make_company):
    # "$200 million" stands for 150M to 250M; a precise 195M with leases lies inside it
    conn = make_company(rounded_presentation(200e6, 195e6))
    result = build(conn)
    rows = by_key(result)
    assert rows[("balance:debt_current", "-")].value == 195e6
    notes = [
        n
        for n in result.notes
        if n.code == "debt_current_within_rounding" and n.params["used_for"] == "balance_sheet"
    ]
    assert len(notes) == 1
    params = notes[0].params
    assert params["debt_current"] == 195e6 and params["debt_current_plain"] == 200e6
    assert params["rounding_unit"] == 10**8 and params["currency"] == "USD"
    assert params["rounding_margin"] == 5e7 and params["gap"] == 5e6
    assert params["period_end"] == "2020-03-31"  # the balance sheet the run reads
    assert params["balance_date"] == "2020-03-31"
    # a quarter end: the cost of debt reads fiscal year ends, not this figure (backlog #451)
    assert params["assumptions"] == ["debt", "nwc_pct"]
    assert params["accession_no"]
    assert "195,000,000" in notes[0].text and "200,000,000" in notes[0].text
    assert "carried forward" not in notes[0].text


@pytest.mark.parametrize(
    ("plain", "with_leases"),
    [
        (200e6, 210e6),  # above: #421's rule, no judgement on rounding
        (200e6, 200e6),  # equal: the plain tag is read
        (200e6, 140e6),  # outside the margin: the plain figure is read
    ],
)
def test_no_rounding_note_otherwise(make_company, plain, with_leases):
    conn = make_company(rounded_presentation(plain, with_leases))
    result = build(conn)
    assert not [n for n in result.notes if n.code == "debt_current_within_rounding"]


def test_the_rounded_plain_figure_is_carried_only_when_the_margin_decides():
    assert choose(6_200e6, 6_180e6).rounded_plain == 6_200e6
    assert choose(6_200e6, 6_234e6).rounded_plain is None  # above: the plain one is not needed
    assert choose(6_200e6, 6_140e6).rounded_plain is None  # the plain figure itself is read


# Backlog #451: the note wherever the rounding-chosen figure is counted.


def rounding_notes(notes, used_for=None):
    return [
        n
        for n in notes
        if n.code == "debt_current_within_rounding"
        and (used_for is None or n.params["used_for"] == used_for)
    ]


def test_a_note_for_each_year_end_of_the_cost_of_debt(make_company):
    conn = make_company(rounded_presentation(200e6, 195e6))
    result = build(conn)
    [kd] = [a for a in result.assumptions if a.name == "cost_of_debt"]
    notes = rounding_notes(result.notes, "cost_of_debt_average")
    assert len(notes) == 2  # the two year ends of the average, neither the balance sheet's
    years = sorted(n.params["fiscal_year"] for n in notes)
    assert years[1] == years[0] + 1 and f"FY{years[1]} interest" in kd.method
    for n in notes:
        p = n.params
        assert p["assumptions"] == ["cost_of_debt"]
        assert p["balance_date"] == p["period_end"]  # its own year end, never carried
        assert p["debt_current"] == 195e6 and p["gap"] == 5e6
        assert f"FY{p['fiscal_year']} cost of debt" in n.text
        assert "carried forward" not in n.text
    assert len(rounding_notes(result.notes)) == 3


@pytest.mark.parametrize(("plain", "with_leases"), [(200e6, 210e6), (200e6, 140e6)])
def test_no_year_end_or_reported_note_when_the_margin_does_not_decide(
    make_company, plain, with_leases
):
    from domains.analysis.reported import reported_period

    conn = make_company(rounded_presentation(plain, with_leases))
    assert not rounding_notes(build(conn).notes)
    net_debt = reported_period(conn, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    assert not rounding_notes(net_debt.notes)


def test_a_year_end_that_is_the_balance_sheet_adds_cost_of_debt_to_its_note():
    from domains.analysis.math_engine import _year_end_rounding_notes, rounding_note

    year_end = choose(200e6, 195e6).model_copy(
        update={"canonical_name": "debt_current", "fiscal_year": 2019}
    )
    other = year_end.model_copy(update={"period_end": date(2018, 12, 31), "fiscal_year": 2018})
    balance = rounding_note(year_end, year_end.period_end, "balance_sheet", ["debt", "nwc_pct"])

    class Result:
        notes = [balance]

    _year_end_rounding_notes([other], [year_end], result=Result)
    assert balance.params["assumptions"] == ["debt", "cost_of_debt", "nwc_pct"]
    [added] = [n for n in Result.notes if n is not balance]
    assert added.params["fiscal_year"] == 2018 and added.params["period_end"] == "2018-12-31"
    _year_end_rounding_notes([year_end], result=Result)  # once only
    assert balance.params["assumptions"] == ["debt", "cost_of_debt", "nwc_pct"]
    assert len(Result.notes) == 2


def test_a_carried_forward_figure_names_the_balance_date(make_company):
    edit = rounded_presentation(200e6, 195e6)

    def no_current_at_the_quarter(tag, row):
        if tag == "LongTermDebtCurrent" and row["end"] == "2020-03-31":
            return None
        return edit(tag, row)

    result = build(make_company(no_current_at_the_quarter))
    [note] = rounding_notes(result.notes, "balance_sheet")
    assert note.params["period_end"] == "2019-12-31"
    assert note.params["balance_date"] == "2020-03-31"
    assert "(carried forward to the 2020-03-31 balance sheet)" in note.text


def test_the_reported_net_debt_carries_the_note(make_company):
    from domains.analysis.reported import reported_period

    conn = make_company(rounded_presentation(200e6, 195e6))
    net_debt = reported_period(conn, "TST", "FY2020Q1", AS_OF).ratio("net_debt")
    [note] = rounding_notes(net_debt.notes)
    p = note.params
    assert p["used_for"] == "net_debt" and "assumptions" not in p
    assert p["period_end"] == p["balance_date"] == "2020-03-31"
    assert p["debt_current"] == 195e6 and p["debt_current_plain"] == 200e6


def test_an_unknown_use_is_refused():
    from domains.analysis.math_engine import rounding_note

    with pytest.raises(ValueError):
        rounding_note(choose(200e6, 195e6), date(2020, 3, 31), "somewhere")


# Backlog #451 item 6 (PR #452 gatekeeper): annual and quarterly reads of the current portion come
# from the placed read (`facts._placed`) over a reported read, not from `_get_facts`'s own path.
# With two tags mapped to `debt_current` itself (CAT's maturities tag, priority 2), the placed read
# must rank them as the single-item read does: the plain tag where both are filed, the other where
# only it is.
MATURITIES = "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"


def second_current_tag(conn, value=25, drop_plain_at="2019-12-31"):
    """File the maturities tag beside every plain current figure (a different value), and drop
    the plain figure at one date so that date has the second-ranked tag only."""
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "SELECT cik, ?, period_start, period_end, fiscal_year, fiscal_period, ?, unit, form, "
        "accession_no, filed_at FROM financial_facts WHERE xbrl_concept = ?",
        (f"us-gaap:{MATURITIES}", value, "us-gaap:LongTermDebtCurrent"),
    )
    conn.execute(
        "DELETE FROM financial_facts WHERE xbrl_concept = ? AND period_end = ?",
        ("us-gaap:LongTermDebtCurrent", drop_plain_at),
    )
    conn.commit()


def read(facts):
    return [(f.period_end, f.fiscal_year, f.fiscal_period, f.value, f.xbrl_concept) for f in facts]


@pytest.mark.parametrize(
    "noncurrent_tag", ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"]
)
@pytest.mark.parametrize("frequency", ["annual", "quarterly"])
@pytest.mark.parametrize("mode", ["latest", "first_reported"])
def test_the_placed_read_ranks_two_current_tags_as_the_single_item_read(
    make_company, mode, frequency, noncurrent_tag
):
    # no lease-inclusive current figure: the merge must give what the item alone gives
    conn = make_company(lease_inclusive(with_leases=None, noncurrent_tag=noncurrent_tag))
    second_current_tag(conn)
    merged = get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    alone = _get_facts(conn, "0000000123", ["debt_current"], AS_OF, mode, frequency)
    assert read(merged) == read(alone)
    tags = {f.period_end: f.xbrl_concept for f in merged}
    assert tags[date(2019, 12, 31)] == f"us-gaap:{MATURITIES}"  # the only one filed there
    assert {t for d, t in tags.items() if d != date(2019, 12, 31)} == {
        "us-gaap:LongTermDebtCurrent"
    }  # the plain tag ranks first wherever both are filed


# Backlog #451 item 7 (PR #452 gatekeeper): a balance labelled FY and one labelled Q4 of the same
# fiscal year at two dates both came back as Q4 in quarterly mode, for every balance item.


def balance(item, value, end, period):
    return Fact(
        canonical_name=item,
        xbrl_concept="us-gaap:Cash",
        period_end=end,
        fiscal_year=2019,
        fiscal_period=period,
        value=value,
        unit="USD",
        accession_no="0000000123-20-000099",
        filed_at=date(2020, 2, 15),
    )


@pytest.mark.parametrize("later", ["FY", "Q4"])
def test_fy_and_q4_of_one_year_at_two_dates_are_one_quarter(later):
    earlier = "Q4" if later == "FY" else "FY"
    facts = [
        balance("cash", 60, date(2019, 12, 28), earlier),
        balance("cash", 61, date(2019, 12, 31), later),
    ]
    quarters = _quarterly(facts)
    assert [(f.period_end, f.fiscal_period, f.value) for f in quarters] == [
        (date(2019, 12, 31), "Q4", 61)  # the later date, as for two dates under one label
    ]
    assert placed(_placed(facts, "quarterly")) == [(date(2019, 12, 31), 2019, "Q4", 61)]
    # the annual read keeps only the FY-labelled one, as before
    [annual] = _placed(facts, "annual")
    assert annual.fiscal_period == "FY" and annual.period_end == date(
        2019, 12, 31 if later == "FY" else 28
    )


def test_fy_and_q4_at_one_date_stay_one_fact_and_other_years_are_untouched():
    facts = [
        balance("cash", 60, date(2019, 12, 31), "FY"),
        balance("cash", 50, date(2019, 9, 30), "Q3"),
    ]
    assert placed(_quarterly(facts)) == [
        (date(2019, 9, 30), 2019, "Q3", 50),
        (date(2019, 12, 31), 2019, "Q4", 60),
    ]
