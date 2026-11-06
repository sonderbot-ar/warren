"""Monte Carlo over shocks: sampling, storage, reproduce and the command line (M4 Step 3)."""

import shutil
import sqlite3
from contextlib import contextmanager

import numpy as np
import pytest

from domains.analysis import __main__ as cli
from domains.analysis import dcf, montecarlo, sim_report
from domains.analysis.coded import SIMULATION_REFUSAL_CODES
from domains.analysis.montecarlo import SimulationError
from domains.analysis.runs import load_outputs, run_baseline
from shared_kernel.database import MIGRATIONS_DIR, apply_migrations, get_db_connection
from tests.analysis.conftest import AS_OF, CHOICES
from tests.analysis.test_dcf import VALUE_DRIVER_ROW, rows
from tests.analysis.test_shocks import shock

RANGE = {"low": -6.0, "base": -2.0, "high": -1.0}


def test_same_seed_gives_identical_outputs_and_another_seed_does_not():
    shocks = [shock(**RANGE, horizon=4)]
    first = montecarlo.simulate(rows(), shocks, n=2000, seed=11)
    assert first == montecarlo.simulate(rows(), shocks, n=2000, seed=11)
    assert first != montecarlo.simulate(rows(), shocks, n=2000, seed=12)


def test_sampled_percentiles_match_low_base_high():
    # a margin shock in quarter 1 moves EBIT there by revenue (100) × magnitude points, so the
    # EBIT percentiles read the magnitude's percentiles back: 20 + p, within 2% of (high − low)
    bands = montecarlo.simulate(rows(), [shock(driver="operating_margin", **RANGE)], seed=3)
    q1 = bands[("ebit", "FY2024Q3")]
    tolerance = 0.02 * (RANGE["high"] - RANGE["low"])
    assert q1.p10 == pytest.approx(20 + RANGE["low"], abs=tolerance)
    assert q1.p50 == pytest.approx(20 + RANGE["base"], abs=tolerance)
    assert q1.p90 == pytest.approx(20 + RANGE["high"], abs=tolerance)
    assert q1.baseline == pytest.approx(20)


def test_no_shocks_every_sample_is_the_baseline():
    bands = montecarlo.simulate(rows(growth=0.02), [], n=50, seed=1)
    baseline = dcf.value(rows(growth=0.02))
    vps = bands[("value_per_share", "-")]
    assert vps.p10 == vps.p50 == vps.p90 == pytest.approx(baseline.value_per_share)


def test_impossible_drivers_stop_the_run():
    wild = shock(driver="operating_margin", low=-500.0, base=0.0, high=10.0)
    with pytest.raises(SimulationError, match="impossible operating_margin"):
        montecarlo.simulate(rows(), [wild], n=1000, seed=1)


def test_a_discount_rate_the_terminal_value_cannot_use_stops_the_run():
    # −1,500 bp on a 10% cost of equity in Y5 leaves it below zero in some samples
    deep = shock(driver="risk_premium", low=-1500.0, base=0.0, high=0.0, horizon=20)
    with pytest.raises(SimulationError, match="discount rate"):
        montecarlo.simulate(rows(), [deep], n=1000, seed=1)


def test_under_the_value_driver_rule_a_rate_at_terminal_growth_stops_the_run():
    # g 4%; −700 bp at p10 on a 10% cost of equity puts Y5's rate below 4% in some samples,
    # which the value-driver perpetuity can't value either (backlog #79)
    low = shock(driver="risk_premium", low=-700.0, base=-300.0, high=0.0, horizon=20)
    with pytest.raises(SimulationError, match="at or below 4.00%"):
        montecarlo.simulate(rows(terminal_growth=0.04) + [VALUE_DRIVER_ROW], [low], n=1000, seed=1)


def test_under_the_value_driver_rule_rates_above_terminal_growth_run():
    # −100 bp at p10: the lowest of 1,000 samples stays far above 4%
    mild = shock(driver="risk_premium", low=-100.0, base=0.0, high=0.0, horizon=20)
    bands = montecarlo.simulate(rows(terminal_growth=0.04) + [VALUE_DRIVER_ROW], [mild], n=1000)
    assert bands[("value_per_share", "-")].p50 > 0


def test_migration_applies_to_an_existing_database(tmp_path):
    db = sqlite3.connect(tmp_path / "old.db")
    db.row_factory = sqlite3.Row
    versions = apply_migrations(db)
    assert versions[-1] >= 8
    db.execute("SELECT sim_id, seed, currency FROM simulations").fetchall()
    assert apply_migrations(db) == []  # already applied: nothing to do


def test_stored_simulation_reproduces_to_the_cent_and_detects_an_edit(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    shocks = [
        shock(**RANGE, horizon=4),
        shock(shock_id="rp", driver="risk_premium", low=0, base=50, high=150, horizon=20),
    ]
    sim_id = montecarlo.save_simulation(company, run_id, shocks, n=500, seed=5)
    assert montecarlo.reproduce_simulation(company, sim_id).ok
    assert [s.shock_id for s in montecarlo.load_simulation_shocks(company, sim_id)] == ["s1", "rp"]
    company.execute("UPDATE shocks SET high = 300 WHERE shock_id = ?", (f"{sim_id}:rp",))
    result = montecarlo.reproduce_simulation(company, sim_id)
    assert not result.ok and "hash" in result.mismatches[0]


def test_a_simulation_stored_before_0012_upgrades_and_still_reproduces(company, tmp_path):
    # backlog #74: build the rows on today's schema, copy them into a v11 database (no
    # shocks.basis, no later tables), then upgrade it; the old shocks must read back as growth
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    shocks = [
        shock(**RANGE, horizon=4),
        shock(shock_id="rp", driver="risk_premium", low=0, base=50, high=150, horizon=20),
    ]
    sim_id = montecarlo.save_simulation(company, run_id, shocks, n=500, seed=5)
    outputs = montecarlo.reproduce_simulation(company, sim_id).outputs_checked
    company.commit()

    v11 = tmp_path / "v11"
    v11.mkdir()
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name[:4]) <= 11:
            shutil.copy(path, v11 / path.name)
    with get_db_connection(tmp_path / "old.db") as old:
        assert max(apply_migrations(old, v11)) == 11
        old.execute("PRAGMA foreign_keys=OFF")  # rows arrive in table order, not key order
        found = old.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        virtual = [name for name, sql in found if sql.startswith("CREATE VIRTUAL")]
        tables = [
            name
            for name, _ in found
            if name != "schema_version"
            and not name.startswith("sqlite_")
            and not any(name.startswith(v) for v in virtual)  # FTS and its shadow tables
        ]
        for table in tables:
            columns = [r[1] for r in old.execute(f"PRAGMA table_info({table})")]
            names = ", ".join(columns)
            marks = ", ".join("?" * len(columns))
            rows_now = company.execute(f"SELECT {names} FROM {table}").fetchall()
            old.executemany(f"INSERT INTO {table} ({names}) VALUES ({marks})", rows_now)
        old.commit()
        assert "basis" not in {r[1] for r in old.execute("PRAGMA table_info(shocks)")}
        assert old.execute("SELECT COUNT(*) FROM shocks").fetchone()[0] == 2

        old.execute("PRAGMA foreign_keys=ON")
        assert apply_migrations(old)[:2] == [12, 13]
        assert old.execute("PRAGMA foreign_key_check").fetchall() == []
        loaded = montecarlo.load_simulation_shocks(old, sim_id)
        assert [(s.shock_id, s.basis) for s in loaded] == [("s1", "growth"), ("rp", "growth")]
        result = montecarlo.reproduce_simulation(old, sim_id)
        assert result.ok, result.mismatches
        assert result.outputs_checked == outputs


def test_report_shows_bands_and_says_what_they_cover(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    sim_id = montecarlo.save_simulation(company, run_id, [shock(**RANGE)], n=200, seed=2)
    text = sim_report.render(company, sim_id)
    for needle in ("## Shocks", "## Revenue", "## Free cash flow", "shocks' size", "don't add up"):
        assert needle in text
    assert "-6 / -2 / -1 pts" in text


def test_cli_simulates_and_reproduces(company, tmp_path, monkeypatch, capsys):
    @contextmanager
    def same_connection(*args):
        yield company

    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    path = tmp_path / "shocks.csv"
    path.write_text(
        ",".join(montecarlo.SHOCK_FIELDS)
        + "\nguide,,revenue_growth,-3,-2,-1,1,2,1,user,test source\n"
    )
    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    monkeypatch.setattr(sim_report, "REPORTS_DIR", tmp_path)
    args = ["simulate", "--run-id", run_id, "--shocks", str(path), "--n", "300", "--seed", "9"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "shocked p10" in out and "WARNING" not in out
    assert cli.main(["reproduce-sim", "--sim-id", f"{run_id}_sim1"]) == 0
    assert (tmp_path / f"{run_id}_sim1.md").exists()


def test_bad_shock_file_is_refused(tmp_path):
    path = tmp_path / "shocks.csv"
    path.write_text(",".join(montecarlo.SHOCK_FIELDS) + "\nx,,beta,0,0,0,1,1,1,user,t\n")
    with pytest.raises(SimulationError, match="line 2"):
        montecarlo.load_shocks(path)


def test_split_normal_draws_use_the_documented_generator():
    # column i of rng.standard_normal((n, k)) is shock i: a re-implementation must match
    z = np.random.Generator(np.random.PCG64(4)).standard_normal((3, 1))[:, 0]
    bands = montecarlo.simulate(rows(), [shock(driver="operating_margin", **RANGE)], n=3, seed=4)
    from domains.analysis import financial_math as fm

    expected = 20 + np.percentile(fm.split_normal(-6, -2, -1, z), 50)
    assert bands[("ebit", "FY2024Q3")].p50 == pytest.approx(expected)


def test_a_level_shock_is_stored_and_reproduces(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    level = shock(**RANGE, horizon=4).model_copy(update={"basis": "level"})
    sim_id = montecarlo.save_simulation(company, run_id, [level], n=200, seed=3)
    [loaded] = montecarlo.load_simulation_shocks(company, sim_id)
    assert loaded.basis == "level"
    assert montecarlo.reproduce_simulation(company, sim_id).ok


def test_a_level_sample_that_removes_all_revenue_stops_the_run():
    level = shock(low=-95.0, base=-70.0, high=-30.0, horizon=4).model_copy(
        update={"basis": "level"}
    )
    with pytest.raises(SimulationError, match="revenue_growth"):
        montecarlo.simulate(rows(), [level], n=2000, seed=1)


# -- rate checks (backlog #90) --------------------------------------------------------------------

# −1,500 / −500 / 0 bp on the cost of equity for the first 4 quarters, no decay; the test company
# has a 10% cost of equity (4% risk-free + 1.0 × 6%) and no debt, so WACC = cost of equity
DEEP = {"driver": "risk_premium", "low": -1500.0, "base": -500.0, "high": 0.0, "horizon": 4}


def _magnitudes(n, seed):
    from domains.analysis import financial_math as fm

    z = np.random.Generator(np.random.PCG64(seed)).standard_normal((n, 1))[:, 0]
    return fm.split_normal(DEEP["low"], DEEP["base"], DEEP["high"], z)


def test_a_negative_risk_premium_and_a_rate_below_zero_are_counted_and_the_run_goes_on():
    n, seed = 10_000, 7
    bands, warnings = montecarlo.simulate_checked(rows(), [shock(**DEEP)], n=n, seed=seed)
    assert bands == montecarlo.simulate(rows(), [shock(**DEEP)], n=n, seed=seed)
    m = _magnitudes(n, seed)
    premium_gone = int((m <= -600).sum())  # β × ERP = 600 bp
    rate_gone = int((m <= -1000).sum())  # the whole 10%
    # independently of the draws: P(m ≤ x) = Φ((x − base) / σ_low), σ_low = 1000 / Z90
    for count, p in ((premium_gone, 0.4490), (rate_gone, 0.2608)):
        assert abs(count / n - p) < 4 * (p * (1 - p) / n) ** 0.5
    quarters = ", ".join(dcf.inputs(rows()).periods[:4])
    premium, rate = warnings
    assert premium.startswith(f"{premium_gone:,} of 10,000 samples ({premium_gone / n:.1%})")
    assert "negative risk premium" in premium and f"in {quarters}." in premium
    assert rate.startswith(f"{rate_gone:,} of 10,000 samples") and "at or below zero" in rate
    assert f"in {quarters}." in rate
    assert "p90" in premium and "p90" in rate  # 45% and 26%: past 10%, short of 50%


def test_most_samples_past_the_floor_can_set_the_p50():
    wide = shock(**DEEP | {"low": -2000.0, "base": -1200.0, "high": -700.0})
    _, warnings = montecarlo.simulate_checked(rows(), [wide], n=2000, seed=1)
    assert "p50" in warnings[0]  # every sample is past −600 bp


def test_a_mild_risk_premium_shock_gives_no_rate_warning():
    mild = shock(driver="risk_premium", low=-200.0, base=-50.0, high=100.0, horizon=20)
    assert montecarlo.simulate_checked(rows(), [mild], n=2000, seed=1)[1] == []
    assert montecarlo.simulate_checked(rows(), [], n=10, seed=1)[1] == []


def test_a_few_samples_past_the_floor_do_not_claim_the_p90():
    # p10 at −400 bp, base −100: σ_low = 300 / Z90, so P(m ≤ −600) = Φ(−2.14) ≈ 1.6%
    few = shock(driver="risk_premium", low=-400.0, base=-100.0, high=0.0, horizon=2)
    warnings = montecarlo.simulate_checked(rows(), [few], n=5000, seed=2)[1]
    assert "negative risk premium" in warnings[0]
    assert not any("p90" in line or "p50" in line for line in warnings)


def test_rate_warnings_are_stored_and_the_simulation_still_reproduces(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    clean = montecarlo.save_simulation(company, run_id, [shock(**RANGE)], n=200, seed=2)
    deep = montecarlo.save_simulation(company, run_id, [shock(**DEEP)], n=500, seed=3)
    notes = {
        sim_id: company.execute(
            "SELECT notes FROM simulations WHERE sim_id = ?", (sim_id,)
        ).fetchone()[0]
        for sim_id in (clean, deep)
    }
    assert notes[clean].split("\n") == [montecarlo.BAND_NOTE, montecarlo.RATES_CLEAN]
    lines = notes[deep].split("\n")
    assert lines[0] == montecarlo.BAND_NOTE and "negative risk premium" in lines[1]
    assert montecarlo.reproduce_simulation(company, deep).ok


def test_report_warnings_say_none_name_the_samples_or_say_not_checked(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    clean = montecarlo.save_simulation(company, run_id, [shock(**RANGE)], n=200, seed=2)
    deep = montecarlo.save_simulation(company, run_id, [shock(**DEEP)], n=500, seed=3)
    assert "## Warnings\n\nNone. No sample" in sim_report.render(company, clean)
    text = sim_report.render(company, deep)
    assert "## Warnings\n\n- " in text and "negative risk premium" in text
    # a simulation stored before the check has only the band note
    company.execute(
        "UPDATE simulations SET notes = ? WHERE sim_id = ?", (montecarlo.BAND_NOTE, clean)
    )
    assert "Not checked: this simulation was stored before" in sim_report.render(company, clean)


def test_cli_prints_rate_warnings(company, tmp_path, monkeypatch, capsys):
    @contextmanager
    def same_connection(*args):
        yield company

    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    path = tmp_path / "shocks.csv"
    path.write_text(
        ",".join(montecarlo.SHOCK_FIELDS) + "\nrp,,risk_premium,-1500,-500,0,1,4,1,user,test\n"
    )
    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    monkeypatch.setattr(sim_report, "REPORTS_DIR", tmp_path)
    args = ["simulate", "--run-id", run_id, "--shocks", str(path), "--n", "300", "--seed", "9"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "WARNING: " in out and "negative risk premium" in out


def test_a_run_with_no_premium_of_its_own_points_at_beta_and_erp_not_the_shocks():
    # β = 0: the cost of equity is the risk-free rate in every sample, before any shock
    [line] = montecarlo.simulate_checked(rows(beta=0.0), [], n=10, seed=1)[1]
    assert line.startswith("10 of 10 samples (100.0%)") and "check the beta and the ERP" in line
    assert "shocks' ranges" not in line


# -- a run with WACC set directly (backlog #212) -------------------------------------------------


def _set_wacc_child(conn, delta=0.01):
    from domains.analysis.whatif import Change, revalue

    run_id = run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    return run_id, revalue(conn, run_id, [Change("wacc", delta=delta)]).run_id


def _sims(conn):
    return conn.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]


def test_a_risk_premium_shock_on_a_run_with_wacc_set_is_refused_with_a_code(company):
    _, child = _set_wacc_child(company)
    wacc = dcf.inputs(montecarlo.load_assumptions(company, child)).wacc_override
    shocks = [
        shock(**RANGE, horizon=4),
        shock(shock_id="rp", driver="risk_premium", low=0, base=50, high=150, horizon=20),
    ]
    before = _sims(company)
    with pytest.raises(SimulationError) as caught:
        montecarlo.save_simulation(company, child, shocks, n=200, seed=1)
    e = caught.value
    assert e.code == "wacc_set_with_risk_premium_shock"
    assert e.params == {"wacc": wacc, "shock_ids": ["rp"]}
    assert e.coded().code == e.code and e.coded().text == str(e)
    assert e.code in SIMULATION_REFUSAL_CODES
    assert _sims(company) == before  # nothing stored
    with pytest.raises(SimulationError, match="set directly"):
        montecarlo.sample_lines(montecarlo.load_assumptions(company, child), shocks, n=10)


def test_a_zero_risk_premium_shock_is_refused_too(company):
    # a zero shock still asks for a cost-of-equity path the set rate ignores
    _, child = _set_wacc_child(company)
    zero = shock(shock_id="z", driver="risk_premium", low=0, base=0, high=0, horizon=20)
    with pytest.raises(SimulationError) as caught:
        montecarlo.save_simulation(company, child, [zero], n=10, seed=1)
    assert caught.value.params["shock_ids"] == ["z"]


def test_other_shocks_on_a_run_with_wacc_set_discount_at_the_set_rate(company):
    _, child = _set_wacc_child(company)
    rows = montecarlo.load_assumptions(company, child)
    sim_id = montecarlo.save_simulation(company, child, [shock(**RANGE, horizon=4)], n=300, seed=2)
    assert montecarlo.reproduce_simulation(company, sim_id).ok
    band = montecarlo.load_bands(company, sim_id)[("value_per_share", "-")]
    stored = load_outputs(company, child)[("value_per_share", "-")]
    assert round(band.baseline, 2) == round(stored, 2)
    _, shocked = montecarlo._shocked(rows, [shock(**RANGE, horizon=4)], 300, 2)
    inp = dcf.inputs(rows)
    assert dcf.discount_rates(shocked) == [inp.wacc_override] * len(inp.periods)


def test_a_baseline_still_takes_a_risk_premium_shock(company):
    run_id = run_baseline(company, "TST", AS_OF, choices=CHOICES, today=AS_OF)
    rp = shock(shock_id="rp", driver="risk_premium", low=0, base=50, high=150, horizon=20)
    sim_id = montecarlo.save_simulation(company, run_id, [rp], n=200, seed=3)
    assert montecarlo.reproduce_simulation(company, sim_id).ok


def test_a_refusal_without_a_code_is_text_only():
    e = SimulationError("need at least one sample")
    assert e.code is None and e.params == {} and e.coded() is None
    with pytest.raises(AssertionError):
        SimulationError("x", code="not_a_catalogued_code")


def test_the_cli_prints_the_refusal_code(company, tmp_path, monkeypatch, capsys):
    _, child = _set_wacc_child(company)
    path = tmp_path / "shocks.csv"
    path.write_text(
        "shock_id,event_id,driver,low,base,high,start_period,horizon,decay,source,rationale\n"
        "rp,,risk_premium,0,50,150,1,20,1.0,user,test\n"
    )

    @contextmanager
    def conn(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", conn)
    code = cli.main(["simulate", "--run-id", child, "--shocks", str(path), "--n", "10"])
    assert code == 1
    assert "FAILED (wacc_set_with_risk_premium_shock)" in capsys.readouterr().out
