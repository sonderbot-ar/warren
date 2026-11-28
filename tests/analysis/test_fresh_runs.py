"""Fresh runs for dates whose newest baseline was read under older rules (backlog #626 item 1,
#485): which dates are stale, a new run for each, and nothing stored changes."""

from datetime import date

from domains.analysis.fresh_runs import StaleDate, refresh, stale_dates
from domains.analysis.reading_rules import READING_RULES_VERSION
from domains.analysis.runs import reproduce, run_baseline
from domains.analysis.single_values import cost_of_debt_notes
from domains.fundamentals.ingest import ingest_company
from domains.market.store import MarketDataError
from tests.analysis.conftest import AS_OF, CHOICES, companyfacts
from tests.fundamentals.conftest import FakeEdgar

OTHER_DAY = date(2020, 5, 29)


def build(conn, ticker, as_of):
    return run_baseline(conn, ticker, as_of, choices=CHOICES, today=AS_OF)


def age(conn, run_id, rules=None, map_sha=None):
    """Make a stored run look as if older code or another concept map had built it."""
    if map_sha is None:
        conn.execute("UPDATE runs SET reading_rules_version = ? WHERE run_id = ?", (rules, run_id))
    else:
        conn.execute("UPDATE runs SET concept_map_sha256 = ? WHERE run_id = ?", (map_sha, run_id))
    conn.commit()


def stored(conn, run_id):
    rows = conn.execute(
        "SELECT name, period, value FROM run_outputs WHERE run_id = ? ORDER BY name, period",
        (run_id,),
    ).fetchall()
    return [tuple(r) for r in rows]


def test_a_run_under_today_s_rules_is_not_stale(company):
    build(company, "TST", AS_OF)
    assert stale_dates(company) == []


def test_older_rules_unrecorded_rules_and_another_map_are_stale(company):
    a = build(company, "TST", AS_OF)
    b = build(company, "TST", OTHER_DAY)
    age(company, a, rules=READING_RULES_VERSION - 1)
    age(company, b, map_sha="0" * 64)
    got = stale_dates(company)
    assert [(s.as_of, s.run_id) for s in got] == [(OTHER_DAY, b), (AS_OF, a)]
    assert got[0].rules_version == READING_RULES_VERSION and not got[0].map_same
    assert got[0].reason == "another concept map"
    assert got[1].map_same and got[1].reason.startswith(
        f"reading rules v{READING_RULES_VERSION - 1}"
    )
    age(company, a, rules=None)
    assert stale_dates(company)[1].reason.startswith("reading rules not recorded")


def test_only_the_newest_baseline_of_a_date_counts(company):
    old = build(company, "TST", AS_OF)
    age(company, old, rules=READING_RULES_VERSION - 1)
    build(company, "TST", AS_OF)  # a newer run under today's rules: the date is fresh
    assert stale_dates(company) == []


def test_what_ifs_and_llm_runs_are_not_the_date_s_baseline(company):
    base = build(company, "TST", AS_OF)
    age(company, base, rules=READING_RULES_VERSION - 1)
    # a newer run holding an LLM-proposed row is not what the app shows, so the date stays stale
    newer = build(company, "TST", AS_OF)
    company.execute(
        "UPDATE assumptions SET source = 'llm_proposed' WHERE run_id = ? AND rowid = "
        "(SELECT MIN(rowid) FROM assumptions WHERE run_id = ?)",
        (newer, newer),
    )
    company.commit()
    assert [s.run_id for s in stale_dates(company)] == [base]


def test_tickers_filter(company):
    age(company, build(company, "TST", AS_OF), rules=None)
    assert len(stale_dates(company, ["tst"])) == 1
    assert stale_dates(company, ["MSFT"]) == []


def test_refresh_builds_a_new_run_and_changes_nothing_stored(company):
    old = build(company, "TST", AS_OF)
    age(company, old, rules=READING_RULES_VERSION - 1)
    before = stored(company, old)
    (done,) = refresh(company, stale_dates(company), build=build)
    assert done.error is None and done.run_id not in (None, old)
    assert done.stale.run_id == old
    assert stored(company, old) == before and reproduce(company, old).ok
    row = company.execute("SELECT * FROM runs WHERE run_id = ?", (done.run_id,)).fetchone()
    assert row["reading_rules_version"] == READING_RULES_VERSION and row["as_of"] == "2020-06-30"
    assert row["parent_run_id"] is None and row["seed"] is None
    assert stale_dates(company) == []  # the date's newest baseline is now today's reading


def test_a_fresh_run_carries_no_run_read_differently(company):
    old = build(company, "TST", AS_OF)
    company.execute(
        "UPDATE assumptions SET value = value + 0.01 WHERE run_id = ? AND name = 'cost_of_debt'",
        (old,),
    )
    age(company, old, rules=READING_RULES_VERSION - 1)
    codes = [n["code"] for n in cost_of_debt_notes(company, old).to_dict()["cell_notes"]]
    assert "run_read_differently" in codes
    (done,) = refresh(company, stale_dates(company), build=build)
    codes = [n["code"] for n in cost_of_debt_notes(company, done.run_id).to_dict()["cell_notes"]]
    assert "run_read_differently" not in codes


def test_a_failed_build_is_reported_and_the_rest_continue(company):
    a = StaleDate("TST", AS_OF, "x", None, True)
    b = StaleDate("TST", OTHER_DAY, "y", None, True)

    def flaky(conn, ticker, as_of):
        if as_of == AS_OF:
            raise MarketDataError("no price stored")
        return build(conn, ticker, as_of)

    first, second = refresh(company, [a, b], build=flaky)
    assert first.run_id is None and "no price stored" in first.error
    assert second.run_id and second.error is None


def test_a_fresh_run_reads_a_newer_ingest_but_nothing_filed_after_its_date(company):
    # professor review: the fresh run reads the newest ingest, cut by filing date at its as_of
    old = build(company, "TST", AS_OF)
    age(company, old, rules=READING_RULES_VERSION - 1)
    facts = companyfacts()
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        {"start": "2020-04-01", "end": "2020-06-30", "val": 999.0, "accn": "0000000123-20-000099",
         "fy": 2020, "fp": "Q2", "form": "10-Q", "filed": "2020-07-30"})  # fmt: skip
    client = FakeEdgar()
    client.facts = facts
    ingest_company(company, "TST", client=client)
    (done,) = refresh(company, stale_dates(company), build=build)
    ingests = company.execute(
        "SELECT run_id, ingest_run_id FROM runs WHERE run_id IN (?, ?)", (old, done.run_id)
    ).fetchall()
    by_run = {r["run_id"]: r["ingest_run_id"] for r in ingests}
    assert by_run[done.run_id] > by_run[old]  # the newer download
    assert stored(company, done.run_id) == stored(company, old)  # the later filing is not read
