"""A teaching lesson per refusal group, and per code where the group's is not enough (backlog
#382): `text.REFUSAL_GROUP_LESSONS` covers every group in `coded.REFUSAL_GROUP_ORDER`,
`text.REFUSAL_LESSONS` covers the `inconsistent_data` codes and `erp_too_few_years`, and
`refusal_lesson` gives every coded refusal a lesson."""

import math
import re
import string

from domains.analysis.coded import ENGINE_REFUSAL_CODES, REFUSAL_GROUP_ORDER, REFUSAL_GROUPS
from domains.analysis.text import (
    REFUSAL_GROUP_LESSONS,
    REFUSAL_LESSONS,
    WARNING_LESSONS,
    Lesson,
    refusal_lesson,
)
from domains.market import erp

ALL = {**{f"group:{g}": lesson for g, lesson in REFUSAL_GROUP_LESSONS.items()}, **REFUSAL_LESSONS}


def test_every_group_has_a_lesson_in_screen_order():
    assert tuple(REFUSAL_GROUP_LESSONS) == REFUSAL_GROUP_ORDER
    for group, lesson in REFUSAL_GROUP_LESSONS.items():
        assert isinstance(lesson, Lesson) and lesson.group == group


def test_code_lessons_are_real_codes_in_their_own_group():
    assert set(REFUSAL_LESSONS) <= ENGINE_REFUSAL_CODES
    for code, lesson in REFUSAL_LESSONS.items():
        assert lesson.group == REFUSAL_GROUPS[code], code


def test_the_first_code_lessons_are_the_ones_the_issue_asks_for():
    inconsistent = {c for c, g in REFUSAL_GROUPS.items() if g == "inconsistent_data"}
    assert inconsistent <= set(REFUSAL_LESSONS)
    assert "erp_too_few_years" in REFUSAL_LESSONS


def test_every_coded_refusal_gets_a_lesson():
    for code in ENGINE_REFUSAL_CODES:
        lesson = refusal_lesson(code)
        expected = REFUSAL_LESSONS.get(code, REFUSAL_GROUP_LESSONS[REFUSAL_GROUPS[code]])
        assert lesson is expected, code
        assert lesson.group == REFUSAL_GROUPS[code], code


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?:\s|$)", text))


def test_lessons_are_plain_short_sentences_with_their_params():
    """A refusal lesson says the rule, why a real company or date hits it, and what to do next:
    up to three sentences (a run warning's has two), no code names, numbers from params."""
    for key, lesson in ALL.items():
        assert _placeholders(lesson.why) == set(lesson.params), key
        text = lesson.text()
        assert "{" not in text and "}" not in text, key
        assert "`" not in text and "_" not in text, key
        assert text.endswith(".") and 1 <= _sentences(text) <= 3, key
        assert all(isinstance(v, int | float) for v in lesson.params.values()), key
        assert not re.search(r"\d", lesson.why), f"{key}: a number not from params"


def test_every_lesson_has_a_reference_or_says_it_is_a_warren_rule():
    for key, lesson in ALL.items():
        assert lesson.reference or lesson.warren_rule, key
        for field in (lesson.reference, lesson.warren_rule):
            assert field is None or (field.strip() == field and not field.endswith(".")), key


def test_the_student_is_never_blamed_and_setup_says_so():
    """Brief, 'When an estimate can't be built': setup words never blame the student, and an
    inconsistent figure is the filing's line, not the company's fault."""
    assert "doesn't depend on the student" in REFUSAL_GROUP_LESSONS["setup"].why
    for key, lesson in ALL.items():
        assert "your fault" not in lesson.why and "you did" not in lesson.why, key


def test_inconsistent_data_lessons_send_the_student_to_the_report():
    for lesson in (
        REFUSAL_GROUP_LESSONS["inconsistent_data"],
        *(REFUSAL_LESSONS[c] for c, g in REFUSAL_GROUPS.items() if g == "inconsistent_data"),
    ):
        assert "open the report" in lesson.why
        assert "Concepts Statement No. 8, chapter 4" in lesson.source() or "ASC 210-10-45-1" in (
            lesson.source()
        )
        # the engine's own words: "a tag picks up the wrong measure"; a lesson never says the
        # filing is wrong, since the printed report is usually right (analyst, professor)
        assert "almost" not in lesson.why and "the filing put" not in lesson.why
        assert "Warren read" in lesson.why


def test_the_erp_lesson_takes_its_numbers_from_the_engine_and_the_paper():
    """Professor (#376 review): a 10-year window's standard error is about 6 points,
    Damodaran's table: 20% over the square root of the years. The minimum is erp.MIN_YEARS,
    so a changed minimum changes the error the lesson shows."""
    lesson = REFUSAL_LESSONS["erp_too_few_years"]
    assert lesson.params["min_years"] == erp.MIN_YEARS
    assert lesson.params["sd"] == 0.2
    se = 0.2 / math.sqrt(erp.MIN_YEARS)
    assert lesson.params["se"] == round(se, 2)
    assert lesson.params["two_se"] == round(2 * se, 2)
    if erp.MIN_YEARS == 10:  # Damodaran (2022), Table 2: 20% / sqrt(10) = 6.32%
        assert "about 6 percentage points" in lesson.text()
        assert "13 points higher or lower" in lesson.text()
    assert "first date" in lesson.why  # erp_too_few_years carries first_as_of (#381)
    assert "Table 2" in lesson.reference and "working rule" in lesson.warren_rule
    assert str(erp.MIN_YEARS) in lesson.warren_rule


def test_the_no_value_lesson_covers_all_three_reasons():
    """no_base_value's reasons: growth not below the rate, a rate not above zero, a rate at or
    below -100% (dcf.py); the lesson names both conditions (professor, product lead)."""
    why = REFUSAL_GROUP_LESSONS["no_value"].why
    assert "above zero" in why and "growth stays below" in why


def test_refusal_and_warning_lessons_share_one_shape():
    assert not set(REFUSAL_LESSONS) & set(WARNING_LESSONS)
