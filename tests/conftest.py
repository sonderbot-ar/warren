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


@pytest.fixture(autouse=True)
def _no_kept_track_record():
    """Every test starts and ends without the track-record rows a process keeps (backlog #477
    item 2), so a test that patches how ranges are built never meets rows another one kept."""
    from domains.evaluation.run_ranges import forget_kept_rows

    forget_kept_rows()
    yield
    forget_kept_rows()


@pytest.fixture
def unlinked_xom():
    """Exxon as it was before backlog #573: its successor's filings not read, so a date from
    `history_ends` on warns (`beyond_history`). Patched in the shared list, so every module that
    imported PHASE1_UNIVERSE sees it."""
    from dataclasses import replace

    from domains.fundamentals.universe import PHASE1_UNIVERSE

    i = next(i for i, c in enumerate(PHASE1_UNIVERSE) if c.ticker == "XOM")
    linked = PHASE1_UNIVERSE[i]
    PHASE1_UNIVERSE[i] = replace(linked, successor_linked=False)
    try:
        yield PHASE1_UNIVERSE[i]
    finally:
        PHASE1_UNIVERSE[i] = linked
