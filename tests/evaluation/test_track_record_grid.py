"""Backlog #189: M10's grid dates in a company's track record, on hand-made grid batches."""

import json
from datetime import date

import pytest

from domains.evaluation import track_record as T
from domains.evaluation.backtest import CENT
from domains.evaluation.harness import score
from tests.evaluation.test_track_record import N, origin, q

FILED = date(2021, 5, 15)
ASOF = date(2021, 7, 1)


def batch(conn, batch_id="eval_g_1", created="2021-06-01T00:00:00Z", version="v-clean"):
    conn.execute(
        "INSERT INTO eval_batches (batch_id, created_at, code_version, cases_sha256) "
        "VALUES (?, ?, ?, 'x')",
        (batch_id, created, version),
    )
    conn.commit()
    return batch_id


def case(conn, on, ticker="TST", event_type="grid"):
    """A grid case of `ticker` dated `on`, with its run; returns (case_id, run_id)."""
    cid = f"{ticker}_{on.isoformat()}"
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    ingest = conn.execute("SELECT MIN(run_id) FROM ingest_runs").fetchone()[0]
    rid = f"{cid}_case"
    if conn.execute("SELECT 1 FROM eval_cases WHERE case_id = ?", (cid,)).fetchone() is None:
        conn.execute(
            "INSERT INTO eval_cases (case_id, ticker, cik, event_date, event_type, description, "
            "horizon_quarters, selected_because) VALUES (?, ?, ?, ?, ?, 'd', 4, 'grid rule: x')",
            (cid, ticker, cik, on.isoformat(), event_type),
        )
        conn.execute(
            "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
            "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
            "VALUES (?, ?, ?, ?, 'v', ?, 'a', 'b', 'c', 'd')",
            (rid, cik, ticker, on.isoformat(), ingest),
        )
    conn.commit()
    return cid, rid


def result(conn, batch_id, cid, rid, variant, item, h, period, forecast, actual=None,
           actual_revenue=None, filed=FILED, status="ok"):  # fmt: skip
    err = None
    if status == "ok":
        err = score(item, forecast, actual, actual if item == "revenue" else actual_revenue)[0]
    conn.execute(
        "INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, horizon, "
        "period_end, forecast, actual, actual_revenue, error, status, actual_filed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, '2021-03-31', ?, ?, ?, ?, ?, ?)",
        (batch_id, cid, rid, variant, item, period, h, forecast, actual, actual_revenue, err,
         status, filed.isoformat() if filed else None),
    )  # fmt: skip
    conn.commit()


def grid_quarter(conn, batch_id, on, h=1, period="FY2021Q1", rev=(100.0, 110.0),
                 ebit=(10.0, 12.0), news=None, filed=FILED, ebit_filed=None,
                 ticker="TST", status="ok"):  # fmt: skip
    """One quarter of a grid case: (forecast, actual) per item; `news` (revenue, EBIT) masked
    forecasts, or None for a case without shocks (no masked row)."""
    cid, rid = case(conn, on, ticker)
    ok = status == "ok"
    result(conn, batch_id, cid, rid, "baseline", "revenue", h, period, rev[0],
           rev[1] if ok else None, None, filed, status)  # fmt: skip
    result(conn, batch_id, cid, rid, "baseline", "ebit", h, period, ebit[0],
           ebit[1] if ok else None, rev[1] if ok else None, ebit_filed or filed,
           status)  # fmt: skip
    if news is not None:
        result(conn, batch_id, cid, rid, "llm_masked", "revenue", h, period, news[0], rev[1],
               None, filed)  # fmt: skip
        result(conn, batch_id, cid, rid, "llm_masked", "ebit", h, period, news[1], ebit[1],
               rev[1], ebit_filed or filed)  # fmt: skip
    return cid


def grid(conn, as_of=ASOF):
    return T.track_record(conn, "TST", as_of, N, check_basis=False).grid


def summary(g, item="revenue", h=None, part="all"):
    (s,) = [s for s in g.summaries if (s.item, s.horizon) == (item, h)]
    return s.news[part]


def codes(g):
    return [n.code for n in g.notes]


# -- which batch ---------------------------------------------------------------------------------


def test_no_grid_batch_gives_no_section(company):
    assert grid(company) is None


def test_the_newest_clean_grid_batch_is_read(company):
    old = batch(company, "eval_g_1", "2021-06-01T00:00:00Z")
    new = batch(company, "eval_g_2", "2021-06-02T00:00:00Z")
    dirty = batch(company, "eval_g_3", "2021-06-03T00:00:00Z", "v-clean+dirty")
    for b in (old, new, dirty):
        grid_quarter(company, b, date(2021, 2, 15))
    g = grid(company)
    assert g.batch_id == new and len(g.rows) == 1


def test_a_batch_holding_a_non_grid_case_is_not_read(company):
    grid_quarter(company, batch(company, "eval_g_1"), date(2021, 2, 15))
    mixed = batch(company, "eval_g_2", "2021-06-02T00:00:00Z")
    grid_quarter(company, mixed, date(2021, 2, 15))
    cid, rid = case(company, date(2020, 3, 1), event_type="earnings")
    result(company, mixed, cid, rid, "baseline", "revenue", 1, "FY2020Q1", 100.0, 100.0)
    assert grid(company).batch_id == "eval_g_1"


# -- rows: the dates -----------------------------------------------------------------------------


def test_a_case_dated_d_is_not_used_and_one_dated_the_day_before_is(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 6, 30), period="FY2021Q2")
    grid_quarter(company, b, date(2021, 7, 1), period="FY2021Q3")
    assert [r.made_on for r in grid(company, date(2021, 7, 1)).rows] == [date(2021, 6, 30)]
    assert len(grid(company, date(2021, 7, 2)).rows) == 2


def test_an_actual_filed_after_d_or_never_dated_is_not_used(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 2, 15), period="FY2021Q1", filed=date(2021, 7, 2))
    grid_quarter(company, b, date(2021, 3, 15), period="FY2021Q1", filed=None)
    grid_quarter(company, b, date(2021, 4, 15), period="FY2021Q1", filed=date(2021, 7, 1))
    g = grid(company, date(2021, 7, 1))
    assert [r.case_id for r in g.rows] == ["TST_2021-04-15"]
    assert [r.case_id for r in grid(company, date(2021, 7, 2)).rows] == [
        "TST_2021-02-15",
        "TST_2021-04-15",
    ]


def test_revenue_filed_by_d_and_ebit_after_d_is_not_used(company):
    grid_quarter(company, batch(company), date(2021, 2, 15), ebit_filed=date(2021, 7, 2))
    g = grid(company, date(2021, 7, 1))
    assert g.rows == [] and g.missing.code == "no_grid_record"
    assert "not_yet_scorable" in codes(g)
    assert len(grid(company, date(2021, 7, 2)).rows) == 1


def test_two_cases_forecasting_one_quarter_give_two_rows(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 1, 15), h=2, news=(105.0, 10.0))
    grid_quarter(company, b, date(2021, 2, 15), h=1, news=(100.0, 11.0))
    g = grid(company)
    assert [(r.case_id, r.horizon) for r in g.rows] == [
        ("TST_2021-01-15", 2),
        ("TST_2021-02-15", 1),
    ]
    assert g.rows[0].items["revenue"].news_forecast == 105.0
    assert g.rows[1].items["revenue"].news_forecast == 100.0  # each case keeps its own news


# -- rows: the misses and the news ---------------------------------------------------------------


def test_the_miss_is_the_batch_scored_miss(company):
    grid_quarter(company, batch(company), date(2021, 2, 15), rev=(100.0, 125.0), ebit=(10.0, 15.0))
    (row,) = grid(company).rows
    stored = {r["item"]: r["error"] for r in company.execute("SELECT * FROM eval_results")}
    rev, ebit = row.items["revenue"], row.items["ebit"]
    assert rev.miss == pytest.approx(stored["revenue"]) == pytest.approx(0.2)
    assert rev.signed_miss == pytest.approx(-0.2)  # forecast too low: negative
    assert ebit.miss == pytest.approx(stored["ebit"]) == pytest.approx(5 / 125)
    assert (rev.miss_unit, ebit.miss_unit) == ("fraction_of_actual", "fraction_of_actual_revenue")
    assert rev.filed_at == FILED


def test_a_case_without_shocks_takes_the_baseline(company):
    grid_quarter(company, batch(company), date(2021, 2, 15), news=None)
    x = grid(company).rows[0].items["revenue"]
    assert x.news_from_baseline and not x.moved and x.closer == "tie"
    assert x.news_forecast == x.forecast and x.news_miss == x.miss


def test_moved_needs_more_than_half_a_cent(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 2, 15), news=(100.0 + CENT * 0.9, 10.0 + CENT * 2))
    x = grid(company).rows[0].items
    assert not x["revenue"].moved and not x["revenue"].news_from_baseline
    assert x["ebit"].moved


def test_closer_says_which_forecast_was_nearer(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 2, 15), news=(105.0, 9.0))  # actual 110 and 12
    x = grid(company).rows[0].items
    assert x["revenue"].closer == "news" and x["ebit"].closer == "baseline"
    assert x["revenue"].news_miss == pytest.approx(5 / 110)
    assert x["revenue"].news_signed_miss == pytest.approx(-5 / 110)


def test_post_cutoff_follows_the_grid_rule(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 2, 15))
    grid_quarter(company, b, date(2026, 8, 15), period="FY2026Q3", filed=date(2026, 10, 30))
    rows = grid(company, date(2026, 11, 16)).rows
    assert [r.post_cutoff for r in rows] == [False, True]


def test_same_as_monthly_compares_the_baseline_with_the_monthly_forecast(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1", rev=110.0, ebit=12.0)])
    b = batch(company)
    grid_quarter(company, b, date(2021, 2, 15), h=1)  # forecast 100 and 10, as the origin
    grid_quarter(company, b, date(2021, 1, 15), h=2, rev=(101.0, 110.0))
    grid_quarter(company, b, date(2021, 3, 15), h=1, period="FY2021Q2", ebit=(10.5, 12.0))
    by = {(r.period, r.horizon): r for r in grid(company).rows}
    assert by[("FY2021Q1", 1)].same_as_monthly is True
    assert by[("FY2021Q1", 2)].same_as_monthly is None  # no monthly row at h2
    assert by[("FY2021Q2", 1)].same_as_monthly is None
    (note,) = [n for n in grid(company).notes if n.code == "grid_repeats_monthly"]
    assert note.params == {"n_rows": 3, "n_same": 1}


# -- summaries -----------------------------------------------------------------------------------


def _moved_cases(conn, n_win, n_lose, n_quiet, start=date(2021, 1, 1)):
    """Revenue actual 110: a win forecasts 105 with news, a loss 95, a quiet case has no shocks."""
    b = batch(conn)
    day = start.toordinal()
    for kind in ["w"] * n_win + ["l"] * n_lose + ["q"] * n_quiet:
        news = {"w": (105.0, 10.0), "l": (95.0, 10.0), "q": None}[kind]
        grid_quarter(conn, b, date.fromordinal(day), news=news)
        day += 1


def test_news_means_over_all_rows_and_over_moved_rows(company):
    _moved_cases(company, 4, 2, 2)
    s = summary(grid(company))
    assert (s.n_rows, s.n_cases, s.n_quarters, s.n_moved) == (8, 8, 1, 6)
    assert (s.wins, s.losses, s.ties) == (4, 2, 0)
    base, win, lose = 10 / 110, 5 / 110, 15 / 110
    assert s.mean_miss_without == pytest.approx(base)
    assert s.mean_miss_with == pytest.approx((4 * win + 2 * lose + 2 * base) / 8)
    assert s.skill == pytest.approx(1 - s.mean_miss_with / s.mean_miss_without)
    assert s.mean_miss_without_moved == pytest.approx(base)
    assert s.mean_miss_with_moved == pytest.approx((4 * win + 2 * lose) / 6)
    assert s.missing is None
    e = summary(grid(company), "ebit")
    assert e.n_moved == 0 and e.missing.code == "few_moved" and e.mean_miss_with_moved is None


def test_few_moved_at_five_and_not_six(company):
    _moved_cases(company, 5, 0, 1)
    s = summary(grid(company))
    assert s.n_moved == 5 and s.missing.code == "few_moved"
    assert s.missing.params == {"n_moved": 5, "min_moved": 6}


def test_six_moved_is_enough(company):
    _moved_cases(company, 6, 0, 0)
    assert summary(grid(company)).missing is None


def test_summaries_split_by_the_models_cutoff_and_by_horizon(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 2, 15), news=(105.0, 10.0))
    grid_quarter(company, b, date(2026, 8, 15), h=2, period="FY2026Q4", news=(95.0, 10.0),
                 filed=date(2026, 10, 30))  # fmt: skip
    g = grid(company, date(2026, 11, 16))
    assert summary(g, part="pre_cutoff").wins == 1 and summary(g, part="pre_cutoff").n_rows == 1
    assert summary(g, part="post_cutoff").losses == 1
    assert summary(g).n_rows == 2
    assert summary(g, h=1).n_rows == 1 and summary(g, h=2, part="post_cutoff").n_rows == 1
    assert summary(g, h=3).n_rows == 0 and summary(g, h=3).mean_miss_without is None


def test_no_p_value_and_no_verdict(company):
    _moved_cases(company, 6, 0, 0)
    d = grid(company).summaries[0].news["all"]
    fields = set(T.NewsSummary.__dataclass_fields__)
    assert not fields & {"sign_p", "verdict"}
    assert d.wins == 6
    assert "news_not_tested_per_company" in codes(grid(company))


# -- notes ---------------------------------------------------------------------------------------


def test_not_yet_scorable_failed_and_left_out(company):
    b = batch(company)
    grid_quarter(company, b, date(2021, 2, 15))
    grid_quarter(company, b, date(2021, 3, 15), period="FY2021Q2", status="missing", filed=None)
    case(company, date(2021, 4, 15))  # in the case list, no forecast in the batch: failed
    company.execute(
        "INSERT INTO companies (cik, ticker, name) VALUES ('0000000002', 'OTH', 'Other')"
    )  # fmt: skip
    case(company, date(2021, 5, 15), ticker="OTH")
    case(company, date(2021, 8, 15), ticker="OTH")  # after D: not named
    g = grid(company)
    notes = {n.code: n.params for n in g.notes}
    assert notes["not_yet_scorable"] == {"case_ids": ["TST_2021-03-15"]}
    assert notes["grid_cases_failed"] == {"case_ids": ["TST_2021-04-15"], "batch_id": b}
    assert notes["left_out"] == {"dates": ["2021-05-15"]}


def test_a_company_with_no_grid_row_gets_a_coded_gap(company):
    company.execute(
        "INSERT INTO companies (cik, ticker, name) VALUES ('0000000002', 'OTH', 'Other')"
    )  # fmt: skip
    grid_quarter(company, batch(company), date(2021, 2, 15), ticker="OTH")
    g = grid(company)
    assert g.rows == [] and g.summaries == []
    assert g.missing.code == "no_grid_record"
    assert g.missing.params == {"ticker": "TST", "as_of": ASOF.isoformat()}


# -- the monthly part is unchanged ---------------------------------------------------------------


def test_the_monthly_part_is_the_same_with_and_without_a_grid_batch(company):
    origin(company, date(2021, 2, 1), [q(1, "FY2021Q1")], {"FY2021Q1": (90.0, 9.0)})
    before = T.track_record(company, "TST", ASOF, N, check_basis=False).to_dict()
    grid_quarter(company, batch(company), date(2021, 2, 15), news=(105.0, 10.0))
    after = T.track_record(company, "TST", ASOF, N, check_basis=False).to_dict()
    assert before.pop("grid") is None and after.pop("grid") is not None
    assert before == after
    (note,) = [n for n in after["notes"] if n["code"] == "cases_not_included"]
    assert note["text"].endswith("the grid dates are, in their own section")


def test_to_dict_round_trips_through_json_and_renders(company):
    _moved_cases(company, 3, 3, 1)
    rec = T.track_record(company, "TST", ASOF, N, check_basis=False)
    d = rec.to_dict()
    assert json.loads(json.dumps(d)) == d
    g = d["grid"]
    assert set(g) == {"batch_id", "rows", "summaries", "notes", "missing"}
    assert set(g["summaries"][0]["news"]) == {"all", "pre_cutoff", "post_cutoff"}
    assert g["rows"][0]["made_on"] == "2021-01-01"
    text = T.render(rec)
    assert "Grid dates (M10, batch eval_g_1)" in text
    assert "| revenue | all | all | 7 | 6 |" in text
