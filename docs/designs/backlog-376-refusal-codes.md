# Backlog #376: a run that can't be built says why, as a code

Issue: https://github.com/sonderbot-ar/warren/issues/376 (front-end R8) · Branch `backlog-376-refusal-codes` · Version v0.9.69 when merged.

## Problem

When a baseline run can't be built, `math_engine.build_inputs` raises `EngineError`, and the market layer it calls raises `MarketDataError`. Both carry English text only, for example "AAPL: no share count above zero reported" (`math_engine._shares`) or "No price for AAPL on or before 2019-03-02" (`market.prices.raw_close`). The student app never shows the engine's English (design principle "no text hard-coded in logic"), so today every refusal becomes one generic sentence: "Warren no pudo calcular esta estimación con los reportes disponibles hasta esa fecha" (`docs/product/brief.md`, the share-count notes under Q3). The student can't tell "pick a later date" from "this company's reports lack a figure" from "today hasn't ended yet".

Run notes already have codes (#172), and so do simulation refusals (`montecarlo.SimulationError.code`, `coded.SIMULATION_REFUSAL_CODES`, #212). Run refusals are the gap.

**What R8 names, and where each one is.** No share count above zero (`_shares`), no price on the date (`raw_close`), before `SUPPORTED_FROM` (`build_inputs`) are refusals. "Beyond history" is not a refusal: a date after a company's filings stop still builds, with the run note `beyond_history` (v0.9.22), which already has a code. Nothing changes for it.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. Codes on both exceptions, and the catalogue.**
  `EngineError(text, code=None, params=None)` and `MarketDataError(text, code=None, params=None)` gain `code`, `params` and `coded()`, exactly as `SimulationError` has (text first, so every existing call is unchanged; `code` None means text only). The constructor asserts a given code is in the new `coded.ENGINE_REFUSAL_CODES`, one catalogue for both exceptions, because the app meets them at the same place (asking for a run). `coded.refusal(exc) -> Coded | None` reads any exception with a `code` (engine, market or simulation) so the app has one call. Params hold only strings, numbers, booleans and lists of them; dates are ISO strings, as run notes' params are.
  Tests (`tests/analysis/test_refusal_codes.py`): a code outside the catalogue is refused by both constructors; a plain `EngineError(text)` and `MarketDataError(text)` have `code` None, `params` {} and `coded()` None; `refusal` returns the same `Coded` as `coded()` for each of the three exceptions and None for a `ValueError`.
  Exit: tests pass.

- **Step 2. Code every refusal a student's run can reach.** The student picks a company and a date; `build_inputs(conn, ticker, as_of)` with the owner's assumptions is that path (`runs.run_baseline`). Each raise on it gets a code and params:

  | Code | Where | Params |
  |---|---|---|
  | `as_of_too_early` | `build_inputs` | `as_of`, `supported_from` |
  | `as_of_in_future` | `build_inputs` (a date after today in New York) | `as_of`, `today` |
  | `company_not_ingested` | `build_inputs` | `ticker` |
  | `no_ingest_run` | `_snapshot` | `ticker` |
  | `no_quarterly_revenue` | `_last_actual_quarter` | `ticker`, `as_of` |
  | `history_too_short` | `_history_years` | `ticker`, `needed`, `found_years` |
  | `too_few_comparatives` | growth, in `_drivers` | `ticker`, `needed`, `found` |
  | `too_few_quarters` | margin by quarter, in `_drivers` | `ticker`, `quarter`, `needed`, `found`, `window` |
  | `seed_quarter_not_reported` | `_revenue_seed` | `ticker`, `fiscal_year`, `quarter` |
  | `flow_item_not_reported` | `resolve` (an income or cash-flow figure with no reported alternative) | `item`, `fiscal_year`, `quarter` (None for a year), `tried` (list of alternatives, each a list of items) |
  | `no_balance_sheet` | `_balance` | `ticker`, `as_of` |
  | `balance_item_not_reported` | `_operating_nwc` (a year's working capital), `_balance` (the latest balance sheet) | `item` and `fiscal_year`, `quarter`; or `ticker`, `item`, `period_end` |
  | `balance_item_negative` | `_balance` | `ticker`, `item`, `period_end`, `value`, `currency` |
  | `securities_exceed_current_assets` | `_balance` (both checks) | `ticker`, `period_end`, `with_cash` (bool), `securities` (with cash when `with_cash`), `current_assets`, `currency` |
  | `no_share_count` | `_shares` | `ticker`, `reason`: `none_reported` or `none_above_zero`; with the second, `skipped`: the counts left out (each `shares_not_positive` note's params), since a refused run stores no notes |
  | `no_interest_with_debt` | `_cost_of_debt` | `ticker`, `fiscal_years` |
  | `market_data_not_loaded` | `market.store.require_coverage`, `market.prices.split_factor` | `source`, `symbol` |
  | `market_data_not_refreshed` | `require_coverage` (download made before the date ended) | `source`, `symbol`, `fetched_at` (as stored, UTC), `as_of`, `covered_through` (the newest date that download serves, ISO) |
  | `no_price_on_date` | `raw_close` | `ticker`, `as_of` |
  | `no_risk_free_rate` | `risk_free_rate` | `series`, `as_of` |
  | `too_few_return_weeks` | `aligned_weekly_returns` | `ticker`, `as_of`, `found`, `needed` |
  | `erp_too_few_years` | `equity_risk_premium` | `as_of`, `first_year`, `last_year`, `min_years` |
  | `market_year_end_missing` | `year_end_values` (index or bond year-end, for the ERP) | `what`, `year` |
  | `no_base_value` | `runs.run_baseline` (the valuation after the build: terminal growth at or above WACC, or a rate not above zero; analyst) | `ticker`, `as_of`, `reason` (`growth_not_below_rate`, `rate_not_positive`, `rate_not_above_minus_100`) |

  The English text of every refusal stays exactly as it is today (CLI output, logs and tests that match text are unchanged).
  **Text only, on purpose** (a student can't reach them by picking a company and a date): the owner's assumptions file checks (`load_user_assumptions`, `UserChoice.from_assumption`), the sources guards in `EngineResult._put` (a programming error), the rebuild of a stored run (`runs.rebuild`: a stored run with a choice no longer supported), and the market download and pin paths (`yahoo_download`, `load_prices`, `fred_download`, `load_yields`, `selected_fetch`, `fetch_with_hash`), which an operator runs.
  The `run` and `reproduce --rebuild` CLI lines print the code before the text when there is one (`FAILED [no_price_on_date]: …`), as `simulate` does.
  Tests (`tests/analysis/test_refusal_codes.py`):
  1. *Every raise carries a code or is on the text-only list.* An AST scan of `math_engine.py` and the four market modules: each `raise EngineError(...)` or `raise MarketDataError(...)` has a `code=` keyword, unless its enclosing function is on a named text-only list in the test (with the reason). A new raise without a code fails the test.
  2. *Every catalogued code is raised somewhere*, and every literal `code=` at a raise is catalogued (no dead or stray codes).
  3. *Behaviour, one test per student-reachable code that a small fixture database can reach:* the date before `SUPPORTED_FROM` and after today, an unknown ticker, no share count (both reasons), no price on the date, a stale download, too few return weeks, too few ERP years, no quarterly revenue, a negative balance item, securities above current assets; each checks the code, the params and that `str(e)` is the old text.
  Exit: tests pass; the full suite and ruff are clean.

- **Step 3. Real data.** On the restored snapshot: `reproduce --all` unchanged (refusals change no stored number). Then ask for one baseline per Phase 1 company on dates that should be refused (2019-02-28, the day after today, and the earliest date each company's first refusal fires on the way forward from 2019-03-01, if any), and on every date the M3 and M9 case lists hold that failed before: every refusal carries a code, and the text matches the old text. Results below.
  Exit: no refusal on real data comes without a code.

**Exit criterion:** all tests pass, ruff is clean, and Step 3 finds no uncoded refusal.

**Point in time.** Nothing new is read. Params only restate what the refusal already says.

**LLMs.** None. No number changes.

## Alternatives considered

- **Wrap market errors inside `build_inputs` and re-raise them as coded `EngineError`.** One exception for the app, but it changes the type every `except MarketDataError` caller and test relies on (`runs.py`, `__main__.py`, the harness). Rejected: a code on `MarketDataError` itself gives the app the same thing through `coded.refusal`.
- **Two catalogues, one per exception.** Rejected: the app asks "why can't this run be built?" once; one set of codes is one text catalogue to keep complete.
- **Code every `EngineError`, including the owner's file checks.** Rejected: a code is a promise the app will translate it; the owner's file and internal guards never reach a student, and the AST test names them, so a later screen that reaches one has to code it.
- **A lesson per refusal (as `WARNING_LESSONS` has for notes).** Out of scope here: the app first needs to tell refusals apart. Left as a follow-up idea for the front-end to request.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/market/store.py`, `domains/market/prices.py`, `domains/market/yields.py`, `domains/market/erp.py`, `domains/analysis/__main__.py` (two CLI lines), tests in `tests/analysis/` and `tests/market/`. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Nothing renamed or removed; every refusal's English text is unchanged. Adds:

- `EngineError` and `MarketDataError` have `code`, `params` and `coded()`; `code` is None for text-only refusals.
- `coded.ENGINE_REFUSAL_CODES` (the 24 codes above, each with its group in `coded.REFUSAL_GROUPS`) and `coded.refusal(exc)`. Add the codes to the app's text catalogue; any refusal with `code` None keeps the generic sentence.
- R8 is served, with one correction: "beyond history" is a run note, not a refusal, and already has its code.

- `coded.REFUSAL_GROUPS` and `REFUSAL_GROUP_ORDER`: what the student can do, for the screen to group by: `later_date`, `earlier_date`, `company_data`, `inconsistent_data`, `no_value`, `setup` (Warren's own data isn't ready; the words must not blame the student).
- The money params (`value`, `securities`, `current_assets`) are in the filing's unit (`currency`, e.g. USD), unscaled, as the facts are.
- `item` and `tried` are engine item names; their Spanish labels depend on the line labels still owed to the brief (#297 item 5).

Questions served: brief Q3, Q5 and Q8 (R8's list): when a run can't be built, the app can say why and what to try (a later date, another company, wait for the day to end). No question changes status.

## Design review (nov.14.2026)

Explainer, analyst, professor and the product lead, fresh context, in parallel. No blockers. Taken:

- **A group per code (professor's "family", product lead's "next step").** `coded.REFUSAL_GROUPS` maps every code to what the student can do, and a test checks every code has one. The app no longer has to hard-code engine knowledge per code.
- **Free-text `where` (product lead).** Split into `fiscal_year` and `quarter` (`math_engine.where_params`); the English label stays only in the text.
- **One name for one date (product lead).** `balance_date` became `period_end`, as run notes use.
- **Money with a unit (product lead).** `currency` from the fact's unit beside every amount.
- **`covered_through` (product lead).** `market_data_not_refreshed` says which newest date that download serves, so the app doesn't redo New York day-end logic.
- **The counts left out (product lead).** `no_share_count` with `none_above_zero` carries them in `skipped`, since a refused run stores no notes for the "Ver reporte" link.
- **`item_not_reported` sat too close to `balance_item_not_reported` (professor).** Renamed `flow_item_not_reported`.
- **"As SimulationError" was vague (explainer).** The base classes stay (`EngineError` a `ValueError`, `MarketDataError` a `RuntimeError`), the constructor asserts as `SimulationError`'s does; params may hold lists of lists (`tried`).
- **`as_of_not_ended` named the wrong thing (explainer).** `build_inputs` compares with today's New York date, so the code is `as_of_in_future` with `today`; a date that is today but not over is `market_data_not_refreshed`.
- **Codes no small fixture reaches (explainer).** `no_ingest_run`, `history_too_short`, `too_few_quarters` and `no_balance_sheet` are covered by the AST tests (coded at the raise, catalogued) but not by a behaviour test: on Test Corp, dropping every current-assets fact trips the working-capital check first, and too few years trips the comparatives check first.

- **The valuation after the build (analyst, blocker).** `runs.run_baseline` values the rows after `build_inputs`; a base case whose terminal growth is at or above WACC raised a `FinancialMathError` with no code. It is now refused as `no_base_value` (group `no_value`) with the reason; any other `FinancialMathError` (a bad argument) still raises as itself. No Phase 1 company hits it on 808 four-weekly dates (analyst), but 58 lose the ERP − 1 SE bound to the same reason, so it is close. `runs.py` joins the AST scan, with `stored_choices` (rebuild) text only.
- **The ERP information lines (analyst).** `math_engine` caught `ValueError` for a too-short window, but `equity_risk_premium` raises `MarketDataError`, a `RuntimeError`: it now skips `erp_too_few_years` by code, so an information line can never refuse a run. Unreachable today (2009–2018 is 10 years from `SUPPORTED_FROM`).

Not taken here, filed as backlog: one date sure to work across the stock, the index and the 10-year yield (analyst: `covered_through` is per symbol); the first date that works on `erp_too_few_years` (analyst) and its standard error (professor); guards for the divide-by-zero cases at `math_engine.py` on a zero quarterly revenue or pretax sum (analyst; Phase 1 can't hit them); lessons per refusal (professor, product lead).

Also not taken: lessons per refusal (professor, product lead) and the ERP's standard error on `erp_too_few_years` (professor) go to backlog issues, not this PR; equity is not a balance item here, so the negative-equity exemption the professor raised doesn't arise (`BALANCE_ITEMS`, `math_engine.py:110`).

## Results on real data (Step 3, nov.14.2026)

On the restored snapshot (saved nov.10.2026, schema 23 after migrations):

- `python -m domains.analysis reproduce --all`: 903 of 903 stored runs reproduce to the cent.
- 1,680 asks (the eight Phase 1 companies on 2019-02-28, every 14 days from 2019-03-01 to today, the last six days, and tomorrow): 1,608 build, 72 are refused, and **every refusal carries a code**; no other kind of error. The refusals: `as_of_too_early` (8, the day before the first supported date), `as_of_in_future` (8, tomorrow) and `market_data_not_refreshed` (56, every date from Nov 1 on, because the snapshot's prices were downloaded on Oct 31; `covered_through` says 2026-10-30). No real company hits a data refusal on any of these dates.
