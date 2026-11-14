"""A share count of zero or below is never used (backlog #364)."""

import pytest

from domains.analysis.math_engine import EngineError, build_inputs
from tests.analysis.conftest import AS_OF, CHOICES

COVER = "dei:EntityCommonStockSharesOutstanding"
DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"
NEWEST_COVER_END = "2020-04-20"  # filed 2020-04-30 with the Q1 2020 10-Q
EARLIER_COVER_END = "2020-02-05"  # filed 2020-02-15 with the FY2019 10-K


def build(conn):
    return build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def notes(result, code="shares_not_positive"):
    return [n for n in result.notes if n.code == code]


def shares_row(result):
    return next(a for a in result.assumptions if a.name == "shares")


def set_cover(conn, value, period_end=None):
    sql = "UPDATE financial_facts SET value = ? WHERE xbrl_concept = ?"
    args = [value, COVER]
    if period_end is not None:
        sql += " AND period_end = ?"
        args.append(period_end)
    conn.execute(sql, args)
    return conn


def newest_diluted(change):
    """Change the newest quarter's diluted count (Q1 2020, filed 2020-04-30)."""

    def edit(tag, row):
        if tag == DILUTED and row["filed"] == "2020-04-30" and row["end"] == "2020-03-31":
            return {**row, "val": change}
        return row

    return edit


def every_diluted(change):
    def edit(tag, row):
        return {**row, "val": change} if tag == DILUTED else row

    return edit


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_a_newest_cover_count_not_above_zero_gives_way_to_the_one_before(company, value):
    set_cover(company, 95, EARLIER_COVER_END)
    set_cover(company, value, NEWEST_COVER_END)
    result = build(company)
    shares = shares_row(result)
    assert shares.value == 95
    assert EARLIER_COVER_END in shares.method
    (note,) = notes(result)
    assert note.params == {
        "count": "cover",
        "value": value,
        "accession_no": note.params["accession_no"],
        "period_end": NEWEST_COVER_END,
    }
    assert note.params["accession_no"]
    assert note.text == (
        f"Cover-page shares for {NEWEST_COVER_END} are filed as {value:g} "
        f"({note.params['accession_no']}); a share count must be above zero, so that count is "
        "not used"
    )


def test_an_older_cover_count_of_zero_is_not_noted(company):
    set_cover(company, 0.0, EARLIER_COVER_END)
    result = build(company)
    assert shares_row(result).value == 100
    assert not notes(result)


def test_with_every_cover_count_at_zero_the_fallback_is_used_and_the_newest_noted(company):
    result = build(set_cover(company, 0.0))
    shares = shares_row(result)
    assert shares.value == 100
    assert shares.method.startswith("fallback: weighted diluted shares")
    (note,) = notes(result)
    assert note.params["count"] == "cover"
    assert note.params["period_end"] == NEWEST_COVER_END


def test_a_newest_diluted_count_of_zero_beside_the_cover_is_not_compared(make_company):
    """Before #364 this divided by zero in the cover-against-diluted check."""
    result = build(make_company(newest_diluted(0.0)))
    assert shares_row(result).value == 100
    (note,) = notes(result)
    assert note.params["count"] == "diluted"
    assert note.params["period_end"] == "2020-03-31"
    assert note.text.startswith("Diluted shares for 2020-03-31 are filed as 0 (")
    assert not notes(result, "shares_cover_differs")
    assert not notes(result, "shares_scale_mismatch")


def test_the_fallback_skips_a_diluted_count_of_zero(make_company):
    conn = make_company(newest_diluted(-100.0))
    conn.execute("DELETE FROM financial_facts WHERE xbrl_concept = ?", (COVER,))
    result = build(conn)
    shares = shares_row(result)
    assert shares.value == 100
    assert "2020-03-31" not in shares.method
    (note,) = notes(result)
    assert note.params["count"] == "diluted"
    assert note.params["value"] == -100.0
    assert not notes(result, "shares_scale_mismatch")


def test_no_count_above_zero_is_refused(make_company):
    conn = set_cover(make_company(every_diluted(0.0)), 0.0)
    with pytest.raises(EngineError, match="no share count above zero reported"):
        build(conn)


def test_counts_above_zero_change_nothing(company):
    result = build(company)
    assert shares_row(result).value == 100
    assert not notes(result)
