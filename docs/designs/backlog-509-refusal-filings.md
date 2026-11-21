# Backlog #509: refusals that name a filing carry its link

Issue: https://github.com/sonderbot-ar/warren/issues/509 (front-end request) · Branch `backlog-509-refusal-filings` · Version v0.10.23 when merged.

Status: In progress (nov.21.2026).

## Problem

The brief ("When an estimate can't be built") says a refusal that names a filed figure links that filing with "Ver reporte", so the student can open the report and see the figure. The built first screen (F2 Step 4b, PR #510, `webapp/refusal.py`) can't: the refusal params carry at most an accession number, never the filing's form, date or EDGAR address, and a refusal has no stored run whose sources the app could read them from.

- `zero_divisor` carries `accession_no` (or `inputs` for a derived fourth quarter) but no CIK, so the app would need its own SQL to build the address.
- `balance_item_negative` and `securities_exceed_current_assets` name a `period_end` but no filing.
- `balance_item_not_reported` and `flow_item_not_reported` name a period, not the filing Warren looked in.
- `no_share_count`'s `skipped` counts carry an accession, not a link.

## Plan

**Step 0. This doc.**

**Step 1. A `filings` param on the six codes.**

- A new constant `coded.FILING_REFUSAL_CODES`: `zero_divisor`, `balance_item_negative`, `securities_exceed_current_assets`, `balance_item_not_reported`, `flow_item_not_reported`, `no_share_count`. A refusal with one of these codes coming out of `math_engine.build_inputs` always has `params["filings"]`: a list of `{accession_no, form, filed_at, url}`, the same shape as a run source's `filing` (`sources._filing`, the #140 `Filing`), so the app reuses its *Fuente* rendering: plain dicts, `filed_at` as ISO text, so the param survives `json.dumps`. Every accession comes from a row of the company's facts, so every entry has a form, a date and a link (tested). An empty list when Warren found no filing; the screen then shows no link.
- Which filings, per code (each accession once, in the order below; within a list, the order the figures are named). The screen matches a filing to the figure it backs by `accession_no` (`skipped[i].accession_no`, `zero_divisor`'s `accession_no` or `inputs`):
  - `zero_divisor`: one quarter or year reported as filed (`accession_no` set, `inputs` empty): its filing; a fourth quarter Warren derived (`accession_no` null): the filings in `inputs`, in their order (the year, then the three quarters); a sum: none (as today, a sum has no single filing).
  - `balance_item_negative`: the filing of the negative figure (its inputs if it were derived).
  - `securities_exceed_current_assets`: current assets' filing first, then the securities lines summed, then cash when `with_cash`; usually all one filing, so one entry.
  - `no_share_count`: `none_above_zero`: the filings of every count in `skipped` (the newer and the older ones; a cover count and a diluted count from one 10-Q share one entry); `none_reported`: none.
  - `balance_item_not_reported` and `flow_item_not_reported` (a line that is missing): the newest filing Warren read for that period, among the facts the run's own point-in-time history holds: the balance sheet's date (`period_end`), or the fiscal year or quarter (`fiscal_year`, `quarter`; `balance_item_not_reported` from the balance step has `period_end`, from the working-capital history `fiscal_year`; `flow_item_not_reported` always `fiscal_year` and `quarter`). Only reported facts count, those with an accession of their own (a derived quarter has `accession_no` null). A missing balance line looks among balances (no `period_start`), a missing flow line among flows, so the filing is one whose statement should have had the line: a 10-K's income statement covers three years, its balance sheet two (on the test company, a missing FY2017 cash names the FY2018 10-K, a missing FY2017 operating income the FY2019 10-K). Newest by filing date, then accession number on a tie. None read for the period gives an empty list.
- How: the engine knows the facts where it refuses, but not a filing's form or the company's CIK. `EngineError` gains an internal attribute `accessions` (a list, or None), set at the raise sites that know the figure's filing (`balance_item_negative`, both `securities_exceed_current_assets`, both `no_share_count`, `zero_divisor`; the three missing-line raises leave it None). It is never put in `params`, so `coded()`, `refusal()` and any serialised error show only `filings`. `_build_inputs` sets it for a missing line from the run's `History` when it is None. `build_inputs`, which has the connection, looks up the company's CIK from the ticker, and turns the accessions into `filings` with `reported._Filings(conn, cik).get(accession)` and `sources._filing` (one query per company, the same lookup and shape `sources.run_sources` uses), only for the six codes.
- Point-in-time: every accession comes from facts the run read as of its date, and a filing's form and filing date never change, so nothing after `as_of` enters. `reported._Filings` reads the form and date of an accession only.
- Callers that use `_balance` or `_operating_nwc` directly (the input charts' missing points, `single_values` and `inputs`) keep their params unchanged: the accessions are an attribute, not a param, so their notes don't change.
- English texts are unchanged; no number, note or stored row changes; `reproduce` is untouched (refused runs store nothing).
- Tests (`tests/analysis/test_refusal_codes.py`): each code reached through `build_inputs` on the test company carries the expected filings with form, date and the EDGAR folder URL; a derived fourth quarter's zero lists its input filings; a sum lists none; a missing line in a year lists the newest filing for that year; `none_reported` lists none; the existing exact-params tests gain the `filings` key; a test that every refusal with one of the six codes has `filings` and others never do; a point-in-time test: an amended 10-K filed after the run's date that gives the missing line's period is never listed (it guards the history read staying point-in-time if this lookup is ever moved to a direct query).
- Exit: full suite, `ruff check` and `ruff format --check` green; on the snapshot, every refused ask with one of the six codes over the eight companies and a grid of dates has `filings`, each with a form and a link; if none is reachable, the doc says so and the tests are the evidence.

**Step 2. Docs** (its own commit). The brief's "When an estimate can't be built" names the `filings` param, where each code's link comes from and that `accession_no` joins a filing to its figure; `docs/team-sync.md` entry on merge.

## Alternatives considered

- **The app builds the link itself from `accession_no` and the company's CIK.** The app would need its own SQL into the facts table (the front-end never reads engine tables), and the missing-line codes have no accession to start from.
- **Put the accessions in `params` at the raise site and expand them later.** `single_values` and `inputs` read `_balance`'s and `_operating_nwc`'s params straight into chart notes; a half-built param would leak there. An attribute keeps those params as they are.
- **Give the engine the CIK and a filings lookup in `History`.** It would put a database read in the pure computing path for the sake of a refusal; the lookup belongs in `build_inputs`, which already enriches `market_data_not_refreshed` the same way (#381).
- **For a missing line, every filing for the period.** The issue asks for the newest one, which is the one Warren's latest-mode read used; listing every filing would bury it.

## Files to change

`domains/analysis/coded.py`, `domains/analysis/math_engine.py`, `tests/analysis/test_refusal_codes.py`, `docs/product/brief.md`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` is unchanged (a backlog item).

## Review notes

- *Explainer* (15 points): the doc now says the constant is new, lists the raise sites that set the accessions, says they never enter `params`, defines "newest" and the tie-break, says which key each code uses and what counts as reported, names `sources._filing`, says what the point-in-time test guards, gives the exit when no real refusal is reachable, and splits the brief into Step 2. Question numbers (Q3, Q5, Q8) are the brief's, as in every engine doc.
- *Front-end lead* (GO, three changes, all taken): plain dicts with ISO dates that survive `json.dumps` (tested); no null form or date (tested; every accession comes from a fact row); `accession_no` joins a filing to its figure, and the securities order is current assets, securities, cash.
- Analyst and professor not run: no method, number or source rule changes; the gatekeeper reviews the PR.
- While building: a missing balance line first named the newest filing of any fact for the year (the FY2019 10-K for FY2017 cash, whose balance sheet doesn't show FY2017); it now looks among balances only, and the test pins the FY2018 10-K.

## Product impact

Adds one param, `filings`, to six refusal codes (brief "When an estimate can't be built"; Q3, Q5, Q8 and every value per share). Nothing is renamed or removed: `accession_no`, `inputs` and `skipped` stay, so the screen built in PR #510 keeps working unchanged and can switch to `filings` when it adds "Ver reporte". No question changes status.
