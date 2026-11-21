# Backlog #502: the diluted series' order, and a full-run test for a year with no annual count

Issue: https://github.com/sonderbot-ar/warren/issues/502 (items 1 and 2) · Branch `backlog-502-diluted-order` · Version v0.10.21 when merged.

Status: Done (nov.20.2026; v0.10.21, PR #504, merge `6ede725`, after CI green and a gatekeeper GO; #502 item 3 stays with the front-end team).

## Problem

The #501 gatekeeper (GO on backlog #481 part 2a, v0.10.20) left two non-blocking follow-ups on the `shares` card of `inputs_behind`:

1. **The quarterly series sorts on a string.** `single_values._shares` sorts the diluted points, gaps included, by `(fiscal_year, fiscal_period)`. That is right only while every period is spelled exactly `Q1`–`Q4`; a stray label (`FY`, `q1`, `Q5`) would be placed by its spelling, silently.
2. **The "no year count" gap is tested only in a unit test.** A fourth-quarter gap whose year has no annual count Warren can read (`annual_period` `None`; Exxon FY2009 and FY2010 on real data) is covered by `test_a_year_with_no_quarter_in_the_window_opens_no_gap`, which calls `_fourth_quarter_gaps` directly with stand-in facts. Nothing checks it through a real run and the whole card.

Item 3 of #502 (the Spanish entry for `no_fourth_quarter_count` in the app's catalogue) is front-end work and stays on the issue for the front-end team.

No number, note, code or field changes. The history is computed when an answer is read and never stored, so `reproduce` is untouched.

## Plan

**Step 0. This doc.** A two-item tidy-up with no output change; the design review is this doc and the gatekeeper on the PR (as for v0.10.18).

**Step 1. Sort on the quarter's number, and the full-run test.**
- `single_values._quarter_number(fiscal_period)`: 1–4 for `Q1`–`Q4`, `ValueError("not a fiscal quarter: …")` for anything else. `_shares` sorts on `(fiscal_year, _quarter_number(fiscal_period))`. The quarterly read (`facts._quarterly`) only ever yields `Q1`–`Q4`, so the guard never fires today; if a future reader change let another label through, the answer fails loudly instead of misplacing a point.
- Tests (`tests/analysis/test_single_values.py`):
  - `test_the_quarterly_series_sorts_on_the_quarters_number`: 1–4 for the four quarters; `FY`, `Q5`, `q1`, `H1` and the empty label are refused.
  - `test_a_year_whose_10k_count_is_not_read_gets_a_gap_without_a_year`: Test Corp with FY2017's year-long diluted count dropped from every filing, run end to end: no `FY2017` point in the yearly series, the `FY2017Q4` gap has `annual_period` `None`, no `period_end`, the "read no count" text and never "did not file"; FY2016, FY2018 and FY2019 keep their own year; FY2017's three quarters, the gap and FY2018Q1 sit in fiscal order.
  - Checked by mutation: sorting quarters in reverse fails both this test and the existing `test_diluted_counts_come_by_quarter_and_by_year_with_each_fourth_quarter_coded`.
- Exit: full suite, `ruff check` and `ruff format --check` green.

## Alternatives considered

- **Sort on `period_end`.** Gaps for a year with no annual count have no `period_end`, so they would need a stand-in date; the quarter number needs none.
- **Keep the string sort and only add a test.** The issue allows it, but a test only pins today's labels; the guard also refuses a future wrong one.
- **A test that feeds the history in reverse.** Tried and dropped: `diluted_facts` already sorts the reads by `period_end`, so reversed reads never reach the final sort and the test passed even with a broken key. It proved nothing.

## Files to change

`domains/analysis/single_values.py`, `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No output is added, renamed or removed; the `shares` card's series, points and order are the same on every run (brief Q3, value per share, unchanged). The Spanish catalogue entry for `no_fourth_quarter_count` (#502 item 3) is still the front-end team's.
