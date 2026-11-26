# Backlog #499: the yield a book cost of debt is compared with, over the fiscal year itself

Issue: https://github.com/sonderbot-ar/warren/issues/499 (from the #498 gatekeeper) · Branch `backlog-499-yield-window` · Version v0.10.50 when merged.

Status: Done (v0.10.50, nov.26.2026; PR #600, merge `06e9ea6`, after CI green and a gatekeeper GO).

## Problem

The cost-of-debt chart (`inputs_behind`, `cost_of_debt_notes`) puts `below_risk_free` on a year whose book cost of debt (interest over average book debt) is below the 10-year Treasury yield. Every year other than the run's own is compared with the average yield over "that fiscal year" (`_below_risk_free` in `domains/analysis/single_values.py`). The #498 gatekeeper left four points:

1. **The window is not the fiscal year.** It is the 365 days ending on the year end (`period_end - 364` to `period_end`). A 53-week year (Apple's FY2023, Johnson & Johnson's FY2020) is 371 days, so its first week is left out; a 52-week year is 364 days, so one day of the year before is read (always a weekend for Apple and J&J, so no yield in practice); a leap year leaves out 1 January (a holiday). In real data the fix moves a handful of trading days: Apple FY2023 (26 to 30 September 2022), J&J FY2020 (30 December 2019 to 3 January 2020), Microsoft and P&G FY2020 (1 July 2019), Walmart FY2025 (1 February 2024) (analyst). The interest fact the point is built from already carries the year's own start (`period_start`).
2. **The yield download may not be the run's.** `Singles.pins()` pins the run's own download when it is still stored; when it is not, the read falls back to the newest download outright (`selected_fetch`), which `require_coverage` refuses if it was made before the date ended. The dates are still before the run's date, but the average may not be the one the run would have read, and nothing says so.
3. **A floored what-if on an old parent.** A parent run stored before sources were recorded gives a child with no sources (`whatif.py`, `parent_sources` empty), so a child whose cost of debt was floored at the risk-free rate gets no `floored_at_risk_free` note. Untested and undocumented.
4. **The used year shows two figures.** Already handled: `below_risk_free`'s `cost_of_debt` param on the used year is the run's own row, and `docs/team-sync.md` tells the app to show the param's figure (#498 entry). Nothing to build.

## Plan

**Step 0. This doc.**

**Step 1. The fiscal year's own window, with tests.**
- `_below_risk_free` takes the year's start: `period_start` of the interest fact the point was built from (`paid.facts[0]`). The window is `period_start` to `period_end`. When the fact has no start (never for a duration fact today), keep the 364-day fallback.
- Tests in `tests/analysis/test_single_values.py`:
  - the existing `test_a_book_cost_of_debt_below_the_yield_says_so` checks `risk_free_from` falls on or after the point's own year start (not `period_end - 364`).
  - new `test_the_year_average_yield_covers_a_53_week_year`, on Apple's FY2023 and J&J's FY2020 real dates with weekday yields, a higher level in the first week: the average and the observation count include the first week (both fail on `main`).
  - new `test_the_year_average_yield_reads_no_day_before_the_year`: a 52-week year on made-up weekday dates; a yield dated the day before its start is not read (fails on `main`).
- Exit: full suite, `ruff check`, `ruff format --check` green.

**Step 2. Say whether the yield download was the run's own, with tests.**
- `Singles` records which of the run's downloads it could pin (computed once per answer). The flag reads the yield's pin alone, never "any pin" (analyst). The `year_average_yield` variant of `below_risk_free` gains the param `yield_fetch_pinned` (bool): true when the run's own 10-year yield download was read, false when it is no longer stored and the newest covering download was read instead.
- Tests: the fixture run gives `yield_fetch_pinned: true`; with the run's yield download deleted, the same note gives `false` and still uses no date after the run's date; with the price download deleted and the yield kept, `true`.
- Exit: as Step 1.

**Step 3. Pin the old-parent case, with a test.**
- `_floored_note`'s docstring says a child of a parent stored before sources were recorded has no stored sources, so it gets no `floored_at_risk_free` note; the cell's value is still the floor (the child's own row).
- No note appears at all in that case (not a note with `book_year` null, which is for a parent whose sources name no interest filing).
- Test: a floored child whose parent's sources are deleted before the what-if shows the floor value in its cost-of-debt cell and no `floored_at_risk_free` note.
- Exit: as Step 1.

## Alternatives considered

- **Start the window at the previous fiscal year's end** (the issue's option). Same dates as `period_start` when the previous year was filed, but needs a second lookup and fails on the first year of a history; the interest fact's own start is already there.
- **Refuse the note when the yield download is not pinned.** Loses a true statement (the dates are still point-in-time); a flag is enough for the app to say "with a later download".
- **Rebuild sources for old parents** (#181 covers sources for older stored runs). Out of scope here.

## Files to change

`domains/analysis/single_values.py` (`_below_risk_free`, `_cost_of_debt_point`, `Singles`, `_floored_note` docstring), `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves Q5 (the inputs behind an answer, the cost-of-debt chart). `below_risk_free`'s `risk_free` and `risk_free_from` on non-used years can move slightly (a 53-week year now reads its first week; the yield average changes by a few hundredths of a point at most), so a borderline year can gain or lose the note. One param is added on the `year_average_yield` variant, `yield_fetch_pinned` (bool); nothing is renamed or removed. The app can keep its current wording; if it wants, it can add "con una descarga posterior de la tasa" when the flag is false. No stored run or reproduce check changes (the notes are read live, not stored).

## Review notes

Product lead (front-end): OK. Serves Q5; nothing changes or breaks; the brief's clause reads `{tasa_libre}` live from the param (brief.md, Q5). The app should word the flag when false: append ", calculada con una descarga de la tasa posterior a la del cálculo original." Taken: the team-sync entry names the param and says it is only on the `year_average_yield` variant.

Analyst: GO with changes. Taken: the 53-week companies are Apple and J&J, not Walmart and P&G; tests on Apple's and J&J's real dates (the 52-week "day before" case is a weekend in real data, so that test uses made-up dates and says so); the flag reads the yield's own pin, with the reverse test; the fallback wording; Step 3 says no note at all. Not taken here, with a reason: flag the price and index downloads too (they feed the price, beta and share series through the same `pins()`); that is a wider output change across several cells, so it is filed as its own backlog issue rather than grown into this item.

Real-data check (snapshot `warren-20261125T103202Z`, each company's newest stored run, 10 years of chart): 16 years carry the `year_average_yield` note (Caterpillar 2, Coca-Cola 5, Microsoft 3, P&G 6); every one has the same window start, average and count on `main` and here, and `yield_fetch_pinned` is true on all 16. Apple, J&J and Walmart have no year below the yield in those windows, so the 53-week fix changes no answer shown today; it matters when one of their week-years is below the yield.

Gatekeeper GO on PR #600: ruff clean, 2957 passed, 10 skipped; with `main`'s `single_values.py` six of the new tests fail (both 53-week cases, the no-day-before test, the three flag tests) and the floored-child test passes, as expected for a documenting step; the edited assertion (1 January instead of `period_end - 364`) is the same bound in a normal year and one day earlier in a leap year, a correction to the new definition, not a weakening. Non-blocking: on `main` the window tests fail on the new argument before the window itself (the 52-week test would still catch `main`'s window); `p.period_start` would be a tighter bound than 1 January in the edited assertion if points carried it; the price and index flag is #601.
