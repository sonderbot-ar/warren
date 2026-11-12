"""A teaching lesson per run-warning code (backlog #197): `text.WARNING_LESSONS` covers every
code the engine emits, sorts each into a known group, and takes its thresholds from the
engine's own constants."""

import re
import string

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


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?:\s|$)", text))


def test_lessons_are_one_or_two_plain_sentences_with_their_params():
    for code, lesson in WARNING_LESSONS.items():
        assert _placeholders(lesson.why) == set(lesson.params), code
        text = lesson.text()
        assert "{" not in text and "}" not in text, code
        assert "`" not in text and "_" not in text, code  # no code names for a student
        assert text.endswith(".") and 1 <= _sentences(text) <= 2, code
        assert all(isinstance(v, int | float) for v in lesson.params.values()), code


def test_every_lesson_has_a_reference_or_says_it_is_a_warren_rule():
    for code, lesson in WARNING_LESSONS.items():
        assert lesson.reference or lesson.warren_rule, code
        for field in (lesson.reference, lesson.warren_rule):
            assert field is None or (field.strip() == field and not field.endswith(".")), code
        assert lesson.source() == "; ".join(s for s in (lesson.reference, lesson.warren_rule) if s)


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


THRESHOLDS = {
    "fundamentals_stale": {"days": math_engine.STALE_AFTER.days},
    "shares_cover_differs": {"tolerance": math_engine.SHARES_TOLERANCE},
    "cost_of_debt_out_of_bounds": dict(
        zip(("low", "high"), math_engine.COST_OF_DEBT_BOUNDS, strict=True)
    ),
    "tax_rate_clipped": dict(zip(("low", "high"), math_engine.TAX_RATE_BOUNDS, strict=True)),
    "margin_outside_history": {
        "sigmas": math_engine.MARGIN_SIGMAS,
        "quarters": math_engine.HISTORY_QUARTERS,
    },
    "thin_terminal_spread": {"spread": math_engine.TERMINAL_SPREAD_WARNING},
    "thin_terminal_spread_at_erp_bound": {"spread": math_engine.TERMINAL_SPREAD_WARNING},
}


def test_thresholds_are_the_engines_and_marked_as_warren_rules():
    """A changed threshold changes the lesson's params, and the Warren rule that names it must
    follow; a Warren threshold is never passed off as a textbook law."""
    for code, lesson in WARNING_LESSONS.items():
        assert lesson.params == THRESHOLDS.get(code, {}), code
    for code, params in THRESHOLDS.items():
        lesson = WARNING_LESSONS[code]
        shown = {f"{v * 100:g}" if isinstance(v, float) else str(v) for v in params.values()}
        assert shown <= _numbers(lesson.text()), code
        assert "working rule" in lesson.warren_rule, code
        assert shown <= _numbers(lesson.warren_rule), code


def test_text_shows_a_fraction_times_100_and_a_count_as_is():
    lesson = Lesson("data", "{a}% and {b} days.", {"a": 0.125, "b": 135}, "ref", None)
    assert lesson.text() == "12.5% and 135 days."
