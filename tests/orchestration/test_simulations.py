"""A run's simulations with their variant (backlog #201), on Test Corp with a fake model."""

import json

import pytest

from domains.analysis import montecarlo
from domains.analysis.coded import SIMULATION_NOTE_CODES
from domains.analysis.shocks import Shock
from domains.orchestration import __main__ as cli
from domains.orchestration import graph
from domains.orchestration.simulations import SimulationListError, run_simulations
from shared_kernel.database import get_db_connection
from tests.analysis.conftest import AS_OF


@pytest.fixture
def folders(tmp_path):
    return graph.Folders(reports=tmp_path / "reports", telemetry=tmp_path / "telemetry")


def both(world, folders):
    out = graph.start(world.deps(), folders, "TST", AS_OF, variants=["named", "masked"],
                      seed=7, n_samples=200, review="auto")  # fmt: skip
    assert out.status == "done", out.error
    return out.state


def manual(world, run_id, seed=11) -> str:
    shock = Shock(shock_id="m1", driver="operating_margin", low=-2.0, base=-1.0, high=0.0,
                  start_period=1, horizon=4, decay=1.0, source="user",
                  rationale="by hand")  # fmt: skip
    return montecarlo.save_simulation(world.conn, run_id, [shock], 200, seed)


def test_a_pipeline_with_both_variants_lists_masked_first_with_its_pipeline(world, folders):
    state = both(world, folders)
    sim_manual = manual(world, state.run_id)
    out = run_simulations(world.conn, state.run_id, folders=folders)
    assert [s.variant for s in out.simulations] == ["masked", "named", "none"]
    masked, named, by_hand = out.simulations
    assert masked.sim_id == state.sim["masked"].sim_id and named.sim_id == state.sim["named"].sim_id
    assert by_hand.sim_id == sim_manual and by_hand.pipelines == [] and by_hand.sources == ["user"]
    assert [p.pipeline_id for p in masked.pipelines] == [state.pipeline_id]
    assert masked.pipelines[0].variants == ["masked"] and masked.pipelines[0].status == "done"
    assert {p.variant for p in masked.proposal_sets} == {"masked"}
    assert masked.proposal_sets[0].set_id == state.proposal_set["masked"]
    assert all(s.primary for s in out.simulations) and not any(s.notes for s in out.simulations)
    assert masked.value_per_share["p50"] == state.sim["masked"].p50
    assert masked.reproduces is None and masked.seed == 7 and masked.n_samples == 200
    sets = {x.variant: x for x in out.proposal_sets}
    assert sets["masked"].sim_ids == [masked.sim_id] and sets["masked"].latest


def test_the_primary_is_the_finished_pipelines_then_the_newest(world, folders):
    state = both(world, folders)
    older = manual(world, state.run_id, seed=1)
    newer = manual(world, state.run_id, seed=2)
    nones = [s for s in run_simulations(world.conn, state.run_id, folders=folders).simulations
             if s.variant == "none"]  # fmt: skip
    assert [s.sim_id for s in nones] == [newer, older]
    assert [s.primary for s in nones] == [True, False]
    # a second masked simulation from the same shocks with another seed comes after the pipeline's
    shocks = montecarlo.load_simulation_shocks(world.conn, state.sim["masked"].sim_id)
    extra = montecarlo.save_simulation(world.conn, state.run_id, shocks, 200, 99)
    masked = [s for s in run_simulations(world.conn, state.run_id, folders=folders).simulations
              if s.variant == "masked"]  # fmt: skip
    assert [s.sim_id for s in masked] == [state.sim["masked"].sim_id, extra]
    assert masked[0].primary and not masked[1].primary


def test_sim10_sorts_before_sim2_newest_first(world, folders):
    state = both(world, folders)
    ids = [manual(world, state.run_id, seed=i) for i in range(10)]  # _sim3 to _sim12
    nones = [s.sim_id for s in run_simulations(world.conn, state.run_id, folders=folders)
             .simulations if s.variant == "none"]  # fmt: skip
    assert nones == ids[::-1] and nones[0].endswith("_sim12")


def test_a_pipeline_filing_under_the_wrong_variant_is_a_note(world, folders):
    state = both(world, folders)
    swapped = {"named": state.sim["masked"], "masked": state.sim["named"]}
    with graph.checkpointer(world.conn) as saver:
        app = graph.build(graph.nodes.Deps(conn=world.conn), folders, saver, state.pipeline_id)
        app.update_state(graph._config(state.pipeline_id), {"sim": swapped}, as_node="write_report")
    out = run_simulations(world.conn, state.run_id, folders=folders)
    codes = [n.code for s in out.simulations for n in s.notes]
    assert codes == ["pipeline_variant_differs", "pipeline_variant_differs"]
    note = out.simulations[0].notes[0]
    assert note.params == {"pipeline_id": state.pipeline_id, "filed": "named", "traced": "masked"}
    assert set(codes) <= SIMULATION_NOTE_CODES


def test_an_ai_id_on_a_hand_made_shock_does_not_trace(world, folders):
    state = both(world, folders)
    own = world.conn.execute("SELECT shock_id FROM proposal_shocks").fetchone()[0]
    fake = Shock(shock_id=own, driver="capex_intensity", low=0.0, base=0.5, high=1.0,
                 start_period=1, horizon=2, decay=1.0, source="user",
                 rationale="typed")  # fmt: skip
    sim_id = montecarlo.save_simulation(world.conn, state.run_id, [fake], 200, 5)
    sim = next(s for s in run_simulations(world.conn, state.run_id, folders=folders).simulations
               if s.sim_id == sim_id)  # fmt: skip
    assert sim.variant == "none" and sim.proposal_sets == []
    assert [(n.code, n.params) for n in sim.notes] == [("shock_not_traced", {"shock_id": own})]


def test_check_reproduces_each_and_a_changed_output_fails(world, folders):
    state = both(world, folders)
    out = run_simulations(world.conn, state.run_id, check=True, folders=folders)
    assert out.checked and [s.reproduces for s in out.simulations] == [True, True]
    world.conn.execute("UPDATE simulation_outputs SET p50 = p50 + 1 WHERE sim_id = ? AND "
                       "name = 'value_per_share'", (state.sim["named"].sim_id,))  # fmt: skip
    world.conn.commit()
    out = run_simulations(world.conn, state.run_id, check=True, folders=folders)
    named = next(s for s in out.simulations if s.variant == "named")
    assert named.reproduces is False and any("value_per_share" in m for m in named.mismatches)


def test_unknown_run_raises_and_a_run_without_simulations_is_empty(world, folders):
    with pytest.raises(SimulationListError):
        run_simulations(world.conn, "NOPE_1", folders=folders)
    state = both(world, folders)
    world.conn.execute("DELETE FROM simulation_outputs")
    world.conn.execute("DELETE FROM simulation_shocks")
    world.conn.execute("DELETE FROM simulations")
    world.conn.commit()
    out = run_simulations(world.conn, state.run_id, folders=folders)
    assert out.simulations == [] and {x.variant for x in out.proposal_sets} == {"named", "masked"}


def test_pipeline_filter_keeps_its_own_and_refuses_another_run(world, folders):
    state = both(world, folders)
    manual(world, state.run_id)
    out = run_simulations(world.conn, state.run_id, pipeline_id=state.pipeline_id, folders=folders)
    assert [s.variant for s in out.simulations] == ["masked", "named"]
    assert {x.set_id for x in out.proposal_sets} == set(state.proposal_set.values())
    with pytest.raises(SimulationListError):
        run_simulations(world.conn, state.run_id, pipeline_id="OTHER_p1", folders=folders)


def test_backtest_rows_with_the_same_seed_and_variant_are_named(world, folders):
    state = both(world, folders)
    world.conn.execute("PRAGMA foreign_keys = OFF")
    world.conn.execute(
        "INSERT INTO eval_results (batch_id, case_id, run_id, variant, item, period, horizon, "
        "forecast, status, seed) VALUES ('eval_x', 'c', ?, 'llm_masked', 'revenue', 'FY2020Q3', "
        "1, 1.0, 'missing', 7)",
        (state.run_id,),
    )
    world.conn.commit()
    sims = run_simulations(world.conn, state.run_id, folders=folders).simulations
    assert [s.backtests for s in sims] == [["eval_x"], []]


KEYS = {"run_id", "ticker", "as_of", "checked", "pipeline_id", "simulations", "proposal_sets"}
SIM_KEYS = {"sim_id", "created_at", "seed", "n_samples", "code_version", "currency", "variant",
            "shocks", "sources", "proposal_sets", "pipelines", "backtests", "value_per_share",
            "primary", "reproduces", "mismatches", "notes"}  # fmt: skip
SET_KEYS = {"set_id", "variant", "case_id", "status", "no_impact", "proposals", "sim_ids",
            "latest"}  # fmt: skip


def test_the_command_prints_and_its_json_keys_are_fixed(world, db_path, tmp_path, monkeypatch,
                                                        capsys):  # fmt: skip
    folders = graph.Folders(tmp_path / "reports", tmp_path / "tel")
    state = both(world, folders)
    monkeypatch.setattr(cli, "get_db_connection",
                        lambda path=None: get_db_connection(path or db_path))  # fmt: skip
    monkeypatch.setattr(cli, "FOLDERS", folders)
    assert cli.main(["simulations", "--run-id", state.run_id, "--check"]) == 0
    text = capsys.readouterr().out
    assert text.index("masked") < text.index("named") and "OK" in text
    assert cli.main(["simulations", "--run-id", state.run_id, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == KEYS and set(data["simulations"][0]) == SIM_KEYS
    assert set(data["proposal_sets"][0]) == SET_KEYS
    assert cli.main(["simulations", "--run-id", "NOPE_1"]) == 2
