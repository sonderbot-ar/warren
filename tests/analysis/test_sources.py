"""A structured source for every assumption row of a run (backlog #175)."""

import json
from contextlib import contextmanager

import pytest

from domains.analysis import __main__ as cli
from domains.analysis import dcf
from domains.analysis import sources as src
from domains.analysis.math_engine import UserChoice, build_inputs, post_checks
from domains.analysis.runs import load_outputs, reproduce, run_baseline, save_run
from domains.analysis.schemas import SINGLE
from domains.analysis.sources import run_sources
from domains.analysis.whatif import Change, revalue
from domains.market.prices import MARKET_INDEX
from tests.analysis.conftest import AS_OF, CHOICES, revenue
from tests.analysis.test_math_engine import drop


def _build(conn, choices=CHOICES):
    return build_inputs(conn, "TST", AS_OF, choices=choices, today=AS_OF)


def _kinds(items):
    return [i["kind"] for i in items]


def test_every_row_has_a_source_and_every_derived_input_is_a_row(company):
    result = _build(company)
    src.check(result.assumptions, result.sources)
    assert set(result.sources) == {(a.name, a.period) for a in result.assumptions}
    used = {i["kind"] for items in result.sources.values() for i in items}
    assert used == {"filing", "market", "owner_choice", "derived", "rule"}
    # Test Corp reports no short-term investments or borrowings: its working capital says so
    rules = {k for k, items in result.sources.items() if "rule" in _kinds(items)}
    assert rules == {("history:nwc", f"FY{y}") for y in (2017, 2018, 2019)}


def test_the_stored_run_keeps_its_sources_and_still_reproduces(company):
    result = _build(company)
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    assert src.load(company, run_id) == result.sources
    assert reproduce(company, run_id).ok


def test_a_seed_quarter_names_its_filing_and_tag(company):
    seed = _build(company).sources[(dcf.SEED, "FY2020Q1")]
    assert _kinds(seed) == ["filing"]
    (fact,) = seed
    assert fact["item"] == "revenue"
    assert fact["concept"] == "us-gaap:Revenues"
    assert fact["period_end"] == "2020-03-31"
    assert fact["fiscal_period"] == "Q1"
    assert fact["accession_no"] and fact["derived"] is False
    assert fact["value"] == pytest.approx(revenue(2020, 1))
    assert fact["filed_at"] <= AS_OF.isoformat()  # public on the run's date


def test_a_rescaled_seed_names_the_year_and_all_four_quarters(make_company):
    def restate(tag, row):
        if tag == "Revenues" and row["form"] == "10-K" and row["end"] == "2019-12-31":
            return {**row, "val": row["val"] * 1.1}
        return row

    conn = make_company(restate)
    conn.execute(
        "INSERT INTO financial_facts (cik, xbrl_concept, period_start, period_end, fiscal_year, "
        "fiscal_period, value, unit, form, accession_no, filed_at) VALUES ('0000000123', "
        "'us-gaap:Revenues', '2019-01-01', '2019-09-30', 2019, 'M9', ?, 'USD', '10-K', "
        "'0000000123-20-000015', '2020-02-15')",
        (1.1 * sum(revenue(2019, q) for q in (1, 2, 3)),),
    )
    result = _build(conn)
    seed = result.sources[(dcf.SEED, "FY2019Q2")]
    assert "differ from the year" in next(
        a.method for a in result.assumptions if (a.name, a.period) == (dcf.SEED, "FY2019Q2")
    )
    assert _kinds(seed) == ["filing"] * 5
    assert seed[0]["fiscal_period"] == "FY"
    assert sorted(f["fiscal_period"] for f in seed[1:]) == ["Q1", "Q2", "Q3", "Q4"]
    q4 = next(f for f in seed if f["fiscal_period"] == "Q4")
    assert q4["derived"] and q4["accession_no"] is None and q4["inputs"]


def test_market_rows_name_their_series_and_dates(company):
    s = _build(company).sources
    (rf,) = s[("risk_free", SINGLE)]
    assert (rf["provider"], rf["series"], rf["measure"]) == ("fred", "DGS10", "yield")
    assert rf["start"] == rf["end"] and rf["end"] < AS_OF.isoformat()
    beta = s[("beta", SINGLE)]
    assert [(b["series"], b["measure"]) for b in beta] == [
        ("TST", "weekly_total_return"),
        (MARKET_INDEX, "weekly_total_return"),
    ]
    assert beta[0]["start"] == beta[1]["start"] and beta[0]["end"] == beta[1]["end"]
    erp = s[("erp", SINGLE)]
    assert [(e["provider"], e["series"]) for e in erp] == [
        ("yahoo", MARKET_INDEX),
        ("fred", "DGS10"),
    ]
    assert erp[0]["start"] == "1988-12-31"  # the first return (1989) starts at the 1988 close
    assert erp[0]["end"] == "2019-12-31"
    assert s[("erp_std_error", SINGLE)] == erp
    (price,) = s[("price", SINGLE)]
    assert (price["series"], price["measure"]) == ("TST", "close")


def test_rows_computed_from_other_rows_name_them(company):
    s = _build(company).sources
    assert s[("terminal_growth", SINGLE)] == [
        src.derived(("risk_free", SINGLE), ("terminal_growth_method", SINGLE))
    ]
    assert s[("equity_market_value", SINGLE)] == [
        src.derived(("price", SINGLE), ("shares", SINGLE))
    ]
    (roll,) = s[("roll_years", SINGLE)]
    assert roll["inputs"] == [{"name": dcf.SEED, "period": "FY2020Q1"}]
    (margin,) = s[("operating_margin", "Y3")]
    assert {(i["name"], i["period"]) for i in margin["inputs"]} == {
        (f"history:{item}", f"FY{y}") for y in (2017, 2018, 2019) for item in ("ebit", "revenue")
    }
    quarter = next(p for (n, p) in s if n == "operating_margin" and p.endswith("Q2"))
    (qm,) = s[("operating_margin", quarter)]
    assert all(i["period"].endswith("Q2") for i in qm["inputs"])
    (debt,) = s[("debt", SINGLE)]
    assert {i["name"] for i in debt["inputs"]} == {
        "balance:debt_current",
        "balance:debt_noncurrent",
    }


def test_revenue_growth_names_both_facts_of_each_comparative(company):
    growth = _build(company).sources[("revenue_growth", "Y3")]
    filings = [g for g in growth if g["kind"] == "filing"]
    assert len(filings) == 6  # three 10-Ks, the year and its prior-year comparative in each
    for current, prior in zip(filings[::2], filings[1::2], strict=True):
        assert current["accession_no"] == prior["accession_no"]
        assert current["fiscal_year"] == prior["fiscal_year"] + 1
    assert growth[-1] == src.derived(("terminal_growth", SINGLE))


def test_the_cost_of_debt_names_the_interest_and_both_years_debt(company):
    kd = _build(company).sources[("cost_of_debt", SINGLE)]
    assert _kinds(kd) == ["filing"] * len(kd)
    items = [(k["item"], k["fiscal_year"]) for k in kd]
    assert ("interest_expense", 2019) in items
    assert {("debt_current", 2018), ("debt_noncurrent", 2018)} <= set(items)
    assert {("debt_current", 2019), ("debt_noncurrent", 2019)} <= set(items)


def test_owner_choices_name_their_row_of_the_file(company):
    (erp_method,) = _build(company).sources[("erp_method", SINGLE)]
    assert erp_method == src.owner_choice(
        "erp_method", "historical_geometric", "test", "2026-10-26"
    )


def test_an_item_not_reported_is_a_rule_not_a_filing(make_company):
    result = _build(make_company(drop({"MinorityInterest"})))
    assert result.sources[("minority_interest", SINGLE)] == [src.rule("not_reported_zero")]
    src.check(result.assumptions, result.sources)


def test_a_run_without_complete_sources_is_refused_and_stores_nothing(company):
    result = _build(company)
    outputs, gaps = dcf.outputs_and_gaps(result.assumptions)
    del result.sources[("beta", SINGLE)]
    with pytest.raises(src.SourceError, match="without a source"):
        save_run(company, result, outputs, post_checks(result.assumptions, outputs), gaps)
    assert company.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"kind": "guess"}, "unknown kind"),
        (src.derived(("no_such_row", SINGLE)), "doesn't store"),
        (src.what_if("P", 1.0, "set", []), "not a what-if"),
    ],
)
def test_check_refuses_malformed_sources(company, bad, message):
    result = _build(company)
    result.sources[("beta", SINGLE)] = [bad]
    with pytest.raises(src.SourceError, match=message):
        src.check(result.assumptions, result.sources)


def test_a_what_if_keeps_the_parents_sources_and_marks_what_changed(company):
    parent = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    child = revalue(company, parent, [Change("shares", value=50.0)]).run_id
    before = src.load(company, parent)
    after = src.load(company, child)
    assert after.keys() == before.keys()
    (changed,) = after[("shares", SINGLE)]
    assert changed["kind"] == "what_if"
    assert changed["parent_run_id"] == parent and changed["how"] == "set"
    assert changed["before"] == pytest.approx(100)
    assert changed["parent_sources"] == before[("shares", SINGLE)]
    # the copied market value was computed from the parent's shares, and says so
    (emv,) = after[("equity_market_value", SINGLE)]
    assert {"name": "shares", "period": SINGLE, "run_id": parent} in emv["inputs"]
    assert after[("beta", SINGLE)] == before[("beta", SINGLE)]


def test_terminal_growth_that_followed_the_risk_free_rate_says_so(company):
    parent = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    child = revalue(company, parent, [Change("risk_free", delta=0.0025)]).run_id
    (tg,) = src.load(company, child)[("terminal_growth", SINGLE)]
    assert tg["kind"] == "what_if" and tg["how"] == "follows_risk_free"


def _moved(rows, key):
    """The rows with one row's value moved by 1% (or by 0.001 when it is zero)."""
    out = []
    for a in rows:
        if (a.name, a.period) == key:
            a = a.model_copy(update={"value": a.value * 1.01 if a.value else 0.001})
        out.append(a)
    return out


@pytest.mark.parametrize("method", ["value_driver_ronic_wacc", "gordon_fcff"])
def test_the_output_trace_matches_the_arithmetic(company, method):
    choices = CHOICES | {
        "terminal_method": UserChoice("terminal_method", method, "test", "2026-10-26", "")
    }
    # working-capital shares that differ by period, so no input cancels out of a change in
    # working capital by coincidence (with one share for all periods, a seed quarter drops out)
    rows = [
        a.model_copy(update={"value": a.value * (1 + 0.01 * i)}) if a.name == "nwc_pct" else a
        for i, a in enumerate(_build(company, choices).assumptions)
    ]
    base, _ = dcf.outputs_and_gaps(rows)
    trace = src.output_trace(rows)
    assert set(trace) >= set(base)
    keys = {(a.name, a.period) for a in rows}
    for out_key, step in trace.items():
        assert step["formula"] in src.FORMULAS
        for ref in step["inputs"]:
            pool = keys if ref["of"] == "row" else set(trace)
            assert (ref["name"], ref["period"]) in pool, (out_key, ref)
    reach = {key: src.reaches(trace, key) for key in base}
    for a in rows:
        if a.value is None:
            continue
        key = (a.name, a.period)
        moved, _ = dcf.outputs_and_gaps(_moved(rows, key))
        for out_key, value in base.items():
            changed = abs(moved[out_key] - value) > 1e-12 * max(1.0, abs(value))
            # moving a row changes exactly the outputs whose trace reaches it
            assert changed == (key in reach[out_key]), (key, out_key, changed)


# -- what the app reads, and the backfill (Steps 2 and 3) ------------------------------------------


def _forget(conn, run_id):
    """The run as it was stored before sources were recorded."""
    conn.execute("DELETE FROM assumption_sources WHERE run_id = ?", (run_id,))
    conn.commit()


def test_run_sources_gives_filings_with_their_link_and_markets_with_their_download(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = run_sources(company, run_id)
    run = company.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert answer.recorded and answer.as_of == AS_OF.isoformat() and answer.ticker == "TST"
    rows = {(r["name"], r["period"]): r for r in answer.rows}
    assert all(r["sources"] and r["gap"] is None for r in rows.values())
    (seed,) = rows[(dcf.SEED, "FY2020Q1")]["sources"]
    assert seed["filing"]["form"] == "10-Q"
    assert seed["filing"]["filed_at"] == "2020-04-30"
    assert seed["filing"]["url"].startswith("https://www.sec.gov/Archives/edgar/data/123/")
    (rf,) = rows[("risk_free", SINGLE)]["sources"]
    assert rf["label"] == "FRED" and rf["fetch_sha256"] == run["yield_fetch_sha256"]
    assert rf["url"] == "https://fred.stlouisfed.org/series/DGS10"
    stock, index = rows[("beta", SINGLE)]["sources"]
    assert stock["fetch_sha256"] == run["price_fetch_sha256"]
    assert index["fetch_sha256"] == run["index_fetch_sha256"]
    assert "%5E" in index["url"]  # ^SP500TR, quoted


def test_run_sources_traces_every_stored_output(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    answer = run_sources(company, run_id)
    stored = load_outputs(company, run_id)
    by_key = {(o["name"], o["period"]): o for o in answer.outputs}
    assert set(stored) <= set(by_key)
    vps = by_key[("value_per_share", SINGLE)]
    assert vps["formula"] == "per_share" and vps["value"] == stored[("value_per_share", SINGLE)]
    assert {"of": "row", "name": "shares", "period": SINGLE} in vps["inputs"]
    assert json.loads(json.dumps(answer.to_dict())) == answer.to_dict()


def test_a_run_stored_before_sources_says_so_on_every_row(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    _forget(company, run_id)
    answer = run_sources(company, run_id)
    assert not answer.recorded
    assert {r["gap"]["code"] for r in answer.rows} == {"not_recorded"}
    assert all(r["sources"] == [] for r in answer.rows)
    assert answer.outputs  # the trace needs no stored source


def test_a_what_if_of_an_older_run_has_no_sources_either(company):
    parent = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    _forget(company, parent)
    child = revalue(company, parent, [Change("beta", value=1.2)]).run_id
    assert not run_sources(company, child).recorded


def test_the_backfill_gives_an_older_run_the_same_sources_back(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    before = src.load(company, run_id)
    _forget(company, run_id)
    assert src.backfill(company, run_id) == ("filled", "")
    assert src.load(company, run_id) == before
    assert src.backfill(company, run_id) == ("already_recorded", "")
    assert reproduce(company, run_id).ok


def test_the_backfill_skips_a_run_that_doesnt_rebuild_exactly(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    _forget(company, run_id)
    company.execute(
        "UPDATE assumptions SET method = 'older code' WHERE run_id = ? AND name = 'beta'",
        (run_id,),
    )
    company.commit()
    status, detail = src.backfill(company, run_id)
    assert status == "rebuild_differs" and "beta" in detail
    assert src.load(company, run_id) == {}


def test_the_backfill_leaves_what_ifs_alone(company):
    parent = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    child = revalue(company, parent, [Change("beta", value=1.2)]).run_id
    _forget(company, child)
    assert src.backfill(company, child)[0] == "what_if_not_backfilled"


def test_the_sources_command(company, monkeypatch, capsys):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)

    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    assert cli.main(["sources", "--run-id", run_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == run_id
    assert cli.main(["sources", "--run-id", run_id, "--name", "risk_free"]) == 0
    text = capsys.readouterr().out
    assert "market: FRED DGS10 yield" in text and "beta" not in text
    _forget(company, run_id)
    assert cli.main(["sources", "--backfill", "--all"]) == 0
    assert "filled 1" in capsys.readouterr().out
    assert cli.main(["sources", "--backfill"]) == 2
    assert cli.main(["sources", "--run-id", "nope"]) == 1
