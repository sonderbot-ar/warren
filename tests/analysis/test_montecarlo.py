"""Monte Carlo over shocks: sampling, storage, reproduce and the command line (M4 Step 3)."""

import sqlite3
from contextlib import contextmanager

import numpy as np
import pytest

from domains.analysis import __main__ as cli
from domains.analysis import dcf, montecarlo, sim_report
from domains.analysis.montecarlo import SimulationError
from domains.analysis.runs import run_baseline
from shared_kernel.database import apply_migrations
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
