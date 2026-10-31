import pytest


@pytest.fixture
def db_path(tmp_path):
    """Path to a fresh, not-yet-created SQLite file, isolated per test."""
    return tmp_path / "test_warren.db"


@pytest.fixture(autouse=True)
def _no_real_anthropic_settings(monkeypatch):
    """No test sees a real key or endpoint, whichever name it is under (backlog #95): a test that
    needs one sets it, and an assertion can never print the owner's key."""
    for name in (
        "WARREN_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
        "WARREN_ANTHROPIC_BASE_URL",
        "ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
