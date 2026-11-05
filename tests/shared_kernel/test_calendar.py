import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from domains.news import gdelt
from shared_kernel import calendar

ROOT = Path(__file__).resolve().parents[2]
RULE_NAMES = {"known_by", "CASE_TZ"}


def test_known_by_is_new_york_midnight_in_utc():
    assert calendar.known_by(date(2020, 6, 30)) == datetime(2020, 7, 1, 4, 0, tzinfo=UTC)  # EDT
    assert calendar.known_by(date(2020, 1, 15)) == datetime(2020, 1, 16, 5, 0, tzinfo=UTC)  # EST


def test_a_news_window_ends_when_the_case_day_ends():
    # the news window and the price and filing rules share one cut-off (backlog #112, #133)
    for as_of in (date(2020, 6, 30), date(2020, 1, 15)):
        assert gdelt.window_bounds(as_of)[1] == calendar.known_by(as_of)


def _source_files() -> list[Path]:
    files = [ROOT / "main.py"]
    for package in ("domains", "shared_kernel"):
        files += sorted((ROOT / package).rglob("*.py"))
    return files


def test_every_module_takes_the_day_end_rule_from_the_kernel():
    # backlog #119 removed the news adapter's re-export; #133 keeps it from coming back
    wrong = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module != "shared_kernel.calendar":
                names = {alias.name for alias in node.names} & RULE_NAMES
                if names:
                    wrong.append(f"{path.relative_to(ROOT)}:{node.lineno} from {node.module}")
            if (
                isinstance(node, ast.Attribute)
                and node.attr in RULE_NAMES
                and not (isinstance(node.value, ast.Name) and node.value.id == "calendar")
            ):
                wrong.append(f"{path.relative_to(ROOT)}:{node.lineno} .{node.attr}")
    assert wrong == []


def test_the_scan_sees_the_kernel_and_its_users():
    files = {p.relative_to(ROOT).as_posix() for p in _source_files()}
    expected = {"shared_kernel/calendar.py", "domains/market/store.py", "domains/news/gdelt.py"}
    assert expected <= files


def test_the_last_ended_day_turns_at_new_york_midnight():
    # summer (EDT, UTC-4) and winter (EST, UTC-5)
    assert calendar.last_ended_day(datetime(2026, 7, 2, 3, 59, 59, tzinfo=UTC)) == date(2026, 6, 30)
    assert calendar.last_ended_day(datetime(2026, 7, 2, 4, 0, tzinfo=UTC)) == date(2026, 7, 1)
    assert calendar.last_ended_day(datetime(2026, 1, 16, 4, 59, 59, tzinfo=UTC)) == date(
        2026, 1, 14
    )
    assert calendar.last_ended_day(datetime(2026, 1, 16, 5, 0, tzinfo=UTC)) == date(2026, 1, 15)


def test_the_last_ended_day_across_both_clock_changes():
    # 2026-03-08 and 2026-11-01 are the US clock changes; midnight after them is 04:00 and 05:00 UTC
    assert calendar.last_ended_day(datetime(2026, 3, 9, 3, 59, tzinfo=UTC)) == date(2026, 3, 7)
    assert calendar.last_ended_day(datetime(2026, 3, 9, 4, 0, tzinfo=UTC)) == date(2026, 3, 8)
    assert calendar.last_ended_day(datetime(2026, 11, 2, 4, 59, tzinfo=UTC)) == date(2026, 10, 31)
    assert calendar.last_ended_day(datetime(2026, 11, 2, 5, 0, tzinfo=UTC)) == date(2026, 11, 1)


def test_the_last_ended_day_has_ended_and_the_next_has_not():
    now = datetime(2025, 12, 31, 0, 17, tzinfo=UTC)
    while now < datetime(2027, 1, 2, tzinfo=UTC):
        day = calendar.last_ended_day(now)
        assert calendar.known_by(day) <= now < calendar.known_by(day + timedelta(days=1))
        now += timedelta(hours=7, minutes=13)


def test_the_last_ended_day_needs_a_time_zone():
    with pytest.raises(ValueError):
        calendar.last_ended_day(datetime(2026, 7, 2, 12, 0))
