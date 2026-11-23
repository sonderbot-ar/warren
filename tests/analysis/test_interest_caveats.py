"""Companies whose interest line is not the interest on their debt (backlog #542)."""

import pytest

from domains.analysis.interest_caveats import (
    CAVEAT_CODES,
    COLUMNS,
    InterestCaveatError,
    caveat_for,
    load_interest_caveats,
)

HEADER = ",".join(COLUMNS)
JNJ = "JNJ,interest_net_of_hedge_gains,2019,,debt_effective_rate,10-K tables,why"


def write(tmp_path, *rows, header=HEADER):
    path = tmp_path / "caveats.csv"
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


def test_the_shipped_file_has_the_jnj_row_only():
    [row] = load_interest_caveats()
    assert (row.ticker, row.code, row.from_fiscal_year, row.to_fiscal_year) == (
        "JNJ",
        "interest_net_of_hedge_gains",
        2019,
        None,
    )
    assert row.rate_item == "debt_effective_rate"
    assert "0000200406-22-000022" in row.evidence and "ASU 2017-12" in row.evidence
    assert row.code in CAVEAT_CODES


def test_caveat_for_covers_its_years_and_company_only():
    assert caveat_for("JNJ", 2019).code == "interest_net_of_hedge_gains"
    assert caveat_for("JNJ", 2025) is not None and caveat_for("JNJ", 2040) is not None
    assert caveat_for("JNJ", 2018) is None
    for ticker in ("AAPL", "MSFT", "KO", "XOM", "PG", "CAT", "WMT"):
        assert caveat_for(ticker, 2021) is None


def test_a_closed_range_ends_at_its_last_year(tmp_path):
    [row] = load_interest_caveats(write(tmp_path, JNJ.replace("2019,,", "2019,2021,")))
    assert row.covers(2019) and row.covers(2021) and not row.covers(2022)


def test_every_problem_is_reported_with_its_line(tmp_path):
    path = write(
        tmp_path,
        "ZZZZ,interest_net_of_hedge_gains,2019,,,x,",
        "JNJ,made_up_code,2019,,,x,",
        "JNJ,interest_net_of_hedge_gains,2021,2020,,x,",
        "JNJ,interest_net_of_hedge_gains,2019,,revenue,x,",
        "KO,interest_net_of_hedge_gains,twenty,,,x,",
        "PG,interest_net_of_hedge_gains,2019,,,,",
    )
    with pytest.raises(InterestCaveatError) as err:
        load_interest_caveats(path)
    text = str(err.value)
    assert "caveats.csv line 2: 'ZZZZ' is not in universe.csv" in text
    assert "line 3: code 'made_up_code'" in text
    assert "line 4: to_fiscal_year 2020 is before from_fiscal_year 2021" in text
    assert "line 5: rate_item 'revenue' is not a reported-only map item" in text
    assert "line 6: fiscal years must be whole numbers" in text
    assert "line 7: evidence is empty" in text


def test_two_rows_for_one_company_and_code_may_not_overlap(tmp_path):
    path = write(tmp_path, JNJ, JNJ.replace("2019,,", "2015,2019,"))
    with pytest.raises(InterestCaveatError, match="line 3: overlaps caveats.csv line 2"):
        load_interest_caveats(path)
    apart = write(tmp_path, JNJ, JNJ.replace("2019,,", "2010,2012,"))
    assert len(load_interest_caveats(apart)) == 2


def test_wrong_columns_are_refused(tmp_path):
    with pytest.raises(InterestCaveatError, match="expected columns"):
        load_interest_caveats(write(tmp_path, JNJ, header="ticker,code"))
