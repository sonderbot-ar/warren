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
from tests.analysis.test_dcf import rows
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
    assert "shocked p10" in out
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
