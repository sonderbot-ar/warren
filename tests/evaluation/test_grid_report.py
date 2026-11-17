"""Grid report statistics (M10 Step 3) on hand-made rows with hand-computed answers."""

from datetime import date

import pytest

from domains.evaluation import backtest as bt
from domains.evaluation import grid_report as gr


def row(case_id, variant, error, horizon=1, item="revenue", status="ok", filed=None, end=None):
    return {"case_id": case_id, "variant": variant, "item": item, "period": f"P{horizon}",
            "horizon": horizon, "error": error, "status": status, "p50": 100.0 + (error or 0),
            "forecast": 100.0 + (error or 0), "actual_filed_at": filed,
            "period_end": end or "2025-12-31"}  # fmt: skip


def test_date_means_average_the_cases_on_each_date():
    ds = {"A_2025-11-15": -0.02, "B_2025-11-15": 0.0, "A_2026-02-15": 0.01}
    assert gr.date_means(ds) == {date(2025, 11, 15): -0.01, date(2026, 2, 15): 0.01}


def test_the_date_sign_test_counts_dates_not_cases():
    # 8 cases better on one date, 1 case worse on each of 2 other dates: by cases 8 / 2
    # (p 0.11), by dates 1 / 2 (p 1.0)
    ds = {f"C{i}_2025-11-15": -0.01 for i in range(8)}
    ds |= {"A_2026-02-15": 0.01, "A_2026-05-15": 0.01}
    t = gr.date_test(ds)
    assert (t.sign.better, t.sign.worse, t.sign.ties) == (1, 2, 0)
    assert t.sign.p == pytest.approx(1.0)
    assert bt.sign_test(list(ds.values())).p == pytest.approx(0.109375)
    assert t.cases == 10 and t.dates == 3 and not t.shown


def test_on_cases_all_on_different_dates_the_date_test_is_the_case_test():
    ds = {f"A_20{19 + i}-05-15": d for i, d in enumerate([-0.03, -0.01, 0.02, -0.02, 0.0])}
    t = gr.date_test(ds)
    case = bt.sign_test(list(ds.values()))
    assert (t.sign.better, t.sign.worse, t.sign.ties, t.sign.p) == (
        case.better, case.worse, case.ties, case.p
    )  # fmt: skip
    assert t.interval == pytest.approx(bt.bootstrap_mean(list(ds.values())))


def test_bootstraps_collapse_when_every_d_is_equal_and_reproduce_with_their_seed():
    ds = {f"A_20{19 + i}-05-15": -0.01 for i in range(6)}
    assert gr.date_bootstrap(ds) == pytest.approx((-0.01, -0.01))
    assert gr.block_bootstrap(ds) == pytest.approx((-0.01, -0.01))
    varied = {f"A_20{19 + i}-05-15": d for i, d in enumerate([-3, -1, 2, -2, 0, 1])}
    assert gr.date_bootstrap(varied) == gr.date_bootstrap(varied)
    assert gr.block_bootstrap(varied) == gr.block_bootstrap(varied)
    assert gr.date_bootstrap({}) is None and gr.block_bootstrap({}) is None


def test_shown_needs_both_the_date_sign_test_and_the_interval():
    ds = {f"A_{2019 + i}-05-15": -0.01 - i / 1000 for i in range(7)}
    t = gr.date_test(ds)
    assert t.sign.better == 7 and t.sign.p == pytest.approx(0.015625)
    assert t.interval[1] < 0 and t.shown
    six = gr.date_test({k: v for k, v in list(ds.items())[:5]})  # 5 of 5: p 0.0625
    assert six.interval[1] < 0 and not six.shown


@pytest.mark.parametrize(
    ("day", "filed", "group"),
    [
        (date(2026, 2, 15), "2026-04-30", "A"),
        (date(2026, 2, 15), "2026-06-30", "A"),
        (date(2026, 5, 15), "2026-07-31", "B"),
        (date(2026, 8, 15), "2026-10-30", "C"),
        (date(2026, 7, 1), "2026-07-31", None),  # window overlaps the cutoff month
        (date(2026, 2, 15), None, None),
    ],
)
def test_memory_groups_follow_the_outcome_filing_date(day, filed, group):
    assert gr.memory_group(day, filed) == group


def test_memory_gaps_are_named_minus_masked_at_h1_only():
    rows = [
        row("A_2026-02-15", "baseline", 0.050, filed="2026-04-30"),
        row("A_2026-02-15", "llm_named", 0.030, filed="2026-04-30"),
        row("A_2026-02-15", "llm_masked", 0.045, filed="2026-04-30"),
        row("A_2026-02-15", "baseline", 0.080, horizon=2, filed="2026-07-30"),
        row("A_2026-02-15", "llm_named", 0.010, horizon=2, filed="2026-07-30"),
        row("B_2026-08-15", "baseline", 0.020, filed="2026-10-30"),  # no shocks: g = 0
    ]
    gaps = gr.memory_gaps(rows)
    # A: e(named) = -0.020, e(masked) = -0.005, g = -0.015; h2 ignored
    assert gaps["revenue"]["A"] == {"A_2026-02-15": pytest.approx(-0.015)}
    assert gaps["revenue"]["C"] == {"B_2026-08-15": 0.0}
    assert "B" not in gaps["revenue"]


def test_counts_put_every_case_in_one_bucket():
    rows = [
        row("A_2026-08-15", "baseline", 0.01),
        row("B_2026-10-15", "baseline", None, status="missing"),
    ]
    c = gr.counts(["A_2026-08-15", "B_2026-10-15", "C_2026-10-15"], rows, {"C_2026-10-15": "x"})
    assert c.scored == 1 and c.not_yet_scorable == ["B_2026-10-15"]
    assert c.failed == {"C_2026-10-15": "x"}


def test_quiet_weeks_tell_no_events_from_no_shock():
    rows = [row("A_2026-08-15", "llm_masked", 0.0)]
    rows += [row(f"{x}_2026-08-15", "baseline", 0.01) for x in "ABC"]
    q = gr.quiet(rows, {"A_2026-08-15": 4, "B_2026-08-15": 3, "C_2026-08-15": 0}, "llm_masked")
    assert q == {"shocks": ["A_2026-08-15"], "no shock": ["B_2026-08-15"],
                 "no events": ["C_2026-08-15"]}  # fmt: skip


def test_h1_closed_compares_the_quarter_end_with_the_case_date():
    assert gr.h1_closed(row("A_2026-07-15", "baseline", 0, end="2026-06-30"))
    assert not gr.h1_closed(row("A_2026-08-15", "baseline", 0, end="2026-09-30"))
