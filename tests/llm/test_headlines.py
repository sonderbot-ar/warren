"""The about-the-company check scored against labelled headlines (M6 Step 4)."""

import re

from domains.llm import headlines
from domains.llm.client import FakeClient
from tests.news.test_store import conn  # noqa: F401 - the conn fixture

D = headlines.RULE_DRAW


def row(n, label, method="org_exact", second="-", ticker="MSFT", draw=D):
    return {"draw": draw, "ticker": ticker, "method": method, "article_id": f"a{n}",
            "title": f"Microsoft headline {n}", "label": label, "second_label": second}  # fmt: skip


# six org_exact rows (4 about) and two dropped rows (1 about); the model keeps a1, a2, a3, a5
ROWS = [row(1, "about"), row(2, "about"), row(3, "related"), row(4, "about", second="about"),
        row(5, "about", second="not"), row(6, "not"),
        row(7, "about", "org_exact_dropped"), row(8, "not", "org_exact_dropped")]  # fmt: skip
ANSWERS = {("MSFT", f"a{n}"): n in (1, 2, 3, 5, 7, 8) for n in range(1, 9)}


def test_precision_and_recall_by_hand():
    first = {r["ticker"]: r for r in headlines.score(ROWS, ANSWERS) if r["labeller"] == "first"}
    msft = first["MSFT"]
    assert (msft["rule_precision"]["k"], msft["rule_precision"]["n"]) == (4, 6)
    assert (msft["model_precision"]["k"], msft["model_precision"]["n"]) == (3, 4)
    assert (msft["recall"]["k"], msft["recall"]["n"]) == (3, 4)
    assert (msft["dropped_called_about"], msft["dropped_called_about_labelled_about"]) == (2, 1)
    assert first["all"]["model_precision"] == msft["model_precision"]


def test_both_labellers_are_reported_on_the_rows_each_labelled():
    second = [r for r in headlines.score(ROWS, ANSWERS) if r["labeller"] == "second"]
    msft = next(r for r in second if r["ticker"] == "MSFT")
    assert msft["rule_precision"]["n"] == 2  # a4 and a5 carry a second label
    assert (msft["model_precision"]["k"], msft["model_precision"]["n"]) == (0, 1)  # a5: not


def test_other_draws_and_unanswered_rows_are_left_out():
    rows = ROWS + [row(9, "about", draw="20261030")]
    answers = dict(ANSWERS)
    del answers[("MSFT", "a6")]
    first = next(r for r in headlines.score(rows, answers) if r["ticker"] == "MSFT")
    assert first["rule_precision"]["n"] == 5


def respond(system, user):
    ids = re.findall(r"^(h\d+) \|", user, re.MULTILINE)
    return {"headlines": [{"id": i, "about": True} for i in ids]}


def test_labels_are_never_in_a_prompt_and_a_rerun_asks_nothing(conn):  # noqa: F811
    rows = [row(n, "about") | {"title": f"Microsoft story {n}", "reason": "SECRET"}
            for n in range(1, 26)]  # fmt: skip
    client = FakeClient(respond)
    assert headlines.check_headlines(conn, client, rows) == (25, 0)
    assert len(client.requests) == 2  # batches of 20 and 5
    for r in client.requests:
        assert "about" not in r["user"].split("Headlines")[1] and "SECRET" not in r["user"]
    assert len(headlines.stored_answers(conn)) == 25
    again = FakeClient(respond)
    assert headlines.check_headlines(conn, again, rows) == (0, 0) and again.requests == []


def test_a_rejected_batch_is_skipped_and_asked_again(conn):  # noqa: F811
    rows = [row(n, "about") for n in range(1, 26)]
    first = FakeClient(lambda system, user: "not json" if "h6 |" in user else respond(system, user))
    assert headlines.check_headlines(conn, first, rows) == (5, 1)  # the 20-headline batch fails
    assert len(headlines.stored_answers(conn)) == 5
    again = FakeClient(respond)
    assert headlines.check_headlines(conn, again, rows) == (20, 0)
    assert len(again.requests) == 1 and len(headlines.stored_answers(conn)) == 25
