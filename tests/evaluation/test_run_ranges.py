"""Backlog #144: the error range and its track record on any run, on hand-made misses."""

import json
import math
from datetime import date, timedelta

import pytest

from domains.analysis import financial_math as fm
from domains.evaluation import ranges as R
from domains.evaluation import ranges_report as RR
from domains.evaluation import run_ranges as RN
from domains.evaluation.harness import EvaluationError
from tests.evaluation.conftest import CHOICES

TODAY = date(2020, 6, 30)
N = 500
D = date(2021, 6, 1)


def pair(h=1, filed=date(2020, 1, 1), rev=0.0, ebit=0.0, ticker="AAA", n=0):
    return R.ErrorPair(f"{ticker}_{n}", ticker, h, f"P{n}", filed, rev, ebit)


def pairs_of(count, ticker="AAA", filed=date(2020, 1, 1), h=1, start=0):
    return [
        pair(h, filed, 0.01 * ((i % 5) - 2), 0.001 * ((i % 3) - 1), ticker, i)
        for i in range(start, start + count)
    ]


# -- synthetic origins in a migrated database ---------------------------------------------------


def add_origin(conn, ticker, as_of, quarters, version="v-test", status="ok", run_id=None):
    """quarters: list of dicts h, period, period_end, filed, actual_rev, actual_ebit (forecast
    revenue 100 and EBIT 10; the miss is computed from the actual)."""
    oid = R.origin_id(ticker, as_of)
    conn.execute(
        "INSERT INTO forecast_origins (origin_id, ticker, as_of, run_id, code_version, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (oid, ticker, as_of.isoformat(), run_id, version, status),
    )
    for q in quarters:
        rev, ebit = q["actual_rev"], q["actual_ebit"]
        for item, fc, act, err in (
            ("revenue", 100.0, rev, math.log(rev / 100.0)),
            ("ebit", 10.0, ebit, (ebit - 10.0) / rev),
        ):
            conn.execute(
                "INSERT INTO baseline_errors (origin_id, ticker, origin_date, horizon, period, "
                "period_end, item, forecast, actual, actual_revenue, actual_filed_at, error, "
                "status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok')",
                (
                    oid,
                    ticker,
                    as_of.isoformat(),
                    q["h"],
                    q["period"],
                    q["period_end"],
                    item,
                    fc,
                    act,
                    rev,
                    q["filed"].isoformat(),
                    err,
                ),
            )
    conn.commit()
    return oid


def history(conn, ticker="AAA", count=25, filed=date(2020, 6, 1), horizons=(1, 2, 3)):
    """`count` old origins (before the rolling test) whose misses are known by 2020-06-01."""
    for i in range(count):
        quarters = [
            {"h": h, "period": f"H{ticker}{i}_{h}", "period_end": "2020-03-31", "filed": filed,
             "actual_rev": 100.0 * math.exp(0.01 * ((i % 5) - 2)), "actual_ebit": 10.0}
            for h in horizons
        ]  # fmt: skip
        add_origin(conn, ticker, date(2020, 1, 1) + timedelta(days=i), quarters)


def scored(h, period, filed, actual_rev=100.0, period_end="2021-03-31"):
    return {"h": h, "period": period, "period_end": period_end, "filed": filed,
            "actual_rev": actual_rev, "actual_ebit": 10.0}  # fmt: skip


def row(ticker, period, period_end, item="revenue", pool="pooled", inside=True, sid=None):
    return {
        "pool": pool, "item": item, "ticker": ticker, "period": period, "period_end": period_end,
        "status": "ok", "p10": 90.0, "p50": 100.0, "p90": 110.0,
        "actual": 100.0 if inside else 200.0, "subject_id": sid or f"{ticker}_{period}",
        "variant": "baseline", "horizon": 1,
    }  # fmt: skip


def quarter_rows(ticker, count, inside=True, item="revenue", pool="pooled"):
    """One row per distinct quarter, `count` quarters from 2018 on."""
    out = []
    for i in range(count):
        y, q = 2018 + i // 4, i % 4 + 1
        out.append(row(ticker, f"FY{y}Q{q}", f"{y}-{q * 3:02d}-28", item, pool, inside))
    return out


def cell(cells, pool="pooled", scope="all", item="revenue"):
    (c,) = [c for c in cells if (c.pool, c.scope, c.item) == (pool, scope, item)]
    return c


# -- the bands ----------------------------------------------------------------------------------


def test_bands_equal_ranges_called_directly_with_the_same_seed():
    pairs = pairs_of(25) + pairs_of(25, "BBB")
    forecasts = {1: (100.0, 10.0)}
    on = date(2020, 3, 1)
    got = RN.bands(forecasts, pairs, on, "AAA", "run1", N)
    for b in got[1]:
        seed = R.range_seed("run1:baseline", b.pool)
        want = R.ranges(R.constant_samples(forecasts, N), pairs, on, b.pool, "AAA", seed, N)[1]
        assert b.revenue == dict(zip(("p10", "p50", "p90"), want.revenue, strict=True))
        assert b.ebit == dict(zip(("p10", "p50", "p90"), want.ebit, strict=True))
        assert (b.n_errors, b.n_quarters) == (want.n_errors, want.n_quarters)
    assert [b.pool for b in got[1]] == ["pooled", "own"]


def test_a_miss_filed_on_d_is_used_and_one_filed_the_next_day_is_not():
    on = date(2020, 3, 1)
    pairs = pairs_of(19) + [pair(1, on, 0.0, 0.0, "AAA", 99)]
    (pooled, _) = RN.bands({1: (100.0, 10.0)}, pairs, on, "AAA", "r", N)[1]
    assert pooled.n_errors == 20 and pooled.missing is None and pooled.revenue is not None
    late = pairs_of(19) + [pair(1, on + timedelta(days=1), 0.0, 0.0, "AAA", 99)]
    (pooled, _) = RN.bands({1: (100.0, 10.0)}, late, on, "AAA", "r", N)[1]
    assert pooled.n_errors == 19 and pooled.revenue is None


def test_19_pooled_misses_are_no_history_and_20_are_a_band():
    on = date(2020, 3, 1)
    (b19, _) = RN.bands({1: (100.0, 10.0)}, pairs_of(19), on, "AAA", "r", N)[1]
    assert b19.missing.code == "no_history"
    assert b19.missing.params == {"horizon": 1, "pool": "pooled", "n_errors": 19, "min_errors": 20}
    assert b19.revenue is None and b19.ebit is None
    assert b19.revenue_vs_forecast is None and b19.ebit_vs_forecast is None
    (b20, _) = RN.bands({1: (100.0, 10.0)}, pairs_of(20), on, "AAA", "r", N)[1]
    assert b20.missing is None and b20.revenue["p10"] < b20.revenue["p90"]


def test_the_own_pool_counts_only_the_companys_misses():
    on = date(2020, 3, 1)
    pairs = pairs_of(30, "BBB") + pairs_of(11, "AAA")
    pooled, own = RN.bands({1: (100.0, 10.0)}, pairs, on, "AAA", "r", N)[1]
    assert (pooled.n_errors, own.n_errors) == (41, 11)
    assert own.missing.code == "no_history" and own.missing.params["min_errors"] == 12
    assert pooled.missing is None
    own12 = RN.bands({1: (100.0, 10.0)}, pairs + pairs_of(1, "AAA", start=50), on, "AAA", "r", N)
    assert own12[1][1].n_errors == 12 and own12[1][1].missing is None


def test_the_change_from_the_forecast_is_computed_with_financial_math():
    rev = {"p10": 90.0, "p50": 100.0, "p90": 112.0}
    ebit = {"p10": 8.0, "p50": 10.0, "p90": 13.0}
    r, e = RN.vs_forecast(rev, ebit, 100.0, 10.0)
    for k in RN.KEYS:
        assert r[k] == fm.growth(rev[k], 100.0) == pytest.approx(rev[k] / 100.0 - 1)
        assert e[k] == fm.ratio(ebit[k] - 10.0, 100.0) == pytest.approx((ebit[k] - 10.0) / 100.0)
    assert RN.vs_forecast(None, ebit, 100.0, 10.0) == (None, None)
    assert RN.vs_forecast(rev, None, 100.0, 10.0) == (None, None)


def test_band_vs_forecast_matches_its_own_numbers():
    (pooled, _) = RN.bands({1: (200.0, 20.0)}, pairs_of(25), date(2020, 3, 1), "AAA", "r", N)[1]
    for k in RN.KEYS:
        assert pooled.revenue_vs_forecast[k] == pytest.approx(pooled.revenue[k] / 200.0 - 1)
        assert pooled.ebit_vs_forecast[k] == pytest.approx((pooled.ebit[k] - 20.0) / 200.0)


def test_basis_flags_are_counted_in_own_bands_and_pooled_bands_are_unchecked():
    pairs = pairs_of(25)
    on = date(2020, 3, 1)
    flags = {(pairs[0].origin_id, pairs[0].period, "ebit"), (pairs[1].origin_id, "other", "ebit"),
             (pairs[2].origin_id, pairs[2].period, "revenue")}  # fmt: skip
    pooled, own = RN.bands({1: (100.0, 10.0)}, pairs, on, "AAA", "r", N, flags)[1]
    assert own.basis_changes == 2  # pair 0 (ebit) and pair 2 (revenue); the "other" period isn't
    assert own.notes == []
    assert pooled.basis_changes is None
    assert [c.code for c in pooled.notes] == ["basis_unchecked"]
    assert pooled.notes[0].params == {"checked": "AAA"}
    # no flags given: nothing is checked, so the own band says so too
    pooled, own = RN.bands({1: (100.0, 10.0)}, pairs, on, "AAA", "r", N)[1]
    assert own.basis_changes is None
    assert [c.code for c in own.notes] == ["basis_unchecked"]
    # a miss not yet public isn't counted
    late = [p for p in pairs]
    late[0] = pair(1, on + timedelta(days=1), 0.0, 0.0, "AAA", 0)
    _, own = RN.bands({1: (100.0, 10.0)}, late, on, "AAA", "r", N, flags)[1]
    assert own.basis_changes == 1


# -- verdict ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("share", "want"),
    [(0.65, "held"), (0.95, "held"), (0.80, "held"), (0.64, "too_narrow"),
     (0.96, "too_wide"), (None, None)],
)  # fmt: skip
def test_verdict_edges(share, want):
    assert RN.verdict(share) == want


# -- coverage cells -----------------------------------------------------------------------------


def test_inside_below_above_sum_to_n():
    rows = quarter_rows("AAA", 12)
    rows[0] = row("AAA", "FY2018Q1", "2018-03-28", inside=False)  # above
    low = row("AAA", "FY2018Q2", "2018-06-28")
    rows[1] = low | {"actual": 50.0}  # below
    c = cell(RN.coverage_cells(rows, "AAA", D))
    assert (c.inside, c.below, c.above) == (10, 1, 1)
    assert c.inside + c.below + c.above == c.n == 12
    assert c.share == pytest.approx(10 / 12)


def test_unscored_rows_are_not_counted():
    rows = quarter_rows("AAA", 12) + [row("AAA", "X", "2019-03-28") | {"status": "no_history"}]
    assert cell(RN.coverage_cells(rows, "AAA", D)).n == 12


def test_three_origins_on_one_quarter_are_three_rows_and_one_quarter():
    rows = [row("AAA", "FY2021Q1", "2021-03-31", sid=f"AAA_2021-0{m}-01") for m in (1, 2, 3)]
    c = cell(RN.coverage_cells(rows, "AAA", D), scope="company")
    assert (c.n, c.n_quarters, c.n_clusters) == (3, 1, 1)


def test_few_scored_at_11_distinct_quarters_and_not_at_12():
    c11 = cell(RN.coverage_cells(quarter_rows("AAA", 11), "AAA", D))
    assert c11.missing.code == "few_scored" and c11.verdict is None
    # a cell its own warning calls meaningless gives no judgement at all (gatekeeper, PR #166)
    assert c11.target_in_interval is None and c11.differs_from_all is None
    assert c11.missing.params == {"n": 11, "n_quarters": 11, "min_quarters": 12}
    assert c11.share == 1.0  # counts stay shown
    c12 = cell(RN.coverage_cells(quarter_rows("AAA", 12), "AAA", D))
    assert c12.missing is None and c12.verdict == "too_wide"
    # many rows on few quarters are still few
    rows = [
        row("AAA", f"FY2018Q{q}", f"2018-{q * 3:02d}-28", sid=f"o{k}")
        for q in (1, 2, 3, 4) for k in range(10)
    ]  # fmt: skip
    assert cell(RN.coverage_cells(rows, "AAA", D)).missing.code == "few_scored"


def test_the_interval_is_the_cluster_bootstrap_of_the_same_rows():
    rows = quarter_rows("AAA", 16)
    rows[3] = row("AAA", "FY2018Q4", "2018-12-28", inside=False)
    rows[9] = row("AAA", "FY2020Q2", "2020-06-28", inside=False)
    cells = RN.coverage_cells(rows, "AAA", D)
    want = RR.cluster_bootstrap(rows)
    for scope in ("all", "company"):
        c = cell(cells, scope=scope)
        assert c.interval == list(want)
        assert c.target_in_interval == (want[0] <= RN.TARGET <= want[1])
    assert cell(cells).n_clusters == len({RR.calendar_quarter(r["period_end"]) for r in rows})
    assert (cell(cells).target, cell(cells).acceptable) == (0.80, [0.65, 0.95])


def test_company_cells_use_only_the_companys_rows():
    rows = quarter_rows("AAA", 12) + quarter_rows("BBB", 12, inside=False)
    cells = RN.coverage_cells(rows, "AAA", D)
    assert cell(cells, scope="all").n == 24 and cell(cells, scope="all").share == 0.5
    assert cell(cells, scope="company").n == 12 and cell(cells, scope="company").share == 1.0


def test_differs_from_all_when_the_all_share_is_outside_the_companys_interval():
    rows = quarter_rows("AAA", 12) + quarter_rows("BBB", 12, inside=False)
    cells = RN.coverage_cells(rows, "AAA", D)
    assert cell(cells, scope="company").differs_from_all is True
    assert cell(cells, scope="all").differs_from_all is None
    same = RN.coverage_cells(quarter_rows("AAA", 12), "AAA", D)
    assert cell(same, scope="company").differs_from_all is False


def test_basis_flags_are_counted_in_company_cells_and_all_cells_are_unchecked():
    rows = quarter_rows("AAA", 12)
    rows[0] = row("AAA", "FY2018Q1", "2018-03-28", inside=False)  # a miss that is a recast
    rows[1] = row("AAA", "FY2018Q2", "2018-06-28")  # a recast that still fell inside
    flags = {(rows[0]["subject_id"], "FY2018Q1", "revenue"),
             (rows[1]["subject_id"], "FY2018Q2", "revenue")}  # fmt: skip
    cells = RN.coverage_cells(rows, "AAA", D, flags)
    c = cell(cells, scope="company")
    assert (c.basis_changes, c.basis_changes_outside) == (2, 1)
    assert c.notes == []
    a = cell(cells, scope="all")
    assert (a.basis_changes, a.basis_changes_outside) == (None, None)
    assert [n.code for n in a.notes] == ["basis_unchecked"]
    # the ebit cell has no flagged ebit rows
    assert cell(cells, scope="company", item="ebit").basis_changes == 0
    # without flags a company cell is unchecked (None) and carries no note of its own
    c = cell(RN.coverage_cells(rows, "AAA", D), scope="company")
    assert (c.basis_changes, c.basis_changes_outside) == (None, None)


def test_a_date_on_or_before_2021_has_no_coverage_history():
    for on in (R.ROLLING_FROM, date(2020, 5, 1)):
        cells = RN.coverage_cells(quarter_rows("AAA", 12), "AAA", on)
        assert len(cells) == 8
        assert all(c.missing.code == "no_coverage_history" and c.verdict is None for c in cells)
        assert cells[0].missing.params == {"origins_from": "2021-01-01", "as_of": on.isoformat()}
    after = RN.coverage_cells(quarter_rows("AAA", 12), "AAA", date(2021, 1, 2))
    assert cell(after).missing is None  # pooled revenue has its 12 quarters


# -- scored_origin_rows on stored origins -------------------------------------------------------


def test_coverage_counts_an_origin_before_d_but_not_one_dated_d(company):
    history(company)
    add_origin(company, "AAA", date(2021, 5, 31), [scored(1, "FY2021Q1", date(2021, 6, 1))])
    add_origin(company, "AAA", date(2021, 6, 1), [scored(1, "FY2021Q2", date(2021, 6, 1))])
    pairs = R.load_pairs(company)
    rows = RN.scored_origin_rows(company, D, pairs, N)
    assert {r["subject_id"] for r in rows} == {"AAA_2021-05-31"}
    assert len(rows) == 4  # 2 pools × 2 items
    assert all(r["ticker"] == "AAA" and r["status"] == "ok" for r in rows)
    # the next day, the origin dated D counts too once its actual is filed
    later = RN.scored_origin_rows(company, date(2021, 6, 2), pairs, N)
    assert {r["subject_id"] for r in later} == {"AAA_2021-05-31", "AAA_2021-06-01"}


def test_a_quarter_filed_after_d_and_origins_before_2021_are_not_counted(company):
    history(company)
    add_origin(company, "AAA", date(2021, 3, 15), [scored(1, "FY2021Q1", date(2021, 6, 2))])
    add_origin(company, "AAA", date(2020, 12, 31), [scored(1, "FY2020Q4", date(2021, 2, 1))])
    add_origin(company, "AAA", date(2021, 1, 1), [scored(1, "FY2020Q4", date(2021, 2, 1))])
    rows = RN.scored_origin_rows(company, D, R.load_pairs(company), N)
    assert {r["subject_id"] for r in rows} == {"AAA_2021-01-01"}  # 2021-01-01 itself counts


def test_one_target_quarter_scored_by_three_origins_is_three_rows_one_quarter(company):
    history(company)
    for as_of, h in ((date(2021, 1, 15), 3), (date(2021, 2, 15), 2), (date(2021, 3, 15), 1)):
        add_origin(company, "AAA", as_of, [scored(h, "FY2021Q2", date(2021, 5, 15), 100.0)])
    rows = RN.scored_origin_rows(company, D, R.load_pairs(company), N)
    assert len(rows) == 12
    c = cell(RN.coverage_cells(rows, "AAA", D), scope="company")
    assert (c.n, c.n_quarters, c.inside) == (3, 1, 3)
    assert c.missing.code == "few_scored"


def test_a_scored_actual_far_from_the_range_is_above(company):
    history(company)
    add_origin(company, "AAA", date(2021, 3, 15), [scored(1, "FY2021Q1", date(2021, 5, 15), 400.0)])
    rows = RN.scored_origin_rows(company, D, R.load_pairs(company), N)
    c = cell(RN.coverage_cells(rows, "AAA", D), scope="company")
    assert (c.inside, c.below, c.above) == (0, 0, 1)


# -- run_ranges on a stored run -----------------------------------------------------------------


@pytest.fixture
def run(company):
    assert R.build_origin(company, "TST", date(2019, 5, 1), TODAY, CHOICES, TODAY) == "built"
    return company.execute("SELECT run_id FROM forecast_origins").fetchone()["run_id"]


def test_a_real_run_gets_bands_for_four_quarters_and_beyond_horizon_for_the_rest(company, run):
    out = RN.run_ranges(company, run, N)
    assert (out.run_id, out.ticker, out.as_of, out.basis) == (
        run,
        "TST",
        date(2019, 5, 1),
        "baseline",
    )
    assert len(out.quarters) >= 5
    assert [q.horizon for q in out.quarters] == list(range(1, len(out.quarters) + 1))
    for q in out.quarters:
        assert [b.pool for b in q.bands] == ["pooled", "own"]
        for b in q.bands:
            if q.horizon <= 4:
                assert b.missing.code == "no_history"  # nothing was filed by 2019-05-01
            else:
                assert b.missing.code == "beyond_horizon"
                assert b.missing.params == {"horizon": q.horizon, "max_horizon": 4}
                assert (b.n_errors, b.revenue, b.ebit) == (0, None, None)
    assert out.errors_filed_to is None


def test_run_bands_equal_ranges_with_the_run_id_seed(company, run):
    for i in range(25):
        quarters = [{"h": 1, "period": f"S{i}", "period_end": "2019-01-31",
                     "filed": date(2019, 3, 1), "actual_rev": 100.0 + (i % 5) - 2,
                     "actual_ebit": 10.0}]  # fmt: skip
        add_origin(
            company, "TST" if i < 15 else "OTH", date(2018, 6, 1) + timedelta(days=i), quarters
        )
    out = RN.run_ranges(company, run, N, check_basis=False)
    q1 = out.quarters[0]
    pairs = [p for p in R.load_pairs(company) if p.filed_at <= date(2019, 5, 1)]
    forecasts = {1: (q1.revenue_forecast, q1.ebit_forecast)}
    for b in q1.bands:
        seed = R.range_seed(f"{run}:baseline", b.pool)
        want = R.ranges(R.constant_samples(forecasts, N), pairs, out.as_of, b.pool, "TST", seed, N)
        assert b.revenue == dict(zip(RN.KEYS, want[1].revenue, strict=True))
        assert b.ebit == dict(zip(RN.KEYS, want[1].ebit, strict=True))
    assert [b.n_errors for b in q1.bands] == [25, 15]
    assert all(b.missing is None for b in q1.bands)
    assert out.errors_sha256 == R.pairs_sha256(pairs)
    assert out.errors_filed_to == date(2019, 3, 1)
    assert out.quarters[1].bands[0].missing.code == "no_history"  # no h2 misses stored


def test_a_run_dated_before_2021_has_no_coverage_history(company, run):
    out = RN.run_ranges(company, run, N)
    assert len(out.coverage) == 8
    assert all(c.missing.code == "no_coverage_history" for c in out.coverage)
    assert {(c.pool, c.scope, c.item) for c in out.coverage} == {
        (p, s, i) for p in R.POOLS for s in RN.SCOPES for i in RN.ITEMS
    }


def test_the_basis_check_runs_on_the_companys_earlier_origins(company, run):
    out = RN.run_ranges(company, run, N)  # check_basis on; no TST origin before the run's date
    own = out.quarters[0].bands[1]
    assert own.basis_changes is None or own.basis_changes == 0
    pooled = out.quarters[0].bands[0]
    assert [n.code for n in pooled.notes] == ["basis_unchecked"]
    unchecked = RN.run_ranges(company, run, N, check_basis=False)
    assert unchecked.quarters[0].bands[1].basis_changes is None
    assert [n.code for n in unchecked.quarters[0].bands[1].notes] == ["basis_unchecked"]


def test_notes_say_the_range_is_the_baselines_and_horizons_are_pooled(company, run):
    out = RN.run_ranges(company, run, N)
    codes = [n.code for n in out.notes]
    assert codes[:2] == ["baseline_only", "horizons_pooled"]
    assert "code_differs" not in codes


def test_code_differs_when_the_runs_code_version_is_not_the_origins(company, run):
    company.execute("UPDATE runs SET code_version = 'other-code' WHERE run_id = ?", (run,))
    company.commit()
    out = RN.run_ranges(company, run, N)
    (note,) = [n for n in out.notes if n.code == "code_differs"]
    assert note.params["run_code_version"] == "other-code"
    versions = [r[0] for r in company.execute("SELECT DISTINCT code_version FROM forecast_origins")]
    assert note.params["origins_code_versions"] == sorted(versions)


def test_the_same_call_twice_gives_the_same_dict(company, run):
    assert RN.run_ranges(company, run, N).to_dict() == RN.run_ranges(company, run, N).to_dict()


def test_to_dict_round_trips_through_json(company, run):
    d = RN.run_ranges(company, run, N).to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["as_of"] == "2019-05-01" and d["coverage"][0]["origins_from"] == "2021-01-01"
    assert d["quarters"][0]["bands"][0]["missing"]["code"] == "no_history"
    top = "run_id ticker as_of currency basis n_samples errors_sha256 errors_filed_to"
    assert set(d) >= set(top.split()) | {"quarters", "coverage", "notes"}


# -- the shocked range (backlog #167) -----------------------------------------------------------


def _with_history(company, count=25):
    for i in range(count):
        quarters = [{"h": h, "period": f"S{i}_{h}", "period_end": "2019-01-31",
                     "filed": date(2019, 3, 1), "actual_rev": 100.0 + (i % 5) - 2,
                     "actual_ebit": 10.0 + (i % 3) - 1} for h in (1, 2)]  # fmt: skip
        add_origin(
            company, "TST" if i < 15 else "OTH", date(2018, 6, 1) + timedelta(days=i), quarters
        )


def _sim(company, run, low=-6.0, base=-2.0, high=-1.0, n=N, seed=7, driver="revenue_growth"):
    from domains.analysis import montecarlo
    from tests.analysis.test_shocks import shock

    s = shock(driver=driver, low=low, base=base, high=high, horizon=4)
    return montecarlo.save_simulation(company, run, [s], n=n, seed=seed)


def test_a_baseline_call_has_no_simulation_and_centres_on_the_forecast(company, run):
    _with_history(company)
    out = RN.run_ranges(company, run, N, check_basis=False)
    assert (out.basis, out.sim_id) == ("baseline", None)
    for q in out.quarters:
        assert (q.revenue_center, q.ebit_center) == (q.revenue_forecast, q.ebit_forecast)
        for b in q.bands:
            assert b.revenue_vs_center == b.revenue_vs_forecast
            assert b.ebit_vs_center == b.ebit_vs_forecast


def test_shocked_bands_equal_ranges_on_the_simulations_samples(company, run):
    from domains.analysis.montecarlo import load_simulation_shocks, sample_lines
    from domains.analysis.runs import load_assumptions

    _with_history(company)
    sim_id = _sim(company, run, n=300, seed=11)
    out = RN.run_ranges(company, run, N, check_basis=False, sim_id=sim_id)
    assert (out.basis, out.sim_id, out.n_samples) == ("shocked", sim_id, 300)
    lines = sample_lines(load_assumptions(company, run), load_simulation_shocks(company, sim_id),
                         300, 11)  # fmt: skip
    samples = {h: (lines[("revenue", q.period)], lines[("ebit", q.period)])
               for h, q in enumerate(out.quarters[:2], start=1)}  # fmt: skip
    pairs = [p for p in R.load_pairs(company) if p.filed_at <= out.as_of]
    for pool_i, pool in enumerate(R.POOLS):
        seed = R.range_seed(f"{sim_id}:shocked", pool)
        want = R.ranges(samples, pairs, out.as_of, pool, "TST", seed, 300)
        for h in (1, 2):
            b = out.quarters[h - 1].bands[pool_i]
            assert b.revenue == dict(zip(RN.KEYS, want[h].revenue, strict=True))
            assert b.ebit == dict(zip(RN.KEYS, want[h].ebit, strict=True))


def test_the_centre_is_the_samples_median_and_vs_center_is_read_from_it(company, run):
    import numpy as np

    from domains.analysis.montecarlo import load_simulation_shocks, sample_lines
    from domains.analysis.runs import load_assumptions

    _with_history(company)
    sim_id = _sim(company, run)
    out = RN.run_ranges(company, run, N, check_basis=False, sim_id=sim_id)
    lines = sample_lines(load_assumptions(company, run), load_simulation_shocks(company, sim_id),
                         N, 7)  # fmt: skip
    for q in out.quarters:  # every quarter, also beyond horizon 4
        assert q.revenue_center == float(np.median(lines[("revenue", q.period)]))
        assert q.ebit_center == float(np.median(lines[("ebit", q.period)]))
    q1 = out.quarters[0]
    assert q1.revenue_center < q1.revenue_forecast  # a negative growth shock
    b = q1.bands[0]
    want_c = RN.vs_forecast(b.revenue, b.ebit, q1.revenue_center, q1.ebit_center)
    want_f = RN.vs_forecast(b.revenue, b.ebit, q1.revenue_forecast, q1.ebit_forecast)
    assert (b.revenue_vs_center, b.ebit_vs_center) == want_c
    assert (b.revenue_vs_forecast, b.ebit_vs_forecast) == want_f  # meaning unchanged


def test_the_centre_matches_the_stored_simulation_p50(company, run):
    from domains.analysis.montecarlo import load_bands

    _with_history(company)
    sim_id = _sim(company, run, driver="operating_margin")
    out = RN.run_ranges(company, run, N, check_basis=False, sim_id=sim_id, coverage=False)
    stored = load_bands(company, sim_id)
    for q in out.quarters:
        assert q.revenue_center == pytest.approx(stored[("revenue", q.period)].p50, abs=0.005)
        assert q.ebit_center == pytest.approx(stored[("ebit", q.period)].p50, abs=0.005)


def test_zero_width_shocks_give_the_baseline_band_drawn_with_the_same_seed(company, run):
    _with_history(company)
    sim_id = _sim(company, run, low=0.0, base=0.0, high=0.0)
    shocked = RN.run_ranges(company, run, N, check_basis=False, sim_id=sim_id, coverage=False)
    q1 = shocked.quarters[0]
    forecasts = {1: (q1.revenue_forecast, q1.ebit_forecast)}
    pairs = [p for p in R.load_pairs(company) if p.filed_at <= shocked.as_of]
    for i, pool in enumerate(R.POOLS):
        seed = R.range_seed(f"{sim_id}:shocked", pool)
        want = R.ranges(R.constant_samples(forecasts, N), pairs, shocked.as_of, pool, "TST", seed,
                        N)  # fmt: skip
        assert q1.bands[i].revenue == pytest.approx(
            dict(zip(RN.KEYS, want[1].revenue, strict=True)), rel=1e-12
        )
        assert q1.bands[i].ebit == pytest.approx(
            dict(zip(RN.KEYS, want[1].ebit, strict=True)), rel=1e-12
        )


def test_a_simulation_of_another_run_or_none_raises(company, run):
    with pytest.raises(EvaluationError, match="not stored"):
        RN.run_ranges(company, run, N, sim_id="NOPE_sim1")
    sim_id = _sim(company, run)
    company.execute("PRAGMA foreign_keys = OFF")  # a simulation stored under another run id
    company.execute("UPDATE simulations SET run_id = 'OTHER' WHERE sim_id = ?", (sim_id,))
    with pytest.raises(EvaluationError, match="not .*" + run):
        RN.run_ranges(company, run, N, sim_id=sim_id)


def test_shocked_notes_and_skipped_coverage(company, run):
    sim_id = _sim(company, run)
    out = RN.run_ranges(company, run, N, sim_id=sim_id, coverage=False)
    codes = [n.code for n in out.notes]
    assert codes[:3] == ["shocked_plus_misses", "coverage_is_baseline", "horizons_pooled"]
    assert "coverage_skipped" in codes and out.coverage == []
    assert out.notes[0].params == {"sim_id": sim_id}
    full = RN.run_ranges(company, run, N, sim_id=sim_id)
    assert len(full.coverage) == 8 and "coverage_skipped" not in [n.code for n in full.notes]
    assert full.to_dict() == RN.run_ranges(company, run, N, sim_id=sim_id).to_dict()
    d = full.to_dict()
    assert json.loads(json.dumps(d)) == d and d["sim_id"] == sim_id


def test_a_run_after_the_newest_stored_miss_says_the_misses_may_be_stale(company, run):
    _with_history(company)  # misses filed 2019-03-01; the run is dated 2019-05-01
    company.execute("DELETE FROM baseline_errors WHERE origin_id = 'TST_2019-05-01'")  # later ones
    (note,) = [n for n in RN.run_ranges(company, run, N, check_basis=False).notes
               if n.code == "errors_stale"]  # fmt: skip
    assert note.params == {"as_of": "2019-05-01", "errors_filed_to": "2019-03-01"}
    quarters = [scored(1, "LATE", date(2019, 5, 1))]
    add_origin(company, "OTH", date(2019, 1, 15), quarters)
    codes = [n.code for n in RN.run_ranges(company, run, N, check_basis=False).notes]
    assert "errors_stale" not in codes  # a miss filed on the run's date: the table is current


def test_an_unknown_run_raises(company):
    with pytest.raises(EvaluationError, match="not stored"):
        RN.run_ranges(company, "no_such_run", N)
