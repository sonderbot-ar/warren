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
  - `math_engine.rounding_note(fact, balance_date, used_for, assumptions=None) -> Coded | None`: `None` unless `fact.canonical_name == "debt_current"` and `fact.rounded_plain is not None`. Params as today (`period_end`, `debt_current`, `debt_current_plain`, `rounding_unit`, `rounding_margin`, `gap`, `currency`, `accession_no`), plus `balance_date` (the date whose debt the figure is counted in), `used_for` (`balance_sheet`, `cost_of_debt_average` or `net_debt`; anything else raises), `fiscal_year` for `cost_of_debt_average`, and, when given, `assumptions` (the run rows whose side panel repeats the note). When `period_end < balance_date` the text adds "(carried forward to the {balance_date} balance sheet)"; for `cost_of_debt_average` it adds "(a year end of the average debt behind the FY{fiscal_year} cost of debt)".
  - `_balance` calls it with `balance_date`, `balance_sheet` and `["debt", "nwc_pct"]`. **Changed after the analyst (item 5):** the balance sheet's note listed `cost_of_debt` though the cost of debt reads only fiscal year ends (`_cost_of_debt`, `debt_parts(history.year(...))`), so on a quarter-end run it pointed at a row the figure does not feed. It now gains `cost_of_debt` only when a year end of the average is the same figure (Step 2).
  - Lesson (`text.py`): "…matches how the company stated its long-term debt on the same balance sheet date (also with leases)." (professor: "on that date" had nothing to refer to), and "The data Warren reads does not say how much a figure was rounded" in place of "The filing does not say" (professor: the XBRL filing carries `decimals`; the company-facts data Warren reads drops it). Two sentences, same params (none), group, reference and rule line. This is the analyst's first option on PR #457 ("say 'at that date'"); see Alternatives for why the note is not dropped.
  - Tests (`tests/analysis/test_current_lease_debt.py`, fixture `rounded_presentation(200e6, 195e6)`: every plain current portion 200M, every lease-inclusive one 195M, unit 10^8, margin 50M): the existing note test gains `balance_date == period_end`, `used_for` and no "carried forward"; its `assumptions` become `["debt", "nwc_pct"]` (the run's balance date, 2020-03-31, is a quarter end); a carried case (no current portion at 2020-03-31, so 2019-12-31 is carried) gives `period_end` 2019-12-31, `balance_date` 2020-03-31 and the clause; an unknown `used_for` raises. `tests/analysis/test_warning_lessons.py`: the lesson holds both new phrases.
  - Exit: full suite, `ruff check .`, `ruff format --check .` clean.

- **Step 2. The note on the cost of debt's year ends.**
  - `_cost_of_debt` (`_year_end_rounding_notes`): for the year it uses (after the `average <= 0` skip), each counted current portion in `start_used` and `end_used` (the facts `debt_parts` counted, so one left out by #408 or replaced by #415 never gets one) that carries `rounded_plain` gives a note with `used_for` `cost_of_debt_average`, its `fiscal_year`, `assumptions` `["cost_of_debt"]` and `balance_date` equal to the fact's own `period_end` (a year's facts are its fiscal-year facts; analyst item 3). When the balance sheet's note names the same fact (same `period_end` and `accession_no`), that note gains `cost_of_debt` (between `debt` and `nwc_pct`) instead of a second note.
  - Tests: on the rounded fixture the run carries one balance-sheet note and two `cost_of_debt_average` notes, FY t−1 and FY t of the cost of debt's method, each with `["cost_of_debt"]`, `balance_date == period_end` and no "carried forward"; a direct test of the same-figure case (the balance note gains `cost_of_debt` once, a different year end still gets its own note); none when the lease figure is above (210M) or outside the margin (140M).
  - Exit: as Step 1.

- **Step 3. The note on the reported view's net debt.**
  - `reported.py`, `net_debt`: after the #408, #412 and #415 notes, a `Coded` `debt_current_within_rounding` from `rounding_note(fact, day, "net_debt")` for the current portion in `debt_parts`' `used` list (analyst item 1: `get("debt_current")` can still return a figure #408 left out), with `day` the period's balance date and no `assumptions`, as the other reported debt notes.
  - Tests (`tests/analysis/test_current_lease_debt.py`, the rounded fixture, period FY2020Q1): the reported `net_debt` carries one note, `used_for` `net_debt`, no `assumptions`, `period_end` = `balance_date` = 2020-03-31; none at 210M or 140M.
  - Exit: as Step 1.

- **Step 4. Real data.** On the restored snapshot: count facts carrying `rounded_plain` in `get_facts` reads of `debt_current` and `debt_noncurrent` for every company, 16 as-of dates (each June 1 from 2012 to 2026, and 2026-11-17), both modes and all three frequencies (analyst item 6: zero notes alone cannot tell "nothing tripped" from "wired wrong"); every stored run's (ticker, date) built fresh; the reported `net_debt` of each company's fiscal years and second quarters FY2010–FY2025; `python -m domains.analysis reproduce --all`. Expected: zero everywhere, and reproduce matches.

## Alternatives considered

- **Emit the note only when the current portion is dated at the balance date (analyst's second option).** Rejected: a carried figure is still counted, and still chosen by the rounding guess; hiding the note would hide the guess. The `carried_forward` note already says it is carried; this note now names both dates.
- **One note per run, listing every date.** Rejected: each note keeps one figure with one filing to open, as the #408, #412 and #415 notes do; a run with the margin deciding at three dates is rare enough that three short notes read better than one list.
- **A note on the cost of debt even when the balance-sheet note names the same fact.** Rejected: it would repeat the same figure and filing on the `cost_of_debt` row, which the balance note's `assumptions` already reaches.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/reported.py`, `domains/analysis/text.py`, `tests/analysis/test_current_lease_debt.py`, `tests/analysis/test_warning_lessons.py`, this doc; after merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

- **Serves:** brief Q1 and Q2 (the reported `net_debt`, group 2 of a figure's notes), Q3, Q4, Q5 and Q8 (the "Los datos de partida" notes and the side panel of `cost_of_debt`).
- **Added:** params `balance_date` and `used_for` on `debt_current_within_rounding` everywhere, and `fiscal_year` when `used_for` is `cost_of_debt_average`; the note on the reported `net_debt`; a run note per fiscal year end of the cost of debt's average debt.
- **Changed:** the balance sheet's note lists `["debt", "nwc_pct"]`, plus `cost_of_debt` only when a year end of the average is the same figure (it listed `cost_of_debt` always). The English lesson says "stated … on the same balance sheet date" and "The data Warren reads does not say"; the English text adds the carried clause or the cost-of-debt clause. Nothing renamed or removed; no value moves; no stored run changes (none carries the note).
- **For the front-end (after the product lead's review):**
  1. Every form follows the convention of the other debt notes: once under "Los datos de partida", again in the side panel of each row in `assumptions`. A `cost_of_debt_average` note therefore shows under "Los datos de partida" and on the `cost_of_debt` row.
  2. Tell the forms apart by `used_for`, never by `assumptions`. For `cost_of_debt_average`, say which average it enters with `fiscal_year`, e.g. "Es uno de los dos cierres de año con que Warren promedia la deuda para el costo de la deuda del FY{fiscal_year}".
  3. When `period_end` < `balance_date` (only `balance_sheet` today), add a clause in the wording of the existing `carried_forward` note (professor item 4), e.g. "(se toma del balance del {period_end} para el del {balance_date})".
  4. On Q1 and Q2 the note goes last in group 2 of `net_debt`, after the #408 and #412 notes. It never appears with `debt_current_total_in_place` (#415 replaces the current portion the note is about) nor with `debt_current_inside_short_term` (#408 leaves it out); it can appear with `commercial_paper_beside_short_term`. A Q2 series gets no series note for it, as for #415 (brief line 169): each period's own note is enough.
  5. The lesson's Spanish may add "en la misma fecha de balance" and "los datos que lee Warren no dicen…".
  6. The brief's "no matching note yet (#451 item 5)" line can go.
  7. Sample params from the fixture, the four shapes (no real filing trips the margin, Step 4):
     - balance sheet: `{"period_end": "2020-03-31", "balance_date": "2020-03-31", "debt_current": 195000000.0, "debt_current_plain": 200000000.0, "rounding_unit": 100000000, "rounding_margin": 50000000.0, "gap": 5000000.0, "currency": "USD", "accession_no": "0000000123-20-000016", "used_for": "balance_sheet", "assumptions": ["debt", "nwc_pct"]}`
     - carried: the same with `"period_end": "2019-12-31"` and `"balance_date": "2020-03-31"`.
     - cost of debt: `{"period_end": "2019-12-31", "balance_date": "2019-12-31", …, "used_for": "cost_of_debt_average", "fiscal_year": 2019, "assumptions": ["cost_of_debt"]}`
     - reported net debt: `{"period_end": "2020-03-31", "balance_date": "2020-03-31", …, "used_for": "net_debt"}` (no `assumptions`).
- **Breaks:** nothing stored. A screen that keyed the `cost_of_debt` row on the balance note's `assumptions` now sees `cost_of_debt` there only in the same-figure case; no stored or fresh run carries the note today.

## Review notes

Design review, nov.18.2026:

- **Explainer: GAPS.** Restated the design correctly. Taken: the Step 2 test count against the dedupe rule (now spelled out: the fixture's balance date is a quarter end, so two year-end notes plus the balance note; the same-figure case has its own test), the fixture and test files named, `day` defined as the period's balance date, the meaning of `assumptions` stated. Not taken: definitions of the rounding unit, the margin and the note groups, which live in #427, #430 and the brief and are linked, not repeated.
- **Analyst: GO.** Taken: 1 (the reported note reads `debt_parts`' `used`, not `get`), 3 (`balance_date` is the fact's own date for a year end), 4 (notes only after the `average <= 0` skip), 5 (the balance note lists `cost_of_debt` only when the figure is a year end of the average), 6 (Step 4 counts the facts, not only the notes). 2 (two facts at one date from the quarterly and annual reads) is pinned by the same-figure test: a different filing gives a second note, which is right since it is a different figure's source.
- **Professor: GO.** Taken: 1 ("on the same balance sheet date"), 2 ("the data Warren reads"), 4 (the Spanish follows `carried_forward`'s wording). Not taken: 3 (the text already names the cost of debt and its year; the lesson already says the effect is small) and 5 (a worked example would break the lesson's two-sentence rule; the front-end may add one to the side panel, #451 item 4).
- **Product lead: CHANGES**, all taken: the display convention kept (1), `used_for` and `fiscal_year` added (2), no series note (3), the order and the notes it can't appear with (4), sample params (5).

## Results (Step 4, nov.18.2026)

On the restored snapshot `warren-20261117T154255Z` (schema 23; no ingest), read-only:

- 768 `get_facts` reads (8 companies × 16 dates × 2 modes × 3 frequencies): **0** facts carry `rounded_plain`.
- 899 of 899 stored runs' (ticker, date) built fresh: **0** rounding notes.
- 249 reported `net_debt` periods: **0** rounding notes.
- `python -m domains.analysis reproduce --all`: **903 of 903** stored runs reproduced to the cent.

## Left on #451

Items 2 (label tie from the fiscal year end), 3 (CAT's maturities tag), 4 (app number line, front-end), 6 (a unit test pinning the placed read against the quarterly path), 7 (FY and Q4 at two dates) and 8 (the 10^7 floor) stay open.
