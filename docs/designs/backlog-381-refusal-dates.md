# Backlog #381: a refused run says which date or filing to try

Issue: https://github.com/sonderbot-ar/warren/issues/381 (from the #376 and #383 reviews) · Branch `backlog-381-refusal-dates` · Version v0.9.71, merged nov.14.2026 (PR #389, merge `5022a0c`, after CI green and a gatekeeper GO with no blockers).

## Problem

v0.9.69 gave every refusal on the way from a company and a date to a run a code and params (#376), and v0.9.70 added `zero_divisor` (#383). Three refusals still leave the app unable to help the student take the next step:

1. **`market_data_not_refreshed`** carries `covered_through` for the one series that failed (`domains/market/store.py`, `require_coverage`). A run reads three series: the company's prices, `^SP500TR` and `DGS10`. Each download can cover a different last day, and the first one checked is the one that refuses. The only date the app can safely offer is the earliest `covered_through` of the three, and nothing computes it.
2. **`erp_too_few_years`** carries `first_year`, `last_year` and `min_years` (`domains/market/erp.py`), but not the first as-of date that would have enough years. The app would have to copy `last_complete_year` and `YEAR_END_LAG` to work it out, which is the engine's rule, not the app's.
3. **`zero_divisor`** with `period_kind` `quarter` or `year` names the period as a label (`FY2018Q3`). A fiscal label reads like a calendar quarter (Apple's fiscal year ends in September), and the student can't open the filing that shows the zero (issue comment, product lead in the #383 review).

The issue's item (c), "operator advice must not reach the student" (the English of `market_data_not_refreshed` ends "refresh it"), is the app's rule: it builds its words from the code and params and never shows the English. Nothing changes in the engine for it; this doc records it under Product impact.

No number changes: these are params on errors that are already raised.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. One date that works for all three series.** New module `domains/market/coverage.py` with `RUN_SERIES` (the three `(source, symbol)` pairs a run reads, the company's symbol as `None`) and `run_covered_through(conn, ticker) -> date | None`: the earliest `last_ended_day(fetched_at)` of the selected download of each series, or `None` when one of them was never loaded. `store.covered_through(fetch)` computes one download's date, and `require_coverage` uses it too, so the per-series param and the combined one can't disagree. `build_inputs` (`domains/analysis/math_engine.py`) catches a `MarketDataError` with code `market_data_not_refreshed`, adds param `all_covered_through` (ISO, or `None`) and raises it again; its text is unchanged. The orchestration's `MARKET_SERIES` is now an alias of `RUN_SERIES` (kept for its tests), so the list of series lives in one place.
  Every coverage check on the `build_inputs` path is on the as-of date (the company's close and weekly returns, the index's weekly returns, the 10-year yield) or on a year-end at least eight days before it (the risk premium's annual returns), so a date every download covers passes them all (analyst review).
  Tests (`tests/market/test_coverage.py` and `tests/analysis/test_refusal_codes.py`): the earliest of three different download days wins, whichever series is older; `None` when a series is missing; a download made at New York midnight covers the day that has just ended; on Test Corp, with each of the three series downloaded earlier in turn, the refusal carries `all_covered_through` equal to the earliest of the three, and a run on that date is not refused with `market_data_not_refreshed` (it builds).
  Exit: tests pass; ruff clean.

- **Step 2. The first as-of date with enough years.** `erp.first_as_of(first_year) -> date`: the first day on which `last_complete_year` reaches `first_year + MIN_YEARS - 1`, that is `date(first_year + MIN_YEARS, 1, 1) + YEAR_END_LAG`. `equity_risk_premium` adds it to `erp_too_few_years` as param `first_as_of` (ISO).
  Tests: a Hypothesis property over dates from 1990 to 2100 and first years: on `first_as_of` the window has exactly `MIN_YEARS` years and the day before has fewer; the Test Corp refusal (first year 2015) carries `first_as_of` `2025-01-08`. The app must still check the date against today: it can be in the future.
  Exit: tests pass; ruff clean.

- **Step 3. The date and filing behind a zero.** `_nonzero` and `_ratio` take the divisor's `Fact` when `period_kind` is `quarter` or `year` (asserted; a sum takes none) and add `period_end` (ISO), `accession_no` (the filing that gives the figure; `None` for a quarter Warren derived, such as a fourth quarter from the year less nine months) and `inputs` (the accessions a derived figure used; empty for a reported one). The four call sites pass the fact they already hold: the seed year, the prior year of a growth comparative, the quarter of an operating margin, and the year of a working-capital ratio (read from `result.revenue_read["history"]`).
  As built: the working-capital site reads the year's revenue from `history.year(y)` (analyst), the same fact `_history_rows` resolves.
  Tests: the three existing Test Corp `zero_divisor` cases for a quarter and a year get the exact new params; a derived fourth quarter (the 10-K year filed equal to its first three quarters) gives `accession_no` `None` and all four inputs (the 10-K and three 10-Qs: `inputs` is flattened, so a derived quarter lists every filing); the sum cases carry none of the three params; `_nonzero` with `quarter` or `year` and no fact is an `AssertionError`. The working-capital site can't be reached on Test Corp (a zero year's revenue is refused first by the growth comparative).
  Exit: tests pass; `reading_rules.md` gets a row under version 2 (only raised errors change); ruff clean.

- **Step 4. Real data.** Restore the snapshot; `python -m domains.analysis reproduce --all --rebuild` must give the same two counts as `main` (runs reproduced to the cent, runs rebuilt to identical rows), and a run asked for a date after the stored downloads end gives a real `all_covered_through`.

## Alternatives considered

- **Check all three series before refusing, inside `require_coverage`.** `store.py` can't know which three series a run reads (it would import `prices` and `yields`, which import it). Catching the refusal once in `build_inputs` keeps `store` a plain store.
- **Give the app `run_covered_through` only, with no param.** The app would call the engine a second time after every refusal of this kind, and on a hosted app between the two calls a download could land. The param records the answer at the moment of the refusal; the function stays public for screens that want to suggest a date before any run.
- **Clamp `first_as_of` to today, or drop it when it is in the future.** The engine's refusal shouldn't depend on the clock beyond what `build_inputs` already checks; the app knows today.
- **Give `zero_divisor` a full filing source (`src.filing`) as one param.** It holds a dozen fields the sentence doesn't need; three flat params match the share-count notes the app already links (`accession_no`, `period_end`).

## Design review (nov.14.2026)

- **Analyst, GO, no blockers.** The earliest of the three downloads passes every coverage check on the run's path (as-of checks, and year-end checks at least 8 days earlier; `known_by(last_ended_day(t)) <= t`); weekends are fine (`raw_close` takes the last close on or before, the yield the last before). `first_as_of` is exactly the first day (`last_complete_year` never goes down). Each call site holds the divisor's fact; a comparative's accession is the newer 10-K that shows it. Notes taken: test wording "not refused with `market_data_not_refreshed`"; dropped the claim "never later than the failing series' date" (a download can land between the refusal and the lookup); Product impact says the date only clears the download check and that the param comes from `build_inputs`; working-capital revenue read from `history`; a derived quarter's `inputs` tested with all its filings.
- **Explainer.** BLOCKING 1 (what a `null` shows) accepted: the group stays `earlier_date`, the app falls back to `covered_through`. BLOCKING 2 (which checks the catch covers) accepted: Step 1 now lists them and why a covered date passes the year-end ones. Notes taken: midnight wording, the sum kinds named, the new `Fact` parameter, the Hypothesis variables (as-of dates 1990–2100, first years 1950–2090), Step 4's counts. Note 3 (the code already existed) was the review reading the branch mid-build. Note 11 rejected: `coded.py` lists codes and closed value sets, not params; the params table is the #376 design doc, updated here.
- **Product lead, GO, no blockers.** Notes taken into Product impact: one date in the sentence and the button; `null` keeps the group; the first year is the owner's, so the Spanish can't offer to change it, and "today" is the last ended New York day; `first_as_of` after the downloads' date means the data isn't there yet; the EDGAR link needs no new param. The brief's own sentences are the front-end team's to edit.
- **Professor.** Not run: no method or literature is involved (params on existing refusals).

## Files to change

`domains/market/coverage.py` (new), `domains/market/store.py`, `domains/market/erp.py`, `domains/analysis/math_engine.py`, `domains/orchestration/nodes.py`, `domains/analysis/reading_rules.md`, `tests/market/test_coverage.py` (new), `tests/market/test_erp.py`, `tests/analysis/test_refusal_codes.py`, `docs/designs/backlog-376-refusal-codes.md` (its params table), and on merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Serves the refusal sentences of the brief's estimate questions (`docs/product/brief.md`: Q3, Q5, Q8 and every value per share), in the two groups that ask the student to pick another date (`later_date`, `earlier_date`) and in `company_data`. Nothing renamed or removed; English texts unchanged.

Added:
- `market_data_not_refreshed`: `all_covered_through` (ISO date or `null`), the newest date all three series a run reads can serve. Offer it on the brief's "Usar el último día disponible" button, and name the same date in the sentence, instead of `covered_through`, which stays as the one failing series' date. The date only clears the download check: the run can still be refused there for another reason (too few risk-premium years with a late first year, thinner filings), and the app words that refusal like any other. `null` means another series was never downloaded; the group stays `earlier_date` and the app falls back to `covered_through`. The param comes from `build_inputs` (and so `run_baseline`); the offline pipeline refuses before it with its own text.
- `erp_too_few_years`: `first_as_of` (ISO date), the first as-of date with enough years for the first year chosen. It can be after the last ended New York day (the `as_of_in_future` rule): then no date works yet. The first year is the owner's setting, so the Spanish must not suggest the student can change it. If `first_as_of` is after `all_covered_through` as the app knows it, a run on it would be refused for old downloads, so say the data isn't there yet.
- `zero_divisor` with `period_kind` `quarter` or `year`: `period_end` (ISO date), `accession_no` (string, or `null` for a quarter Warren derived) and `inputs` (list of accessions; empty for a reported figure). Show the period's end date beside its label, and "Ver reporte" on `accession_no`, or on each of `inputs` when it is `null` (a derived quarter can list four filings). The EDGAR link is built from the accession and the company's CIK, as the share-count notes' links are; no new param. The sum kinds carry none of the three.

For the app (issue item c): never show the English of a refusal. `market_data_not_refreshed`'s ends with advice for whoever runs Warren ("refresh it"); the student's sentence comes from the code and params only.

## Results (Step 4, nov.14.2026)

On the restored snapshot (`warren-20261110T202538Z`), with the Step 3 code: `python -m domains.analysis reproduce --all --rebuild` gives 903 of 903 stored runs reproduced to the cent and 821 of 903 rebuilt to identical rows, the same two counts as v0.9.70 on `main` (the 82 rebuild differences are older runs whose reading rules weren't recorded, as in the #383 results). No number changes.

Asking for Nov 13, 2026 for Apple, Microsoft, Exxon and Coca-Cola is refused with `market_data_not_refreshed` carrying `covered_through` and `all_covered_through` both `2026-10-30`: the snapshot's three downloads were made the same day, so here the two dates agree. A run on `2026-10-30` builds for all four (140 to 143 rows). The case where the series differ is covered by the Test Corp tests.

## Gatekeeper (nov.14.2026)

GO, no blockers: ruff clean, 2,295 passed (10 skipped for a missing browser), fingerprint `b9b57dc7c910` matches the reading-rules row, no test weakened. Nits: `MARKET_SERIES` is kept as an alias (the doc's wording fixed above); `_nonzero` asserts the fact on every call, not only on a zero, which is safe today because every quarter and year site passes the fact it already holds; `first_as_of` has no upper bound, by design.
