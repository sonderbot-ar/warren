# Backlog #381: a refused run says which date or filing to try

Issue: https://github.com/sonderbot-ar/warren/issues/381 (from the #376 and #383 reviews) · Branch `backlog-381-refusal-dates`.

## Problem

v0.9.69 gave every refusal on the way from a company and a date to a run a code and params (#376), and v0.9.70 added `zero_divisor` (#383). Three refusals still leave the app unable to help the student take the next step:

1. **`market_data_not_refreshed`** carries `covered_through` for the one series that failed (`domains/market/store.py`, `require_coverage`). A run reads three series: the company's prices, `^SP500TR` and `DGS10`. Each download can cover a different last day, and the first one checked is the one that refuses. The only date the app can safely offer is the earliest `covered_through` of the three, and nothing computes it.
2. **`erp_too_few_years`** carries `first_year`, `last_year` and `min_years` (`domains/market/erp.py`), but not the first as-of date that would have enough years. The app would have to copy `last_complete_year` and `YEAR_END_LAG` to work it out, which is the engine's rule, not the app's.
3. **`zero_divisor`** with `period_kind` `quarter` or `year` names the period as a label (`FY2018Q3`). A fiscal label reads like a calendar quarter (Apple's fiscal year ends in September), and the student can't open the filing that shows the zero (issue comment, product lead in the #383 review).

The issue's item (c), "operator advice must not reach the student" (the English of `market_data_not_refreshed` ends "refresh it"), is the app's rule: it builds its words from the code and params and never shows the English. Nothing changes in the engine for it; this doc records it under Product impact.

No number changes: these are params on errors that are already raised.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. One date that works for all three series.** New module `domains/market/coverage.py` with `RUN_SERIES` (the three `(source, symbol)` pairs a run reads, the company's symbol as `None`) and `run_covered_through(conn, ticker) -> date | None`: the earliest `last_ended_day(fetched_at)` of the selected download of each series, or `None` when one of them was never loaded. `store.covered_through(fetch)` computes one download's date, and `require_coverage` uses it too, so the per-series param and the combined one can't disagree. `build_inputs` (`domains/analysis/math_engine.py`) catches a `MarketDataError` with code `market_data_not_refreshed`, adds param `all_covered_through` (ISO, or `None`) and raises it again; its text is unchanged. The orchestration's `MARKET_SERIES` is replaced by `RUN_SERIES`, so the list of series lives in one place.
  Tests (`tests/market/test_coverage.py` and `tests/analysis/test_refusal_codes.py`): the earliest of three different download days wins, whichever series is older; `None` when a series is missing; a day-end download (New York midnight) counts its own day; the refusal on Test Corp carries `all_covered_through` equal to the earliest of the three and never later than the failing series' `covered_through`; a run on `all_covered_through` is not refused for market data.
  Exit: tests pass; ruff clean.

- **Step 2. The first as-of date with enough years.** `erp.first_as_of(first_year) -> date`: the first day on which `last_complete_year` reaches `first_year + MIN_YEARS - 1`, that is `date(first_year + MIN_YEARS, 1, 1) + YEAR_END_LAG`. `equity_risk_premium` adds it to `erp_too_few_years` as param `first_as_of` (ISO).
  Tests: a Hypothesis property over dates from 1990 to 2100 and first years: on `first_as_of` the window has exactly `MIN_YEARS` years and the day before has fewer; the Test Corp refusal (first year 2015) carries `first_as_of` `2025-01-08`. The app must still check the date against today: it can be in the future.
  Exit: tests pass; ruff clean.

- **Step 3. The date and filing behind a zero.** `_nonzero` and `_ratio` take the divisor's `Fact` when `period_kind` is `quarter` or `year` (asserted; a sum takes none) and add `period_end` (ISO), `accession_no` (the filing that gives the figure; `None` for a quarter Warren derived, such as a fourth quarter from the year less nine months) and `inputs` (the accessions a derived figure used; empty for a reported one). The four call sites pass the fact they already hold: the seed year, the prior year of a growth comparative, the quarter of an operating margin, and the year of a working-capital ratio (read from `result.revenue_read["history"]`).
  Tests: the three existing Test Corp `zero_divisor` cases for a quarter and a year get the exact new params; a derived fourth quarter (zero only in the 10-K year and its nine months) gives `accession_no` `None` and both inputs; the sum cases carry neither param; `_nonzero` with `quarter` or `year` and no fact is an `AssertionError`.
  Exit: tests pass; `reading_rules.md` gets a row under version 2 (only raised errors change); ruff clean.

- **Step 4. Real data.** Restore the snapshot; `python -m domains.analysis reproduce --all --rebuild` must give the same counts as `main` (no number changes), and the stored market downloads give a real `all_covered_through` on a date after their last day.

## Alternatives considered

- **Check all three series before refusing, inside `require_coverage`.** `store.py` can't know which three series a run reads (it would import `prices` and `yields`, which import it). Catching the refusal once in `build_inputs` keeps `store` a plain store.
- **Give the app `run_covered_through` only, with no param.** The app would call the engine a second time after every refusal of this kind, and on a hosted app between the two calls a download could land. The param records the answer at the moment of the refusal; the function stays public for screens that want to suggest a date before any run.
- **Clamp `first_as_of` to today, or drop it when it is in the future.** The engine's refusal shouldn't depend on the clock beyond what `build_inputs` already checks; the app knows today.
- **Give `zero_divisor` a full filing source (`src.filing`) as one param.** It holds a dozen fields the sentence doesn't need; three flat params match the share-count notes the app already links (`accession_no`, `period_end`).

## Files to change

`domains/market/coverage.py` (new), `domains/market/store.py`, `domains/market/erp.py`, `domains/analysis/math_engine.py`, `domains/orchestration/nodes.py`, `domains/analysis/reading_rules.md`, `tests/market/test_coverage.py` (new), `tests/analysis/test_refusal_codes.py`, `docs/designs/backlog-376-refusal-codes.md` (its params table), and on merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Serves the refusal sentences of the brief's estimate questions (`docs/product/brief.md`: Q3, Q5, Q8 and every value per share), in the two groups that ask the student to pick another date (`later_date`, `earlier_date`) and in `company_data`. Nothing renamed or removed; English texts unchanged.

Added:
- `market_data_not_refreshed`: `all_covered_through` (ISO date or `null`), the newest date all three series a run reads can serve. Offer it as "prueba con el {fecha}" instead of `covered_through`, which stays as the one failing series' date. `null` means a series was never loaded, and the app shows the `setup` sentence.
- `erp_too_few_years`: `first_as_of` (ISO date), the first as-of date with enough years for the chosen first year. It can be after today: then the app says no date works yet with this first year.
- `zero_divisor` with `period_kind` `quarter` or `year`: `period_end` (ISO date), `accession_no` (string, or `null` for a quarter Warren derived) and `inputs` (list of accessions; empty for a reported figure). Show the period's end date beside its label, and "Ver reporte" on `accession_no`, or on each of `inputs` when it is `null`. The sum kinds carry none of the three.

For the app (issue item c): never show the English of a refusal. `market_data_not_refreshed`'s ends with advice for whoever runs Warren ("refresh it"); the student's sentence comes from the code and params only.
