# Backlog #564: a cost-of-debt year whose 10-K is not filed yet gets its own reason

Issue: https://github.com/sonderbot-ar/warren/issues/564 (front-end ask, from the #563 review) · Branch `backlog-564-not-filed-yet` · Version v0.10.40 when merged.

Status: In progress (nov.24.2026).

## Problem

The cost-of-debt chart (`inputs_behind`, and `single_values.cost_of_debt_notes`) ends at the newest fiscal year with a filed quarter. That year is still in progress on the run's date, or has ended with its 10-K not out, so it has no annual interest figure. Its point reads `not_computable`, reason `no_interest_reported`, "FY2026 reports no interest". A student reads "the company reported no interest" when the truth is "the annual report is not out yet". On the snapshot of nov.23, every company's newest run (2026-10-30) shows this on its last chart year. It fails brief Q3 (where a number comes from).

## Plan

**Step 0. This doc.**

**Step 1. `not_filed_yet`.**

- New reason in `single_values.MISSING_REASONS`: `not_filed_yet`, params `fiscal_year` and `period_end` (ISO date), beside `reason`.
- Rule, in `_cost_of_debt_point`, only where the point has no cost of debt: a year is *not filed yet* when it is after the newest fiscal year with an annual revenue figure known on the run's date (the same revenue facts and "latest period end" pick as the chart's window, `_cost_of_debt_window`). A filed year with no interest keeps `no_interest_reported`; a filed year with zero average debt keeps `average_debt_not_positive`.
- `period_end` is the year's *expected* end, since no filing has given it yet. It is read forward from the filed years' own periods (start and end, all known on the run's date), never from the company table's current fiscal-year-end field (that is today's value, not the run date's). Function `single_values.expected_year_end(filed, years_ahead)`, pure, tested alone:
  - A calendar-month year (the newest filed year is not 364 or 371 days long): the same day one year on per year ahead, kept at the month's end when the filed year ended on one (Walmart's 31 January; 29 February falls to the 28th).
  - A 52 or 53-week year: it ends on the same weekday nearest a fixed date, its anchor (Apple: the Saturday nearest 27 September; Johnson & Johnson: the Sunday nearest 31 December). Every filed end is within three days of the anchor, so the anchor is the middle of the band of dates all filed ends allow, and of two middle days the later. With one or two filed years the band is wide and the middle a guess; when no date fits every end (a changed calendar) the newest end alone is the anchor.
  - A first draft read only the newest year forward (same weekday nearest the same date a year on). It is a week early before every 53-week year, which on the snapshot is 6 of 143 past years and, worse, Johnson & Johnson's FY2026 itself (it ends 3 January 2027, not 27 December 2026). The anchor rule replaced it.
- Tests (`tests/analysis/test_single_values.py`):
  - The test company's FY2020 (in progress on 2020-06-30) reads `not_filed_yet` with `period_end` 2020-12-31 on the chart, at 3, 5 and 10 years, and on `cost_of_debt_notes`, and the two stay equal; no earlier chart year reads it.
  - FY2013 (no interest) still reads `no_interest_reported` and FY2014 `average_debt_not_positive` (existing test, unchanged).
  - `expected_year_end` on Apple's and Johnson & Johnson's real filed ends (FY2026, both 53-week years seen from the year before, FY2023 and FY2020, and the year after one, two years ahead), calendar December, June, Walmart's 31 January, a mid-month end, 29 February both ways; one 52-week year alone (the documented week-early guess); a changed calendar (falls back to the newest end); no filed year or `years_ahead` below 1 raise `ValueError`.
  - Every reason the chart gives is still in `MISSING_REASONS` (existing test).
  - Not tested with a run whose date is after the year's end and before its 10-K: the test company's data ends in 2020 and such a run needs market data it lacks. The rule does not look at the run date (only at which annual figures are known), so the case is the same code path; Apple's 2026-10-30 run in Step 2 is a real one.
- Exit: the new tests fail on `main` and pass here; full suite, `ruff check`, `ruff format --check` green.

**Step 2. Real data, read-only.** On the restored snapshot:
- For each of the eight companies' newest runs, the last chart year reads `not_filed_yet` and no earlier chart year does.
- Backtest the expected end: for every filed fiscal year of every company, `expected_year_end` from the years before it against the filed end. Report how many are exact and the largest miss.

Result (snapshot `warren-20261123T052122Z`, nov.24.2026):
- All eight companies' newest runs (2026-10-30), at 5 and 10 years: the last chart year, and only it, reads `not_filed_yet`, and every chart year's point still equals `cost_of_debt_notes`. Apple's two years before keep `no_interest_reported` (it stopped reporting the line after FY2023), as they should. Expected ends: Apple FY2026 2026-09-26 (it has ended; the 10-K came out the day after the run date), Caterpillar, Coca-Cola and Exxon 2026-12-31, Johnson & Johnson 2027-01-03 (a 53-week year), Microsoft and P&G 2027-06-30, Walmart 2027-01-31.
- Backtest: 142 of 143 filed years exact. The one miss is Johnson & Johnson's FY2009 read from FY2008 alone (one year gives no band), a week early.

## Alternatives considered

- **Give the 10-K's due date (`due_date`) instead of `period_end`.** The front-end accepts either. The due date is the year end plus 60, 75 or 90 days by filer status, which Warren does not store: one more rule on top of the same estimate. Rejected.
- **The company table's `fiscal_year_end` (MMDD from the SEC).** It is today's value, not the run date's, and gives no weekday rule for 52/53-week years. Rejected for the point-in-time rule.
- **Read only the newest filed year forward.** Simpler, but a week early before every 53-week year (6 of 143 on the snapshot, and Johnson & Johnson's FY2026 today). Replaced by the anchor band.
- **Name each company's rule ("last Saturday of September") in the universe file.** Exact, but it is a hand-written fact per company that the filings already show; the band reads it from them and keeps companies as data without a new column.
- **Leave `period_end` out and let the app say only "not filed yet".** Loses the "ended but not filed" against "still in progress" split the brief already words. Rejected; the estimate is good to the day on most years (Step 2 measures it).
- **Refuse the year instead of answering.** The chart must still show the year's place (brief: a gap, never a zero). Rejected.

## Files to change

- `domains/analysis/single_values.py`
- `tests/analysis/test_single_values.py`
- this doc; on merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (none: backlog)

## Product impact

- Serves brief Q3 on the cost of debt: the chart's newest year no longer says "reports no interest" when its 10-K is not out.
- Adds one reason to `MISSING_REASONS`, `not_filed_yet`, params `fiscal_year` and `period_end`, as the front-end asked; the brief's Spanish for it (PR #567) uses `period_end` against the *fecha de corte*. Nothing is renamed or removed. The app can drop its stopgap (hiding the newest year's `no_interest_reported`).
- Said straight: `period_end` is an expected date, not a filed one. On the snapshot it matched the filed end on 142 of 143 past years; it can be a week off when a 52/53-week company has only a year or two filed, or changes its calendar. The brief's two variants compare it with the *fecha de corte*, so a miss matters only when the run date falls in that week. The front-end may still prefer wording that does not pin the day for the "termina" variant.
