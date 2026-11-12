"""A teaching lesson per run-warning code (backlog #197): `text.WARNING_LESSONS` covers every
code the engine emits, sorts each into a known group, and quotes the engine's own thresholds."""

import re

from domains.analysis import math_engine
from domains.analysis.coded import RUN_NOTE_CODES
from domains.analysis.text import WARNING_GROUPS, WARNING_LESSONS, Lesson


def test_every_coded_warning_has_a_lesson():
    # note_text is a stored line Warren could not code: free text has nothing to teach
    assert set(WARNING_LESSONS) == RUN_NOTE_CODES - {"note_text"}


def test_groups_are_known_and_in_reading_order():
    assert list(WARNING_GROUPS) == ["data", "assumption", "valuation"]
    assert all(isinstance(lesson, Lesson) for lesson in WARNING_LESSONS.values())
    assert {lesson.group for lesson in WARNING_LESSONS.values()} == set(WARNING_GROUPS)


def test_lessons_are_plain_sentences_about_the_code_not_one_run():
    for code, lesson in WARNING_LESSONS.items():
        for field in (lesson.why, lesson.source):
            assert field.strip() == field and field, code
            assert "{" not in field and "}" not in field, code  # no unfilled placeholder
            assert "`" not in field, code  # no code names for a student
            assert "_" not in field.replace("universe.csv", ""), code
        assert lesson.why.endswith("."), code
        assert not lesson.source.endswith("."), code


def test_each_warning_is_in_the_group_the_design_gives_it():
    groups = {code: lesson.group for code, lesson in WARNING_LESSONS.items()}
    assert groups["thin_terminal_spread"] == "valuation"
    assert groups["no_value_per_share"] == "valuation"
    assert groups["tax_rate_clipped"] == "assumption"
    assert groups["wacc_outside_its_parts"] == "assumption"
    assert groups["balance_counted_zero"] == "data"
    assert groups["run_mixes_meanings"] == "data"


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def test_lessons_quote_the_thresholds_the_engine_uses():
    """A changed threshold changes the lesson with it, and a Warren threshold is never passed
    off as a textbook law: the source calls it a working rule."""
    pct = lambda x: f"{x * 100:g}"  # noqa: E731
    expected = {
        "fundamentals_stale": {str(math_engine.STALE_AFTER.days)},
        "shares_cover_differs": {pct(math_engine.SHARES_TOLERANCE)},
        "cost_of_debt_out_of_bounds": {pct(b) for b in math_engine.COST_OF_DEBT_BOUNDS},
        "tax_rate_clipped": {pct(b) for b in math_engine.TAX_RATE_BOUNDS},
        "margin_outside_history": {
            str(math_engine.MARGIN_SIGMAS),
            str(math_engine.HISTORY_QUARTERS),
        },
        "thin_terminal_spread": {pct(math_engine.TERMINAL_SPREAD_WARNING)},
        "thin_terminal_spread_at_erp_bound": {pct(math_engine.TERMINAL_SPREAD_WARNING)},
    }
    for code, numbers in expected.items():
        lesson = WARNING_LESSONS[code]
        assert numbers <= _numbers(lesson.why), code
        assert "Warren working rule" in lesson.source, code
