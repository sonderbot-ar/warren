"""Backlog #146: past events chosen by rule, on hand-made cases, origins and hindsight."""

import csv
import json
from datetime import date

import pytest

from domains.analysis.reported import Coded
from domains.evaluation import past_events as P
from domains.evaluation.cases import Case
from domains.evaluation.harness import EvaluationError
from domains.evaluation.hindsight import Hindsight, Item, Quarter
from tests.evaluation.test_track_record import origin, q

ASOF = date(2021, 7, 1)


def case(cid, ticker="TST", when="2020-06-01", kind="guidance", scope=""):
    return Case(cid, ticker, date.fromisoformat(when), kind, f"{cid} happened", 4, "rule",
                f"https://example.com/{cid}", scope)  # fmt: skip


def item(name, forecast, actual, miss_unit="fraction_of_actual"):
    if actual is None:
        code = Coded("not_reported", {}, "not yet")
        return Item(name, "USD", forecast, None, None, None, miss_unit, missing=code)
    scale = actual if name == "revenue" else 200.0
    signed = (forecast - actual) / scale
    return Item(name, "USD", forecast, actual, abs(signed), signed, miss_unit)


def seen(run_id, quarters):
    """A Hindsight whose quarters are (period, revenue actual or None); forecast revenue 100,
    EBIT 10, actual EBIT 10 (the EBIT miss is 0)."""
    qs = []
    for h, (period, rev) in enumerate(quarters, start=1):
        ebit = None if rev is None else 10.0
        qs.append(Quarter(period, 2020, "Q1", h, None if rev is None else date(2020, 9, 30), 91,
                          [item("revenue", 100.0, rev),
                           item("ebit", 10.0, ebit, "fraction_of_actual_revenue")]))  # fmt: skip
    return Hindsight(run_id, "TST", date(2020, 5, 31), ASOF, qs)


def store_case(conn, c, periods, batch="eval_test_1"):
    """The case's baseline rows in a batch, on a run of its own; returns the run id."""
    rid = f"{c.case_id}_1"
    cik = conn.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    ingest = conn.execute("SELECT MIN(run_id) FROM ingest_runs").fetchone()[0]
    conn.execute(
        "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
        "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
        "VALUES (?, ?, 'TST', ?, 'v', ?, 'a', 'b', 'c', 'd')",
        (rid, cik, c.event_date.isoformat(), ingest),
    )
    conn.execute(
        "INSERT OR IGNORE INTO eval_batches (batch_id, code_version, cases_sha256) "
        "VALUES (?, 'v', 'x')", (batch,))  # fmt: skip
    conn.execute(
        "INSERT INTO eval_cases (case_id, ticker, cik, event_date, event_type, description, "
        "horizon_quarters, selected_because) VALUES (?, 'TST', ?, ?, ?, 'd', 4, 'rule')",
        (c.case_id, cik, c.event_date.isoformat(), c.event_type),
    )
    for h, period in enumerate(periods, start=1):
        for it in ("revenue", "ebit"):
            conn.execute(
                "INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, "
                "horizon, forecast, status) VALUES (?, ?, ?, 'baseline', ?, ?, ?, 1.0, 'ok')",
                (batch, c.case_id, rid, it, period, h),
            )
    conn.commit()
    return rid


def usual_set(conn, misses, h=1):
    """One origin per target quarter at horizon h, with revenue misses `misses` (forecast 100,
    actual 100 / (1 + m) so |forecast − actual| / actual = m)."""
    for i, m in enumerate(misses):
        year, quarter = divmod(2017 * 4 + i, 4)
        origin(conn, date(2021, 1, 1 + i),
               [q(h, f"FY{year}Q{quarter + 1}", rev=100.0 / (1 + m))])  # fmt: skip


def call(conn, cases, hs=None, **kw):
    kw.setdefault("check_basis", False)
    hs = hs or {}
    return P.past_events(conn, "TST", kw.pop("kind", "guidance"), kw.pop("as_of", ASOF),
                         cases=cases, hindsight=lambda c, rid, on: hs[rid], **kw)  # fmt: skip


# -- metrics to watch ---------------------------------------------------------------------------


def test_the_real_metrics_file_loads_with_a_row_for_every_askable_type():
    metrics = P.load_metrics()
    assert set(metrics) == P.ASKABLE
    assert all(m.source for rows in metrics.values() for m in rows)


def _write(tmp_path, rows):
    path = tmp_path / "m.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(P.METRIC_COLUMNS)
        w.writerows(rows)
    return path


def _full(extra=()):
    return [(t, "m1", "a metric", "10-K", "ASC 1", "") for t in sorted(P.ASKABLE)] + list(extra)


@pytest.mark.parametrize(
    "rows, message",
    [
        (_full([("guidance", "m2", "x", "10-K", "", "")]), "source is empty"),
        (_full([("weather", "m2", "x", "10-K", "s", "")]), "unknown event type"),
        (_full([("control", "m2", "x", "10-K", "s", "")]), "unknown event type"),
        (_full([("guidance", "m1", "x", "10-K", "s", "")]), "duplicate"),
        (_full()[1:], "no row for"),
    ],
)
def test_a_bad_metrics_file_is_refused(tmp_path, rows, message):
    with pytest.raises(ValueError, match=message):
        P.load_metrics(_write(tmp_path, rows))


def test_a_metrics_file_with_wrong_columns_is_refused(tmp_path):
    path = tmp_path / "m.csv"
    path.write_text("event_type,metric\nguidance,x\n")
    with pytest.raises(ValueError, match="columns"):
        P.load_metrics(path)


# -- the rule -----------------------------------------------------------------------------------


def test_the_rule_takes_same_type_cases_of_every_company_and_no_control():
    cases = [case("TST_a"), case("AAA_b", "AAA", "2020-07-01"), case("TST_c", kind="m_and_a"),
             case("TST_ctl", kind="control"), case("AAA_d", "AAA", kind="litigation")]  # fmt: skip
    chosen, others = P.select_cases(cases, "TST", "guidance", ASOF)
    assert [c.case_id for c in chosen] == ["TST_a", "AAA_b"]  # same company first
    assert [c.case_id for c in others] == ["TST_c"]  # the company's own, other type


def test_an_event_dated_d_is_left_out_and_one_dated_the_day_before_is_kept():
    cases = [case("on_d", when="2021-07-01"), case("before", when="2021-06-30")]
    chosen, _ = P.select_cases(cases, "TST", "guidance", ASOF)
    assert [c.case_id for c in chosen] == ["before"]


def test_same_company_cases_sort_newest_first():
    cases = [case("old", when="2019-01-01"), case("new", when="2021-01-01")]
    assert [c.case_id for c in P.select_cases(cases, "TST", "guidance", ASOF)[0]] == ["new", "old"]


@pytest.mark.parametrize(
    "text, horizons",
    [("X consolidated from 2023-10-13 (h4)", {4}), ("Y from 2024-05-03 (h3-h4)", {3, 4}),
     ("Z (h1-h4)", {1, 2, 3, 4}), ("", set()), (None, set())],
)  # fmt: skip
def test_scope_text_names_its_horizons(text, horizons):
    assert P.scope_horizons(text) == horizons


# -- the usual miss -----------------------------------------------------------------------------


def test_compare_ranks_a_miss_against_the_usual_set():
    usual = [i / 100 for i in range(1, 13)]  # 1% to 12%, twelve quarters
    u = P.compare(0.115, usual)
    assert u.n_quarters == 12 and u.median_miss == pytest.approx(0.065)
    assert u.p90_miss == pytest.approx(0.109)  # inclusive: position 1 + 0.9 × 11 = 10.9
    assert u.rank == pytest.approx(11 / 12) and u.beyond_usual is True and u.missing is None
    assert P.compare(0.05, usual).beyond_usual is False


def test_fewer_than_twelve_usual_quarters_gives_no_verdict():
    u = P.compare(0.5, [0.01] * 11)
    assert u.beyond_usual is None and u.missing.code == "few_usual_quarters"
    assert u.rank == 1.0  # still shown
    none = P.compare(0.5, [])
    assert none.n_quarters == 0 and none.rank is None and none.missing.code == "few_usual_quarters"


def test_the_case_periods_and_controls_scope_quarters_leave_the_usual_set(company):
    usual_set(company, [0.01, 0.02, 0.03, 0.04])  # FY2017Q1..Q4 at h1
    event = case("TST_e")
    store_case(company, event, ["FY2017Q1", "FY2017Q2"])
    control = case("TST_ctl", when="2019-01-01", kind="control", scope="deal (h2)")
    store_case(company, control, ["FY2017Q3", "FY2017Q4"])
    plain = case("TST_plain", when="2019-06-01", kind="control")
    store_case(company, plain, ["FY2017Q3"])
    excluded = P.event_periods(company, [event, control, plain])
    assert excluded == {"FY2017Q1", "FY2017Q2", "FY2017Q4"}  # a plain control's quarter stays
    usual = P.usual_misses(company, "TST", ASOF, excluded, None)
    assert usual[("revenue", 1)] == [pytest.approx(0.03)]


def test_a_basis_flagged_quarter_leaves_the_usual_set(company):
    usual_set(company, [0.01, 0.02])
    flags = {("TST_2021-01-01", "FY2017Q1", "ebit")}  # either item drops the quarter
    usual = P.usual_misses(company, "TST", ASOF, set(), flags)
    assert usual[("revenue", 1)] == [pytest.approx(0.02)]


def test_an_event_after_d_does_not_shape_the_usual_set(company):
    usual_set(company, [0.01, 0.02])
    later = case("TST_later", when="2021-08-01")
    store_case(company, later, ["FY2017Q1"])
    shown = case("TST_e", when="2020-06-01")
    rid = store_case(company, shown, ["FY2030Q1"])
    rec = call(company, [later, shown], {rid: seen(rid, [("FY2021Q1", 90.0)])})
    (u,) = [rec.cases[0].quarters[0].items["revenue"].usual]
    assert u.n_quarters == 2  # FY2017Q1 still counts: the later event was not known on D


# -- the call -----------------------------------------------------------------------------------


def test_a_case_shows_forecast_actual_margin_and_its_usual_comparison(company):
    usual_set(company, [i / 100 for i in range(1, 13)])
    c = case("TST_e")
    rid = store_case(company, c, ["FY2030Q1"])
    rec = call(company, [c], {rid: seen(rid, [("FY2021Q1", 80.0), ("FY2021Q2", None)])})
    (pc,) = rec.cases
    assert pc.same_company and pc.same_type and pc.same_mechanism is None
    assert pc.run_id == rid and pc.reported_quarters == 1 and pc.compared_quarters == 1
    first, second = pc.quarters
    rev = first.items["revenue"]
    assert rev.miss == pytest.approx(0.25) and rev.usual.beyond_usual is True
    assert first.forecast_margin == pytest.approx(0.1)
    assert first.actual_margin == pytest.approx(0.125)
    assert second.items["revenue"].missing.code == "not_reported"
    assert second.items["revenue"].usual is None and second.actual_margin is None
    assert rec.n == 1 and rec.n_compared == 1 and rec.thin_evidence


def test_scope_change_quarters_are_shown_but_not_compared(company):
    usual_set(company, [0.01] * 12)
    c = case("TST_m", kind="m_and_a", scope="Deal consolidated (h2-h4)")
    rid = store_case(company, c, ["FY2030Q1"])
    hs = {rid: seen(rid, [("FY2021Q1", 90.0), ("FY2021Q2", 90.0)])}
    (pc,) = call(company, [c], hs, kind="m_and_a").cases
    one, two = pc.quarters
    assert not one.scope_change and one.items["revenue"].usual.n_quarters == 12
    assert two.scope_change and two.items["revenue"].usual.missing.code == "scope_change"
    assert two.items["revenue"].miss is not None  # the miss is still shown
    assert pc.compared_quarters == 1


def test_n_counts_cases_with_a_reported_quarter_and_stays_thin_without_directions(company):
    cases, hs = [], {}
    for i in range(6):
        c = case(f"TST_{i}", when=f"2020-0{i + 1}-01")
        rid = store_case(company, c, [f"FY2031Q{1 + i % 4}"], batch=f"eval_b_{i}")
        hs[rid] = seen(rid, [("FY2021Q1", 90.0)])
        cases.append(c)

    def thin(rec):
        return [n for n in rec.notes if n.code == "thin_evidence"][0].params

    six = call(company, cases, hs)
    assert six.n == 6 and six.thin_evidence  # six cases, but which way each went is unknown
    assert thin(six) == {"n": 6, "threshold": 6, "reason": "direction_not_recorded"}
    hs["TST_5_1"] = seen("TST_5_1", [("FY2021Q1", None)])
    five = call(company, cases, hs)
    assert five.n == 5 and five.n_listed == 6 and five.thin_evidence
    assert thin(five) == {"n": 5, "threshold": 6, "reason": "few_cases"}


def test_scope_is_decided_by_the_consolidation_date_not_the_label():
    text = "Deal consolidated from 2023-10-13 (h1-h4)"
    assert P.scope_from(text) == date(2023, 10, 13)
    assert not P.in_scope(text, 1, date(2023, 9, 30))  # ended before the close
    assert P.in_scope(text, 2, date(2023, 12, 31))
    assert P.in_scope(text, 1, date(2023, 10, 13))  # ends on the close: holds a day of it
    assert P.in_scope(text, 3, None)  # not reported yet: the label decides
    assert not P.in_scope("Deal (h3-h4)", 2, date(2023, 12, 31))  # no date: the label decides


def test_a_quarter_that_ended_before_the_event_is_shown_not_compared(company):
    usual_set(company, [0.01] * 12)
    c = case("TST_e", when="2020-10-15")
    rid = store_case(company, c, ["FY2030Q1"])
    h = seen(rid, [("FY2020Q3", 90.0), ("FY2020Q4", 90.0)])
    q1, q2 = h.quarters
    h = Hindsight(rid, "TST", h.as_of, ASOF, [
        Quarter(q1.period, 2020, "Q3", 1, date(2020, 9, 30), 92, q1.items),
        Quarter(q2.period, 2020, "Q4", 2, date(2020, 12, 31), 92, q2.items)])  # fmt: skip
    (pc,) = call(company, [c], {rid: h}).cases
    first, second = pc.quarters
    assert first.ended_before_event and first.items["revenue"].miss is not None
    assert first.items["revenue"].usual.missing.code == "ended_before_event"
    assert not second.ended_before_event  # compared, against h2's (empty) usual set
    assert second.items["revenue"].usual.missing.code == "few_usual_quarters"


def test_the_real_case_file_scope_dates_flag_the_right_quarters():
    from domains.evaluation.cases import load_cases

    by = {c.case_id: c for c in load_cases()}
    msft = by["MSFT_2023-10-13"].scope_change
    assert not P.in_scope(msft, 1, date(2023, 9, 30)) and P.in_scope(msft, 2, date(2023, 12, 31))
    xom = by["XOM_2023-10-11"].scope_change
    assert not P.in_scope(xom, 3, date(2024, 3, 31)) and P.in_scope(xom, 4, date(2024, 6, 30))
    assert not P.in_scope(by["MSFT_2023-01-18"].scope_change, 4, date(2023, 9, 30))


def test_other_type_cases_are_context_not_counted(company):
    a, b = case("TST_g"), case("TST_r", kind="restructuring")
    ra, rb = store_case(company, a, ["FY2030Q1"]), store_case(company, b, ["FY2030Q2"])
    hs = {ra: seen(ra, [("FY2021Q1", 90.0)]), rb: seen(rb, [("FY2021Q1", 90.0)])}
    rec = call(company, [a, b], hs)
    assert rec.n == 1 and [c.case_id for c in rec.same_company_other_type] == ["TST_r"]
    assert rec.same_company_other_type[0].same_type is False


def test_no_case_of_the_type_gives_no_cases_and_still_the_metrics(company):
    rec = call(company, [case("TST_g")], {}, kind="policy")
    assert rec.n == 0 and rec.missing.code == "no_cases" and rec.thin_evidence
    assert [m.metric_id for m in rec.metrics] == [m.metric_id for m in P.load_metrics()["policy"]]


def test_a_case_without_a_stored_run_is_listed_as_not_scored(company):
    rec = call(company, [case("TST_none")], {})
    assert rec.n == 0 and rec.n_listed == 1 and rec.cases[0].missing.code == "not_scored"


def test_the_case_run_comes_from_the_newest_batch(company):
    c = case("TST_e")
    store_case(company, c, ["FY2030Q1"], batch="eval_a")
    company.execute("UPDATE eval_batches SET created_at = '2020-01-01T00:00:00Z'")
    company.execute(
        "INSERT INTO runs (run_id, cik, ticker, as_of, code_version, ingest_run_id, "
        "concept_map_sha256, price_fetch_sha256, index_fetch_sha256, yield_fetch_sha256) "
        "SELECT 'TST_e_2', cik, ticker, as_of, code_version, ingest_run_id, 'a', 'b', 'c', 'd' "
        "FROM runs WHERE run_id = 'TST_e_1'")  # fmt: skip
    company.execute("INSERT INTO eval_batches (batch_id, code_version, cases_sha256) "
                    "VALUES ('eval_b', 'v', 'x')")  # fmt: skip
    company.execute("INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, "
                    "horizon, forecast, status) VALUES ('eval_b', 'TST_e', 'TST_e_2', "
                    "'baseline', 'revenue', 'FY2030Q1', 1, 1.0, 'ok')")  # fmt: skip
    company.commit()
    assert P.case_runs(company, ["TST_e"]) == {"TST_e": "TST_e_2"}


@pytest.mark.parametrize("kind", ["control", "weather"])
def test_an_unknown_event_type_is_refused_with_a_code(company, kind):
    with pytest.raises(P.PastEventsError) as e:
        call(company, [], {}, kind=kind)
    assert e.value.code == "unknown_event_type" and "policy" in e.value.params["allowed"]


def test_an_unknown_ticker_is_refused(company):
    with pytest.raises(EvaluationError, match="not been ingested"):
        P.past_events(company, "ZZZ", "guidance", ASOF, cases=[])


def test_to_dict_is_plain_json_and_render_names_the_rule(company):
    usual_set(company, [0.01] * 12)
    c = case("TST_e")
    rid = store_case(company, c, ["FY2030Q1"])
    rec = call(company, [c], {rid: seen(rid, [("FY2021Q1", 90.0)])})
    d = json.loads(json.dumps(rec.to_dict()))
    assert d["cases"][0]["event_date"] == "2020-06-01" and d["threshold"] == 6
    assert {n["code"] for n in d["notes"]} >= {
        "rule",
        "mechanism_untagged",
        "beyond_usual_by_chance",
        "thin_evidence",
    }
    text = P.render(rec)
    assert "Rule: every case in the library of type guidance" in text and "TST_e" in text


def test_the_question_date_reaches_the_actuals(company):
    c = case("TST_e")
    rid = store_case(company, c, ["FY2030Q1"])
    asked = []

    def hindsight(conn, run_id, on):
        asked.append((run_id, on))
        return seen(run_id, [("FY2021Q1", 90.0)])

    P.past_events(company, "TST", "guidance", ASOF, cases=[c], check_basis=False,
                  hindsight=hindsight)  # fmt: skip
    assert asked == [(rid, ASOF)]  # actuals are cut at D, not later


def test_a_deal_closing_after_d_is_not_shown_yet(company):
    c = case("TST_m", kind="m_and_a", scope="Deal consolidated from 2021-09-01 (h1-h4)")
    rid = store_case(company, c, ["FY2030Q1"])
    hs = {rid: seen(rid, [("FY2021Q1", 90.0), ("FY2021Q2", None)])}
    (pc,) = call(company, [c], hs, kind="m_and_a").cases
    assert pc.scope_change is None and not any(q.scope_change for q in pc.quarters)
    later = call(company, [c], hs, kind="m_and_a", as_of=date(2021, 9, 2)).cases[0]
    assert later.scope_change.startswith("Deal consolidated")


# -- backlog #252: coverage and merger notes -----------------------------------------------------


def _ends(company, monkeypatch, ends="2020-12-31"):
    """Give the fixture company a pinned CIK whose filings stop on `ends`."""
    from domains.fundamentals import universe as U

    cik = company.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    row = U.UniverseCompany(
        "TST", cik, "Test Corp moved to a new CIK.", date.fromisoformat(ends),
        "holding_company_reorganisation", "0000000002", "Test Holdings",
    )  # fmt: skip
    monkeypatch.setattr(U, "PHASE1_UNIVERSE", [*U.PHASE1_UNIVERSE, row])
    return cik


def test_a_company_whose_filings_stopped_by_d_gets_the_runs_coverage_note(company, monkeypatch):
    cik = _ends(company, monkeypatch)
    rec = call(company, [case("TST_g")], {})
    notes = [n for n in rec.notes if n.code == "beyond_history"]
    assert len(notes) == 1
    p = notes[0].params
    assert (p["ticker"], p["cik"], p["as_of"], p["history_ends"]) == (
        "TST",
        cik,
        ASOF.isoformat(),
        "2020-12-31",
    )
    assert (p["reason"], p["successor_cik"], p["successor_name"]) == (
        "holding_company_reorganisation", "0000000002", "Test Holdings")  # fmt: skip
    assert "missing here" in notes[0].text and notes[0].text in P.render(rec)
    json.dumps(rec.to_dict())


def test_no_coverage_note_before_the_filings_stop(company, monkeypatch):
    _ends(company, monkeypatch, ends="2021-07-02")  # the day after ASOF
    assert not any(n.code == "beyond_history" for n in call(company, [case("TST_g")], {}).notes)


def test_a_coverage_note_comes_from_a_case_company_too(company, monkeypatch):
    """The question names another company; the case company's filings stopped."""
    _ends(company, monkeypatch)
    cik = company.execute("SELECT cik FROM companies WHERE ticker = 'TST'").fetchone()[0]
    company.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000099', 'OTH', 'O')")
    rec = P.past_events(company, "OTH", "guidance", ASOF, cases=[case("TST_g")],
                        check_basis=False, hindsight=lambda c, r, on: None)  # fmt: skip
    assert [n.params["cik"] for n in rec.notes if n.code == "beyond_history"] == [cik]


# -- backlog #256: whose filings stop ----------------------------------------------------------


def test_the_question_companys_note_is_the_runs_note_with_role_question(company, monkeypatch):
    """TST is both the question's company and a case's: one note, `question`, the run's text."""
    from domains.fundamentals.universe import coverage_gap

    cik = _ends(company, monkeypatch)
    notes = [n for n in call(company, [case("TST_g")], {}).notes if n.code == "beyond_history"]
    text, params = coverage_gap(cik, ASOF)
    assert [(n.text, n.params) for n in notes] == [(text, {**params, "role": "question"})]


def test_a_case_companys_note_says_it_is_a_past_case(company, monkeypatch):
    from domains.fundamentals.universe import coverage_gap

    cik = _ends(company, monkeypatch)
    company.execute("INSERT INTO companies (cik, ticker, name) VALUES ('0000000099', 'OTH', 'O')")
    rec = P.past_events(company, "OTH", "guidance", ASOF, cases=[case("TST_g")],
                        check_basis=False, hindsight=lambda c, r, on: None)  # fmt: skip
    (note,) = [n for n in rec.notes if n.code == "beyond_history"]
    text, params = coverage_gap(cik, ASOF)
    assert note.params == {**params, "role": "case"}
    assert note.text == (
        "TST is in this answer as a past case, not the question's company: its filings from "
        "2020-12-31 on are missing here, so its typical forecast errors, and any of its case "
        f"quarters reported from then on, stop at that date. {text}"
    )
    assert note.text in P.render(rec)
    json.dumps(rec.to_dict())


def test_the_question_companys_note_comes_before_the_case_companies(monkeypatch):
    from domains.fundamentals import universe as U

    rows = [
        U.UniverseCompany(
            t, c, "moved.", date(2020, 12, 31), "holding_company_reorganisation", s, "New"
        )  # fmt: skip
        for t, c, s in [("AAA", "0000000101", "0000000201"), ("ZZZ", "0000000102", "0000000202")]
    ]
    monkeypatch.setattr(U, "PHASE1_UNIVERSE", [*U.PHASE1_UNIVERSE, *rows])
    monkeypatch.setattr(P, "get_universe_company", lambda t: {r.ticker: r for r in rows}[t])
    notes = P.coverage_notes("ZZZ", {"AAA", "ZZZ"}, ASOF)
    assert [(n.params["ticker"], n.params["role"]) for n in notes] == [
        ("ZZZ", "question"),
        ("AAA", "case"),
    ]


@pytest.mark.parametrize("kind, has", [("m_and_a", True), ("guidance", False)])
def test_a_merger_question_carries_the_shock_sizing_caveat(company, kind, has):
    rec = call(company, [case("TST_m", kind="m_and_a"), case("TST_g")], {}, kind=kind)
    caveats = [n for n in rec.notes if n.code == "merger_shocks_missized"]
    assert bool(caveats) is has
    if has:  # no deal is named: a question dated before a deal must not learn of it
        assert "Activision" not in caveats[0].text and "Pioneer" not in caveats[0].text
