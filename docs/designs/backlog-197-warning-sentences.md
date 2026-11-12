# Backlog #197: a teaching sentence per run warning

Issue: https://github.com/sonderbot-ar/warren/issues/197 · Branch `backlog-197-warning-sentences` · Status: merged as v0.9.60 (PR #345, merge `7f912c6`, nov.12.2026).

From the professor's review of #172 (PR #195, `docs/designs/backlog-172-run-warning-codes.md`, Design review).

## Problem

Since v0.9.15 every run warning is a code with parameters (`domains/analysis/coded.py`, `RUN_NOTE_CODES`, 20 codes today) and an English line that says *what* happened ("Effective tax rate 61.2% clipped to 50%"). Nothing says *why it matters* or what a student should check. The missing-value reasons already have that (`domains/analysis/text.py`, `REASON_SENTENCES`, shown in the run report since #9). A student who sees "Counted as zero: minority_interest" learns nothing from it; a teaching platform (Decision 11) should turn each warning into a short lesson.

The issue left open who owns the sentence: the engine (beside `REASON_SENTENCES`) or the app's catalogue (`webapp/text/*.json`). The product lead also suggested a group per code (data quality against how far to trust the valuation).

## Decision on ownership (accepted by the product lead at design review)

The engine owns the **English lesson, its group, its params and its sources**; the app owns the **Spanish words**, filled from the same params. Same split as `REASON_SENTENCES` and every coded note so far: the engine says what is true and where it comes from (it knows its own thresholds and rules, and a test keeps a lesson for every code it emits), the app translates and lays it out (`webapp/text.py`: "The engine's coded notes … get their words here too, under `engine.<code>`"). The group is a code, not words, so the app can sort by it without parsing English. The engine's run report, read by the owner, shows the English lesson too.

## Plan

- **Step 0. This design doc.** Exit: reviewed. (Backlog items have no row in the build plan; the version is recorded in `docs/versions.md` and `docs/team-sync.md`.)

- **Step 1. The catalogue.** In `domains/analysis/text.py`:
  - `WARNING_GROUPS`: three group codes, in the order a screen reads them, with English names:
    - `data`: "The figures the run reads" (the inputs may be missing, old, or on different footings);
    - `assumption`: "An assumption outside its usual range" (Warren held it at a limit, as for the tax rate, or only flags it);
    - `valuation`: "How far to trust the value" (the structure of the DCF makes the value fragile or leaves part of it out).
  - `Lesson(group, why, params, reference, warren_rule)` (frozen dataclass) and `WARNING_LESSONS: dict[str, Lesson]`, one per code in `RUN_NOTE_CODES` except `note_text` (a stored line Warren could not code: there is nothing to teach about free text). `why` is one or two plain sentences, why this matters for the value and what to look at, with `{name}` placeholders for `params` (product lead's blocker: a threshold written into the English would be typed again by hand in Spanish). `params` hold the engine's own thresholds, read from its constants: a float is a fraction (0.1 for 10%, 0.03 for 3 percentage points) and the template writes the unit; an int is a count. `lesson.text()` gives the English with the numbers filled in. `reference` is a published source or None; `warren_rule` says where a rule or threshold of Warren's own is written (a file, a constant, a build-plan rule), or None; at least one is set, so a student never reads a Warren threshold as a textbook law (#84 asks for a source for the 3-point line and stays open). `lesson.source()` joins the two for the engine's own report; a screen can show `reference` alone and say "regla de trabajo de Warren" when `warren_rule` is set.
  - The groups and sources (the `why` texts are in the code; the explainer, analyst, professor and product lead reviewed them there):

    | Code | Group | Source |
    |---|---|---|
    | `beyond_history` | data | Warren rule: the company list's coverage note (`domains/fundamentals/universe.csv`), point-in-time data (Structure Guide, Decision 7) |
    | `data_warning` | data | Warren rule (a warning raised while reading the filings) |
    | `concept_map_changed` | data | Warren rule: the concept map decides which XBRL tag counts as which line (Structure Guide, Decision 2) |
    | `fundamentals_stale` | data | SEC Forms 10-Q and 10-K, General Instruction A (due 40–45 days after a quarter, 60–90 after a year); 135 days is a Warren working rule (`math_engine.STALE_AFTER`). The lesson says the next report is often not due yet: 14 of the 15 stored notes are Feb 15 runs whose 10-K was filed days later (analyst) |
    | `balance_carried_forward` | data | Warren rule D3 (`docs/build-plan.md`, balance sheet) |
    | `balance_counted_zero` | data | Warren rule D3 (`docs/build-plan.md`, balance sheet) |
    | `balance_date_differs` | data | Koller, Goedhart and Wessels, *Valuation* (7th ed.), "Moving from Enterprise Value to Value per Share"; Warren rule D3 |
    | `shares_cover_differs` | data | FASB ASC 260, *Earnings per Share*; Warren rule D4 (`docs/build-plan.md`); the 10% line is a Warren working rule (`math_engine.SHARES_TOLERANCE`) |
    | `margin_quarter_two_bases` | data | FASB Concepts Statement No. 8, ch. 3 (comparability) |
    | `seed_year_two_bases` | data | FASB Concepts Statement No. 8, ch. 3 (comparability) |
    | `run_mixes_meanings` | data | FASB Concepts Statement No. 8, ch. 3 (comparability) |
    | `cost_of_debt_out_of_bounds` | assumption | Damodaran, *Investment Valuation* (3rd ed.), ch. 8, cost of debt (a rating or a market yield, not interest over book debt); 0–15% is a Warren working rule (`math_engine.COST_OF_DEBT_BOUNDS`) |
    | `tax_rate_clipped` | assumption | Damodaran, *Investment Valuation* (3rd ed.), ch. 10, effective and marginal tax rates; 0–50% is a Warren working rule (`math_engine.TAX_RATE_BOUNDS`) |
    | `margin_outside_history` | assumption | Nissim and Penman (2001), "Ratio Analysis and Equity Valuation", *Review of Accounting Studies* 6 (profit margins revert); Fama and French (2000), "Forecasting Profitability and Earnings", *Journal of Business* 73(2) (profitability reverts); 2 standard deviations over 12 quarters is a Warren working rule |
    | `wacc_outside_its_parts` | assumption | Brealey, Myers and Allen, *Principles of Corporate Finance*, the weighted-average cost of capital: a weighted average with positive weights lies between its parts |
    | `thin_terminal_spread` | valuation | Damodaran, *Investment Valuation* (3rd ed.), ch. 12, terminal value; the 3-point line is a Warren working rule (`math_engine.TERMINAL_SPREAD_WARNING`; #84) |
    | `thin_terminal_spread_at_erp_bound` | valuation | as `thin_terminal_spread` |
    | `no_value_per_share` | valuation | Gordon and Shapiro (1956), *Management Science* 3(1); Gordon (1962), *The Investment, Financing, and Valuation of the Corporation*; Damodaran, *Investment Valuation* (3rd ed.), ch. 12: the growing perpetuity has a value only when growth is below the discount rate |
    | `erp_bounds_not_computed` | valuation | Damodaran, "Equity Risk Premiums (ERP): Determinants, Estimation and Implications" (annual update): the historical premium's standard error |

  Tests (`tests/analysis/test_warning_lessons.py`): the lessons' keys are exactly `RUN_NOTE_CODES − {"note_text"}`, so a new code fails until it has a lesson; every group is in `WARNING_GROUPS`; each `why`'s placeholders are exactly its `params`; each `text()` is one or two sentences with no code names; each lesson has a `reference` or a `warren_rule`; each lesson's `params` equal the engine's constants (`STALE_AFTER`, `SHARES_TOLERANCE`, `COST_OF_DEBT_BOUNDS`, `TAX_RATE_BOUNDS`, `MARGIN_SIGMAS`, `HISTORY_QUARTERS`, `TERMINAL_SPREAD_WARNING`), a lesson with no threshold has none, and the `warren_rule` text names the same numbers and says "working rule" (so a changed constant fails until the rule's words follow). A lesson is about the code, not one run: the run's own numbers are in the note's text. Exit: tests and ruff pass.

- **Step 2. The group on a run's notes.** `RunNotes.to_dict()` (`domains/analysis/runs.py`) gives each note a `group` (the code from `WARNING_LESSONS`, `null` for `note_text`). Nothing else in the output changes; `Coded` itself is unchanged, so `reported_period` and the what-if are untouched. The `notes` command's plain-text output prints the group name before each line. Tests: a baseline fixture's notes carry their group; a `note_text` line carries `null`; the JSON keeps every existing field. Exit: tests pass, existing `run_notes` tests unchanged.

- **Step 3. The lesson in the run report.** The run report's "Warnings" section (`domains/analysis/report.py`, now one bullet per stored line) reads the coded notes (`runs.run_notes`) and, under each line, adds "*Why it matters:* {why} (Source: {source})", once per code . Lines are ordered as stored; the grouping is for screens, not this flat report. A run with no coded notes (`recorded: false`) prints as before. Each code is a different lesson; the second line of the same code gets no repeat. Tests: the stored lines print unchanged and in order, each code's lesson appears exactly once; a run stored as text only (`note_text`) has no lesson; "None." when there are no warnings. Exit: tests pass; no stored data, number or reproduce check changes (the report is rendered on demand from stored rows).

## Alternatives considered

- **The app's catalogue owns the sentence.** It must translate anyway. But the sentence quotes the engine's thresholds (135 days, 10%, 0–50%, 3 points), which would then live in two repos' worth of code with no test tying them; the engine's own report would stay without the lesson; and the owner reads the engine's reports, not the app.
- **Put the lesson in each note's `params` or `text`.** Would change every stored note and `runs.notes`, which the reproduce check and the backfill compare byte for byte. A lookup by code changes nothing stored.
- **One sentence per code with the run's numbers filled in.** The note's own text already carries the numbers; a lesson that stays the same for every run is translated once.
- **More groups (e.g. split "data" into missing vs not comparable).** Three is what a screen can show as headings; the order inside a group is the engine's.

## Files to change

`domains/analysis/text.py`, `domains/analysis/runs.py`, `domains/analysis/__main__.py` (the `notes` command's text output), `domains/analysis/report.py`, `tests/analysis/test_warning_lessons.py` (new), `tests/analysis/test_run_notes.py`, `tests/analysis/test_report_cli.py` if it pins the Warnings section; at merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves every screen that shows a run's notes (brief Q3, Q5 and Q8, F2's first screen) and design principle "explain, don't just flag". Added: `domains.analysis.text.WARNING_GROUPS` (`data`, `assumption`, `valuation`, in reading order), `WARNING_LESSONS` (per code: `group`, `why`, `source`, English), and `group` on each note in `run_notes(...).to_dict()`. Nothing renamed or removed; no stored data changes; no migration. Added for each lesson: `params` (the thresholds; floats are fractions), `reference` (published, or null) and `warren_rule` (or null). The app writes its own Spanish template per code under its own keys in `webapp/text/es.json`, fills it from `params` in the region's number format, and can test its catalogue against `WARNING_LESSONS`'s keys as it does against `RUN_NOTE_CODES`. A `note_text` note has `group: null` and no lesson. Whether a screen shows `source` to students is the front-end team's choice.

## Design review (nov.12.2026)

- **Explainer.** Three-sentence lessons: cut to one or two, and a test counts them. `data_warning`'s rule now says where it comes from. The report's "once per code" is now explicit. Ownership settled by the product lead. Key scheme: the app owns its keys; the doc no longer suggests one. Ideas left as is: the order inside a group is the stored order; simulation note codes are out of scope (`SIMULATION_NOTE_CODES` are not a run's notes); an unknown stored code gets `group: null`.
- **Analyst.** Blocker taken: `fundamentals_stale` said a newer report "probably exists", but 14 of the 15 stored notes are Feb 15 runs whose 10-K was filed days later (CAT, JNJ, KO, XOM); the lesson now says the next report is often not due yet, or Warren may be missing one. Taken: `shares_cover_differs` says Warren divides by the cover count and names a figure in the wrong unit (KO 2019's diluted shares filed in millions), and drops "a split Warren missed" (splits are adjusted on both counts); `balance_counted_zero` no longer says "usually none" and gives both directions (CAT's current debt is counted zero in 113 of 113 runs; most real zeros are cash-side items, which make the value too low); `tax_rate_clipped` says "booked", not "paid"; `balance_date_differs` reworded; "shares" in `run_mixes_meanings` is "each quarter's share of the year"; the `assumption` group's description. The 135-day line itself and CAT's current debt are follow-up issues. Not taken: testing the 40–45 and 60–90 day figures (they are the SEC's, cited, not Warren constants).
- **Professor.** Citations checked: Damodaran ch. 10 confirmed, ch. 8 and 12 consistent with the book; FASB CON 8 ch. 3, Fama and French (2000), Gordon (1962), ASC 260, SEC General Instruction A confirmed. Blockers taken: the stale lesson (as the analyst's); `margin_outside_history` now cites Nissim and Penman (2001) for margins and says "profit margins", Fama and French kept for profitability. Suggestions taken: Koller edition and chapter, Gordon and Shapiro (1956), the normal gap between diluted and cover shares. Ideas for student screens (links per source, group intros) are the front-end's.
- **Product lead.** Split accepted. Blocker taken: thresholds are `params`, so the Spanish fills the same numbers in the region's format. Groups and order accepted (brief, "Notes on an estimate": data first); suggested headings "Los datos de partida", "Supuestos fuera de lo habitual", "Qué tanto confiar en el valor". Taken: `source` split into `reference` and `warren_rule`; plainer English throughout ("percentage points", "an analyst", no "footings", "recast" or "XBRL tag", "the range Warren shows by moving the equity risk premium up and down", "a new run made today"). Ideas filed as a follow-up issue: `anchors` per note, a separate `check` field, a revision mark per lesson.

## PR review (nov.12.2026)

- **Gatekeeper: GO** (PR #345; 2,159 passed, 10 skipped; ruff clean; CI green). No blockers. Ideas taken in the record commit: Step 0 no longer claims a build-plan line; the margin lesson says "up to 12 quarters" (`post_check_notes` uses the quarterly rows there are, at most `HISTORY_QUARTERS`). Into #344: `Lesson.params` read-only; a retired code would print as "Not coded".
