# Backlog #561: the cost-of-debt notes call refuses a year outside the chart, and types its point

Issue: https://github.com/sonderbot-ar/warren/issues/561 (from the #560 review: product lead and gatekeeper) · Branch `backlog-561-notes-window` · Version v0.10.39 when merged.

Status: Done (v0.10.39, nov.24.2026, PR #563, merge `8637726`). Gatekeeper GO; follow-ups #564 (the year in progress, front-end ask) and #565.

## Problem

`single_values.cost_of_debt_notes(conn, run_id, fiscal_year)` (v0.10.38) answers any year. A year after the newest filing known on the run's date comes back `not_computable` with `no_interest_reported`, which a student would read as "the company reported no interest" when the truth is "not filed yet". Only the docstring warns. The app asks only for chart years today, so no screen shows this yet, but nothing stops it. Second, `CostOfDebtNotes.point` is typed `object` to dodge an import cycle.

## Plan

**Step 0. This doc.**

**Step 1. Refuse a year the chart does not show, and type the point.**

- `single_values._cost_of_debt_window(singles) -> (first_year, last_year) | None`: the chart's window read from the history the call already loads, not from the fiscal-calendar reader. The last year is the newer of two fiscal years: the newest quarterly revenue figure's and the newest annual revenue figure's, each the one with the latest period end, exactly as `reported.latest_period` picks them for the chart; the first is `last - years + 1`. None when there is no revenue figure (the chart has no window then either).
- `cost_of_debt_notes(conn, run_id, fiscal_year=None, years=None)`: a year that is not the run's own and not in the window raises `InputsError` code `year_outside_window`, params `fiscal_year`, `first_year`, `last_year` (both None with no window) and `years`. The run's own year is always answered, as the chart always shows it. No year asked is unchanged.
- `years` is new, default `inputs.DEFAULT_YEARS`, the same meaning as `inputs_behind`'s, so an app that builds a longer chart can ask for its older years. It is checked by one shared function, `inputs.check_years` (`years_out_of_range`, same params), now used by both calls.
- `CostOfDebtNotes.point` is typed `"Point | None"` through a `TYPE_CHECKING` import of `inputs.Point`.
- Tests (`tests/analysis/test_single_values.py`):
  - For charts of 3, 5, 8 and 10 years: every chart year still equals the chart (point and cell notes), the chart's years are one unbroken run, and the year before the first and after the last are refused with the code and exact params.
  - A year after the newest filed year (FY2021 on the test company) and a long-ago year (1990) are refused, not read as `no_interest_reported`.
  - The run's own year is answered when it is older than the window (the chart adds it), and the year next to it is still refused.
  - A history with no revenue figure refuses every year but the run's own, with null bounds.
  - `years` out of range is refused with the same code and params as `inputs_behind`.
  - The old "a year with no interest gives its reason" test asked for 1990, now refused; it now asks an eight-year chart's FY2013 (no interest) and FY2014 (no average debt), both chart years, so both reasons are still pinned and now also equal to the chart.
  - The "reads no fiscal calendar and no other cell" test still passes: the window check needs no reader.
- Exit: the new tests fail on `main` (no refusal, no `years`) and pass here; full suite, `ruff check` and `ruff format --check` green.

**Step 2. Real data.** On the restored snapshot, read-only: for the newest baseline run of each of the eight companies, the call's window equals `inputs_behind`'s cost-of-debt chart years at 5 and 10 years, every chart year is answered and equal, and the years on either side are refused. Nothing is written.

Result (snapshot `warren-20261123T052122Z`, nov.24.2026): on all eight companies' newest runs (2026-10-30), at 5 and 10 years, the window read from the history equals the chart's years, every chart year's point and cell notes are equal, and the years on either side are refused with the chart's bounds. Said straight, as the last bullet of *Product impact* warns: every company's newest chart year (FY2026, or FY2027 for Microsoft, P&G and Walmart, whose fiscal years run ahead) is a year in progress and reads `no_interest_reported`.

## Review (nov.24.2026)

- **Product lead: GO** on *Product impact*. Agrees `year_outside_window` needs no group and no Spanish line: students reach only the codes in `coded.ENGINE_REFUSAL_CODES` by picking a company and a date, and the app asks only chart years; `years_out_of_range` has no group either. Confirmed the in-progress year is not handled by the brief or the first screen and asked for `not_filed_yet` (filed as #564) and for the issue number here (done).
- **Gatekeeper: GO** (PR #563, head `b051f07`): the window's rule and data match `reported.latest_period` and `_views` (same `get_facts` calls, same keys, sorted output so ties resolve alike); the new tests fail on `main` (17 failed); the FY1990 test's replacement is stronger (both reasons, equal to the chart). Follow-ups in #565: an unmocked no-revenue test, and annual revenue with no quarter (no chart, but the window answers; unreachable in Phase 1).
- **Explainer, analyst, professor:** not run; no method or number changes, and the window rule is checked against the chart on every company (Step 2).

## Alternatives considered

- **Read the window from the fiscal-calendar reader**, as the chart does. Exact by construction, but it costs the call most of what #550 saved. The history gives the same two fiscal years (same revenue facts, same "latest period end" pick); Step 2 checks it on every company.
- **Answer the year with a new reason, `not_filed_yet`, instead of refusing.** Kinder to a caller, but the app has no screen that asks for such a year, and a refusal keeps the call's contract to "the chart's years", which is what the equality tests check. Rejected.
- **Put `year_outside_window` in `coded.OTHER_REFUSAL_GROUPS`.** No student can reach it: the app asks only for years it got from the chart. It is a caller's mistake, like `years_out_of_range`, which has no group either. Left out; the front-end can ask for a group if a screen ever needs one.

## Files to change

- `domains/analysis/single_values.py`, `domains/analysis/inputs.py` (`check_years` split out, no behaviour change)
- `tests/analysis/test_single_values.py`
- this doc; on merge `docs/versions.md`, `docs/team-sync.md`

## Product impact

- Serves brief Q3 (where a number comes from) on the cost of debt: the call can no longer say "reported no interest" for a year not filed yet.
- Adds one refusal code on `cost_of_debt_notes`, `year_outside_window`, and one optional argument, `years`. Nothing in `inputs_behind` changes. The front-end needs no Spanish line unless it asks for years outside the chart; if it wants one, the brief's catalogue is its to write.
- Not changed here, said straight: the chart itself shows the fiscal year in progress (the test company's FY2020) as `no_interest_reported` when its 10-K is not out yet. That is the same "not filed yet read as reported none" problem one level up; filed as #564 (`backlog`, `front-end`): a distinct reason, `not_filed_yet`, which the front-end asked for.
- The app must pass `years` equal to the chart's 3, 5 or 10-year switch (`docs/designs/f2-input-charts.md`), or a longer chart's older years are refused (product lead).
