# Backlog #565 and #569: the cost-of-debt chart's edges (window, filed year, week years)

Issues: https://github.com/sonderbot-ar/warren/issues/565 (from the #563 gatekeeper) and https://github.com/sonderbot-ar/warren/issues/569 (from the #568 analyst and gatekeeper) · Branch `backlog-565-window-edges` · Version v0.10.41 when merged.

Status: In progress (nov.24.2026).

## Problem

Two follow-up issues on the same few functions in `domains/analysis/single_values.py`, all edge cases none of the eight Phase 1 companies reaches today, but each a way the cost-of-debt chart or its notes call could say something false on a new company:

1. **#565 item 1.** `_cost_of_debt_window`'s "no revenue, no window" branch is only tested through a mock that replaces the function, so the branch itself never runs in a test.
2. **#565 item 2.** The chart needs both the newest quarter and the newest year with revenue (`inputs._Reader.latest`, which raises `ReportedError` when either is missing), but `_cost_of_debt_window` returns a window when only one of them has revenue. `cost_of_debt_notes` would then answer years for a chart that cannot be built.
3. **#569 item 1.** A year is "not filed yet" when it is after the newest fiscal year with an annual revenue figure known on the run's date. A 10-K whose revenue Warren does not read (an unmapped tag; Exxon's FY2009–2010 revenue arrives only as 2012 comparatives) would make a filed year read "not filed yet".
4. **#569 item 3.** `_filed_fiscal_year` picks the newest year by period end only; `_filed_years` sorts by end then start. Two periods can share an end (Caterpillar FY2009–2010), so the two picks could disagree.
5. **#569 item 2.** A 52/53-week filer that tags its year's start as the prior year's end has years of 365 or 372 days, so `expected_year_end` would read it as a calendar-month year and give the wrong expected end.
6. **#569 item 4.** No fixture test of a run dated after a fiscal year has ended but before its 10-K is out; only Apple's real 2026-10-30 run shows that case.

## Plan

**Step 0. This doc.**

**Step 1. The window needs both frequencies (#565).**

- `_cost_of_debt_window` returns None when the quarterly or the annual facts hold no revenue figure (with a start), as the chart's reader refuses; the docstring says so.
- Tests (`tests/analysis/test_single_values.py`), on a real `math_engine.History` built from `Fact`s, no mock: no revenue at all, annual only, quarterly only (each None), both (the window, last year the newer of the two), and revenue given only as instants (None).
- Exit: the annual-only and quarterly-only tests fail on `main`; full suite and ruff green.

**Step 2. One pick of the newest filed year, cross-checked with the 10-K forms (#569 items 1 and 3).**

- One helper, `_annual_revenue(history)`, sorted by end then start, feeds both `_filed_years` and the newest filed fiscal year, so the two cannot disagree.
- New `_newest_filed_year(singles)`: the newer of (a) the fiscal year of the newest annual revenue figure and (b) the newest `fiscal_year` of a 10-K or 10-K/A in `filing_labels` with `fiscal_period = 'FY'` and `filed_at` on or before the run's date (the same `filed_at <= as_of` rule as the facts query). A year after it is `not_filed_yet`; a year the 10-K forms show as filed but with no revenue Warren reads falls to the existing branches (`no_interest_reported` or `average_debt_not_positive`), never "not filed yet".
- `expected_year_end` still reads forward from the revenue years (they carry the periods); its `years_ahead` is counted from the newest revenue year. When the 10-K forms are newer than the revenue, `not_filed_yet` uses the forms' year for "filed" and the revenue years for the expected end.
- Tests: on the fixture company with the FY2019 10-K's annual revenue and interest dropped (the tag unmapped, in effect), `_newest_filed_year` is 2019 and FY2019 is not `not_filed_yet` (fails on `main`); on the unedited fixture it is 2019 both ways; a 10-Q never counts; a 10-K filed after the run's date never counts.
- Exit: the new tests fail on `main` and pass here; suite and ruff green.

**Step 3. Week years counted as 365 or 372 days (#569 item 2).**

- `expected_year_end` treats the newest year as a 52/53-week year when it is 364 or 371 days long, as now, or when it is 365 or 372 days long *and* its end is 364 or 371 days after the previous filed end (the weekday repeats). A calendar year is also 365 days long when its start is tagged on 1 January, but its ends are 365 or 366 days apart, so it never passes the second test.
- Tests: Apple's and Johnson & Johnson's real ends with each start tagged as the prior year's end give the same expected ends as today's tests; a calendar December year tagged the same way stays a calendar year; one 365-day year alone stays calendar (no previous end to compare).
- Exit: the 365/372 tests fail on `main`; suite and ruff green.

**Step 4. A run after the year ends, before its 10-K (#569 item 4).**

- Fixture test: a baseline run of the test company dated 2020-02-10 (FY2019 ended 2019-12-31; its 10-K is filed 2020-02-15). The chart's last year is FY2019 and reads `not_filed_yet` with `period_end` 2019-12-31; the run's own year is FY2018; `cost_of_debt_notes` for FY2019 equals the chart's point.
- Exit: test passes here (it pins existing behaviour; it is expected to pass on `main` too).

**Step 5. Real data, read-only.** On the restored snapshot, for all eight companies' newest runs at 5 and 10 years, every chart point and `cost_of_debt_notes` point equals what `main` gives (no change expected), and on every stored run's (company, date) the revenue year and the 10-K forms' year agree (the analyst's 899 pairs), so the cross-check changes nothing today.

## Alternatives considered

- **Use only the 10-K forms for "filed".** Simpler, but the forms' `fiscal_year` is Warren's label for the filing, read through the fiscal calendar (#310), and a database ingested before migration 0022 has no labels; the revenue figure is the rule that shipped and was measured. Taking the newer of the two keeps today's answers and only adds the case the analyst found.
- **Soften the docstring for #565 item 2 instead of refusing.** The gatekeeper offered either. Refusing is the same rule as the chart's, so the notes call and the chart cannot disagree; chosen.
- **Test the weekday pattern alone for week years (#569 item 2's second option).** Reading every gap between filed ends is more general, but a company that moved calendars would mix both kinds of gap. Checking the newest gap only, and only when the length is 365 or 372, leaves every result today unchanged.

## Files to change

- `domains/analysis/single_values.py`
- `tests/analysis/test_single_values.py`
- this doc; on merge `docs/versions.md`, `docs/team-sync.md`

## Product impact

- Serves brief Q3 (where a number comes from) on the cost of debt. No output is added, renamed or removed; no new code or param.
- On the eight companies nothing changes (Step 5 checks it). On a new company: a year whose 10-K is out but whose revenue Warren cannot read now reads "reports no interest" or "average debt is zero" instead of "not filed yet"; a company whose filings give revenue for only one frequency now has the notes call refuse every year with `year_outside_window` (bounds null), as the chart already has no window.
