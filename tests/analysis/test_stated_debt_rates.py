"""The rates companies state on their own debt, and which debt each covers (backlog #543)."""

import pytest

from domains.analysis.stated_debt_rates import (
    ACCESSION,
    COLUMNS,
    SHORT_RATE_COVERS,
    StatedDebtRatesError,
    load_stated_debt_rates,
    stated_rates_for,
)

HEADER = ",".join(COLUMNS)
KO = (
    "KO,debt_average_rate_long_term,debt_average_rate_short_term,short_term_borrowings,"
    "10-K 0000021344-22-000009"
)


def write(tmp_path, *rows, header=HEADER):
    path = tmp_path / "rates.csv"
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


def test_the_shipped_rows_say_which_debt_each_short_rate_covers():
    rows = {r.ticker: r for r in load_stated_debt_rates()}
    assert set(rows) == {"KO", "PG", "JNJ"}
    assert (rows["KO"].long_rate_item, rows["KO"].short_rate_item) == (
        "debt_average_rate_long_term",
        "debt_average_rate_short_term",
    )
    assert rows["KO"].short_rate_covers == "short_term_borrowings"
    assert rows["PG"].short_rate_covers == "due_within_one_year"
    assert rows["PG"].short_rate_item == "debt_average_rate_short_term"
    assert rows["JNJ"].long_rate_item == "debt_effective_rate"
    assert rows["JNJ"].short_rate_item is None and rows["JNJ"].short_rate_covers is None
    for row in rows.values():
        assert row.accessions, row.ticker
        assert ACCESSION.search(row.evidence)
        assert row.short_rate_covers in (*SHORT_RATE_COVERS, None)
    assert rows["KO"].accessions == ("0000021344-22-000009",)
    assert rows["PG"].accessions == ("0000080424-22-000064",)
    assert rows["JNJ"].accessions == ("0000200406-22-000022",)


def test_stated_rates_for_returns_the_shipped_row_or_none():
    assert stated_rates_for("KO").short_rate_covers == "short_term_borrowings"
    assert stated_rates_for("PG").ticker == "PG"
    for ticker in ("AAPL", "MSFT", "XOM", "WMT", "TST", ""):
        assert stated_rates_for(ticker) is None


def test_the_covers_values_name_the_debt_they_put_under_the_short_rate():
    assert SHORT_RATE_COVERS["short_term_borrowings"] == {
        "short_term_borrowings",
        "commercial_paper",
    }
    assert SHORT_RATE_COVERS["due_within_one_year"] == {
        "short_term_borrowings",
        "commercial_paper",
        "debt_current",
        "debt_current_total",
    }


def test_a_valid_file_loads_and_a_missing_short_rate_is_allowed(tmp_path):
    jnj = "JNJ,debt_effective_rate,,,10-K 0000200406-22-000022"
    ko, plain = load_stated_debt_rates(write(tmp_path, KO, jnj))
    assert ko.accessions == ("0000021344-22-000009",)
    assert plain.short_rate_item is None and plain.short_rate_covers is None


def test_every_problem_is_reported_with_its_line(tmp_path):
    ok = "10-K 0000021344-22-000009"
    path = write(
        tmp_path,
        f"ZZZZ,debt_average_rate_long_term,,,{ok}",
        f"KO,revenue,,,{ok}",
        f"PG,debt_average_rate_long_term,debt_average_rate_short_term,,{ok}",
        f"JNJ,debt_effective_rate,,due_within_one_year,{ok}",
        f"MSFT,debt_average_rate_long_term,debt_average_rate_short_term,made_up,{ok}",
        "AAPL,debt_average_rate_long_term,,,no filing named",
        f"KO,debt_average_rate_long_term,,,{ok}",
        f"XOM,debt_average_rate_long_term,not_an_item,short_term_borrowings,{ok}",
        f"WMT,debt_average_rate_long_term,,,{ok},extra",
    )
    with pytest.raises(StatedDebtRatesError) as err:
        load_stated_debt_rates(path)
    text = str(err.value)
    assert "rates.csv line 2: 'ZZZZ' is not in universe.csv" in text
    assert "line 3: 'revenue' is not a reported-only map item" in text
    assert "line 4: a short-term rate item needs short_rate_covers, and back" in text
    assert "line 5: a short-term rate item needs short_rate_covers, and back" in text
    assert "line 6: short_rate_covers 'made_up' is not one of" in text
    assert "line 7: evidence names no filing a reader can check" in text
    assert "line 8: KO is listed twice" in text
    assert "line 9: 'not_an_item' is not a reported-only map item" in text
    assert "line 10: wrong number of fields" in text


def test_a_long_item_must_be_a_reported_only_item(tmp_path):
    row = "KO,revenue,,," + "10-K 0000021344-22-000009"
    with pytest.raises(StatedDebtRatesError, match="line 2: 'revenue' is not a reported-only"):
        load_stated_debt_rates(write(tmp_path, row))


def test_wrong_columns_are_refused(tmp_path):
    with pytest.raises(StatedDebtRatesError, match="expected columns"):
        load_stated_debt_rates(write(tmp_path, KO, header="ticker,long_rate_item"))


def test_evidence_with_no_accession_is_refused_even_with_text(tmp_path):
    row = "KO,debt_average_rate_long_term,,,Note 10 of the 10-K"
    with pytest.raises(StatedDebtRatesError, match="line 2: evidence names no filing"):
        load_stated_debt_rates(write(tmp_path, row))


def test_accessions_are_listed_once_each_in_order(tmp_path):
    evidence = '"0000021344-22-000009, 0000021344-21-000008, 0000021344-22-000009"'
    row = f"KO,debt_average_rate_long_term,,,{evidence}"
    [loaded] = load_stated_debt_rates(write(tmp_path, row))
    assert loaded.accessions == ("0000021344-22-000009", "0000021344-21-000008")
