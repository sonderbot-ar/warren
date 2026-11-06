"""The "today" defaults follow the New York calendar, not the machine's date (backlog #163).

Every test freezes the clock at 2026-07-02 02:00 UTC: the machine's UTC date is July 2, the date
in New York is July 1 (22:00 EDT), and the last day that has ended there is June 30. So a default
taken from the machine's date shows up as July 2, a label as July 1 and a data cut-off as June 30.
"""

from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest

from domains.analysis import __main__ as analysis_cli
from domains.analysis import math_engine
from domains.analysis.math_engine import EngineError, build_inputs
from domains.evaluation import __main__ as evaluation_cli
from domains.evaluation import backtest_batch, harness, ranges
from domains.evaluation.backtest_batch import batch_notes, run_backtest
from domains.fundamentals import quality
from domains.fundamentals.quality import build_report
from shared_kernel import calendar
from tests.evaluation.test_harness import case

NOW = datetime(2026, 7, 2, 2, 0, tzinfo=UTC)
NEW_YORK_DATE = date(2026, 7, 1)
LAST_ENDED = date(2026, 6, 30)


class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            raise AssertionError("a naive now() reads the machine's clock")
        return NOW.astimezone(tz)


@pytest.fixture
def frozen(monkeypatch):
    for module in (analysis_cli, math_engine, backtest_batch, harness, ranges, quality):
        monkeypatch.setattr(module, "datetime", Frozen)


class Stop(Exception):
    pass


def test_the_frozen_instant_is_three_different_days():
    assert NOW.date() == date(2026, 7, 2)
    assert calendar.case_today(NOW) == NEW_YORK_DATE
    assert calendar.last_ended_day(NOW) == LAST_ENDED


def test_a_backtest_with_no_dates_scores_on_the_last_ended_day_and_is_labelled_new_york_today(
    company, frozen
):
    batch = run_backtest(company, [], "sha", n_samples=10)
    assert batch == "eval_2026-07-01_1"
    assert batch_notes(company, batch)["actuals_as_of"] == "2026-06-30"


def test_an_explicit_today_still_sets_both_as_before(company, frozen):
    batch = run_backtest(company, [], "sha", today=date(2020, 6, 30), n_samples=10)
    assert batch == "eval_2020-06-30_1"
    assert batch_notes(company, batch)["actuals_as_of"] == "2020-06-30"


def test_a_case_with_no_actuals_date_reads_actuals_known_by_the_last_ended_day(
    company, frozen, monkeypatch
):
    seen = []

    def spy(conn, cik, as_of, mode):
        seen.append(as_of)
        raise Stop

    monkeypatch.setattr(harness, "_quarterly", spy)
    with pytest.raises(Stop):
        harness.evaluate_case(company, case(), today=date(2020, 6, 30), n_samples=10)
    assert seen == [LAST_ENDED]


def test_a_run_may_be_dated_the_new_york_date_but_not_the_machines(company, frozen):
    with pytest.raises(EngineError, match=f"to {NEW_YORK_DATE}, got 2026-07-02"):
        build_inputs(company, "TST", date(2026, 7, 2))


def test_the_quality_report_defaults_to_the_last_ended_day(company, frozen):
    assert build_report(company, "TST", known_gaps=[]).as_of == LAST_ENDED


def test_the_fallback_check_defaults_to_the_last_ended_day(company, frozen, monkeypatch, capsys):
    seen = []

    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(analysis_cli, "get_db_connection", same_connection)
    monkeypatch.setattr(analysis_cli, "fallback_backtest", lambda conn, d: seen.append(d) or [])
    analysis_cli.main(["fallbacks"])
    assert seen == [LAST_ENDED]


def test_origins_stop_at_the_last_ended_day_and_score_on_it(company, frozen, monkeypatch):
    seen = []
    monkeypatch.setattr(
        ranges, "build_origin", lambda conn, t, d, actuals, choices, today: seen.append(
            (d, actuals, today)) or "kept"
    )  # fmt: skip
    ranges.build_origins(company, ["TST"], start=date(2026, 5, 1), end=date(2026, 12, 1))
    assert seen == [(date(2026, 5, 1), LAST_ENDED, None), (date(2026, 6, 1), LAST_ENDED, None)]


def test_a_range_build_is_labelled_new_york_today(company, frozen):
    build = ranges.run_build(company, LAST_ENDED)
    assert build == "ranges_2026-07-01_1"


def test_ranges_test_scores_on_the_last_ended_day(company, monkeypatch, capsys):
    seen = []

    @contextmanager
    def same_connection(*args):
        yield company

    def spy(conn, actuals_as_of, *args, **kwargs):
        seen.append(actuals_as_of)
        raise Stop

    monkeypatch.setattr(evaluation_cli, "get_db_connection", same_connection)
    monkeypatch.setattr(calendar, "last_ended_day", lambda now: LAST_ENDED if now.tzinfo else None)
    monkeypatch.setattr(ranges, "run_build", spy)
    with pytest.raises(Stop):
        evaluation_cli.main(["ranges", "test"])
    assert seen == [LAST_ENDED]


def test_a_pipelines_today_is_the_new_york_date(company):
    # it decides whether a pipeline's review is manual (a recent date) or auto
    from domains.orchestration.nodes import Deps

    assert Deps(conn=company, now=lambda: NOW).today() == NEW_YORK_DATE


def test_a_batch_with_no_date_is_labelled_new_york_today(company, frozen):
    # `evaluate run` reaches this default through `run_batch`
    assert harness.new_batch(company, [], "sha", None) == "eval_2026-07-01_1"
