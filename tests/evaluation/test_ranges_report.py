"""M9 metrics on hand-made rows, and the build, report and reproduce check on Test Corp."""

from datetime import date

import pytest

from domains.evaluation import ranges as R
from domains.evaluation import ranges_report as RR
from tests.evaluation.conftest import CHOICES

TODAY = date(2020, 6, 30)


def row(actual, p10=90.0, p90=110.0, end="2021-03-31", **kw):
    base = {"status": "ok", "actual": actual, "p10": p10, "p50": 100.0, "p90": p90,
            "period_end": end, "horizon": 1, "as_of": "2021-02-01", "item": "revenue",
            "subject_kind": "origin", "subject_id": "A_2021-02-01", "variant": "baseline",
            "pool": "pooled", "period": "FY2021Q1"}  # fmt: skip
    return base | kw


def test_calendar_quarter_of_a_fiscal_quarter():
    assert RR.calendar_quarter("2020-04-30") == (2020, 2)  # Walmart's Q1 FY2021
    assert RR.calendar_quarter("2019-12-28") == (2019, 4)  # Apple's Q1 FY2020


def test_cover_counts_the_ends_inside_and_splits_misses():
    c = RR.cover([row(90.0), row(110.0), row(89.0), row(111.0), row(100.0, status="missing")])
    assert (c.inside, c.below, c.above, c.n) == (2, 1, 1, 4)
    assert c.share == 0.5


def test_one_cluster_gives_a_point_interval():
    rows = [row(100.0), row(100.0), row(120.0)]  # all in 2021 Q1
    assert RR.cluster_bootstrap(rows, draws=200) == pytest.approx((2 / 3, 2 / 3))
    assert RR.block_bootstrap(rows, draws=200) == pytest.approx((2 / 3, 2 / 3))


def test_the_bootstrap_reproduces_with_its_seed_and_spans_the_clusters():
    rows = [row(100.0, end=f"20{y}-03-31") for y in range(10, 20)]
    rows += [row(150.0, end=f"20{y}-06-30") for y in range(10, 20)]
    a, b = RR.cluster_bootstrap(rows, draws=500), RR.cluster_bootstrap(rows, draws=500)
    assert a == b and a[0] < 0.5 < a[1]
    lo, hi = RR.block_bootstrap(rows, draws=500)
    assert lo <= 0.5 <= hi


@pytest.mark.parametrize(
    "inside, interval, companies, expected",
    [
        (80, (0.75, 0.85), {"A": (80, 100)}, "met for every company"),
        (80, (0.75, 0.85), {"A": (99, 100), "B": (61, 100)}, "met on average"),
        (68, (0.60, 0.82), None, "inconclusive"),
        (50, (0.40, 0.60), None, "failed: too narrow"),
        (97, (0.95, 0.99), None, "failed: too wide"),
    ],
)
def test_the_pass_rule(inside, interval, companies, expected):
    c = RR.Cover(inside, 100 - inside, 0)
    comp = {k: RR.Cover(i, n - i, 0) for k, (i, n) in (companies or {}).items()}
    assert RR.verdict(c, interval, comp or None) == expected


def test_h1_ended_compares_the_quarter_end_with_the_forecast_date():
    assert RR.h1_ended(row(1.0, end="2021-01-31", as_of="2021-02-01"))
    assert not RR.h1_ended(row(1.0, end="2021-03-31", as_of="2021-02-01"))
    assert not RR.h1_ended(row(1.0, end="2021-01-31", horizon=2))


def test_width_is_relative_to_the_revenue_p50():
    rows = [row(1.0), row(1.0, item="ebit", p10=10.0, p90=14.0)]
    assert RR.widths(rows) == {"revenue": pytest.approx(0.2), "ebit": pytest.approx(0.04)}


# -- build, report, reproduce on Test Corp -----------------------------------------------------


@pytest.fixture
def built(company, monkeypatch):
    monkeypatch.setattr(R, "MIN_ERRORS", {"pooled": 2, "own": 2})
    monkeypatch.setattr(R, "ROLLING_FROM", date(2019, 1, 1))
    monkeypatch.setattr(RR, "ROLLING_FROM", date(2019, 1, 1))
    R.build_origins(company, ["TST"], date(2019, 4, 1), date(2020, 3, 1), TODAY, CHOICES, TODAY)
    build_id = R.run_build(company, TODAY, n=500, today=TODAY)
    return company, build_id


def test_a_build_ranges_the_origins_from_earlier_errors_only(built):
    conn, build_id = built
    rows = [dict(r) for r in conn.execute("SELECT * FROM range_results WHERE build_id = ?",
                                          (build_id,))]  # fmt: skip
    first = [r for r in rows if r["subject_id"] == "TST_2019-04-01"]
    assert first and all(r["status"] == "no_history" for r in first)  # nothing known yet
    ok = [r for r in rows if r["status"] == "ok"]
    assert ok  # later origins have a range
    # Test Corp is forecast without error, so every range is the forecast itself
    assert all(r["p10"] == pytest.approx(r["forecast"]) == pytest.approx(r["p90"]) for r in ok)
    assert all(r["p10"] == pytest.approx(r["actual"], rel=1e-9) for r in ok)
    text = RR.render(conn, build_id)
    assert "The pass rule" in text and "Limitations" in text


def test_a_stored_build_reproduces_and_an_edit_fails_it(built):
    conn, build_id = built
    check = R.reproduce_build(conn, build_id)
    assert check.ok, check.mismatches
    assert check.errors_checked > 0 and check.rows_checked > 0
    with conn:
        conn.execute(
            "UPDATE range_results SET p90 = p90 + 1 WHERE rowid = (SELECT MIN(rowid) FROM "
            "range_results WHERE status = 'ok')"
        )
    assert any("p90" in m for m in R.reproduce_build(conn, build_id).mismatches)


def test_an_edited_error_fails_the_reproduce_check(built):
    conn, build_id = built
    with conn:
        conn.execute(
            "UPDATE baseline_errors SET error = error + 0.01 WHERE rowid = (SELECT MIN(rowid) "
            "FROM baseline_errors WHERE status = 'ok')"
        )
    mismatches = R.reproduce_build(conn, build_id).mismatches
    assert any("error: stored" in m for m in mismatches)
