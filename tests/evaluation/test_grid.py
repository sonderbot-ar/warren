"""Grid cases (M10): the date rule, the cutoff rule, the left-out rule and the regenerate check."""

from datetime import date

import pytest

from domains.evaluation import grid
from domains.evaluation.cases import COLUMNS, CaseError, load_cases
from domains.fundamentals.universe import UniverseCompany

UNIVERSE = [
    UniverseCompany("AAPL"),
    UniverseCompany("XOM", "0000034088", "", date(2026, 8, 3)),
]


def days(end=grid.GRID_END):
    return [g.day for g in grid.grid_dates(end)]


def test_the_dates_are_the_rule():
    found = days()
    assert found[0] == date(2019, 4, 1)
    assert found[-1] == date(2026, 10, 15)
    pre = [g.day for g in grid.grid_dates() if not g.post_cutoff]
    post = [g.day for g in grid.grid_dates() if g.post_cutoff]
    assert len(pre) == 29 and pre[-1] == date(2026, 4, 1)
    assert all(d.day == 1 and d.month in (1, 4, 7, 10) for d in pre)
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
    assert days(date(2019, 6, 30)) == [date(2019, 4, 1)]


def test_a_company_is_left_out_from_its_history_end():
    cases, left_out = grid.grid_cases(UNIVERSE)
    xom = [c.event_date for c in cases if c.ticker == "XOM"]
    assert max(xom) == date(2026, 8, 1)
    assert [c for c, _ in left_out] == [
        "XOM_2026-08-15", "XOM_2026-09-01", "XOM_2026-09-15", "XOM_2026-10-01", "XOM_2026-10-15"
    ]  # fmt: skip
    assert len(cases) == 36 * 2 - 5


def test_a_new_company_is_on_every_date_with_no_code_change():
    cases, _ = grid.grid_cases([*UNIVERSE, UniverseCompany("NEWCO")])
    assert [c.event_date for c in cases if c.ticker == "NEWCO"] == days()


def test_grid_cases_are_tagged_and_the_post_cutoff_ones_say_so():
    cases, _ = grid.grid_cases(UNIVERSE)
    assert all(c.is_grid and c.horizon_quarters == 4 and not c.source_url for c in cases)
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


def test_a_grid_date_that_collides_with_a_hand_picked_case_is_refused(tmp_path, events):
    events.write_text(
        ",".join(COLUMNS) + "\n"
        "AAPL_2020-04-01,AAPL,2020-04-01,guidance,Something,4,event rule: company announcement,"
        "https://example.com/,\n"
    )
    with pytest.raises(CaseError, match="collide with hand-picked cases: AAPL_2020-04-01"):
        grid.write_grid(tmp_path / "grid.csv", UNIVERSE, events_path=events)


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
