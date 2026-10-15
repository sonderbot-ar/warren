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
