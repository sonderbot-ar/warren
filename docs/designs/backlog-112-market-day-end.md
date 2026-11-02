# Backlog #112: prices are only used once their day has ended in New York

Issue: https://github.com/sonderbot-ar/warren/issues/112 · Branch `backlog-112-market-day-end` · Version v0.8.1 when merged.

## Problem

From the M7 PR review (#109, analyst and gatekeeper):

1. **A direct run can still read an intraday "close".** The pipeline (`domains/orchestration/nodes.py`, `load_market`) refuses a market download made before the as-of day ended in New York. But the rule every market query goes through, `domains/market/store.py` `require_coverage`, compares UTC calendar dates: a Yahoo download at 15:00 UTC on the as-of day passes, and its last row is a mid-session price. `python -m domains.analysis run` on the day itself reads it. That breaks the point-in-time rule in CLAUDE.md: the price was not final yet.
2. **The boundary is not tested.** The pipeline test uses 05:00 UTC the next day, which passes in both summer (EDT, midnight is 04:00 UTC) and winter (EST, 05:00 UTC). Nothing tests one second before and exactly at the cut-off.
3. **No failure test for the telemetry restore.** `shared_kernel/snapshot.py` raises a `SnapshotError` when the telemetry swap fails; no test reaches that branch.
4. **The strict cut-off is not written down.** The rule waits for New York midnight, not the 16:00 close, so a run just after the close downloads again (or refuses offline).

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. One day-end rule for every source.** Move `known_by` and `CASE_TZ` from `domains/news/gdelt.py` into a new `shared_kernel/calendar.py`; `gdelt` imports them from there, so `gdelt.known_by` keeps working and no caller changes. The market layer must not import the news adapter (Decision 11, guardrail 1: a source's adapter is its own), so the rule moves to the kernel that both use. `require_coverage` then parses `fetched_at` as a UTC instant and refuses a download made before `known_by(as_of)`, with a message that says the as-of day had not ended in New York. The pipeline's own check stays (it also handles `--refresh`) and now agrees with the store by construction.

Tests: `tests/market/test_store_day_end.py` (new): a download at 15:00 UTC on the as-of day is refused; in summer (2020-06-30, EDT) a download at 03:59:59 UTC the next day is refused and one at 04:00:00 is used; in winter (2020-01-15, EST) 04:59:59 is refused and 05:00:00 is used; a download dated days later is used. `tests/shared_kernel/test_calendar.py`: `known_by` in both seasons, and `gdelt.known_by is calendar.known_by`. The pipeline test gets the same two boundary cases. Exit: the store tests fail on the old code; full suite green.

**Step 2. Telemetry restore failure test and the doc line.** Mirror `test_a_failed_raw_move_keeps_the_old_raw_files_and_says_so` for telemetry: a half-done move that then fails raises `SnapshotError` ("telemetry files were not"), the old telemetry file is still there, the database is the new one and nothing is left in temporary folders. Add one line to `docs/designs/m7-orchestration.md` (Data freshness): the cut-off is New York midnight, not the 16:00 close, so a run between the close and midnight downloads again, or refuses with `--offline`. Exit: suite green.

**Step 3. Real-data check.** On the restored snapshot: `python -m domains.analysis reproduce --all` and `python -m domains.evaluation reproduce --batch eval_2026-11-02_1 --guidance domains/evaluation/guidance.csv` still pass, because every stored download was made days or years after its as-of date. Exit: same counts as before the change.

## Alternatives considered

- *Use the 16:00 close (or 20:00 UTC) as the cut-off.* Rejected for now: Yahoo's daily row can be revised after the close (late prints, and the adjusted close on dividend days), and one cut-off shared with news and filings is simpler to teach and test. The cost is one extra download for a run made between 16:00 and midnight.
- *Import `gdelt.known_by` into the market store.* Rejected: it would make the price layer depend on the news adapter.
- *Compare against the last row's date instead of the fetch time.* Rejected in M7 already: weekends, holidays and late series (DGS10) would force a download on every run.

No design decision changes. No number changes: every stored run's downloads were made well after its as-of date.

## Files

`shared_kernel/calendar.py` (new), `domains/news/gdelt.py`, `domains/market/store.py`, `tests/market/test_store_day_end.py` (new), `tests/shared_kernel/test_calendar.py` (new), `tests/orchestration/test_nodes.py`, `tests/shared_kernel/test_snapshot.py`, `docs/designs/m7-orchestration.md`, `docs/versions.md`, `docs/build-plan.md`.

## Review log

Design review not run: the issue is the reviewers' own four-point fix list, with no financial logic. Gatekeeper at the PR stage.

## Where the work stopped

- Steps 0–3 done (nov.02.2026). 659 tests pass; the five new store tests fail on the old code. On the restored snapshot (`warren-20261102T002927Z`): 27 of 27 runs reproduce to the cent, the M8 batch reproduces (728 rows, 39 simulations), and `require_coverage` accepts every stored download for all 27 stored as-of dates (270 checks, 0 refused). PR open; gatekeeper next.
