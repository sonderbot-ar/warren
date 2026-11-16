import warnings
from datetime import date

import pytest

from domains.fundamentals.facts import get_facts
from domains.fundamentals.universe import (
    COVERAGE_REASONS,
    PHASE1_UNIVERSE,
    CoverageWarning,
    UniverseError,
    coverage_fields,
    coverage_gap,
    get_universe_company,
    load_universe,
    warn_if_beyond_history,
)
from shared_kernel.data_warnings import DataWarning

XOM_CIK = "0000034088"
XOM_SUCCESSOR = "0002115436"


def test_xom_is_pinned_to_the_predecessor_cik_with_a_history_end():
    xom = get_universe_company("xom")
    assert (xom.cik, xom.history_ends) == (XOM_CIK, date(2026, 8, 3))
    assert len(PHASE1_UNIVERSE) == 8


def test_xom_has_a_reason_and_its_successor():
    xom = get_universe_company("XOM")
    assert (xom.reason, xom.successor_cik, xom.successor_name) == (
        "holding_company_reorganisation",
        XOM_SUCCESSOR,
        "ExxonMobil Holdings Corp",
    )
    assert coverage_fields(XOM_CIK, "2026-08-03") == {
        "reason": "holding_company_reorganisation",
        "successor_cik": XOM_SUCCESSOR,
        "successor_name": "ExxonMobil Holdings Corp",
    }
    assert coverage_fields(XOM_CIK, "2026-07-01") is None  # a cut-off since corrected
    assert coverage_fields("0000320193", "2026-08-03") is None
    assert coverage_fields(None, None) is None


def test_every_reason_in_the_file_is_in_the_closed_set():
    reasons = {c.reason for c in PHASE1_UNIVERSE if c.reason}
    assert reasons and reasons <= COVERAGE_REASONS


def test_query_past_the_history_end_warns():
    with pytest.warns(CoverageWarning, match="XOM"):
        warn_if_beyond_history(XOM_CIK, date(2026, 8, 3))


def test_the_warning_carries_reason_and_successor_and_keeps_its_text():
    with pytest.warns(CoverageWarning) as caught:
        warn_if_beyond_history(XOM_CIK, date(2026, 9, 30))
    w = caught[0].message
    assert isinstance(w, DataWarning)
    assert w.fields == {
        "ticker": "XOM",
        "cik": XOM_CIK,
        "as_of": "2026-09-30",
        "history_ends": "2026-08-03",
        "reason": "holding_company_reorganisation",
        "successor_cik": XOM_SUCCESSOR,
        "successor_name": "ExxonMobil Holdings Corp",
        "note": get_universe_company("XOM").note,
    }
    # the English text is the one #172 stored, byte for byte
    assert str(w) == (
        f"XOM (CIK {XOM_CIK}) as of 2026-09-30: filings from 2026-08-03 onward are on another "
        f"CIK and are missing here, so recent periods will be absent. "
        f"{get_universe_company('XOM').note}"
    )


def test_query_before_the_history_end_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_beyond_history(XOM_CIK, date(2026, 8, 2))
        warn_if_beyond_history("0000320193", date(2030, 1, 1))  # AAPL has no history end


def test_get_facts_carries_the_warning(ingested):
    conn, _ = ingested
    with pytest.warns(CoverageWarning):
        get_facts(conn, XOM_CIK, ["revenue"], "2027-01-01")


def test_csv_holds_the_phase1_list_in_order():
    assert [c.ticker for c in PHASE1_UNIVERSE] == [
        "AAPL", "MSFT", "WMT", "KO", "PG", "JNJ", "CAT", "XOM",
    ]  # fmt: skip
    assert all(
        c.cik is None
        and c.history_ends is None
        and c.reason is None
        and c.successor_cik is None
        and c.successor_name is None
        for c in PHASE1_UNIVERSE[:-1]
    )
    assert "ExxonMobil Holdings Corp" in get_universe_company("XOM").note


def _write(tmp_path, body):
    path = tmp_path / "universe.csv"
    path.write_text("ticker,cik,history_ends,reason,successor_cik,successor_name,note\n" + body)
    return path


def test_a_new_company_is_one_row(tmp_path):
    path = _write(tmp_path, "AAPL,,,,,,\nAMXB,0001129137,,,,,a new company needs no code\n")
    new = load_universe(path)[1]
    assert (new.ticker, new.cik, new.note) == ("AMXB", "0001129137", "a new company needs no code")


REORG = "holding_company_reorganisation"
NEW = "0002115436,ExxonMobil Holdings Corp"


@pytest.mark.parametrize(
    "body, message",
    [
        ("aapl,,,,,,\n", "line 2: ticker must be non-empty and upper case"),
        (",,,,,,\n", "line 2: ticker must be non-empty"),
        ("AAPL,,,,,,\nAAPL,,,,,,\n", "line 3: duplicate ticker AAPL"),
        ("AAPL,34088,,,,,\n", "line 2: cik must be empty or ten digits"),
        (f"XOM,0000034088,2026-13-01,{REORG},{NEW},\n", "line 2: history_ends must be an ISO date"),
        (f"XOM,,2026-08-03,{REORG},{NEW},\n", "line 2: history_ends needs a pinned cik"),
        ("XOM,0000034088,2026-08-03,,,,\n", "line 2: history_ends needs a reason"),
        ("XOM,0000034088,2026-08-03,merged,,,\n", "line 2: reason must be one of"),
        (f"XOM,0000034088,,{REORG},,,\n", "line 2: reason needs a history_ends"),
        (
            f"XOM,0000034088,2026-08-03,{REORG},2115436,Holdings,\n",
            "successor_cik must be empty or ten",
        ),
        (f"XOM,0000034088,2026-08-03,{REORG},0000034088,Holdings,\n", "successor_cik must differ"),
        ("XOM,0000034088,,,0002115436,Holdings,\n", "line 2: successor_cik needs a history_ends"),
        (f"XOM,0000034088,2026-08-03,{REORG},,,\n", "needs successor_cik and successor_name"),
        ("XOM,0000034088,2026-08-03,,,Holdings,\n", "successor_cik and successor_name go together"),
        (
            f"XOM,0000034088,2026-08-03,{REORG},{NEW},\nCVX,0000034088,,,,,\n",
            "line 3: cik 0000034088 is pinned twice",
        ),
        ("AAPL,,,,,,a, b\n", "line 2: wrong number of fields"),
        ("AAPL,,\n", "line 2: wrong number of fields"),
    ],
)
def test_bad_rows_are_named_by_line(tmp_path, body, message):
    with pytest.raises(UniverseError, match=message):
        load_universe(_write(tmp_path, body))


def test_every_problem_is_reported_at_once(tmp_path):
    with pytest.raises(UniverseError, match="line 2.*line 3"):
        load_universe(_write(tmp_path, "aapl,,,,,,\nMSFT,123,,,,,\n"))


def test_the_old_four_columns_are_refused(tmp_path):
    path = tmp_path / "universe.csv"
    path.write_text("ticker,cik,history_ends,note\nAAPL,,,\n")
    with pytest.raises(UniverseError, match="reason"):
        load_universe(path)


def test_wrong_columns_are_refused(tmp_path):
    path = tmp_path / "universe.csv"
    path.write_text("ticker,cik\nAAPL,\n")
    with pytest.raises(UniverseError, match="Expected columns"):
        load_universe(path)


def test_coverage_gap_gives_the_warnings_own_text_and_fields_and_none_before_the_end():
    """Backlog #252: the past-events call states the coverage warning as a note."""
    assert coverage_gap(XOM_CIK, date(2026, 8, 2)) is None
    assert coverage_gap("0000320193", date(2030, 1, 1)) is None
    assert coverage_gap(None, date(2030, 1, 1)) is None
    text, fields = coverage_gap(XOM_CIK, date(2026, 9, 30))
    with pytest.warns(CoverageWarning) as caught:
        warn_if_beyond_history(XOM_CIK, date(2026, 9, 30))
    assert str(caught[0].message) == text and caught[0].message.fields == fields
    assert fields["history_ends"] == "2026-08-03" and fields["successor_cik"] == XOM_SUCCESSOR


# -- backlog #256: the note is shown on any date from the cut-off, so it names no later date -----


def _xom_with_note(tmp_path, note, ends="2026-08-03"):
    return _write(tmp_path, f'XOM,0000034088,{ends},{REORG},{NEW},"{note}"\n')


@pytest.mark.parametrize(
    "note, message",
    [
        ("Linked on 2026-08-04.", "line 2: note names 2026-08-04, after history_ends"),
        ("The two CIKs were linked in 2027.", "line 2: note names the year 2027, after"),
        ("Filed 2026-02-30.", "line 2: note names '2026-02-30', which is not a date"),
        ("Linked in October 2026.", "line 2: note names 'October 2026', which begins after"),
        ("Linked in Q4 2026.", "line 2: note names 'Q4 2026', which begins after"),
        ("Linked in 4Q2026.", "line 2: note names '4Q2026', which begins after"),
        ("Linked in November 2026.", "line 2: note names 'November 2026', which begins after"),
        ("Linked 2026-11-04T00:00.", "line 2: note names 2026-11-04, after history_ends"),
        ("Its FY2028 10-K is on the new CIK.", "line 2: note names 'FY2028', more than a year"),
        ("Q1 FY2027 is on the new CIK; linked in 2027.", "line 2: note names the year 2027"),
    ],
)
def test_a_note_naming_a_date_after_the_cut_off_is_refused(tmp_path, note, message):
    with pytest.raises(UniverseError, match=message):
        load_universe(_xom_with_note(tmp_path, note))


@pytest.mark.parametrize(
    "note",
    [
        "History ends on 2026-08-03, the reorganisation was on 2026-07-01.",
        "Filings start in 2026; the old registrant filed since 1993.",
        "A ten-digit CIK such as 0002115436 is not a year.",
        "The Q2 2026 10-Q was filed in August 2026; Q3 2026 began before the cut-off.",
        "Its fiscal 2027 first-quarter 10-Q was filed 2026-06-02; FY2027 began in 2026.",
        "Its senior notes due 2030 moved to the new CIK.",
    ],
)
def test_a_note_naming_the_cut_off_or_earlier_loads(tmp_path, note):
    assert load_universe(_xom_with_note(tmp_path, note))[0].note == note


def test_a_note_on_a_row_without_a_cut_off_is_not_checked(tmp_path):
    path = _write(tmp_path, "AMXB,0001129137,,,,,listed again in 2031\n")
    assert load_universe(path)[0].note == "listed again in 2031"


def test_the_checked_in_universe_names_no_date_after_its_cut_offs():
    """load_universe() raising would fail this: the file has a cut-off row (Exxon), and that
    row's note names 2026-07-01, Q2 2026 and 2026-08-03, none after its cut-off."""
    assert any(c.history_ends for c in load_universe())
