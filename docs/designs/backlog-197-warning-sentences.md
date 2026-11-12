# Backlog #197: a teaching sentence per run warning

Issue: https://github.com/sonderbot-ar/warren/issues/197 · Branch `backlog-197-warning-sentences` · Status: In progress (nov.12.2026).

From the professor's review of #172 (PR #195, `docs/designs/backlog-172-run-warning-codes.md`, Design review).

## Problem

Since v0.9.15 every run warning is a code with parameters (`domains/analysis/coded.py`, `RUN_NOTE_CODES`, 20 codes today) and an English line that says *what* happened ("Effective tax rate 61.2% clipped to 50%"). Nothing says *why it matters* or what a student should check. The missing-value reasons already have that (`domains/analysis/text.py`, `REASON_SENTENCES`, shown in the run report since #9). A student who sees "Counted as zero: minority_interest" learns nothing from it; a teaching platform (Decision 11) should turn each warning into a short lesson.

The issue left open who owns the sentence: the engine (beside `REASON_SENTENCES`) or the app's catalogue (`webapp/text/*.json`). The product lead also suggested a group per code (data quality against how far to trust the valuation).

## Decision on ownership (proposed; product lead to confirm at review)

The engine owns the **English lesson, its group and its source**; the app owns the **Spanish words**. Same split as `REASON_SENTENCES` and every coded note so far: the engine says what is true and where it comes from (it knows its own thresholds and rules, and a test keeps a lesson for every code it emits), the app translates and lays it out (`webapp/text.py`: "The engine's coded notes … get their words here too, under `engine.<code>`"). The group is a code, not words, so the app can sort by it without parsing English. The engine's run report, read by the owner, shows the English lesson too.

## Plan

- **Step 0. This design doc.** Status "In progress" in the build plan's roadmap line (backlog items have no row of their own). Exit: reviewed.

- **Step 1. The catalogue.** In `domains/analysis/text.py`:
  - `WARNING_GROUPS`: three group codes, in the order a screen reads them, with English names:
    - `data`: "The figures the run reads" (the inputs may be missing, old, or on different footings);
    - `assumption`: "An assumption outside its usual range" (Warren bounded it or flags it as unusual);
    - `valuation`: "How far to trust the value" (the structure of the DCF makes the value fragile or leaves part of it out).
  - `Lesson(group, why, source)` (frozen dataclass) and `WARNING_LESSONS: dict[str, Lesson]`, one per code in `RUN_NOTE_CODES` except `note_text` (a stored line Warren could not code: there is nothing to teach about free text). `why` is one or two plain sentences: why this matters for the value, and what to look at. `source` is a published reference, or, where the threshold is Warren's own, the words "Warren working rule" and where the rule is written (so a student never reads a threshold as a textbook law; #84 asks for a source for the 3-point line and stays open).
  - The proposed groups and sources (the `why` texts are in the code and reviewed there):

    | Code | Group | Source |
    |---|---|---|
    | `beyond_history` | data | Warren rule: the company list's coverage note (`domains/fundamentals/universe.csv`), point-in-time data (Structure Guide, Decision 7) |
    | `data_warning` | data | Warren rule (a warning raised while reading the filings) |
    | `concept_map_changed` | data | Warren rule: the concept map decides which XBRL tag counts as which line (Structure Guide, Decision 2) |
    | `fundamentals_stale` | data | SEC Forms 10-Q and 10-K, general instructions (due 40–45 days after a quarter, 60–90 after a year); 135 days is a Warren working rule (`math_engine.STALE_AFTER`) |
    | `balance_carried_forward` | data | Warren rule D3 (`docs/build-plan.md`, balance sheet) |
    | `balance_counted_zero` | data | Warren rule D3 (`docs/build-plan.md`, balance sheet) |
    | `balance_date_differs` | data | Koller, Goedhart and Wessels, *Valuation* (McKinsey), from enterprise value to equity value: net debt and the claims on the firm are read at the valuation date |
    | `shares_cover_differs` | data | Warren rule D4 (`docs/build-plan.md`); diluted shares as in ASC 260, *Earnings per Share*; the 10% line is a Warren working rule (`math_engine.SHARES_TOLERANCE`) |
    | `margin_quarter_two_bases` | data | FASB Concepts Statement No. 8, ch. 3 (comparability) |
    | `seed_year_two_bases` | data | FASB Concepts Statement No. 8, ch. 3 (comparability) |
    | `run_mixes_meanings` | data | FASB Concepts Statement No. 8, ch. 3 (comparability) |
    | `cost_of_debt_out_of_bounds` | assumption | Damodaran, *Investment Valuation* (3rd ed.), ch. 8, cost of debt (a rating or a market yield, not interest over book debt); 0–15% is a Warren working rule (`math_engine.COST_OF_DEBT_BOUNDS`) |
    | `tax_rate_clipped` | assumption | Damodaran, *Investment Valuation* (3rd ed.), ch. 10, effective and marginal tax rates; 0–50% is a Warren working rule (`math_engine.TAX_RATE_BOUNDS`) |
    | `margin_outside_history` | assumption | Fama and French (2000), "Forecasting Profitability and Earnings", *Journal of Business* 73(2): profitability reverts toward its mean; 2 standard deviations over 12 quarters is a Warren working rule |
    | `wacc_outside_its_parts` | assumption | Brealey, Myers and Allen, *Principles of Corporate Finance*, the weighted-average cost of capital: a weighted average with positive weights lies between its parts |
    | `thin_terminal_spread` | valuation | Damodaran, *Investment Valuation* (3rd ed.), ch. 12, terminal value; the 3-point line is a Warren working rule (`math_engine.TERMINAL_SPREAD_WARNING`; #84) |
    | `thin_terminal_spread_at_erp_bound` | valuation | as `thin_terminal_spread` |
    | `no_value_per_share` | valuation | Gordon (1962), *The Investment, Financing, and Valuation of the Corporation*; Damodaran, *Investment Valuation* (3rd ed.), ch. 12: the growing perpetuity has a value only when growth is below the discount rate |
    | `erp_bounds_not_computed` | valuation | Damodaran, "Equity Risk Premiums (ERP): Determinants, Estimation and Implications" (annual update): the historical premium's standard error |

  Tests (`tests/analysis/test_warning_lessons.py`): the lessons' keys are exactly `RUN_NOTE_CODES − {"note_text"}`, so a new code fails until it has a lesson; every group is in `WARNING_GROUPS`; every `why` and `source` is non-empty, has no `{` placeholder (a lesson is about the code, not one run's numbers; the numbers are in the note's own text) and no code name in backticks; every threshold the engine uses (`STALE_AFTER`, `SHARES_TOLERANCE`, `COST_OF_DEBT_BOUNDS`, `TAX_RATE_BOUNDS`, `MARGIN_SIGMAS`, `HISTORY_QUARTERS`, `TERMINAL_SPREAD_WARNING`) that a `why` names agrees with the constant (the test reads the numbers from the constants, so changing a threshold fails until the sentence follows). Exit: tests and ruff pass.

- **Step 2. The group on a run's notes.** `RunNotes.to_dict()` (`domains/analysis/runs.py`) gives each note a `group` (the code from `WARNING_LESSONS`, `null` for `note_text`). Nothing else in the output changes; `Coded` itself is unchanged, so `reported_period` and the what-if are untouched. The `notes` command's plain-text output prints the group name before each line. Tests: a baseline fixture's notes carry their group; a `note_text` line carries `null`; the JSON keeps every existing field. Exit: tests pass, existing `run_notes` tests unchanged.

- **Step 3. The lesson in the run report.** The run report's "Warnings" section (`domains/analysis/report.py`, now one bullet per stored line) reads the coded notes (`runs.run_notes`) and, under each line, adds "*Why it matters:* {why} (Source: {source})", once per code (two `balance_*` lines of the same code share one lesson). Lines are ordered as stored; the grouping is for screens, not this flat report. A run with no coded notes (`recorded: false`) prints as before. Tests: a fixture run with a counted-zero item shows the lesson once; a `note_text` line has none; "None." when there are no warnings. Exit: tests pass; no stored data, number or reproduce check changes (the report is rendered on demand from stored rows).

## Alternatives considered

- **The app's catalogue owns the sentence.** It must translate anyway. But the sentence quotes the engine's thresholds (135 days, 10%, 0–50%, 3 points), which would then live in two repos' worth of code with no test tying them; the engine's own report would stay without the lesson; and the owner reads the engine's reports, not the app.
- **Put the lesson in each note's `params` or `text`.** Would change every stored note and `runs.notes`, which the reproduce check and the backfill compare byte for byte. A lookup by code changes nothing stored.
- **One sentence per code with the run's numbers filled in.** The note's own text already carries the numbers; a lesson that stays the same for every run is translated once.
- **More groups (e.g. split "data" into missing vs not comparable).** Three is what a screen can show as headings; the order inside a group is the engine's.

## Files to change

`domains/analysis/text.py`, `domains/analysis/runs.py`, `domains/analysis/__main__.py` (the `notes` command's text output), `domains/analysis/report.py`, `tests/analysis/test_warning_lessons.py` (new), `tests/analysis/test_run_notes.py`, `tests/analysis/test_report_cli.py` if it pins the Warnings section; at merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves every screen that shows a run's notes (brief Q3, Q5 and Q8, F2's first screen) and design principle "explain, don't just flag". Added: `domains.analysis.text.WARNING_GROUPS` (`data`, `assumption`, `valuation`, in reading order), `WARNING_LESSONS` (per code: `group`, `why`, `source`, English), and `group` on each note in `run_notes(...).to_dict()`. Nothing renamed or removed; no stored data changes; no migration. The app translates `why` under its own keys (e.g. `engine.lesson.<code>`) and can test its catalogue against `WARNING_LESSONS`'s keys as it does against `RUN_NOTE_CODES`. A `note_text` note has `group: null` and no lesson. Whether a screen shows `source` to students is the front-end team's choice.
