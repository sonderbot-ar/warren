"""The hindsight re-score (backlog #633): the M9 origins' run of the time beside a fresh run under
today's rules, against the same actuals, on Test Corp; nothing is stored."""

import math
from datetime import date

import pytest

from domains.analysis.reading_rules import READING_RULES_VERSION
from domains.analysis.runs import run_baseline
from domains.evaluation import ranges as R
from domains.evaluation import rescore as S
from tests.evaluation.conftest import CHOICES

TODAY = date(2020, 6, 30)
ORIGIN = date(2019, 5, 1)


def origin(conn, as_of=ORIGIN):
    R.build_origin(conn, "TST", as_of, TODAY, CHOICES, TODAY)
    return conn.execute(
        "SELECT run_id FROM forecast_origins WHERE as_of = ?", (as_of.isoformat(),)
    ).fetchone()[0]


def age(conn, run_id):
    conn.execute(
        "UPDATE runs SET reading_rules_version = ? WHERE run_id = ?",
        (READING_RULES_VERSION - 1, run_id),
    )
    conn.commit()


def fresh(conn, as_of=ORIGIN):
    return run_baseline(conn, "TST", as_of, choices=CHOICES, today=TODAY)


def counts(conn):
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def test_a_fresh_run_with_the_same_forecast_compares_with_no_change(company):
    age(company, origin(company))
    fresh(company)
    got = S.hindsight_rescore(company, actuals_as_of=TODAY)
    assert got.origins == 1 and got.rescored == 1 and not got.failed
    assert got.pairs and all(p.change == pytest.approx(0, abs=1e-12) for p in got.pairs)
    assert {p.item for p in got.pairs} == {"revenue", "ebit"}
    assert got.stored_drift == 0
    line = next(x for x in S.summary(got) if x.ticker == "All" and x.item == "revenue")
    assert line.moved == 0 and line.moved_change is None
    assert line.quarters == len({p.period for p in got.pairs if p.item == "revenue"})


def test_a_changed_forecast_moves_the_error_by_what_m9_gives(company):
    age(company, origin(company))
    run_id = fresh(company)
    company.execute(
        "UPDATE run_outputs SET value = value * 1.1 "
        "WHERE run_id = ? AND name = 'revenue' AND period = 'FY2019Q3'",
        (run_id,),
    )
    company.commit()
    got = S.hindsight_rescore(company, actuals_as_of=TODAY)
    moved = [p for p in got.pairs if abs(p.change) > S.MOVED]
    assert [(p.period, p.item) for p in moved] == [("FY2019Q3", "revenue")]
    assert moved[0].change == pytest.approx(-math.log(1.1), rel=1e-9)
    line = next(x for x in S.summary(got) if x.ticker == "TST" and x.item == "revenue")
    assert line.moved == 1 and line.better + line.worse == 1
    assert S.largest(got) == moved


def test_origins_without_a_fresh_run_or_already_fresh_are_counted_apart(company):
    origin(company)  # its own run is under today's rules
    got = S.hindsight_rescore(company, actuals_as_of=TODAY)
    assert got.skipped == {"origin: its own run is already under today's rules": 1}
    age(company, company.execute("SELECT run_id FROM forecast_origins").fetchone()[0])
    got = S.hindsight_rescore(company, actuals_as_of=TODAY)
    assert got.skipped == {"origin: no fresh run under today's rules": 1}
    assert got.rescored == 0 and not got.pairs


def test_a_differing_actual_is_not_compared():
    old = [_row("FY2019Q3", "revenue", 100.0, 0.01)]
    new = [_row("FY2019Q3", "revenue", 101.0, 0.02)]
    out = S.Rescore(TODAY)
    S.compare("TST_2019-05-01", "TST", old, new, out)
    assert out.pairs == [] and out.skipped == {"actual differs": 1}


def test_quarters_pair_by_period_not_horizon():
    # the fresh run read one more filed quarter: the same period at a shorter horizon
    old = [_row("FY2019Q3", "revenue", 100.0, 0.01, horizon=2)]
    new = [_row("FY2019Q3", "revenue", 100.0, 0.03, horizon=1)]
    out = S.Rescore(TODAY)
    S.compare("TST_2019-05-01", "TST", old, new, out)
    assert [(p.horizon, p.change) for p in out.pairs] == [(2, pytest.approx(0.02))]


def _row(period, item, actual, error, horizon=1, status="ok"):
    return {
        "period": period, "item": item, "horizon": horizon, "actual": actual,
        "actual_revenue": actual, "error": error, "status": status,
    }  # fmt: skip


def test_nothing_is_stored_and_two_calls_agree(company):
    age(company, origin(company))
    fresh(company)
    before = counts(company)
    a = S.hindsight_rescore(company, actuals_as_of=TODAY)
    b = S.hindsight_rescore(company, actuals_as_of=TODAY)
    assert counts(company) == before
    assert a.pairs == b.pairs and S.summary(a) == S.summary(b)


def test_the_report_says_hindsight_in_its_title_and_every_table(company, tmp_path):
    age(company, origin(company))
    fresh(company)
    text = S.write_report(S.hindsight_rescore(company, actuals_as_of=TODAY), tmp_path / "r.md")
    text = text.read_text()
    assert text.splitlines()[0].startswith(f"# {S.LABEL}")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    tables = [h for h in headings if not h.startswith(("## Not compared", "## Fresh runs"))]
    assert tables and all(S.LABEL in h for h in tables)
    assert "not Warren's forecast record" in text and "No significance test" in text


def test_the_command_writes_the_report(company, monkeypatch, tmp_path):
    from domains.evaluation import __main__ as cli

    age(company, origin(company))
    fresh(company)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "get_db_connection", _reuse(company))
    assert cli.main(["rescore", "--actuals-as-of", TODAY.isoformat()]) == 0
    assert (tmp_path / "data" / "reports" / "eval" / "rescore_hindsight.md").exists()


def _reuse(conn):
    from contextlib import contextmanager

    @contextmanager
    def opened():
        yield conn

    return opened
