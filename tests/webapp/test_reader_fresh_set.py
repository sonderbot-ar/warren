"""The fresh exam for prompt 3 (F2 Step 3 part 3, nov.07.2026).

The 204 questions of the labelled set were all read while the prompt was revised, so prompt 3
can only be judged on questions nobody had seen: about 200 written by the student-reviewer
after prompt 3 was committed, labelled under part 1's rules and frozen here before any model
read them (`docs/designs/f2-web-app.md`, "Step 3 results, part 3").
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date

import pytest

from webapp.reader import prompt
from webapp.reader import score as scoring
from webapp.reader.reading import KINDS, Reading, check, normalise

TODAY = date(2026, 11, 6)
FRESH = scoring.load_set(scoring.FRESH_SET)
OLD = scoring.load_set()

# Frozen before the run, like the labelled set: a label changed after it would bend the exam.
FRESH_SET_SHA256 = "a0129039c78d6d5f4307ab9fa575e515ba8ffef0ddd935ae43f03844d883c93d"


def test_the_fresh_labels_are_frozen():
    assert hashlib.sha256(scoring.FRESH_SET.read_bytes()).hexdigest() == FRESH_SET_SHA256


def test_about_200_questions_all_held_out():
    """The exam's size: 0 confidently wrong in 200 bounds the rate below 1.9% (Wilson), which
    a batch of 60 cannot (below 6%)."""
    assert len(FRESH) >= 200
    assert len({r["id"] for r in FRESH}) == len(FRESH)
    assert {r["source"] for r in FRESH} == {scoring.HELD_OUT_SOURCE}
    langs = Counter(r["lang"] for r in FRESH)
    assert set(langs) == {"es", "en"}
    assert 0.4 <= langs["es"] / len(FRESH) <= 0.6
    kinds = Counter(r["expected"]["kind"] for r in FRESH)
    assert set(kinds) == set(KINDS)
    assert all(n >= 10 for n in kinds.values()), kinds


def test_no_fresh_question_repeats_one_already_seen():
    seen = {normalise(r["text"]) for r in OLD}
    texts = [normalise(r["text"]) for r in FRESH]
    assert len(set(texts)) == len(texts)
    assert not seen & set(texts)


@pytest.mark.parametrize("row", FRESH, ids=[r["id"] for r in FRESH])
def test_every_fresh_label_passes_the_code_check(row):
    checked = check(Reading.from_dict(row["expected"]), row["text"], TODAY)
    assert checked.dropped == (), checked.dropped
    assert not checked.unsure


def test_the_prompt_quotes_no_fresh_question():
    """Prompt 3 was committed before the fresh set existed; this keeps it that way."""
    text = normalise(prompt.system_prompt())
    words = text.split()
    grams = {tuple(words[i : i + 5]) for i in range(len(words) - 4)}
    for row in FRESH:
        own = normalise(row["text"]).split()
        assert normalise(row["text"]) not in text, row["id"]
        assert not {tuple(own[i : i + 5]) for i in range(len(own) - 4)} & grams, row["id"]


def test_the_fresh_labels_score_perfectly_against_themselves():
    answers = {r["id"]: r["expected"] for r in FRESH}
    report = scoring.score(FRESH, answers, TODAY)
    assert report["passes"]
    assert report["held_out"]["n"] == len(FRESH)
