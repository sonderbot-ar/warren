"""Grid cases (M10): the date rule, the cutoff rule, the left-out rule and the regenerate check."""

import dataclasses
from datetime import date

import pytest

from domains.evaluation import grid
from domains.evaluation.cases import COLUMNS, CaseError, load_cases
from domains.evaluation.harness import EvaluationError, guard_coverage
from domains.fundamentals.universe import UniverseCompany

UNIVERSE = [
    UniverseCompany("AAPL"),
    UniverseCompany("XOM", "0000034088", "", date(2026, 8, 3)),
]


def days(end=grid.GRID_END):
    return [g.day for g in grid.grid_dates(end)]


def test_the_dates_are_the_rule():
    found = days()
    assert found[0] == date(2019, 5, 15)
    assert found[-1] == date(2026, 10, 15)
    pre = [g.day for g in grid.grid_dates() if not g.post_cutoff]
    post = [g.day for g in grid.grid_dates() if g.post_cutoff]
    assert len(pre) == 29 and pre[-1] == date(2026, 5, 15)
    assert all(d.day == 15 and d.month in (2, 5, 8, 11) for d in pre)
    assert post == [date(2026, 7, 15), date(2026, 8, 1), date(2026, 8, 15), date(2026, 9, 1),
                    date(2026, 9, 15), date(2026, 10, 1), date(2026, 10, 15)]  # fmt: skip
    assert found == sorted(found) and len(found) == len(set(found)) == 36


def test_a_date_in_the_cutoff_month_or_its_window_is_on_neither_grid():
    # Jun 2026 is the cutoff month; 2026-07-01's window (Jun 25 - Jul 1) overlaps it
    assert date(2026, 7, 1) not in days()
    assert not grid.is_post_cutoff(date(2026, 7, 1))
    assert not grid.is_pre_cutoff(date(2026, 7, 1))


@pytest.mark.parametrize(
    ("day", "post"),
    [
        (date(2026, 6, 30), False),
        (date(2026, 7, 1), False),
        (date(2026, 7, 6), False),  # window starts Jun 30
        (date(2026, 7, 7), True),  # window starts Jul 1
        (date(2026, 7, 8), True),
    ],
)
def test_post_cutoff_needs_the_whole_window_after_the_cutoff_month(day, post):
    assert grid.WINDOW_DAYS == 7
    assert grid.is_post_cutoff(day) is post


def test_the_window_matches_the_pipeline():
    from domains.orchestration.nodes import NEWS_DAYS

    assert grid.WINDOW_DAYS == NEWS_DAYS


def test_an_end_date_cuts_the_grid():
    assert days(date(2026, 8, 1))[-2:] == [date(2026, 7, 15), date(2026, 8, 1)]
    assert days(date(2019, 8, 14)) == [date(2019, 5, 15)]


def test_a_company_gets_the_horizon_the_coverage_guard_accepts():
    cases, left_out = grid.grid_cases(UNIVERSE)
    xom = {c.event_date: c.horizon_quarters for c in cases if c.ticker == "XOM"}
    assert xom[date(2025, 2, 15)] == 4
    assert xom[date(2025, 5, 15)] == 3
    assert xom[date(2025, 8, 15)] == 2
    assert xom[date(2025, 11, 15)] == 1
    assert max(xom) == date(2025, 11, 15)
    assert [c for c, _ in left_out] == [f"XOM_{d.isoformat()}" for d in days()
                                        if d > date(2025, 11, 15)]  # fmt: skip
    assert len(cases) == 36 * 2 - 9
    for case in cases:  # every horizon passes the harness's own guard, and one more would not
        guard_coverage(case)
        if case.ticker == "XOM" and case.horizon_quarters < 4:
            longer = dataclasses.replace(case, horizon_quarters=case.horizon_quarters + 1)
            with pytest.raises(EvaluationError, match="coverage"):
                guard_coverage(longer)


def test_a_new_company_is_on_every_date_with_no_code_change():
    cases, _ = grid.grid_cases([*UNIVERSE, UniverseCompany("NEWCO")])
    assert [c.event_date for c in cases if c.ticker == "NEWCO"] == days()


def test_grid_cases_are_tagged_and_the_post_cutoff_ones_say_so():
    cases, _ = grid.grid_cases(UNIVERSE)
    assert all(c.is_grid and not c.source_url for c in cases)
    assert all(c.horizon_quarters == 4 for c in cases if c.ticker == "AAPL")
    assert {c.selected_because for c in cases if grid.is_post_cutoff(c.event_date)} == {grid.POST}
    assert {c.selected_because for c in cases if grid.is_pre_cutoff(c.event_date)} == {grid.PRE}


@pytest.fixture
def events(tmp_path):
    path = tmp_path / "cases.csv"
    path.write_text(",".join(COLUMNS) + "\n")
    return path


def test_a_written_grid_loads(tmp_path, events):
    path = tmp_path / "grid.csv"
    written = grid.write_grid(path, UNIVERSE, events_path=events)
    loaded = grid.load_grid(path, UNIVERSE, events_path=events)
    assert loaded == written


def test_a_hand_edited_grid_is_refused(tmp_path, events):
    path = tmp_path / "grid.csv"
    grid.write_grid(path, UNIVERSE, events_path=events)
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(lines[:-1]))  # drop a date
    with pytest.raises(CaseError, match="not what the grid rule generates"):
        grid.load_grid(path, UNIVERSE, events_path=events)


def test_a_grid_date_shared_with_a_hand_picked_case_stays_and_is_listed(tmp_path, events):
    events.write_text(
        ",".join(COLUMNS) + "\n"
        "AAPL_2020-05-15,AAPL,2020-05-15,guidance,Something,4,event rule: company announcement,"
        "https://example.com/,\n"
    )
    cases = grid.write_grid(tmp_path / "grid.csv", UNIVERSE, events_path=events)
    assert "AAPL_2020-05-15" in {c.case_id for c in cases}
    assert grid.shared_with_hand_picked(cases, events) == ["AAPL_2020-05-15"]


def test_storing_a_grid_case_never_overwrites_a_hand_picked_one(company, tmp_path):
    from domains.evaluation.cases import Case, store_cases

    ticker = company.execute("SELECT ticker FROM companies LIMIT 1").fetchone()[0]
    hand = Case(f"{ticker}_2020-05-15", ticker, date(2020, 5, 15), "guidance", "Hand", 4,
                "event rule: company announcement", "https://example.com/", "")  # fmt: skip
    gridded = dataclasses.replace(hand, event_type="grid", description=grid.DESCRIPTION,
                                  selected_because=grid.PRE, source_url="")  # fmt: skip
    store_cases(company, [hand])
    store_cases(company, [gridded])
    row = company.execute(
        "SELECT event_type FROM eval_cases WHERE case_id = ?", (hand.case_id,)
    ).fetchone()
    assert row[0] == "guidance"
    store_cases(company, [hand])  # and the hand-picked row still updates
    assert company.execute("SELECT COUNT(*) FROM eval_cases").fetchone()[0] == 1


def test_a_grid_row_needs_the_grid_rule(tmp_path):
    path = tmp_path / "cases.csv"
    row = "AAPL_2020-04-01,AAPL,2020-04-01,grid,Grid date,4,picked by me,,\n"
    path.write_text(",".join(COLUMNS) + "\n" + row)
    with pytest.raises(CaseError, match="admitted by the grid rule"):
        load_cases(path)


def test_the_checked_in_grid_matches_the_rule():
    cases = grid.load_grid()
    assert len({c.event_date for c in cases}) == 36
    assert all(c.is_grid for c in cases)
