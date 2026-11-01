"""M6 Step 8: the real client's request shape, efforts and cutoffs, and the stability check."""

from types import SimpleNamespace

import pytest

from domains.llm import calls, extract
from domains.llm.client import AnthropicClient, FakeClient
from domains.llm.taxonomy import load_event_types
from domains.news import matching
from shared_kernel import config
from tests.llm.test_extract import DAY, answer, story
from tests.news.test_store import conn  # noqa: F401 - the conn fixture

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


class _Messages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            content=[
                SimpleNamespace(type="thinking"),
                SimpleNamespace(type="tool_use", input={"ok": True}),
            ],  # fmt: skip
        )


def _client():
    pytest.importorskip("anthropic")
    client = AnthropicClient("sk-test")
    client._client = SimpleNamespace(messages=_Messages())
    return client


def test_the_request_uses_no_forced_tool_and_no_temperature_and_sets_effort():
    # current models answer 400 to a forced tool choice or a temperature (M6 Step 8)
    client = _client()
    reply = client.call("claude-sonnet-5-5", "System.", "Question?", SCHEMA)
    sent = client._client.messages.kwargs
    assert sent["tool_choice"] == {"type": "auto"} and "temperature" not in sent
    assert sent["output_config"] == {"effort": "medium"}
    assert sent["system"].endswith(AnthropicClient.USE_TOOL)
    assert reply.raw_json == '{"ok": true}'  # the tool's input, past the thinking block


def test_an_answer_without_the_tool_comes_back_empty_so_it_is_retried():
    client = _client()
    messages = client._client.messages
    messages.create = lambda **kw: SimpleNamespace(
        model=kw["model"], usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        content=[SimpleNamespace(type="text", text="ok")],
    )  # fmt: skip
    assert client.call("claude-haiku-5-5", "S", "U", SCHEMA).raw_json == ""


def test_each_node_has_an_effort_and_a_cutoff_from_the_model_card():
    assert config.model_effort("claude-haiku-5-5") == "low"
    assert config.model_effort("claude-sonnet-5-5") == "medium"
    for node in ("extract_events", "check_headlines", "propose_shocks"):
        cutoff = config.node_model(node).training_cutoff
        assert cutoff is not None and cutoff.year == 2026  # Jun 2026, every case is earlier
    with pytest.raises(config.ConfigError):
        config.model_effort("claude-unknown")


def _cases(n=1):
    return [SimpleNamespace(case_id=f"MSFT_2022-06-0{2 + k}"[:15], ticker="MSFT",
                            event_date=DAY) for k in range(n)]  # fmt: skip


def _stability(conn, client, cases):  # noqa: F811
    aliases = matching.load_aliases(conn)
    rule = matching.load_headline_rule(conn, aliases)
    return extract.stability(conn, client, cases, aliases, rule, "test")


def test_stability_asks_three_times_and_stores_no_classification(conn):  # noqa: F811
    story(conn)
    client = FakeClient(answer())
    [row] = _stability(conn, client, _cases())
    assert row.types == ("guidance",) * 3 and row.same
    assert len(client.requests) == 3
    assert conn.execute("SELECT COUNT(*) FROM event_classifications").fetchone()[0] == 0
    refs = [r[0] for r in conn.execute("SELECT ref FROM llm_calls ORDER BY call_id")]
    assert refs == [f"{row.event_id}:stability:{k}" for k in (1, 2, 3)]


def test_a_changed_type_or_a_failed_run_is_not_the_same(conn):  # noqa: F811
    story(conn)
    kinds = iter(["guidance", "guidance", "litigation"])
    client = FakeClient(lambda s, u: answer(next(kinds))(s, u))
    [row] = _stability(conn, client, _cases())
    assert row.types == ("guidance", "guidance", "litigation") and not row.same
    assert not extract.Stability("c", "e", ("guidance", "failed", "guidance")).same


def test_cases_without_an_event_are_skipped(conn):  # noqa: F811
    assert _stability(conn, FakeClient([]), _cases()) == []  # no news stored


def test_the_taxonomy_goes_to_the_model_as_an_enum(conn):  # noqa: F811
    story(conn)
    client = FakeClient(answer())
    _stability(conn, client, _cases())
    types = list(load_event_types())
    for r in client.requests:
        assert r["schema"]["properties"]["event_type"]["enum"] == types
        assert "exactly as listed" in r["system"]
    # the schema the model sees is a copy; the Pydantic model's own schema is unchanged
    assert "enum" not in extract.EventClassification.model_json_schema()["properties"]["event_type"]


def test_choices_only_apply_to_a_top_level_string_field():
    schema = extract.EventClassification.model_json_schema()
    with pytest.raises(ValueError):
        calls.with_choices(schema, {"reasons": ["x"]})  # a list, not a string
    with pytest.raises(ValueError):
        calls.with_choices(schema, {"event_type": []})
    with pytest.raises(ValueError):
        calls.with_choices(schema, {"missing": ["x"]})
