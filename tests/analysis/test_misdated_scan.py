"""The misdated-figure scan against `misdated_facts.csv` (backlog #613 item 1).

Test Corp gets Coca-Cola's FY2016 shape by hand: a loss of 320 on paying debt off early filed for
2015 in a 10-K of 2016, and the same 320 filed for 2016 in a 10-K of 2017.
"""

from datetime import date

import pytest

from domains.analysis import __main__ as cli
from domains.analysis import misdated_facts as mf
from domains.fundamentals import universe

ITEM = "debt_extinguishment_in_interest"
F2015 = ("0000000123-16-000001", "2016-02-25")
F2016 = ("0000000123-17-000001", "2017-02-24")
LATE = date(2026, 1, 1)
LOAD = mf.load_misdated_facts  # the real loader, before a test replaces it


def add(conn, year, value, filing, tag="us-gaap:GainsLossesOnExtinguishmentOfDebt"):
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) "
        "VALUES (?, ?, ?, ?, ?, 'FY', ?, 'USD', '10-K', ?, ?)",
        (cik, tag, f"{year}-01-01", f"{year}-12-31", year, value, *filing),
    )


def row(year=2016, accession=F2016[0], item=ITEM):
    return mf.MisdatedFact("TST", item, year, accession, year - 1, f"{accession} says {year - 1}")


@pytest.fixture
def tst(company, monkeypatch):
    monkeypatch.setattr(universe, "load_universe", lambda: [universe.UniverseCompany("TST")])
    add(company, 2015, -320, F2015)
    add(company, 2016, -320, F2016)
    return company


def listing(monkeypatch, *rows):
    monkeypatch.setattr(mf, "load_misdated_facts", lambda: list(rows))


def test_a_listed_candidate_needs_no_one(tst, monkeypatch):
    listing(monkeypatch, row())
    [result] = mf.scan(tst, LATE)
    [(candidate, listed)] = result.candidates
    assert (candidate.fiscal_year, candidate.accession_no) == (2016, F2016[0])
    assert listed == row()
    assert result.not_found == [] and not result.needs_a_person
    assert mf.scan_lines(result)[0].startswith("listed      TST debt_extinguishment_in_interest")


def test_an_unlisted_candidate_gets_a_template_row_the_loader_refuses(tst, monkeypatch, tmp_path):
    listing(monkeypatch)
    [result] = mf.scan(tst, LATE)
    assert result.needs_a_person
    lines = mf.scan_lines(result)
    assert lines[0].startswith("NOT LISTED  TST debt_extinguishment_in_interest FY2016")
    template = lines[1].split("add: ", 1)[1]
    assert template.startswith(f"TST,{ITEM},2016,{F2016[0]},2015,")
    # the placeholder evidence quotes neither the year nor the filing, so it cannot be loaded
    path = tmp_path / "misdated_facts.csv"
    path.write_text(",".join(mf.COLUMNS) + "\n" + template + "\n")
    with pytest.raises(mf.MisdatedFactsError, match="evidence must quote"):
        LOAD(path)


def test_a_candidate_on_an_unchecked_item_says_so(tst, monkeypatch):
    listing(monkeypatch)
    add(tst, 2015, 50, F2015, tag="us-gaap:InterestPaid")
    add(tst, 2016, 50, F2016, tag="us-gaap:InterestPaid")
    [result] = mf.scan(tst, LATE)
    lines = mf.scan_lines(result)
    unchecked = [i for i, line in enumerate(lines) if "interest_paid" in line]
    assert unchecked, lines
    assert "not read against the list" in lines[unchecked[0] + 1]
    assert result.needs_a_person


def test_a_listed_row_the_scan_no_longer_finds_is_reported(tst, monkeypatch):
    listing(monkeypatch, row(), row(2015, F2015[0]))
    [result] = mf.scan(tst, LATE)
    assert result.not_found == [row(2015, F2015[0])]
    assert result.needs_a_person
    assert mf.scan_lines(result)[-1].startswith("NOT FOUND   TST debt_extinguishment_in_interest")


def test_a_listed_row_not_public_yet_is_neither_found_nor_missing(tst, monkeypatch):
    listing(monkeypatch, row())
    [result] = mf.scan(tst, date(2016, 6, 1))
    assert result.candidates == [] and result.not_found == []
    assert not result.needs_a_person


def test_an_unknown_ticker_is_refused(tst):
    with pytest.raises(ValueError, match="not in universe.csv"):
        mf.scan(tst, LATE, ["ZZZ"])


def test_the_command_exits_1_and_never_writes_the_file(tst, monkeypatch, capsys):
    listing(monkeypatch)
    before = mf.MISDATED_FACTS_PATH.read_bytes()

    class Conn:
        def __enter__(self):
            return tst

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "get_db_connection", lambda: Conn())
    assert cli.main(["misdated-scan", "--as-of", "2026-01-01"]) == 1
    assert "NOT LISTED  TST" in capsys.readouterr().out
    listing(monkeypatch, row())
    assert cli.main(["misdated-scan", "--ticker", "tst", "--as-of", "2026-01-01"]) == 0
    assert mf.MISDATED_FACTS_PATH.read_bytes() == before


def test_the_shipped_list_rows_are_all_on_checked_items():
    assert {r.canonical_name for r in mf.load_misdated_facts()} <= set(mf.CHECKED_ITEMS)
