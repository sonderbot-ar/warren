"""The grid driver (M10 Step 2): order, resume, the spending cap and failures, with a fake graph."""

from datetime import UTC, date, datetime

import pytest

from domains.evaluation import grid_run
from domains.evaluation.cases import Case
from domains.evaluation.harness import case_seed
from domains.llm import calls
from domains.orchestration.graph import Outcome

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def case(ticker, day, post=False):
    return Case(f"{ticker}_{day}", ticker, date.fromisoformat(day), "grid", "Grid date: no event",
                4, "grid rule: post-cutoff 1st/15th" if post else "grid rule: mid-quarter 15th",
                "", "")  # fmt: skip


CASES = [
    case("AAA", "2025-11-15"),
    case("BBB", "2025-11-15"),
    case("AAA", "2026-08-15", post=True),
    case("BBB", "2026-08-15", post=True),
    case("AAA", "2026-05-15"),
]


class FakeGraph:
    """Writes a pipeline row and one Sonnet call of `tokens` input tokens per started case."""

    def __init__(self, conn, tokens=10_000, fail=(), budget_on=()):
        self.conn, self.tokens, self.fail, self.budget_on = conn, tokens, set(fail), set(budget_on)
        self.started, self.resumed, self.seeds = [], [], {}

    def _row(self, pid, ticker, as_of, status):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO pipeline_runs (pipeline_id, ticker, as_of, variants, "
                "review, seed, n_samples, status, telemetry_path, code_version, started_at) "
                "VALUES (?, ?, ?, 'named,masked', 'auto', 1, 100, ?, 't', 'c', ?)",
                (pid, ticker, as_of, status, NOW.strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            self.conn.execute(
                "INSERT INTO llm_calls (batch_id, node, model, prompt_name, prompt_version, "
                "prompt_sha256, ref, attempt, input_json, status, input_tokens, output_tokens, "
                "created_at) VALUES (?, 'propose_shocks', 'claude-sonnet-5-5', 'p', 1, 'x', 'r', "
                "1, '{}', 'ok', ?, 0, ?)",
                (pid, self.tokens, NOW.strftime("%Y-%m-%dT%H:%M:%SZ")),
            )

    def start(self, ticker, as_of, seed, budget):
        cid = f"{ticker}_{as_of}"
        self.started.append(cid)
        self.seeds[cid] = seed
        pid = f"{cid}_p1"
        if cid in self.budget_on:
            self._row(pid, ticker, as_of.isoformat(), "failed")
            return Outcome(pid, "failed", None, error=calls.BudgetSpent("spent"))
        if cid in self.fail:
            self._row(pid, ticker, as_of.isoformat(), "failed")
            return Outcome(pid, "failed", None, error=RuntimeError("engine said no"))
        self._row(pid, ticker, as_of.isoformat(), "done")
        return Outcome(pid, "done", None)

    def resume(self, pipeline_id, budget):
        self.resumed.append(pipeline_id)
        ticker, as_of, _ = pipeline_id.split("_")
        self._row(pipeline_id, ticker, as_of, "done")
        return Outcome(pipeline_id, "done", None)


def run(conn, fake, max_usd=10.0):
    return grid_run.run_grid(conn, CASES, max_usd, fake.start, fake.resume, now=lambda: NOW,
                             log=lambda _: None)  # fmt: skip


def test_post_cutoff_dates_run_first_then_the_newest_pre_cutoff(company):
    fake = FakeGraph(company)
    summary = run(company, fake)
    assert fake.started == ["AAA_2026-08-15", "BBB_2026-08-15", "AAA_2026-05-15",
                            "AAA_2025-11-15", "BBB_2025-11-15"]  # fmt: skip
    assert summary.done == fake.started and not summary.failed and summary.stopped is None
    assert fake.seeds["AAA_2026-05-15"] == case_seed("AAA_2026-05-15")


def test_a_done_case_is_skipped_and_a_failed_one_resumed(company):
    fake = FakeGraph(company, fail={"AAA_2026-05-15"})
    first = run(company, fake)
    assert first.failed == {"AAA_2026-05-15": "engine said no"}
    assert len(first.done) == 4  # the failure didn't stop the rest
    again = FakeGraph(company)
    second = run(company, again)
    assert again.started == [] and again.resumed == ["AAA_2026-05-15_p1"]
    assert second.done == ["AAA_2026-05-15"] and len(second.done_before) == 4


def test_the_cap_stops_cleanly_before_a_case_could_pass_it(company):
    # each case costs 100,000 Sonnet input tokens = $0.20; cap $1.00 with a $0.50 reserve:
    # after 3 cases $0.60 is spent and 0.60 + 0.50 > 1.00, so the 4th is not started
    fake = FakeGraph(company, tokens=100_000)
    summary = run(company, fake, max_usd=1.00)
    assert len(fake.started) == 3
    assert summary.spent_usd == pytest.approx(0.60)
    assert summary.not_run == ["AAA_2025-11-15", "BBB_2025-11-15"]
    assert summary.stopped.startswith("cap: $0.60 spent of $1.00")
    # a later run with more room picks up where it stopped
    more = FakeGraph(company, tokens=100_000)
    assert run(company, more, max_usd=5.0).done == ["AAA_2025-11-15", "BBB_2025-11-15"]


def test_calls_made_before_the_run_started_do_not_count(company):
    with company:
        company.execute(
            "INSERT INTO llm_calls (batch_id, node, model, prompt_name, prompt_version, "
            "prompt_sha256, ref, attempt, input_json, status, input_tokens, output_tokens, "
            "created_at) VALUES ('old', 'propose_shocks', 'claude-sonnet-5-5', 'p', 1, 'x', 'r', "
            "1, '{}', 'ok', 50000000, 0, '2026-11-01T00:00:00Z')"
        )
    summary = run(company, FakeGraph(company, tokens=0), max_usd=1.0)
    assert summary.spent_usd == 0 and len(summary.done) == 5


def test_a_spent_token_budget_stops_the_run(company):
    fake = FakeGraph(company, budget_on={"BBB_2026-08-15"})
    summary = run(company, fake)
    assert summary.stopped == "token budget spent on BBB_2026-08-15"
    assert summary.not_run == ["AAA_2026-05-15", "AAA_2025-11-15", "BBB_2025-11-15"]


def test_a_model_without_a_price_is_refused(company):
    with company:
        company.execute(
            "INSERT INTO llm_calls (batch_id, node, model, prompt_name, prompt_version, "
            "prompt_sha256, ref, attempt, input_json, status, input_tokens, output_tokens, "
            "created_at) VALUES ('x', 'n', 'mystery-model', 'p', 1, 'x', 'r', 1, '{}', 'ok', 1, "
            "1, '2026-11-20T12:00:00Z')"
        )
    with pytest.raises(grid_run.GridRunError, match="no price for model 'mystery-model'"):
        run(company, FakeGraph(company))


def test_every_configured_model_has_a_price():
    from shared_kernel.config import NODE_MODELS

    assert {m.model for m in NODE_MODELS.values()} <= set(grid_run.PRICES_USD_PER_MTOK)


def test_since_counts_what_an_earlier_run_spent(company):
    with company:
        company.execute(
            "INSERT INTO llm_calls (batch_id, node, model, prompt_name, prompt_version, "
            "prompt_sha256, ref, attempt, input_json, status, input_tokens, output_tokens, "
            "created_at) VALUES ('first', 'propose_shocks', 'claude-sonnet-5-5', 'p', 1, 'x', "
            "'r', 1, '{}', 'ok', 300000, 0, '2026-11-20T09:00:00Z')"
        )  # $0.60 spent by a run that started at 09:00 and was cut off
    fake = FakeGraph(company, tokens=0)
    summary = grid_run.run_grid(company, CASES, 1.0, fake.start, fake.resume, now=lambda: NOW,
                                log=lambda _: None, since="2026-11-20T09:00:00Z")  # fmt: skip
    assert summary.spent_usd == pytest.approx(0.60)
    assert summary.stopped.startswith("cap: $0.60 spent of $1.00") and fake.started == []
