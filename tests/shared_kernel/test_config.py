import pytest

from shared_kernel import config


def test_paths_resolve_under_project_root():
    for path in (config.DATA_DIR, config.DB_PATH, config.RAW_EDGAR_DIR, config.REPORTS_DIR):
        assert path.is_relative_to(config.PROJECT_ROOT)


def test_sec_user_agent_returns_configured_value(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", '"Jane Doe jane@example.com"')
    assert config.sec_user_agent() == "Jane Doe jane@example.com"


@pytest.mark.parametrize("value", ["", config.PLACEHOLDER_USER_AGENT, "Jane Doe"])
def test_sec_user_agent_rejects_missing_placeholder_or_emailless(monkeypatch, value):
    monkeypatch.setenv("SEC_USER_AGENT", value)
    with pytest.raises(config.ConfigError):
        config.sec_user_agent()


def test_anthropic_api_key_returns_configured_value(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", '"sk-test-123"')
    assert config.anthropic_api_key() == "sk-test-123"


def test_anthropic_api_key_missing_names_the_steps_not_the_value(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  ")
    with pytest.raises(config.ConfigError, match="ANTHROPIC_API_KEY") as err:
        config.anthropic_api_key()
    assert ".env" in str(err.value)


def test_every_llm_node_has_a_model():
    for node in ("extract_events", "check_headlines", "propose_shocks"):
        assert config.node_model(node).model.startswith("claude-")


def test_unknown_node_is_a_config_error():
    with pytest.raises(config.ConfigError, match="no model"):
        config.node_model("write_poetry")
