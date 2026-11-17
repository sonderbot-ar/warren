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
    # every first-party package; webapp joined after #133 (backlog #136)
    files = [ROOT / "main.py"]
    for package in ("domains", "shared_kernel", "webapp"):
        files += sorted((ROOT / package).rglob("*.py"))
    return files


KERNEL = "shared_kernel.calendar"


def _kernel_names(tree: ast.Module) -> set[str]:
    """Names the module binds to the kernel's calendar module, and only those (backlog #136)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "shared_kernel":
            names |= {a.asname or a.name for a in node.names if a.name == "calendar"}
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == KERNEL and a.asname:
                    names.add(a.asname)
    return names


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


def _wrong_uses(tree: ast.Module, where: str) -> list[str]:
    """Every place a module takes the day-end rule from anywhere but the kernel."""
    kernel = _kernel_names(tree) | {KERNEL}
    wrong = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module != KERNEL:
            names = {alias.name for alias in node.names} & RULE_NAMES
            if names:
                wrong.append(f"{where}:{node.lineno} from {node.module}")
        if (
            isinstance(node, ast.Attribute)
            and node.attr in RULE_NAMES
            and _dotted(node.value) not in kernel
        ):
            wrong.append(f"{where}:{node.lineno} .{node.attr}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in RULE_NAMES
            and _dotted(node.args[0]) not in kernel
        ):
            # a rule name by string; a name built at run time can't be read by a scan
            wrong.append(f"{where}:{node.lineno} getattr")
    return wrong


def _kernel_imports(tree: ast.Module) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == KERNEL
        and {alias.name for alias in node.names} & RULE_NAMES
    )


def test_every_module_takes_the_day_end_rule_from_the_kernel():
    # backlog #119 removed the news adapter's re-export; #133 keeps it from coming back
    wrong, kernel_imports = [], 0
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        wrong += _wrong_uses(tree, str(path.relative_to(ROOT)))
        kernel_imports += _kernel_imports(tree)
    assert wrong == []
    # the scan must have seen the rule's real users, not just read files (backlog #136)
    assert kernel_imports >= 1


@pytest.mark.parametrize(
    "source",
    [
        "from domains.news import gdelt as calendar\ncalendar.known_by(d)",
        "import domains.news.gdelt as calendar\ncalendar.CASE_TZ",
        "from domains.news import gdelt\ngdelt.known_by(d)",
        "from domains.news.gdelt import known_by",
        "from domains.news import gdelt\ngetattr(gdelt, 'known_by')(d)",
        "import calendar\ncalendar.known_by(d)",
    ],
)
def test_the_scan_catches_a_borrowed_rule(source):
    # mutation cases from the #135 gatekeeper review (backlog #136)
    assert _wrong_uses(ast.parse(source), "x.py") != []


@pytest.mark.parametrize(
    "source",
    [
        "from shared_kernel.calendar import known_by, CASE_TZ",
        "from shared_kernel import calendar\ncalendar.known_by(d)",
        "from shared_kernel import calendar as cal\ncal.CASE_TZ",
        "import shared_kernel.calendar\nshared_kernel.calendar.known_by(d)",
        "import shared_kernel.calendar as cal\ncal.known_by(d)",
        "from shared_kernel import calendar\ngetattr(calendar, 'known_by')(d)",
        "getattr(obj, 'other')",
    ],
)
def test_the_scan_passes_the_kernel(source):
    assert _wrong_uses(ast.parse(source), "x.py") == []


def test_the_scan_sees_the_kernel_and_its_users():
    files = {p.relative_to(ROOT).as_posix() for p in _source_files()}
    expected = {
        "shared_kernel/calendar.py",
        "domains/market/store.py",
        "domains/news/gdelt.py",
        "webapp/__main__.py",
    }
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


def test_case_today_turns_at_new_york_midnight():
    # backlog #163: the date in New York, for labels and bounds; a cut-off is the day before
    assert calendar.case_today(datetime(2026, 7, 2, 3, 59, tzinfo=UTC)) == date(2026, 7, 1)
    assert calendar.case_today(datetime(2026, 7, 2, 4, 0, tzinfo=UTC)) == date(2026, 7, 2)
    assert calendar.case_today(datetime(2026, 1, 16, 4, 59, tzinfo=UTC)) == date(2026, 1, 15)
    assert calendar.case_today(datetime(2026, 1, 16, 5, 0, tzinfo=UTC)) == date(2026, 1, 16)
    now = datetime(2026, 11, 2, 4, 59, tzinfo=UTC)
    assert calendar.last_ended_day(now) == calendar.case_today(now) - timedelta(days=1)


def test_case_today_needs_a_time_zone():
    with pytest.raises(ValueError):
        calendar.case_today(datetime(2026, 7, 2, 12, 0))


CLOCK_FILES = [
    "domains/analysis/__main__.py",
    "domains/analysis/math_engine.py",
    "domains/fundamentals/quality.py",
    "domains/evaluation/harness.py",
    "domains/evaluation/backtest_batch.py",
    "domains/evaluation/ranges.py",
    "domains/evaluation/__main__.py",
]


def _clock_files() -> list[Path]:
    return _source_files() + sorted((ROOT / "webapp").rglob("*.py"))


def _clock_names(tree: ast.Module) -> set[str]:
    """Every name the module binds to the `datetime` module or its `date` and `datetime` types."""
    names = {"date", "datetime"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name == "datetime"}
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            names |= {a.asname or a.name for a in node.names if a.name in {"date", "datetime"}}
    return names


def _is_clock(node: ast.expr, names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    return isinstance(node, ast.Attribute) and node.attr in {"date", "datetime"}


def _naive(call: ast.Call) -> bool:
    values = list(call.args) + [k.value for k in call.keywords]
    return not values or any(isinstance(v, ast.Constant) and v.value is None for v in values)


def _reads_the_machine(call: ast.Call, names: set[str]) -> bool:
    """`today()`, `utcnow()`, `utcfromtimestamp()` or a naive `now()` on a clock type."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and _is_clock(func.value, names)):
        return False
    return func.attr in {"today", "utcnow", "utcfromtimestamp"} or (
        func.attr == "now" and _naive(call)
    )


def test_no_module_reads_the_machines_date():
    # backlog #163: `today()`, `utcnow()` and a `now()` with no time zone on the clock types read
    # the machine's clock in its own zone; defaults go through `calendar.case_today` or
    # `calendar.last_ended_day`. Injected clocks (`deps.now()`) are not the machine's.
    wrong = []
    for path in _clock_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = _clock_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _reads_the_machine(node, names):
                wrong.append(f"{path.relative_to(ROOT)}:{node.lineno} .{node.func.attr}()")
    assert wrong == []


def test_the_clock_scan_catches_each_form():
    def caught(source: str) -> bool:
        tree = ast.parse(source)
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        return _reads_the_machine(call, _clock_names(tree))

    assert caught("from datetime import date\ndate.today()")
    assert caught("from datetime import date as d\nd.today()")
    assert caught("import datetime as dt\ndt.date.today()")
    assert caught("from datetime import datetime\ndatetime.now()")
    assert caught("from datetime import datetime\ndatetime.now(None)")
    assert caught("from datetime import datetime\ndatetime.now(tz=None)")
    assert caught("from datetime import datetime\ndatetime.utcnow()")
    assert caught("from datetime import datetime\ndatetime.utcfromtimestamp(0)")
    assert not caught("from datetime import UTC, datetime\ndatetime.now(UTC)")
    assert not caught("deps.now()")


def test_the_clock_scan_sees_the_modules_it_fixed_and_the_app():
    files = {p.relative_to(ROOT).as_posix() for p in _clock_files()}
    assert set(CLOCK_FILES) | {"shared_kernel/calendar.py", "webapp/app.py"} <= files
    for name in CLOCK_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "case_today" in text or "last_ended_day" in text, name
