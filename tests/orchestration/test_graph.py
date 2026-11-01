"""The graph end to end on Test Corp with the model stubbed (M7 Steps 3 and 4): checkpoints,
resume after a failure, the review pause, and the report."""

import json

import pytest

from domains.orchestration import graph, nodes, report, text
from tests.analysis.conftest import AS_OF


@pytest.fixture
def folders(tmp_path):
    return graph.Folders(reports=tmp_path / "reports", telemetry=tmp_path / "telemetry")


def go(world, folders, **kwargs):
    kwargs = {"seed": 7, "n_samples": 200, "review": "auto"} | kwargs
    return graph.start(world.deps(), folders, "TST", AS_OF, **kwargs)


def lines(folders, pid):
    path = folders.telemetry / f"{pid}.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_the_graph_runs_end_to_end_with_a_checkpoint_and_two_lines_per_node(world, folders):
    out = go(world, folders)
    assert out.status == "done", out.error
    s = out.state
    assert s.sim["named"] is not None and s.report_path
    row = world.conn.execute("SELECT * FROM pipeline_runs WHERE pipeline_id = ?",
                             (out.pipeline_id,)).fetchone()  # fmt: skip
    assert row["status"] == "done" and row["finished_at"] and row["run_id"] == s.run_id
    events = lines(folders, out.pipeline_id)
    assert [e["node"] for e in events[::2]] == list(graph.NODE_ORDER)
    assert {e["status"] for e in events[1::2]} == {"ok"}
    llm = {e["node"]: e["llm"] for e in events if e["status"] == "ok" and e["llm"]}
    assert llm["extract_events"][0]["calls"] == 1 and llm["propose_shocks"][0]["calls"] == 1
    steps = graph.history(world.conn, folders, out.pipeline_id)
    assert [node for _, node, _ in steps] == list(graph.NODE_ORDER)
    assert dict((n, c) for _, n, c in steps)["build_baseline"] == [
        "baseline_reused", "baseline_value_per_share", "run_id"]  # fmt: skip


def test_the_graph_gives_the_numbers_the_nodes_give_by_hand(world, folders):
    out = go(world, folders)
    by_hand = out.state.model_copy(update=nodes.simulate(out.state, world.deps()))
    assert by_hand.sim == out.state.sim  # the stored simulation, the same seed and shocks
    vps = world.conn.execute(
        "SELECT p50 FROM simulation_outputs WHERE sim_id = ? AND name = 'value_per_share'",
        (out.state.sim["named"].sim_id,),
    ).fetchone()[0]
    assert vps == out.state.sim["named"].p50


def test_a_failed_node_is_resumed_without_running_the_nodes_before_it(world, folders, monkeypatch):
    real = nodes.simulate
    calls = {"n": 0}

    def flaky(state, deps):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full\nmore detail")
        return real(state, deps)

    monkeypatch.setattr(nodes, "simulate", flaky)
    out = go(world, folders)
    assert out.status == "failed" and "disk full" in str(out.error)
    status = world.conn.execute("SELECT status FROM pipeline_runs").fetchone()[0]
    assert status == "failed"
    assert lines(folders, out.pipeline_id)[-1] == lines(folders, out.pipeline_id)[-1] | {
        "status": "error", "error": "RuntimeError: disk full"}  # fmt: skip
    again = graph.resume(world.deps(), folders, out.pipeline_id)
    assert again.status == "done" and again.state.sim["named"] is not None
    started = [e["node"] for e in lines(folders, out.pipeline_id) if e["status"] == "started"]
    assert started.count("simulate") == 2
    assert all(started.count(n) == 1 for n in graph.NODE_ORDER if n != "simulate")
    assert graph.resume(world.deps(), folders, out.pipeline_id).status == "done"  # nothing left


def test_later_pauses_with_the_state_saved_and_resume_applies_the_answers(world, folders):
    out = go(world, folders, review="later")
    assert out.status == "waiting_review"
    [proposal] = out.waiting["proposals"]["named"]
    assert proposal["driver"] == "revenue_growth" and out.waiting["problem"] is None
    status = world.conn.execute("SELECT status FROM pipeline_runs").fetchone()[0]
    assert status == "waiting_review"
    assert world.conn.execute("SELECT COUNT(*) FROM proposal_shocks").fetchone()[0] == 0
    # asking again without answers changes nothing
    assert graph.resume(world.deps(), folders, out.pipeline_id).status == "waiting_review"
    pid = proposal["proposal_id"]
    edit = {pid: {"action": "edit", "changes": {"base": -0.4, "low": -0.8, "high": -0.1}}}
    done = graph.resume(world.deps(), folders, out.pipeline_id, answers=edit)
    assert done.status == "done", done.error
    shock = world.conn.execute("SELECT * FROM shocks WHERE shock_id = ?", (f"llm:{pid}",))
    shock = shock.fetchone()
    assert shock["source"] == "user" and shock["base"] == -0.4
    reviewed = world.conn.execute("SELECT * FROM shock_proposals").fetchone()
    assert reviewed["status"] == "edited" and reviewed["reviewer"] == "owner"


def test_a_bad_batch_of_answers_writes_nothing_and_is_asked_again(world, folders):
    out = go(world, folders, review="later")
    pid = out.waiting["proposals"]["named"][0]["proposal_id"]
    for bad in ({}, {pid: {"action": "maybe"}}, {pid: {"action": "edit", "changes": {}}},
                {pid: {"action": "approve"}, 999: {"action": "approve"}},
                {pid: {"action": "edit", "changes": {"low": 5.0}}}):  # fmt: skip
        again = graph.resume(world.deps(), folders, out.pipeline_id, answers=bad)
        assert again.status == "waiting_review" and again.waiting["problem"], bad
        assert world.conn.execute("SELECT COUNT(*) FROM proposal_shocks").fetchone()[0] == 0
        assert world.conn.execute(
            "SELECT status FROM shock_proposals").fetchone()[0] == "proposed"  # fmt: skip
    reject = {pid: {"action": "reject", "reason": "already priced"}}
    done = graph.resume(world.deps(), folders, out.pipeline_id, answers=reject)
    assert done.status == "done" and done.state.sim == {"named": None}
    body = report.body(folders.reports / f"{out.pipeline_id}.md")
    assert text.NO_SHOCK_LINE.format(why=text.NO_SHOCK["rejected"]) in body


def test_the_report_has_every_section_and_renders_the_same_twice(world, folders):
    out = go(world, folders)
    path = folders.reports / f"{out.pipeline_id}.md"
    written = path.read_text()
    headings = ("## 1. Value per share", "## 2. Paths", "## 3. Shocks and their evidence",
                "## 4. News used", "## 5. Assumptions with sources", "## 6. Trace")  # fmt: skip
    for heading in headings:
        assert heading in written
    assert text.RANGE in written and "not a forecast of the share price" in written
    assert "Test Corp cuts its revenue outlook" in written  # the shock's evidence headline
    assert "auto_approved by none" in written
    final = graph.resume(world.deps(), folders, out.pipeline_id).state
    assert report.render(world.conn, final) == report.body(path)
    assert report.render(world.conn, final) == report.render(world.conn, final)
    assert written.index(text.TRACE_MARKER) > written.index("## 5.")


def test_a_manual_review_after_the_as_of_date_is_marked_as_hindsight(world, folders):
    out = go(world, folders, review="manual")
    pid = out.waiting["proposals"]["named"][0]["proposal_id"]
    done = graph.resume(world.deps(), folders, out.pipeline_id,
                        answers={pid: {"action": "approve"}})  # fmt: skip
    body = report.body(folders.reports / f"{out.pipeline_id}.md")
    assert done.status == "done" and "they may have known what happened next" in body


def test_a_second_pipeline_inherits_earlier_verdicts_and_says_so(world, folders):
    go(world, folders)
    world.now = world.now.replace(hour=23)
    second = go(world, folders, review="manual")
    assert second.status == "done"  # nothing left to review: no pause
    body = report.body(folders.reports / f"{second.pipeline_id}.md")
    assert "the earlier verdict stands" in body


def test_defaults_auto_for_old_dates_and_both_variants_for_eval_cases(world):
    from datetime import date

    assert graph.default_review(date(2020, 6, 30), date(2026, 11, 1)) == "auto"
    assert graph.default_review(date(2026, 10, 28), date(2026, 11, 1)) == "manual"
    assert graph.is_case("MSFT", date(2022, 6, 2)) and not graph.is_case("TST", AS_OF)


def test_tracing_to_an_outside_service_stops_the_start(world, folders, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(Exception, match="LANGSMITH_TRACING"):
        go(world, folders)
    assert world.conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] == 0
