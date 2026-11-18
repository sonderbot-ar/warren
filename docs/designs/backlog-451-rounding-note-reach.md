# Backlog #451: the rounding note wherever a rounding-chosen figure is counted

Issue: https://github.com/sonderbot-ar/warren/issues/451 (items 1 and 5 of the body and first comment, and the analyst's item on #455's PR #457) · Branch `backlog-451-rounding-note-reach`.

## Problem

Since v0.10.5 (#430) the run note `debt_current_within_rounding` says when Warren read a lease-inclusive current portion of long-term debt *below* a plain figure that looks rounded (`facts.current_on_noncurrent_basis`, `Fact.rounded_plain`). It is emitted from one place, `math_engine._balance`, for the balance sheet the run values from. Three gaps:

1. **The cost of debt's year ends (issue item 1, analyst).** `_cost_of_debt` averages debt at the ends of FY t and FY t−1 through `debt_parts(history.year(...))`. A rounding-chosen current portion at either date moves that average with no note. The effect is at most half a rounding unit (5M at the 10^7 floor), but the student is told nothing.
2. **The reported view's net debt (first comment, item 5, product lead).** `reported.py` computes `net_debt` for brief Q1 and Q2 through `debt_parts` too, and adds a `Coded` note for #408, #412 and #415, but not for #430. The brief says so ("The reported view's net debt (Q1, Q2) gets no matching note yet (#451 item 5)").
3. **A carried-forward current portion (analyst on PR #457).** The balance sheet's current portion is `history.latest_before("debt_current", balance_date)`, so it can be dated earlier than the balance sheet. The lesson's "matches how the company states its long-term debt (also with leases)" is true at the note's own `period_end`, where the merge compared the two tags with that date's long-term debt, not necessarily at the balance date. The note does not say which balance date it was carried to.

**On today's data nothing changes:** no filing in Warren's data trips the rounding margin (#427 survey, #430 Step 3), so no stored or fresh run, and no reported series, gains a note. No figure moves; this is about what a run *says*.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. One builder for the note, and the balance date in it.**
  - `math_engine.rounding_note(fact, balance_date, assumptions=None) -> Coded | None`: `None` unless `fact.canonical_name == "debt_current"` and `fact.rounded_plain is not None`. Params as today (`period_end`, `debt_current`, `debt_current_plain`, `rounding_unit`, `rounding_margin`, `gap`, `currency`, `accession_no`), plus `balance_date` (the date whose debt the figure is counted in) and, when given, `assumptions`. When `period_end < balance_date` the text adds "(carried forward to the {balance_date} balance sheet)".
  - `_balance` calls it with `balance_date` and `["debt", "cost_of_debt", "nwc_pct"]`: same note as before, plus the new param.
  - Lesson (`text.py`): "…matches how the company stated its long-term debt on that date (also with leases)." Two sentences, same params (none), group, reference and rule line. This is the analyst's first option ("say 'at that date'"); see Alternatives for why the note is not dropped.
  - Tests (`tests/analysis/test_current_lease_debt.py`): the existing note test gains `balance_date == period_end` and no "carried forward" in the text; a carried case (the fixture's last balance sheet without a current portion, so the earlier one is carried) gives `period_end < balance_date` and the clause; the lesson test holds "on that date".
  - Exit: full suite, `ruff check .`, `ruff format --check .` clean.

- **Step 2. The note on the cost of debt's year ends.**
  - `_cost_of_debt`: for the year it uses, each counted current portion in `end_used` and `start_used` that carries `rounded_plain` gives a note with `assumptions` `["cost_of_debt"]` and `balance_date` the fiscal year's end, unless the balance-sheet note already names the same fact (same `period_end` and `accession_no`), which already lists `cost_of_debt`. Only facts `debt_parts` counted are checked, so a current portion left out by #408 or replaced by #415 never gets one.
  - Tests: on the rounded fixture (every current portion 200M plain, 195M with leases) the run carries one balance-sheet note and one note per year end the cost of debt reads, each with `["cost_of_debt"]` and its year end's date; none when the lease figure is above, equal or outside the margin.
  - Exit: as Step 1.

- **Step 3. The note on the reported view's net debt.**
  - `reported.py`, `net_debt`: after the #408, #412 and #415 notes, a `Coded` `debt_current_within_rounding` from `rounding_note(fact, day)` for the counted current portion (no `assumptions`, as the other reported debt notes).
  - Tests (`tests/analysis/test_reported*.py` style, on the rounded fixture): the reported `net_debt` of a period carries the note with its params; none when the margin does not decide.
  - Exit: as Step 1.

- **Step 4. Real data.** On the restored snapshot, the reported `net_debt` of every company's fiscal years and every fresh run on the stored run dates carry no `debt_current_within_rounding` note (nothing trips the margin), and `python -m domains.analysis reproduce --all` matches. If the snapshot cannot be restored, the fixture tests stand and the PR says so.

## Alternatives considered

- **Emit the note only when the current portion is dated at the balance date (analyst's second option).** Rejected: a carried figure is still counted, and still chosen by the rounding guess; hiding the note would hide the guess. The `carried_forward` note already says it is carried; this note now names both dates.
- **One note per run, listing every date.** Rejected: each note keeps one figure with one filing to open, as the #408, #412 and #415 notes do; a run with the margin deciding at three dates is rare enough that three short notes read better than one list.
- **A note on the cost of debt even when the balance-sheet note names the same fact.** Rejected: it would repeat the same figure and filing on the `cost_of_debt` row, which the balance note's `assumptions` already reaches.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/reported.py`, `domains/analysis/text.py`, `tests/analysis/test_current_lease_debt.py`, `tests/analysis/test_warning_lessons.py`, this doc; after merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

- **Serves:** brief Q1 and Q2 (the reported `net_debt`, group 2 of a figure's notes), Q3, Q4, Q5 and Q8 (the "Los datos de partida" notes and the side panel of `cost_of_debt`).
- **Added:** param `balance_date` on `debt_current_within_rounding` (every place it appears); the note on the reported `net_debt`; the note on a run with `assumptions` `["cost_of_debt"]` alone, for a year end of the cost of debt.
- **Changed:** the English lesson says "stated … on that date"; the English text adds "(carried forward to the … balance sheet)" when the dates differ. Nothing renamed or removed; no value moves; no stored run changes (none carries the note).
- **For the front-end:** the brief's Spanish may add "en esa fecha" to the lesson; a carried note may say "(se arrastra al balance del {balance_date})"; a `cost_of_debt`-only note shows only on that row's side panel, naming the fiscal year end; on Q1 and Q2 the note goes last in group 2 of `net_debt`, after `debt_current_total_in_place`; the brief's "no matching note yet (#451 item 5)" line can go.
- **Breaks:** nothing.

## Left on #451

Items 2 (label tie from the fiscal year end), 3 (CAT's maturities tag), 4 (app number line, front-end), 6 (a unit test pinning the placed read against the quarterly path), 7 (FY and Q4 at two dates) and 8 (the 10^7 floor) stay open.
