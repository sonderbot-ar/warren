"""A tag that changes meaning (backlog #295): a later filing gives the best tag a new value for
periods filed before, and repeats the old value under another tag of the same item. Modelled on
Exxon's revenue: `Revenues` moved from sales to total revenues and other income in its
2019-11-06 10-Q, while `RevenueFromContractWithCustomerExcludingAssessedTax` kept the sales."""

from dataclasses import replace
from datetime import date

import pytest

from domains.fundamentals.concepts import load_concept_map, sync_concepts
from domains.fundamentals.facts import Fact, meaning_of, meaning_state, tag_meaning_changes

CIK = "0000000123"
BEST, OTHER = "us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
Q3 = ("2018-07-01", "2018-09-30")
M9 = ("2018-01-01", "2018-09-30")
FY = ("2018-01-01", "2018-12-31")


@pytest.fixture
def db(conn):
    sync_concepts(conn, load_concept_map())
    conn.execute("INSERT INTO companies (cik, ticker, name) VALUES (?, 'TST', 'Test Corp')", (CIK,))
    return conn


def put(conn, tag, period, value, accession, filed_at, form="10-Q"):
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "VALUES (?, ?, ?, ?, 2018, 'Q3', ?, 'USD', ?, ?, ?)",
        (CIK, tag, *period, value, form, accession, filed_at),
    )


def first_filings(conn):
    put(conn, BEST, Q3, 74_187, "a-2018-q3", "2018-11-07")
    put(conn, BEST, M9, 211_079, "a-2018-q3", "2018-11-07")


def redefine(conn, periods=(Q3, M9), keep_old=True):
    """The 2019 Q3 10-Q: the best tag's comparatives on the new meaning, the old figures kept
    under another tag (or not, which is a restatement)."""
    old = {Q3: 74_187, M9: 211_079}
    new = {Q3: 76_605, M9: 218_317}
    for period in periods:
        put(conn, BEST, period, new[period], "b-2019-q3", "2019-11-06")
        if keep_old:
            put(conn, OTHER, period, old[period], "b-2019-q3", "2019-11-06")


def test_a_redefined_tag_is_found_and_dated_by_its_first_filing(db):
    first_filings(db)
    redefine(db)
    (change,) = tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09")
    assert (change.canonical_name, change.xbrl_concept, change.other_concept) == (
        "revenue",
        BEST,
        OTHER,
    )
    assert (change.accession_no, change.form, change.filed_at) == (
        "b-2019-q3",
        "10-Q",
        date(2019, 11, 6),
    )
    assert change.periods == [
        (date(2018, 1, 1), date(2018, 9, 30), 211_079, 218_317),
        (date(2018, 7, 1), date(2018, 9, 30), 74_187, 76_605),
    ]


def test_nothing_is_found_before_the_filing_is_public(db):
    first_filings(db)
    redefine(db)
    assert tag_meaning_changes(db, CIK, ["revenue"], "2019-11-05") == []


def test_one_period_alone_is_not_a_change_of_meaning(db):
    """JNJ's cash at 2023-01-01: cut for Kenvue in one 10-Q, kept whole under the restricted-cash
    tag. One recast period is more often a restatement."""
    first_filings(db)
    redefine(db, periods=(Q3,))
    assert tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09") == []


def test_a_restatement_without_the_old_figure_is_not_a_change_of_meaning(db):
    first_filings(db)
    redefine(db, keep_old=False)
    assert tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09") == []


def test_a_move_inside_the_threshold_is_not_a_change(db):
    put(db, BEST, Q3, 1_000, "a", "2018-11-07")
    put(db, BEST, M9, 3_000, "a", "2018-11-07")
    for period, value in ((Q3, 1_004), (M9, 3_012)):  # 0.4% moves
        put(db, BEST, period, value, "b", "2019-11-06")
    put(db, OTHER, Q3, 1_000, "b", "2019-11-06")
    put(db, OTHER, M9, 3_000, "b", "2019-11-06")
    assert tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09") == []


def test_periods_counted_across_filings_and_dated_by_the_first(db):
    """Exxon: the 10-Q shows two redefined periods, the next 10-K two more; still one change,
    dated by the 10-Q."""
    first_filings(db)
    put(db, BEST, FY, 279_332, "a-2018-k", "2019-02-27", form="10-K")
    redefine(db, periods=(Q3,))
    put(db, BEST, FY, 290_212, "c-2019-k", "2020-02-26", form="10-K")
    put(db, OTHER, FY, 279_332, "c-2019-k", "2020-02-26", form="10-K")
    assert tag_meaning_changes(db, CIK, ["revenue"], "2020-02-25") == []  # one period so far
    (change,) = tag_meaning_changes(db, CIK, ["revenue"], "2020-02-26")
    assert (change.accession_no, len(change.periods)) == ("b-2019-q3", 2)


def _fact(tag, filed_at, derived=False, inputs=()):
    return Fact(
        canonical_name="revenue",
        xbrl_concept=tag,
        period_start=date(2018, 10, 1),
        period_end=date(2018, 12, 31),
        value=1.0,
        unit="USD",
        filed_at=filed_at,
        derived=derived,
        inputs=list(inputs),
    )


def test_meaning_of_reads_the_tag_and_the_newest_input(db):
    first_filings(db)
    redefine(db)
    changes = tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09")
    assert meaning_of(_fact(BEST, date(2019, 11, 5)), changes) is None  # filed before
    assert meaning_of(_fact(BEST, date(2019, 11, 6)), changes) is changes[0]
    assert meaning_of(_fact(OTHER, date(2020, 1, 1)), changes) is None  # the other tag
    derived = _fact(f"{BEST} − {OTHER}", date(2020, 2, 26), derived=True)
    assert meaning_of(derived, changes) is changes[0]
    assert meaning_of(_fact(BEST, date(2020, 1, 1)), []) is None


# -- backlog #297: old, new or mixed ----------------------------------------------------------


def test_a_derived_quarter_with_inputs_on_both_sides_is_mixed(db):
    """Exxon FY2017Q4 plain: the year from the 2020 10-K (new) less nine months from 2017 (old)."""
    first_filings(db)
    redefine(db)
    changes = tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09")
    filed = {"k-2020": date(2020, 2, 26), "q-2017": date(2017, 11, 7), "q-2019": date(2019, 11, 6)}
    mixed = _fact(BEST, date(2020, 2, 26), derived=True, inputs=["k-2020", "q-2017"])
    assert meaning_state(mixed, changes, filed) == ("mixed", changes[0])
    assert meaning_of(mixed, changes, filed) is None
    new = _fact(BEST, date(2020, 2, 26), derived=True, inputs=["k-2020", "q-2019"])
    assert meaning_state(new, changes, filed) == ("new", changes[0])
    old = _fact(BEST, date(2017, 11, 7), derived=True, inputs=["q-2017"])
    assert meaning_state(old, changes, filed) == ("old", changes[0])
    # without the inputs' dates a derived quarter is judged on its newest input, as in v0.9.46
    assert meaning_state(mixed, changes) == ("new", changes[0])


def test_a_reported_value_is_never_mixed_and_an_unchanged_tag_has_no_change(db):
    first_filings(db)
    redefine(db)
    changes = tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09")
    filed = {"x": date(2017, 1, 1)}
    assert meaning_state(_fact(BEST, date(2020, 1, 1)), changes, filed) == ("new", changes[0])
    assert meaning_state(_fact(OTHER, date(2020, 1, 1)), changes, filed) == ("old", None)


def test_two_changes_of_one_tag_are_dated_by_the_earliest(db):
    """If one tag ever shows two "other tags", the earliest change dates the fact."""
    first_filings(db)
    redefine(db)
    (change,) = tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09")
    later = replace(change, other_concept="us-gaap:SalesRevenueNet", filed_at=date(2020, 2, 26))
    for changes in ([change, later], [later, change]):
        assert meaning_state(_fact(BEST, date(2020, 3, 1)), changes) == ("new", change)
        assert meaning_state(_fact(BEST, date(2019, 12, 1)), changes) == ("new", change)


def test_the_quality_report_keeps_only_periods_in_its_fiscal_years(db):
    """Like `disagreements`, the report's meaning changes are cut to its fiscal years (#297)."""
    from domains.fundamentals.quality import QualityReport, _within_years

    first_filings(db)
    redefine(db)
    changes = tag_meaning_changes(db, CIK, ["revenue"], "2026-11-09")

    def cells(start, end):
        span = {"period_start": date.fromisoformat(start), "period_end": date.fromisoformat(end)}
        fact = _fact(BEST, date(2020, 1, 1)).model_copy(update=span)
        return {("revenue", 2018, "FY"): fact}

    (kept,) = _within_years(changes, cells("2018-01-01", "2018-12-31"))
    assert len(kept.periods) == 2 and kept.filed_at == date(2019, 11, 6)
    assert _within_years(changes, cells("2018-10-01", "2018-12-31")) == []  # both end 2018-09-30
    assert _within_years(changes, cells("2020-01-01", "2020-12-31")) == []
    assert _within_years(changes, {}) == []

    report = QualityReport("TST", CIK, "Test Corp", date(2026, 11, 9), ["revenue"])
    report.meaning_changes = changes
    text = report.to_markdown()
    assert "measure different lines" in text and "redefined" not in text
