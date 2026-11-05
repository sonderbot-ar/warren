"""The question reader's prompt, its model interface and its runner (F2 Step 3, part 2).

No model runs here: a fake backend stands in, so these tests check the plumbing and the rules
around the model, not its score. The score is recorded from a real run in
`docs/designs/f2-web-app.md`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from webapp.reader import model as reader
from webapp.reader import prompt
from webapp.reader import run as runner
from webapp.reader import score as scoring
from webapp.reader.reading import INPUTS, KINDS, OUT_OF_SCOPE, Reading, check, normalise, tickers

TODAY = date(2026, 11, 4)
ROWS = scoring.load_set()


class Fake:
    name = "fake"

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def complete(self, system, user, schema):
        self.calls.append((system, user, schema))
        answer = self.answers(user) if callable(self.answers) else self.answers
        if isinstance(answer, Exception):
            raise answer
        return answer


# --- the exam does not leak into the prompt -----------------------------------------------


def _grams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = normalise(text).split()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def test_the_prompt_quotes_no_question_of_the_set():
    """No question of the set, nor any run of five of its words, is in the prompt (Step 3:
    the set is the reader's exam; Dwork et al. 2015)."""
    text = prompt.system_prompt()
    prompt_grams = _grams(text)
    for row in ROWS:
        assert normalise(row["text"]) not in normalise(text), row["id"]
        shared = _grams(row["text"]) & prompt_grams
        assert not shared, (row["id"], shared)


def test_the_examples_pass_the_code_check_unchanged():
    for question, partial in prompt.EXAMPLES:
        answer = prompt._example_answer(partial)
        checked = check(Reading.from_dict(answer), question, TODAY)
        assert not checked.unsure, (question, checked.dropped)
        assert checked.kind == answer["kind"]


def test_the_prompt_offers_exactly_the_vocabularies_the_check_accepts():
    schema = prompt.answer_schema()
    props = schema["properties"]
    assert props["kind"]["enum"] == list(KINDS)
    assert props["companies"]["items"]["enum"] == list(tickers())
    assert props["inputs"]["items"]["properties"]["name"]["enum"] == list(INPUTS)
    assert [v for v in props["out_of_scope"]["enum"] if v] == list(OUT_OF_SCOPE)
    assert set(prompt.INPUT_MEANINGS) == set(INPUTS)
    assert set(prompt.COMPANY_NAMES) == set(tickers())
    text = prompt.system_prompt()
    for name in (*INPUTS, *tickers(), *OUT_OF_SCOPE):
        assert name in text


def test_the_prompt_asks_for_no_number():
    rules = prompt.RULES.lower()
    assert "never compute" in rules and "copy" in rules


# --- the reader ---------------------------------------------------------------------------


def test_a_good_answer_is_checked_and_returned():
    answer = {
        "kind": "cambio_de_supuesto",
        "out_of_scope": None,
        "companies": ["AAPL"],
        "period": None,
        "as_of": None,
        "inputs": [
            {"name": "beta", "how": "set", "direction": None, "value_text": "1,3", "via": None}
        ],
        "unsure": False,
    }
    fake = Fake(json.dumps(answer))
    reading = reader.read_question("¿Y si la beta de Apple fuera 1,3?", TODAY, fake)
    assert reading.kind == "cambio_de_supuesto" and not reading.unsure
    assert reading.inputs[0].value_text == "1,3"
    system, user, schema = fake.calls[0]
    assert system == prompt.system_prompt() and "beta de Apple" in user
    assert schema == prompt.answer_schema()


def test_a_value_the_question_never_wrote_is_dropped():
    answer = {
        "kind": "cambio_de_supuesto",
        "companies": ["AAPL"],
        "inputs": [{"name": "beta", "how": "set", "value_text": "1.5"}],
    }
    reading = reader.read_question("¿Y si sube la beta de Apple?", TODAY, Fake(json.dumps(answer)))
    assert reading.unsure and reading.inputs[0].value_text is None


@pytest.mark.parametrize(
    "answer",
    [OSError("connection refused"), TimeoutError(), "not json", "[1, 2]", ""],
)
def test_a_reader_that_cannot_answer_gives_an_unsure_empty_reading(answer):
    reading = reader.read_question("¿Cuánto vendió Apple?", TODAY, Fake(answer))
    assert reading.unsure and reading.kind == "" and reading.dropped == ("reader",)


def test_an_empty_think_block_before_the_answer_is_tolerated():
    raw = '<think>\n\n</think>\n{"kind": "dato", "companies": ["KO"]}'
    assert reader.parse_answer(raw) == {"kind": "dato", "companies": ["KO"]}


def test_ollama_backend_sends_the_schema_and_temperature_zero(monkeypatch):
    sent = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"message": {"content": '{"kind": "dato"}'}}).encode()

    def fake_urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr(reader.urllib.request, "urlopen", fake_urlopen)
    out = reader.OllamaBackend(model="qwen3:8b").complete("S", "U", {"type": "object"})
    assert out == '{"kind": "dato"}'
    assert sent["url"] == "http://127.0.0.1:11434/api/chat"
    body = sent["body"]
    assert body["format"] == {"type": "object"} and body["think"] is False
    assert body["options"]["temperature"] == 0 and body["options"]["seed"] == reader.SEED


# --- the runner and the scorer ------------------------------------------------------------


def test_the_runner_writes_answers_the_scorer_reads(tmp_path):
    """The labels themselves, sent through the runner, score 100% and clear the bar."""
    by_text = {f"Question: {row['text']}\nAnswer:": row["expected"] for row in ROWS}
    fake = Fake(lambda user: json.dumps(by_text[user]))
    out = tmp_path / "answers.jsonl"
    runner.run(fake, ROWS, out, {"backend": "fake"}, log=open("/dev/null", "w"))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"meta": {"backend": "fake"}}
    assert len(lines) == len(ROWS) + 1
    assert scoring.main(["--answers", str(out), "--today", TODAY.isoformat()]) == 0


def test_an_unanswered_question_is_stored_as_null_and_scored_unsure(tmp_path):
    out = tmp_path / "answers.jsonl"
    runner.run(Fake(OSError()), ROWS[:3], out, {}, log=open("/dev/null", "w"))
    answers = [json.loads(line) for line in out.read_text().splitlines()[1:]]
    assert all(a["reading"] is None for a in answers)
    report = scoring.score(ROWS[:3], {a["id"]: a["reading"] for a in answers}, TODAY)
    assert report["overall"]["unsure"] == 1.0 and report["overall"]["right"] == 0.0


def test_prompt_hash_changes_with_the_prompt(monkeypatch):
    before = runner.prompt_sha256()
    monkeypatch.setattr(prompt, "RULES", prompt.RULES + " ")
    monkeypatch.setattr(runner, "system_prompt", prompt.system_prompt)
    assert runner.prompt_sha256() != before


# --- the recorded runs (nov.05.2026) ------------------------------------------------------

RUNS = scoring.LABELLED_SET.parent / "runs"
RECORDED = {  # file: (model sha256 prefix, questions fully right, clears the bar)
    "2026-11-05-qwen3-4b-q4km.jsonl": ("7485fe6f", 140, False),
    "2026-11-05-qwen3-8b-q4km.jsonl": ("d98cdcbd", 161, False),
}
PROMPT_OF_THE_RUNS = "b29a95aafe5e8d100781b812bd033b9228812e8789b07d0e0be91c9b5d34548c"


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_a_recorded_run_reproduces_its_score(name):
    """The score in the design doc comes back from the stored answers, without the model."""
    lines = (RUNS / name).read_text(encoding="utf-8").splitlines()
    meta = json.loads(lines[0])["meta"]
    model_prefix, right, passes = RECORDED[name]
    assert meta["model"]["sha256"].startswith(model_prefix)
    assert meta["prompt_sha256"] == PROMPT_OF_THE_RUNS
    assert meta["set_sha256"] == hashlib.sha256(scoring.LABELLED_SET.read_bytes()).hexdigest()
    answers = {json.loads(x)["id"]: json.loads(x)["reading"] for x in lines[1:]}
    report = scoring.score(ROWS, answers, TODAY)
    assert sum(q["right"] for q in report["questions"]) == right
    assert report["passes"] is passes
