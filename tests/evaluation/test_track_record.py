"""Backlog #145: a company's forecast track record, on hand-made origins with known misses."""

import json
import math
from datetime import UTC, date, datetime

import pytest

from domains.evaluation import hindsight
from domains.evaluation import ranges as R
from domains.evaluation import run_ranges as RN
from domains.evaluation import track_record as T
from domains.evaluation.harness import EvaluationError, label, parse_label, score
from tests.evaluation.test_run_ranges import add_origin, history

N = 200
ASOF = date(2021, 7, 1)
FILED = date(2021, 5, 15)


def q(h, period, filed=FILED, rev=100.0, ebit=10.0, end="2021-03-31"):
    """One scored quarter of an origin (the forecast is revenue 100, EBIT 10)."""
    return {"h": h, "period": period, "period_end": end, "filed": filed,
            "actual_rev": rev, "actual_ebit": ebit}  # fmt: skip


def prior_of(period):
    year, quarter = parse_label(period)
    return label(year - 1, quarter)


def origin(conn, as_of, quarters, bench=None, ticker="TST", version="v-test"):
    """A stored TST origin with its run; `bench` maps a target period to (revenue, EBIT) held
    in the run's history rows a year earlier (an item given as None has no history row)."""
    rid = f"{ticker}_{as_of.isoformat()}_1"
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    ingest = conn.execute("SELECT MIN(run_id) FROM ingest_runs").fetchone()[0]
    conn.execute(
        "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
        "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
        "VALUES (?, ?, ?, ?, ?, ?, 'a', 'b', 'c', 'd')",
        (rid, cik, ticker, as_of.isoformat(), version, ingest),
    )
    conn.execute(  # a real run always holds assumptions (load_assumptions refuses an empty one)
        "INSERT INTO assumptions (run_id, name, period, value, source, method) "
        "VALUES (?, 'tax_rate', '-', 0.2, 'user', 'test')", (rid,))  # fmt: skip
    for period, (rev, ebit) in (bench or {}).items():
        for name, value in (("history:revenue", rev), ("history:ebit", ebit)):
            if value is not None:
                conn.execute(
                    "INSERT INTO assumptions (run_id, name, period, value, source, method) "
                    "VALUES (?, ?, ?, ?, 'computed', 'test')",
                    (rid, name, prior_of(period), value),
                )
    conn.commit()
    return add_origin(conn, ticker, as_of, quarters, version, run_id=rid)


def tr(conn, as_of=ASOF, **kw):
    kw.setdefault("check_basis", False)
    return T.track_record(conn, "TST", as_of, N, **kw)


def seq(conn, outcomes, h=1, start=(2017, 1)):
    """One origin per target quarter. Revenue forecast 100: "w" Warren closer (actual 100,
    benchmark 90), "l" benchmark closer (actual 80, benchmark 80), "t" tie (100, 100). EBIT is
    forecast, actual and benchmark all 10: a tie."""
    for i, kind in enumerate(outcomes):
        year, quarter = divmod(start[0] * 4 + start[1] - 1 + i, 4)
        period = f"FY{year}Q{quarter + 1}"
        rev, bench = {"w": (100.0, 90.0), "l": (80.0, 80.0), "t": (100.0, 100.0)}[kind]
        end = f"{year}-{(quarter + 1) * 3:02d}-28"
        origin(conn, date(2021, 1, 1 + i), [q(h, period, rev=rev, end=end)],
               {period: (bench, 10.0)})  # fmt: skip


def summary(rec, item="revenue", h=None):
    (s,) = [s for s in rec.summaries if (s.item, s.horizon) == (item, h)]
    return s


def codes(coded):
    return [c.code for c in coded]


# -- rows: the dates ----------------------------------------------------------------------------


def test_origins_repeating_one_forecast_make_one_row(company):
    for d in (date(2021, 2, 1), date(2021, 3, 1), date(2021, 4, 1)):
        origin(company, d, [q(1, "FY2021Q1")], {"FY2021Q1": (90.0, 9.0)})
    origin(company, date(2021, 4, 2), [q(2, "FY2021Q1")], {"FY2021Q1": (90.0, 9.0)})
    rec = tr(company)
    by = {(r.period, r.horizon): r for r in rec.rows}
    assert set(by) == {("FY2021Q1", 1), ("FY2021Q1", 2)}
    one = by[("FY2021Q1", 1)]
    assert one.n_origins == 3 and one.made_on == date(2021, 2, 1)
    assert one.origin_id == "TST_2021-02-01" and one.run_id == "TST_2021-02-01_1"
    assert by[("FY2021Q1", 2)].n_origins == 1 and by[("FY2021Q1", 2)].made_on == date(2021, 4, 2)
    (dedup,) = [n for n in rec.notes if n.code == "deduplicated"]
    assert dedup.params == {"rows": 2, "origins": 4}


def test_an_origin_dated_d_is_not_used_and_one_dated_the_day_before_is(company):
    d = date(2021, 6, 1)
    origin(company, date(2021, 5, 31), [q(1, "FY2021Q1", date(2021, 5, 20))])
    origin(company, d, [q(1, "FY2021Q2", date(2021, 5, 20))])
    assert [r.period for r in tr(company, d).rows] == ["FY2021Q1"]
    assert sorted(r.period for r in tr(company, date(2021, 6, 2)).rows) == ["FY2021Q1", "FY2021Q2"]


def test_an_actual_filed_the_day_after_d_is_not_used(company):
    d = date(2021, 6, 1)
    origin(company, date(2021, 1, 15), [q(1, "FY2020Q2", d), q(2, "FY2020Q3", date(2021, 6, 2))])
    rec = tr(company, d)
    assert [r.period for r in rec.rows] == ["FY2020Q2"]
    assert rec.rows[0].items["revenue"].filed_at == d
    assert sorted(r.period for r in tr(company, date(2021, 6, 2)).rows) == ["FY2020Q2", "FY2020Q3"]


def test_revenue_filed_by_d_but_ebit_filed_after_d_is_not_used(company):
    d = date(2021, 6, 1)
    origin(company, date(2021, 1, 15), [q(1, "FY2020Q3", date(2021, 5, 1)), q(2, "FY2020Q4")])
    company.execute(
        "UPDATE baseline_errors SET actual_filed_at = '2021-06-02' "
        "WHERE item = 'ebit' AND period = 'FY2020Q3'"
    )
    company.commit()
    assert [r.period for r in tr(company, d).rows] == ["FY2020Q4"]
    later = tr(company, date(2021, 6, 2))
    assert sorted(r.period for r in later.rows) == ["FY2020Q3", "FY2020Q4"]
    row = [r for r in later.rows if r.period == "FY2020Q3"][0]
    assert row.items["revenue"].filed_at == date(2021, 5, 1)
    assert row.items["ebit"].filed_at == date(2021, 6, 2)


def test_failed_origins_are_not_rows_but_are_noted(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1")], version="v1")
    origin(company, date(2021, 3, 1), [q(1, "FY2021Q1")], version="v2")
    add_origin(company, "TST", date(2021, 3, 5), [], status="failed")
    company.execute("UPDATE forecast_origins SET reason = 'no filing' WHERE status = 'failed'")
    company.commit()
    rec = tr(company)
    assert [r.n_origins for r in rec.rows] == [2]
    (diff,) = [n for n in rec.notes if n.code == "code_differs"]
    assert diff.params == {"origins_code_versions": ["v1", "v2"]}
    (failed,) = [n for n in rec.notes if n.code == "origins_failed"]
    assert failed.params["n"] == 1 and failed.params["reasons"] == ["no filing"]


# -- rows: the misses ---------------------------------------------------------------------------


def test_miss_and_signed_miss_equal_the_harness_score(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1", rev=80.0, ebit=5.0),
                                       q(2, "FY2021Q2", rev=125.0, ebit=20.0)])  # fmt: skip
    rec = tr(company)
    by = {r.period: r for r in rec.rows}
    for period, rev, ebit in (("FY2021Q1", 80.0, 5.0), ("FY2021Q2", 125.0, 20.0)):
        rv, eb = by[period].items["revenue"], by[period].items["ebit"]
        err, signed, _ = score("revenue", 100.0, rev, rev)
        assert (rv.miss, rv.signed_miss, rv.forecast, rv.actual) == (err, signed, 100.0, rev)
        err, signed, _ = score("ebit", 10.0, ebit, rev)
        assert (eb.miss, eb.signed_miss, eb.forecast, eb.actual) == (err, signed, 10.0, ebit)
        assert (rv.miss_unit, eb.miss_unit) == (
            hindsight.MISS_UNITS["revenue"], hindsight.MISS_UNITS["ebit"])  # fmt: skip
    assert by["FY2021Q1"].items["revenue"].signed_miss == pytest.approx(0.25)  # too high
    assert by["FY2021Q1"].items["ebit"].signed_miss == pytest.approx(5.0 / 80.0)  # of revenue
    assert by["FY2021Q2"].items["revenue"].signed_miss == pytest.approx(-0.2)  # too low
    assert by["FY2021Q2"].items["ebit"].miss == pytest.approx(10.0 / 125.0)


def test_signed_miss_has_the_opposite_sign_to_the_stored_log_error(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1", rev=80.0), q(2, "FY2021Q2", rev=125.0)])
    rec = tr(company)
    for r in rec.rows:
        (stored,) = company.execute(
            "SELECT error FROM baseline_errors WHERE origin_id = ? AND period = ? "
            "AND item = 'revenue'", (r.origin_id, r.period)).fetchone()  # fmt: skip
        assert stored == pytest.approx(math.log(r.items["revenue"].actual / 100.0))
        assert stored * r.items["revenue"].signed_miss < 0


# -- the benchmark ------------------------------------------------------------------------------


def test_the_benchmark_is_the_runs_history_a_year_earlier(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1", rev=80.0, ebit=5.0)],
           {"FY2021Q1": (90.0, 9.0)})  # fmt: skip
    # a later origin's run holds other history; the row keeps the first origin's
    origin(company, date(2021, 3, 1), [q(1, "FY2021Q1", rev=80.0, ebit=5.0)],
           {"FY2021Q1": (1.0, 1.0)})  # fmt: skip
    (row,) = tr(company).rows
    rv, eb = row.items["revenue"], row.items["ebit"]
    assert (rv.benchmark_forecast, eb.benchmark_forecast) == (90.0, 9.0)
    assert rv.benchmark_signed_miss == score("revenue", 90.0, 80.0, 80.0)[1]
    assert rv.benchmark_miss == score("revenue", 90.0, 80.0, 80.0)[0] == pytest.approx(0.125)
    assert eb.benchmark_miss == score("ebit", 9.0, 5.0, 80.0)[0] == pytest.approx(4.0 / 80.0)
    assert rv.benchmark_missing is None and eb.benchmark_missing is None
    assert rv.closer == "benchmark" and eb.closer == "benchmark"  # .25 vs .125; .0625 vs .05


def test_a_missing_history_row_gives_no_benchmark(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1"), q(2, "FY2021Q2")],
           {"FY2021Q2": (100.0, None)})  # fmt: skip
    by = {r.period: r for r in tr(company).rows}
    for item in ("revenue", "ebit"):
        x = by["FY2021Q1"].items[item]
        assert x.benchmark_forecast is None and x.benchmark_miss is None
        assert x.benchmark_signed_miss is None and x.closer is None
        assert x.benchmark_missing.code == "no_benchmark"
        assert x.benchmark_missing.params == {"period": "FY2021Q1", "prior": "FY2020Q1"}
    q2 = by["FY2021Q2"].items
    assert q2["revenue"].benchmark_missing is None and q2["revenue"].closer == "tie"
    assert q2["ebit"].benchmark_forecast is None and q2["ebit"].benchmark_missing.code == (
        "no_benchmark")  # fmt: skip


def test_closer_is_tie_on_equal_misses_and_warren_or_benchmark_otherwise(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1", rev=100.0), q(2, "FY2021Q2", rev=110.0),
                                       q(3, "FY2021Q3", rev=80.0)])  # fmt: skip
    origin(company, date(2021, 2, 2), [q(1, "FY2021Q4", rev=100.0)])
    # a symmetric benchmark misses by the same amount as Warren: 100 vs 100 and 90 / 110 on 100
    company.execute("DELETE FROM assumptions")
    for rid, period, value in (
        ("TST_2021-02-01_1", "FY2020Q1", 100.0),  # forecast 100, actual 100, benchmark 100: tie
        ("TST_2021-02-01_1", "FY2020Q2", 90.0),  # actual 110: Warren .0909, benchmark .1818
        ("TST_2021-02-01_1", "FY2020Q3", 80.0),  # actual 80: benchmark exact
        ("TST_2021-02-02_1", "FY2020Q4", 120.0),  # actual 100: Warren 0, benchmark .2
    ):
        company.execute(
            "INSERT INTO assumptions VALUES (?, 'history:revenue', ?, ?, 'computed', 't')",
            (rid, period, value),
        )
        company.execute(
            "INSERT INTO assumptions VALUES (?, 'history:ebit', ?, 10.0, 'computed', 't')",
            (rid, period),
        )
    company.commit()
    by = {r.period: r.items["revenue"] for r in tr(company).rows}
    assert by["FY2021Q1"].closer == "tie"
    assert by["FY2021Q1"].miss == by["FY2021Q1"].benchmark_miss == 0.0
    assert by["FY2021Q2"].closer == "warren"
    assert by["FY2021Q3"].closer == "benchmark"
    assert by["FY2021Q4"].closer == "warren"
    assert by["FY2021Q2"].benchmark_miss == pytest.approx(20.0 / 110.0)


# -- summaries ----------------------------------------------------------------------------------


def test_wins_losses_and_ties_add_up_to_the_rows_at_a_horizon(company):
    seq(company, "wwwlltwlt")
    rec = tr(company)
    for item in ("revenue", "ebit"):
        for h in (1, 2, 3, 4):
            s = summary(rec, item, h)
            assert s.wins + s.losses + s.ties == (s.n_rows if h == 1 else 0)
    s = summary(rec, "revenue", 1)
    assert (s.wins, s.losses, s.ties, s.n_rows, s.n_quarters) == (4, 3, 2, 9, 9)
    e = summary(rec, "ebit", 1)  # forecast, actual and benchmark all equal: every one a tie
    assert (e.wins, e.losses, e.ties) == (0, 0, 9)
    assert e.sign_p is None and e.verdict is None
    assert (s.item, s.miss_unit) == ("revenue", "fraction_of_actual")
    assert e.miss_unit == "fraction_of_actual_revenue"


def test_all_horizons_are_tested_once_per_target_quarter(company):
    # quarter A is forecast at h1 (benchmark 20, Warren better by .75 - 0 ... see below) and h2
    # (benchmark exact, Warren worse): per row one win and one loss, per quarter one mean
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1", rev=80.0)], {"FY2021Q1": (20.0, 10.0)})
    origin(company, date(2021, 3, 1), [q(2, "FY2021Q1", rev=80.0)], {"FY2021Q1": (80.0, 10.0)})
    rec = tr(company)
    h1, h2, both = (summary(rec, "revenue", h) for h in (1, 2, None))
    assert (h1.wins, h1.losses) == (1, 0) and (h2.wins, h2.losses) == (0, 1)
    # Warren .25 vs benchmark .75 (diff -.5) at h1, vs 0 (diff +.25) at h2: mean -.125, a win
    assert (both.n_rows, both.n_quarters) == (2, 1)
    assert (both.wins, both.losses, both.ties) == (1, 0, 0)
    assert both.wins + both.losses + both.ties != both.n_rows
    assert {"horizons_pooled", "tested_per_quarter"} <= set(codes(both.notes))
    assert both.missing.code == "few_quarters" and both.verdict is None


def test_no_verdict_at_horizon_two_or_more_and_a_note_says_why(company):
    seq(company, "w" * 12, h=2)
    rec = tr(company)
    for h in (2, 3, 4):
        s = summary(rec, "revenue", h)
        assert s.verdict is None
        assert ("overlapping_horizon" in codes(s.notes)) is True
    s2 = summary(rec, "revenue", 2)
    assert (s2.n_rows, s2.wins, s2.missing) == (12, 12, None)
    assert s2.sign_p == pytest.approx(2 / 2**12)  # a verdict would have been warren_better
    assert "overlapping_horizon" not in codes(summary(rec, "revenue", 1).notes)
    assert summary(rec, "revenue", None).verdict == "warren_better"  # per quarter, all horizons


def test_few_quarters_at_11_distinct_quarters_and_not_at_12(company):
    seq(company, "w" * 11)
    s = summary(tr(company), "revenue", 1)
    assert s.missing.code == "few_quarters" and s.n_quarters == 11 and s.verdict is None
    assert s.missing.params == {"n_quarters": 11, "min_quarters": 12}
    assert s.sign_p is not None  # the counts stay shown
    origin(company, date(2021, 1, 12), [q(1, "FY2020Q4", end="2020-12-28")],
           {"FY2020Q4": (90.0, 10.0)})  # fmt: skip
    s = summary(tr(company), "revenue", 1)
    assert s.n_quarters == 12 and s.missing is None and s.verdict == "warren_better"


def test_the_verdict_is_warren_better_only_when_the_sign_test_is_below_05(company):
    seq(company, "wwwwwwwwllll")
    s = summary(tr(company), "revenue", 1)
    assert (s.wins, s.losses) == (8, 4) and s.sign_p == pytest.approx(2 * 794 / 4096)
    assert s.verdict == "not_shown"
    # skill = 1 - mean miss / benchmark mean miss; Warren .25 × 4 over 12, benchmark .1 × 8
    assert s.mean_miss == pytest.approx(4 * 0.25 / 12)
    assert s.benchmark_mean_miss == pytest.approx(8 * 0.1 / 12)
    assert s.skill == pytest.approx(1 - s.mean_miss / s.benchmark_mean_miss) == pytest.approx(-0.25)
    assert (s.median_miss, s.benchmark_median_miss) == (0.0, pytest.approx(0.1))


def test_a_clear_win_or_loss_gives_the_verdict_and_skill_one_when_warren_is_exact(company):
    seq(company, "w" * 12)
    s = summary(tr(company), "revenue", 1)
    assert s.sign_p == pytest.approx(2 / 4096) and s.verdict == "warren_better"
    assert s.mean_miss == 0.0 and s.skill == 1.0


def test_benchmark_better_when_the_benchmark_wins_most_quarters(company):
    seq(company, "l" * 12)
    s = summary(tr(company), "revenue", 1)
    assert (s.wins, s.losses) == (0, 12) and s.verdict == "benchmark_better"
    assert s.benchmark_mean_miss == 0.0 and s.skill is None  # nothing to divide by


def test_missing_benchmarks_are_left_out_of_the_tests_but_not_of_the_rows(company):
    seq(company, "w" * 12)
    origin(company, date(2021, 1, 20), [q(1, "FY2020Q1", rev=80.0, end="2020-03-28")])
    s = summary(tr(company), "revenue", 1)
    assert s.n_rows == 13 and s.wins + s.losses + s.ties == 12


# -- ranges -------------------------------------------------------------------------------------


def scored_row(company, as_of, pool="pooled", item="revenue", period=None, h=None):
    raw = RN.scored_origin_rows(company, ASOF, R.load_pairs(company), N)
    (row,) = [r for r in raw if r["subject_id"] == f"TST_{as_of}" and r["pool"] == pool
              and r["item"] == item and (period is None or r["period"] == period)
              and (h is None or r["horizon"] == h)]  # fmt: skip
    return row


def test_a_group_made_only_before_2021_is_warm_up(company):
    history(company, "OTH")
    origin(company, date(2020, 10, 1), [q(1, "FY2020Q3", date(2021, 1, 20))])
    origin(company, date(2020, 11, 1), [q(1, "FY2020Q3", date(2021, 1, 20))])
    (row,) = tr(company).rows
    assert row.n_origins == 2 and row.made_on == date(2020, 10, 1)
    for item in ("revenue", "ebit"):
        for pool in R.POOLS:
            held = row.items[item].ranges[pool]
            assert held.missing.code == "warm_up" and held.held is None
            assert (held.made_on, held.p10, held.p90) == (None, None, None)
            assert held.missing.params == {"made_on": "2020-11-01", "origins_from": "2021-01-01"}
    assert summary(tr(company), "revenue", None).ranges["pooled"].n_rows == 0


def test_a_group_spanning_2021_takes_its_range_from_the_later_origin(company):
    history(company, "OTH")
    origin(company, date(2020, 12, 15), [q(1, "FY2020Q4", date(2021, 3, 1), end="2020-12-28")])
    origin(company, date(2021, 2, 1), [q(1, "FY2020Q4", date(2021, 3, 1), end="2020-12-28")])
    (row,) = tr(company).rows
    assert row.made_on == date(2020, 12, 15) and row.n_origins == 2
    for item in ("revenue", "ebit"):
        held = row.items[item].ranges["pooled"]
        want = scored_row(company, "2021-02-01", item=item)
        assert held.made_on == date(2021, 2, 1)
        assert (held.p10, held.p90) == (want["p10"], want["p90"])
        assert held.missing is None and held.held == "inside"
    assert row.items["revenue"].ranges["own"].missing.code == "no_history"  # no TST misses yet


def test_held_inside_below_or_above_and_ends_count_as_inside(company):
    history(company, "OTH")
    origin(company, date(2021, 3, 15), [q(1, "FY2021Q1"), q(2, "FY2021Q2"), q(3, "FY2021Q3")])
    p = {h: scored_row(company, "2021-03-15", h=h) for h in (1, 2, 3)}
    assert p[1]["p10"] < 100.0 < p[1]["p90"]
    actuals = {1: p[1]["p10"], 2: p[2]["p10"] - 0.5, 3: p[3]["p90"] + 0.5}
    for h, a in actuals.items():
        company.execute(
            "UPDATE baseline_errors SET actual = ? WHERE horizon = ? AND item = 'revenue'", (a, h)
        )
    company.commit()
    held = {r.horizon: r.items["revenue"].ranges["pooled"] for r in tr(company).rows}
    assert held[1].held == "inside" and held[1].p10 == actuals[1]
    assert held[2].held == "below" and held[3].held == "above"
    for h in (1, 2, 3):
        assert (held[h].p10, held[h].p90) == (p[h]["p10"], p[h]["p90"])
        assert held[h].made_on == date(2021, 3, 15)


def test_the_range_cell_counts_shares_and_the_others_exclude_the_company(company):
    history(company, "OTH")
    origin(company, date(2021, 3, 15), [q(1, "FY2021Q1"), q(2, "FY2021Q2"), q(3, "FY2021Q3")])
    # the other company: one actual inside its h1 range, one far above
    add_origin(company, "OTH", date(2021, 3, 16), [q(1, "FY2021Q1")])
    add_origin(company, "OTH", date(2021, 3, 17), [q(1, "FY2021Q2", rev=400.0)])
    pa = {h: scored_row(company, "2021-03-15", h=h) for h in (1, 2, 3)}
    for h, a in ((2, pa[2]["p10"] - 0.5), (3, pa[3]["p90"] + 0.5)):
        company.execute(
            "UPDATE baseline_errors SET actual = ? WHERE origin_id = 'TST_2021-03-15' "
            "AND horizon = ? AND item = 'revenue'", (a, h))  # fmt: skip
    company.commit()
    rec = tr(company)
    allh = summary(rec, "revenue", None).ranges["pooled"]
    assert (allh.inside, allh.below, allh.above) == (1, 1, 1)
    assert (allh.n_rows, allh.n_quarters, allh.share) == (3, 3, pytest.approx(1 / 3))
    assert allh.others_share == 0.5  # OTH's two h1 rows; none of TST's three
    assert allh.missing.code == "few_scored" and allh.verdict is None
    assert allh.missing.params == {"n_quarters": 3, "min_quarters": 12}
    assert allh.differs_from_others is None and allh.target_in_interval is None
    assert allh.notes == []
    one = summary(rec, "revenue", 1).ranges["pooled"]
    assert (one.inside, one.n_rows, one.n_quarters, one.share) == (1, 1, 1, 1.0)
    assert one.others_share == 0.5
    assert codes(one.notes) == ["all_inside"] and one.notes[0].params == {"n_rows": 1}
    assert summary(rec, "revenue", 2).ranges["pooled"].others_share is None
    assert (one.target, one.acceptable) == (T.TARGET, list(T.ACCEPTABLE))
    # by origin counts every monthly origin; here each group has a single origin
    assert one.share_by_origin == 1.0 and allh.share_by_origin == pytest.approx(1 / 3)


def test_a_cell_with_12_distinct_quarters_is_judged_and_11_is_few_scored(company):
    history(company, "OTH")
    for i in range(12):
        year, quarter = divmod(2017 * 4 + i, 4)
        period, end = f"FY{year}Q{quarter + 1}", f"{year}-{quarter * 3 + 3:02d}-28"
        origin(company, date(2021, 2, 1 + i), [q(1, period, end=end)])
    c = summary(tr(company), "revenue", 1).ranges["pooled"]
    assert (c.n_rows, c.n_quarters) == (12, 12) and c.missing is None
    assert c.share == 1.0 and c.verdict == "too_wide" and c.interval is not None
    assert codes(c.notes) == ["all_inside"]
    company.execute("DELETE FROM baseline_errors WHERE origin_id = 'TST_2021-02-12'")
    company.execute("DELETE FROM forecast_origins WHERE origin_id = 'TST_2021-02-12'")
    company.commit()
    c = summary(tr(company), "revenue", 1).ranges["pooled"]
    assert c.n_quarters == 11 and c.missing.code == "few_scored" and c.verdict is None


def test_one_quarter_at_two_horizons_is_two_rows_and_one_quarter(company):
    history(company, "OTH")
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1")])
    origin(company, date(2021, 3, 1), [q(2, "FY2021Q1")])
    c = summary(tr(company), "revenue", None).ranges["pooled"]
    assert (c.n_rows, c.n_quarters, c.n_clusters) == (2, 1, 1)


def test_ranges_are_baseline_only_and_the_notes_say_so(company):
    rec = tr(company)
    assert codes(rec.notes)[:5] == ["deduplicated", "benchmark_is_srw", "baseline_only",
                                    "cases_not_included", "headline"]  # fmt: skip
    assert rec.headline == {"horizon": None, "pool": "pooled"}


# -- basis changes ------------------------------------------------------------------------------


def test_basis_flags_mark_rows_and_count_in_summaries(company, monkeypatch):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1")])
    origin(company, date(2021, 3, 1), [q(1, "FY2021Q1")])
    origin(company, date(2021, 4, 1), [q(1, "FY2021Q2", end="2021-06-28")])
    flags = {("TST_2021-03-01", "FY2021Q1", "revenue"),  # the group's second origin counts
             ("TST_2021-04-01", "FY2021Q1", "ebit")}  # not this origin's quarter  # fmt: skip
    seen = []

    def fake(conn, ticker, on):
        seen.append((ticker, on))
        return flags

    monkeypatch.setattr(RN, "basis_flags", fake)
    rec = tr(company, check_basis=True)
    assert seen == [("TST", ASOF)]
    assert {r.period: r.basis_change for r in rec.rows} == {"FY2021Q1": True, "FY2021Q2": False}
    for item in ("revenue", "ebit"):
        assert summary(rec, item, None).basis_changes == 1
        assert summary(rec, item, 1).basis_changes == 1
        assert summary(rec, item, 2).basis_changes == 0
        assert summary(rec, item, None).ranges["pooled"].basis_changes == 0  # no scored rows
    off = tr(company, check_basis=False)
    assert [r.basis_change for r in off.rows] == [None, None]
    assert summary(off, "revenue", None).basis_changes is None
    assert summary(off, "revenue", None).ranges["pooled"].basis_changes is None
    basis = "a change of reporting basis"
    assert "FY2021Q1 *" in T.render(rec) and basis in T.render(rec)
    assert basis not in T.render(off) and "FY2021Q1 *" not in T.render(off)


# -- the call -----------------------------------------------------------------------------------


def test_the_same_call_twice_gives_the_same_dict(company):
    history(company, "OTH")
    seq(company, "wlwwtl")
    assert tr(company).to_dict() == tr(company).to_dict()
    assert tr(company) == tr(company)


def test_to_dict_round_trips_through_json(company):
    history(company, "OTH")
    seq(company, "wlw")
    d = tr(company).to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["ticker"] == "TST" and d["as_of"] == "2021-07-01" and d["currency"] == "USD"
    assert d["as_of_default"] is False and d["missing"] is None
    assert d["rows"][0]["made_on"] == "2021-01-01"
    assert d["rows"][0]["items"]["revenue"]["filed_at"] == "2021-05-15"
    assert d["notes"][0]["code"] == "deduplicated"
    assert len(d["summaries"]) == 10  # revenue and EBIT × (all horizons, 1, 2, 3, 4)
    assert set(d) >= {"ticker", "as_of", "headline", "rows", "summaries", "notes", "errors_sha256"}


def test_an_unknown_ticker_raises(company):
    with pytest.raises(EvaluationError, match="ZZZ has not been ingested"):
        T.track_record(company, "zzz", ASOF, N)


def test_a_company_with_no_rows_is_coded_not_raised(company):
    rec = T.track_record(company, "tst", ASOF, N, check_basis=False)
    assert rec.ticker == "TST" and rec.rows == [] and rec.summaries == []
    assert rec.missing.code == "no_track_record"
    assert rec.missing.params == {"ticker": "TST", "as_of": "2021-07-01"}
    text = T.render(rec)
    assert "TST track record as of 2021-07-01" in text and rec.missing.text in text
    assert rec.to_dict()["missing"]["code"] == "no_track_record"


def test_as_of_none_is_the_last_ended_day_in_new_york(company):
    now = datetime(2021, 7, 2, 3, 0, tzinfo=UTC)  # 23:00 on July 1 in New York
    rec = T.track_record(company, "TST", None, N, False, now)
    assert rec.as_of == date(2021, 6, 30) and rec.as_of_default is True
    later = T.track_record(company, "TST", None, N, False, datetime(2021, 7, 2, 12, tzinfo=UTC))
    assert later.as_of == date(2021, 7, 1)
    assert T.track_record(company, "TST", date(2021, 7, 1), N, False, now).as_of_default is False
    assert "(the last day ended in New York)" in T.render(rec)


def test_render_shows_the_summaries_and_each_items_quarters(company):
    seq(company, "wl")
    text = T.render(tr(company))
    assert "TST track record as of 2021-07-01" in text
    assert "| revenue | all | 2 |" in text and "FY2017Q1" in text and "FY2017Q2" in text
    assert "revenue: forecast, first-reported actual" in text and "ebit: forecast" in text
    assert "Note: " in text


# -- the benchmark with drift (backlog #188) ----------------------------------------------------


def hist_rows(conn, run_id, rows):
    """Add history rows to a run: `rows` maps a period to (revenue, EBIT)."""
    for period, (rev, ebit) in rows.items():
        for name, value in (("history:revenue", rev), ("history:ebit", ebit)):
            if value is not None:
                conn.execute(
                    "INSERT INTO assumptions (run_id, name, period, value, source, method) "
                    "VALUES (?, ?, ?, ?, 'computed', 'test')",
                    (run_id, name, period, value),
                )
    conn.commit()


def quarters_back(year, quarter, n):
    """The n fiscal quarters ending at (year, quarter), oldest first, as labels."""
    out = []
    for i in range(n - 1, -1, -1):
        y, qq = divmod(year * 4 + quarter - 1 - i, 4)
        out.append(f"FY{y}Q{qq + 1}")
    return out


def grower(conn, as_of, target, h=1, n=12, step=5.0, rev=None, start=100.0):
    """An origin forecasting `target` at horizon h whose run holds n history quarters ending at
    target − h, revenue rising by `step` a quarter (EBIT a tenth of it)."""
    year, quarter = parse_label(target)
    last = divmod(year * 4 + quarter - 1 - h, 4)
    periods = quarters_back(last[0], last[1] + 1, n)
    values = {p: (start + step * i, (start + step * i) / 10) for i, p in enumerate(periods)}
    actual = start + step * (n - 1 + h) if rev is None else rev
    origin(conn, as_of, [q(h, target, rev=actual, ebit=actual / 10)])
    hist_rows(conn, f"TST_{as_of.isoformat()}_1", values)
    return values


def test_drift_forecast_is_last_years_quarter_plus_the_mean_seasonal_change():
    values = [10, 20, 30, 40, 12, 24, 33, 48, 15, 25, 39, 52]
    known = {parse_label(p): v for p, v in zip(quarters_back(2020, 4, 12), values, strict=True)}
    fc, step, n = T.drift_forecast(known, "FY2021Q1")
    changes = [12 - 10, 24 - 20, 33 - 30, 48 - 40, 15 - 12, 25 - 24, 39 - 33, 52 - 48]
    assert n == 8 and step == pytest.approx(sum(changes) / 8)
    assert fc == pytest.approx(15 + sum(changes) / 8)  # FY2020Q1 + δ
    # at horizon 3 the base is still a known quarter (t − 4 is before the last reported)
    fc3, _, _ = T.drift_forecast(known, "FY2021Q3")
    assert fc3 == pytest.approx(39 + sum(changes) / 8)


def test_drift_needs_four_changes_and_the_year_earlier_quarter():
    known = {parse_label(p): 1.0 for p in quarters_back(2020, 4, 7)}  # 3 changes
    assert T.drift_forecast(known, "FY2021Q1") == (None, None, 3)
    known = {parse_label(p): 1.0 for p in quarters_back(2020, 4, 8)}  # 4 changes
    assert T.drift_forecast(known, "FY2021Q1") == (1.0, 0.0, 4)
    del known[(2020, 1)]
    assert T.drift_forecast(known, "FY2021Q1")[0] is None


def test_the_drift_row_is_exact_on_a_steady_grower_and_beats_the_plain_benchmark(company):
    grower(company, date(2021, 2, 1), "FY2021Q1")
    (row,) = tr(company).rows
    rv = row.items["revenue"]
    d = rv.drift
    # revenue rises 5 a quarter, so 20 a year: Q(t−4) + 20 is the actual exactly
    assert d.n_changes == 8 and d.step == pytest.approx(20.0)
    assert d.forecast == pytest.approx(rv.actual) and d.miss == pytest.approx(0.0)
    assert d.missing is None
    assert rv.benchmark_forecast == pytest.approx(rv.actual - 20.0)
    eb = row.items["ebit"].drift
    assert eb.step == pytest.approx(2.0) and eb.miss == pytest.approx(0.0, abs=1e-12)
    # Warren forecast 100 against an actual of 160: the drift benchmark is closer
    assert d.closer == "benchmark"
    signed = score("revenue", d.forecast, rv.actual, rv.actual)[1]
    assert d.signed_miss == pytest.approx(signed)


def test_the_drift_reads_only_the_origin_runs_own_history(company):
    grower(company, date(2021, 2, 1), "FY2021Q1")
    # a later origin of the same group holds other history: the row keeps the first run's
    origin(company, date(2021, 3, 1), [q(1, "FY2021Q1", rev=160.0, ebit=16.0)])
    hist_rows(company, "TST_2021-03-01_1", {p: (1.0, 1.0) for p in quarters_back(2020, 4, 12)})
    (row,) = tr(company).rows
    assert row.n_origins == 2 and row.items["revenue"].drift.step == pytest.approx(20.0)


def test_no_drift_with_three_changes_and_no_benchmark_without_last_years_quarter(company):
    grower(company, date(2021, 2, 1), "FY2021Q1", n=7)
    (row,) = tr(company).rows
    d = row.items["revenue"].drift
    assert (d.forecast, d.step, d.miss, d.closer) == (None, None, None, None)
    assert d.missing.code == "no_drift" and d.n_changes == 3
    assert d.missing.params == {"period": "FY2021Q1", "n_changes": 3, "min_changes": 4}
    assert row.items["revenue"].benchmark_missing is None  # M3's benchmark still exists
    company.execute("DELETE FROM assumptions WHERE period = 'FY2020Q1'")
    company.commit()
    d = tr(company).rows[0].items["revenue"].drift
    assert d.missing.code == "no_benchmark"


def test_the_drift_summary_follows_the_benchmarks_test_rules(company):
    history(company, "OTH")
    for i in range(12):  # 12 quarters at h1 where the drift benchmark is exact
        year, quarter = divmod(2018 * 4 + i, 4)
        grower(company, date(2021, 1, 1 + i), f"FY{year}Q{quarter + 1}")
    rec = tr(company)
    s1 = summary(rec, "revenue", 1).drift
    assert s1.n_rows == 12 and (s1.wins, s1.losses, s1.ties) == (0, 12, 0)
    assert s1.verdict == "benchmark_better" and s1.sign_p < 0.05 and s1.missing is None
    assert s1.median_miss == pytest.approx(0.0) and s1.mean_miss == pytest.approx(0.0, abs=1e-12)
    assert s1.skill is None  # the drift benchmark's mean miss is 0
    # M3's benchmark fields are unchanged by the drift
    plain = summary(rec, "revenue", 1)
    assert plain.benchmark_median_miss > 0 and plain.verdict is not None
    company.execute("DELETE FROM baseline_errors WHERE origin_id = 'TST_2021-01-12'")
    company.execute("DELETE FROM forecast_origins WHERE origin_id = 'TST_2021-01-12'")
    company.commit()
    s1 = summary(tr(company), "revenue", 1).drift
    assert s1.missing.code == "few_quarters" and s1.verdict is None


def test_no_drift_verdict_at_horizon_two_and_all_horizons_tested_per_quarter(company):
    for i in range(12):
        year, quarter = divmod(2018 * 4 + i, 4)
        period = f"FY{year}Q{quarter + 1}"
        grower(company, date(2021, 1, 1 + i), period, h=2)
        grower(company, date(2021, 2, 1 + i), period, h=1)
    rec = tr(company)
    s2 = summary(rec, "revenue", 2).drift
    assert s2.verdict is None and s2.sign_p is not None and s2.n_rows == 12
    allh = summary(rec, "revenue", None).drift
    assert allh.n_rows == 24 and allh.wins + allh.losses + allh.ties == 12  # one per quarter
    assert allh.verdict == "benchmark_better"


def test_drift_skill_is_on_the_rows_that_have_a_drift_forecast(company):
    grower(company, date(2021, 2, 1), "FY2021Q1", rev=170.0)  # drift 140 + 20, Warren 100
    grower(company, date(2021, 2, 2), "FY2021Q2", n=6)  # no drift: left out of its skill
    rec = tr(company)
    s = summary(rec, "revenue", 1).drift
    assert s.n_rows == 1
    want = 1 - (70 / 170) / (10 / 170)
    assert s.skill == pytest.approx(want)


def test_the_note_names_the_drift_benchmark_and_the_old_notes_keep_their_order(company):
    rec = tr(company)
    assert codes(rec.notes)[:6] == [
        "deduplicated", "benchmark_is_srw", "baseline_only", "cases_not_included", "headline",
        "benchmark_with_drift",
    ]  # fmt: skip
    (n,) = [x for x in rec.notes if x.code == "benchmark_with_drift"]
    assert n.params == {"min_changes": 4}


# -- the Wilson interval (backlog #188) ---------------------------------------------------------


def test_wilson_matches_a_hand_computed_interval():
    z = T.WILSON_Z
    p, n = 0.8, 20
    centre = (p + z * z / 40) / (1 + z * z / 20)
    half = z / (1 + z * z / 20) * math.sqrt(p * 0.2 / 20 + z * z / 1600)
    assert T.wilson(p, n) == pytest.approx((centre - half, centre + half))
    assert T.wilson(0.5, 0) is None
    lo, hi = T.wilson(1.0, 20)
    assert hi == 1.0 and 0.85 < lo < 0.9  # every actual inside still leaves doubt
    assert z == pytest.approx(1.6448536, abs=1e-6)


def test_a_range_cell_takes_its_wilson_interval_on_the_clusters(company):
    history(company, "OTH")
    for i in range(12):
        year, quarter = divmod(2017 * 4 + i, 4)
        period, end = f"FY{year}Q{quarter + 1}", f"{year}-{quarter * 3 + 3:02d}-28"
        origin(company, date(2021, 2, 1 + i), [q(1, period, end=end)])
    c = summary(tr(company), "revenue", 1).ranges["pooled"]
    assert c.share == 1.0 and c.interval == [1.0, 1.0]  # the bootstrap says nothing
    assert c.wilson_n == c.n_clusters == 12
    assert c.wilson_interval == pytest.approx(list(T.wilson(1.0, 12)))
    assert c.wilson_interval[0] < 1.0


def test_a_cell_without_rows_has_no_wilson_interval(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1")])
    c = summary(tr(company), "revenue", 1).ranges["own"]
    assert c.n_rows == 0 and c.wilson_interval is None and c.wilson_n is None


def test_the_drift_fields_reach_the_dict_and_the_text(company):
    grower(company, date(2021, 2, 1), "FY2021Q1")
    rec = tr(company)
    d = rec.to_dict()
    assert json.loads(json.dumps(d)) == d
    item = d["rows"][0]["items"]["revenue"]
    assert set(item["drift"]) == {"forecast", "step", "n_changes", "miss", "signed_miss",
                                  "closer", "missing", "left_out", "basis_checked"}  # fmt: skip
    s = d["summaries"][0]
    assert set(s["drift"]) == {"n_rows", "median_miss", "mean_miss", "skill", "wins", "losses",
                               "ties", "sign_p", "verdict", "missing"}  # fmt: skip
    assert {"wilson_interval", "wilson_n"} <= set(s["ranges"]["pooled"])
    text = T.render(rec)
    assert "Second benchmark: the same quarter a year earlier plus" in text


class FakeReads:
    """`FactReads` stand-in: `first` holds the quarters as first reported, `by_date` the latest
    values on each date; both map (item, year, "Qn") to (value, filed_at)."""

    def __init__(self, first, by_date):
        self.first, self.by_date = first, by_date

    def quarterly(self, cik, on, mode):
        from types import SimpleNamespace

        if mode == "first_reported":
            facts = self.first
        else:
            facts = self.by_date[max(d for d in self.by_date if d <= on)]
        return {k: SimpleNamespace(value=v, filed_at=f, mixed_vintage=False)
                for k, (v, f) in facts.items()}  # fmt: skip


def jnj_reads():
    """J&J-shaped: FY2022Q3 was first reported at 104 beside FY2021Q3 at 100, then recast to 85
    a year later; FY2023Q3 was reported at 90 beside the recast 85."""
    q3, q4, q3b = date(2022, 11, 1), date(2023, 2, 1), date(2023, 11, 1)
    first = {
        ("revenue", 2022, "Q3"): (104.0, q3), ("operating_income", 2022, "Q3"): (10.4, q3),
        ("revenue", 2022, "Q4"): (104.0, q4), ("operating_income", 2022, "Q4"): (10.4, q4),
        ("revenue", 2023, "Q3"): (90.0, q3b), ("operating_income", 2023, "Q3"): (9.0, q3b),
    }  # fmt: skip
    by_date = {
        q3: {("revenue", 2021, "Q3"): (100.0, q3), ("operating_income", 2021, "Q3"): (10.0, q3)},
        q4: {("revenue", 2021, "Q4"): (100.2, q4), ("operating_income", 2021, "Q4"): (10.0, q4)},
        q3b: {("revenue", 2022, "Q3"): (85.0, q3b), ("operating_income", 2022, "Q3"): (8.5, q3b)},
    }  # fmt: skip
    return FakeReads(first, by_date)


def test_mixed_pairs_leave_out_a_change_that_spans_a_recast():
    hist = {
        "revenue": {(2021, 3): 100.0, (2021, 4): 100.0, (2022, 3): 85.0, (2022, 4): 104.0,
                    (2023, 3): 90.0},
        "ebit": {(2021, 3): 10.0, (2021, 4): 10.0, (2022, 3): 8.5, (2022, 4): 10.4,
                 (2023, 3): 9.0},
    }  # fmt: skip
    alts = dict.fromkeys(hist["ebit"], 0)
    mixed = T.mixed_pairs(jnj_reads(), "0", date(2024, 2, 1), hist, alts)
    # 2022Q3 (recast 85) beside 2021Q3 (100): mixed; 2022Q4 beside 100.2 (within 0.5%) and
    # 2023Q3 beside the recast 2022Q3: kept
    assert mixed == {"revenue": {(2022, 3)}, "ebit": {(2022, 3)}}


def test_mixed_pairs_leave_out_a_prior_quarter_the_filing_printed_otherwise():
    hist = {"revenue": {(2022, 3): 104.0, (2021, 3): 95.0}, "ebit": {}}
    mixed = T.mixed_pairs(jnj_reads(), "0", date(2023, 1, 1), hist, {})
    assert mixed["revenue"] == {(2022, 3)}  # the filing printed 100 for 2021Q3, the run 95


def test_mixed_pairs_leave_out_an_ebit_change_across_two_definitions():
    hist = {"revenue": {(2021, 1): 100.0, (2022, 1): 110.0},
            "ebit": {(2021, 1): 10.0, (2022, 1): 11.0}}  # fmt: skip
    reads = FakeReads({}, {date(2022, 5, 1): {}})  # nothing to compare: the revenue pair is kept
    mixed = T.mixed_pairs(reads, "0", date(2022, 6, 1), hist, {(2021, 1): 0, (2022, 1): 1})
    assert mixed == {"revenue": set(), "ebit": {(2022, 1)}}


def test_a_left_out_change_is_named_and_not_counted(company):
    values = grower(company, date(2021, 2, 1), "FY2021Q1")
    known = {parse_label(p): v[0] for p, v in values.items()}
    first = sorted(known)[4]
    fc, step, n = T.drift_forecast(known, "FY2021Q1", {first})
    assert n == 7 and step == pytest.approx(20.0)
    rv = tr(company).rows[0].items["revenue"].drift
    assert rv.basis_checked is False and rv.left_out == []  # check_basis off in these tests


def test_fiscal_year_history_rows_are_not_seasonal_quarters(company):
    grower(company, date(2021, 2, 1), "FY2021Q1")
    hist_rows(company, "TST_2021-02-01_1", {"FY2019": (500.0, 50.0)})
    d = tr(company).rows[0].items["revenue"].drift
    assert d.n_changes == 8 and d.step == pytest.approx(20.0)


def test_the_call_checks_the_basis_and_leaves_out_the_mixed_change(company, monkeypatch):
    values = grower(company, date(2021, 2, 1), "FY2021Q1")
    # the filing that first reported FY2020Q3 gave FY2019Q3 another value than the run's
    first = {("revenue", 2020, "Q3"): (values["FY2020Q3"][0], date(2020, 11, 1))}
    by_date = {date(2020, 11, 1): {("revenue", 2019, "Q3"): (1.0, date(2020, 11, 1))}}
    monkeypatch.setattr(T, "FactReads", lambda conn: FakeReads(first, by_date))
    monkeypatch.setattr(RN, "basis_flags", lambda conn, ticker, on: set())
    d = tr(company, check_basis=True).rows[0].items["revenue"].drift
    assert d.basis_checked is True and d.left_out == ["FY2020Q3"]
    assert d.n_changes == 7 and d.step == pytest.approx(20.0)
