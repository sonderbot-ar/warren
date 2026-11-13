"""A share count filed in the wrong unit is named and never used (backlog #343)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domains.analysis.math_engine import SHARE_SCALES, SHARES_TOLERANCE, build_inputs, share_scale
from tests.analysis.conftest import AS_OF, CHOICES

COVER = "dei:EntityCommonStockSharesOutstanding"
DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"

counts = st.floats(min_value=1.0, max_value=1e10, allow_nan=False, allow_infinity=False)
near_one = st.floats(min_value=1 - SHARES_TOLERANCE * 0.99, max_value=1 + SHARES_TOLERANCE * 0.99)


@given(counts, counts)
def test_share_scale_is_symmetric(a, b):
    assert share_scale(a, b) == share_scale(b, a)


@given(counts, near_one)
def test_counts_within_the_tolerance_have_no_scale(a, wobble):
    assert share_scale(a, a * wobble) is None


@given(counts, st.sampled_from(SHARE_SCALES), near_one)
def test_a_count_a_thousand_or_a_million_off_is_found(a, scale, wobble):
    assert share_scale(a, a * scale * wobble) == scale
    assert share_scale(a * wobble, a / scale) == scale  # the larger one wobbles


@pytest.mark.parametrize("ratio", [700, 1_300, 2, 7, 500_000, 1_200_000])
def test_other_gaps_are_not_a_unit_error(ratio):
    assert share_scale(100.0, 100.0 * ratio) is None


@pytest.mark.parametrize("value", [0.0, -5.0])
def test_a_count_that_is_not_positive_has_no_scale(value):
    assert share_scale(value, 100.0) is None


def build(conn):
    return build_inputs(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def notes(result, code):
    return [n for n in result.notes if n.code == code]


def shares_row(result):
    return next(a for a in result.assumptions if a.name == "shares")


def newest(tag_to_change, change):
    """Rescale the newest quarter's diluted count (Q1 2020, filed 2020-04-30)."""

    def edit(tag, row):
        if tag == tag_to_change and row["filed"] == "2020-04-30" and row["end"] == "2020-03-31":
            return {**row, "val": change(row["val"])}
        return row

    return edit


def without_cover(conn):
    conn.execute("DELETE FROM financial_facts WHERE xbrl_concept = ?", (COVER,))
    return conn


@pytest.mark.parametrize("scale", SHARE_SCALES)
@pytest.mark.parametrize("smaller", [True, False])
def test_a_diluted_count_in_the_wrong_unit_beside_the_cover_is_named(make_company, scale, smaller):
    change = (lambda v: v / scale) if smaller else (lambda v: v * scale)
    result = build(make_company(newest(DILUTED, change)))
    assert not notes(result, "shares_cover_differs")
    (note,) = notes(result, "shares_scale_mismatch")
    diluted = 100 / scale if smaller else 100 * scale
    assert note.params == {
        "cover_shares_adjusted": 100,
        "tolerance": SHARES_TOLERANCE,
        "diluted_shares_adjusted": pytest.approx(diluted),
        "scale": scale,
        "diluted_accession_no": note.params["diluted_accession_no"],
        "diluted_period_end": "2020-03-31",
    }
    assert note.params["diluted_accession_no"]
    assert f"about {scale:,} times apart" in note.text
    assert note.text.endswith("the cover-page count is used")
    assert shares_row(result).value == 100  # the cover count, as before


@pytest.mark.parametrize("ratio", [1.5, 700, 1_300])
def test_any_other_gap_beside_the_cover_is_still_a_difference(company, ratio):
    company.execute(
        "UPDATE financial_facts SET value = ? WHERE xbrl_concept = ?", (100 * ratio, COVER)
    )
    result = build(company)
    assert not notes(result, "shares_scale_mismatch")
    assert len(notes(result, "shares_cover_differs")) == 1


def test_without_a_cover_count_the_fallback_is_unchanged(make_company):
    result = build(without_cover(make_company(None)))
    assert shares_row(result).value == 100
    assert shares_row(result).method.startswith("fallback: weighted diluted shares")
    assert not notes(result, "shares_scale_mismatch")


@pytest.mark.parametrize("scale", SHARE_SCALES)
def test_the_fallback_skips_a_count_in_the_wrong_unit(make_company, scale):
    result = build(without_cover(make_company(newest(DILUTED, lambda v: v / scale))))
    shares = shares_row(result)
    assert shares.value == 100  # an earlier filed count, not 100 / scale
    assert "2020-03-31" not in shares.method
    (note,) = notes(result, "shares_scale_mismatch")
    assert note.params["median_diluted_adjusted"] == 100
    assert note.params["diluted_shares_adjusted"] == pytest.approx(100 / scale)
    assert note.params["scale"] == scale
    assert note.params["diluted_period_end"] == "2020-03-31"
    assert "cover_shares_adjusted" not in note.params
    assert note.text.endswith("that count is not used")
