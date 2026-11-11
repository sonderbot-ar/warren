# Backlog #297 item 1 (run part): a run whose revenue crosses a tag's change of meaning

Issue: https://github.com/sonderbot-ar/warren/issues/297 · Branch `backlog-297-run-meaning` · Status: in progress (nov.11.2026).

Built here: item 1's second half, the run note. v0.9.49 built its first half (`facts.meaning_state` says "mixed" for a derived quarter worked out across the change); v0.9.50 built item 2 for a series of reported periods. Left in #297: item 2 for trailing sums, track records and forecast errors; items 4, 5, 7, 11, 12, 13.

## Problem

Exxon's `us-gaap:Revenues` meant sales until the 10-Q of 2019-11-06 and total revenues and other income from then on (`facts.MeaningChange`). The reported view says so on a line (v0.9.49) and across a series (v0.9.50). A run says nothing.

A run reads revenue in three places (`math_engine.build_inputs`):

1. **The seed** (`_revenue_seed`): the last four reported quarters, which the forecast grows from; when a year's quarters do not add up to the year, also that year's annual figure (year × each quarter's share).
2. **The quarterly margins** (`_drivers`): EBIT ÷ revenue for each of the last 12 quarters, averaged by fiscal quarter, for forecast quarters 1–8.
3. **The annual history** (`_history_rows`, `_drivers`): the last three fiscal years' revenue, the denominator of the annual margin (years 3–5) and of the D&A, capex and working-capital shares.

Growth is not one of them: it averages same-filing 10-K comparisons (D2), and each comparison is current year against prior year as one filing shows them, so both sides of each carry one meaning.

On a run dated after the change, these figures can carry different meanings. Example, as of 2020-03-01 (the 10-K of 2020-02-26 refiled 2017 and 2018 on the new meaning): the seed is FY2019Q1 and Q2 (sales, never refiled) and FY2019Q3 and Q4 (total revenues and other income); the forecast grows from a base half on one line and half on another. The margin window FY2017Q1–FY2019Q4 divides EBIT by sales in most quarters and by the broader total in a few, and the annual margin for years 3–5 divides by the broader total, so the margin the forecast applies does not match the revenue it applies it to. The analyst counted 90 of Exxon's 100 stored runs dated after the change (issue, item 1); how many actually read figures on both sides is Step 2's scan.

No number is wrong in the sense of a bug: each figure is what Exxon filed. But the run mixes two definitions without saying so, and the brief's Q3 and Q5 (a run's value and its assumptions) cannot explain an Exxon run honestly.

## Plan

**Step 0. This doc.** No build plan change (backlog item).

**Step 1. The note (`math_engine`).**

- While building, the run records each revenue fact it reads, by part: `seed` (the four seed quarters, plus the year's annual figure when the year × share rule applies), `operating_margin` (the margin window's quarters), `history` (the three annual years). Kept on `EngineResult` in a field that is never stored (`revenue_read`), so stored runs, rows and snapshots are unchanged.
- `build_inputs` also reads `facts.tag_meaning_changes(conn, cik, ["revenue"], as_of)` and the filing date of every accession of the company (one query, as `reported._Filings` does; the helper moves to `facts.filing_dates` and `reported` uses it), inside the block that already records data warnings. Both are point in time: the changes come from filings public on `as_of`; the filing dates are only used for the accessions of facts already read as of `as_of`.
- Each fact's state for a change follows `reported._series_meaning_notes` (v0.9.50), now shared as `facts.state_for_change`: `meaning_state` when the fact's tag is the changed one; "old" when under the changed tag before the change or under the other tag; "other" for any other tag (nothing is known of its meaning).
- Note `run_mixes_meanings`, one per change, ordered by filing date, when across all three parts any figure is "mixed", or at least one is "new" and at least one is not. Same rule as the series note, so the two never disagree on the same facts. Params: `item` (`revenue`), `tag`, `other_tag`, `changed_on` (ISO), `form`, `accession_no` (the first filing that shows the change), `old_periods`, `new_periods`, `mixed_periods`, `other_tag_periods` (period labels in time order, quarters `FYyyyyQn` and years `FYyyyy`; each label once), and `parts` (the run parts, in the order `seed`, `operating_margin`, `history`, whose own figures do not all carry one meaning; can be empty when each part is on one meaning but the parts differ, e.g. a margin on sales applied to a seed on the broader total).
- English fallback (Exxon as of 2020-03-01, wording to be checked against the real params): "This run reads revenue as us-gaap:Revenues with more than one meaning: FY2017Q1, … carry the tag's earlier meaning; FY2019Q3, … the meaning the 10-Q filed 2019-11-06 gave it. The forecast's seed and the margins (quarterly and annual) are worked out on revenue that is not like for like, so the margin the forecast applies may not match the revenue it applies it to. Only the periods the change shows are also filed on the earlier meaning, under us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax." The second sentence names the parts in `parts`, or, when `parts` is empty, says each part is on one meaning but they differ.
- No value, row, method text or source changes. The code joins `RUN_NOTE_CODES`.
- Tests (`tests/analysis/test_math_engine.py`, Test Corp with `Revenues` 4% higher from its Q3 2019 10-Q and the old figures kept under the contract-revenue tag, the `_redefine_revenues` edit of v0.9.46, moved to a shared test helper): a run as of a date after the change gets the note with the periods in the right lists, the parts that mix, the tags and the date; the run's rows equal those of the same run without the edit scaled where the facts moved (no row text changes because of the note); a run before the change is public gets none; unchanged Test Corp gets none; a run whose three parts are each wholly on the new meaning gets none; the code is in `RUN_NOTE_CODES`; `reported_series` gives the same notes as before (the shared helper changes nothing there).
- Exit: full suite passes, ruff clean.

**Step 2. Real data** (snapshot `warren-20261110T202538Z`). Scan every stored baseline run date for the note, and rebuild every stored baseline run on main and on the branch. Expect: every row identical to main; the only change is the new note, on Exxon runs dated after 2019-11-06 that the scan names; every stored run still reproduces (`python -m domains.analysis reproduce --all`).
- Exit: as expected; the results go below.

**Point in time.** One new query per run (the company's filing dates), used only for accessions already read as of `as_of`; `tag_meaning_changes` is already point in time. **LLMs.** None. **Invariants.** No number changes; stored runs reproduce from their stored rows; `rebuild` of named runs differs in notes only (rows are compared, notes are not).

## Alternatives considered

- **One note per part.** Three notes on most affected runs, saying the same break three times; the `parts` param carries the same information.
- **Note only when a part mixes internally.** Misses the case where each part is on one meaning but they differ (a margin on sales applied to a seed on the broader total), which is the mismatch that matters most for the forecast.
- **Restate onto one meaning.** Item 4 and item 11 (like-for-like growth, margins on sales) ask a version of this. It changes numbers and is a method choice; this step only says where the break is.
- **Include growth.** Each growth figure is one filing's current against prior year, on one meaning; the three comparisons may sit on different meanings from each other (the 10-K of 2019 on sales, of 2020 on the broader total), but each is a growth rate, a ratio of like with like, so averaging them is sound. Left out; said in Limits.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/fundamentals/facts.py` (`filing_dates`, `state_for_change`), `domains/analysis/reported.py` (uses the shared helpers; no behaviour change), `tests/analysis/test_math_engine.py` (or a new `tests/analysis/test_run_meaning.py`), this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

- **Added:** run-note code `run_mixes_meanings`, params as in Step 1, on `run_notes(conn, run_id)` and the pipeline's run. Nothing renamed or removed; no value changes.
- Serves brief Q3 and Q5 (a run's value, its assumptions and forecast): an Exxon run dated after 2019-11-06 can now say its revenue mixes two definitions. Q1, Q2 and Q6: no change.
- Stored runs keep their stored notes; a new run (or `run_notes --backfill` on a run stored before 0021) gets it. The app shows it with the run's other notes; rank it with `tag_changed_meaning` (brief, "Notes on a reported figure": "can't be read as asked" first).
- Suggested Spanish, generic as the series note's (no line names until item 5): "Esta corrida usa ingresos de {empresa} con una etiqueta XBRL que no mide lo mismo en todos los periodos: {old} usan la definición anterior y {new} la definición nueva, desde que el {form} presentado el {fecha} cambió lo que mide la etiqueta. {partes} se calculan sobre ingresos que no son comparables entre sí." Never "reexpresado" or "presentación".

## Limits

- Only revenue, and only a change the filings show (`tag_meaning_changes`); a reclassification with no other tag (item 13) is not seen.
- Growth's three same-filing comparisons can each sit on a different meaning; not flagged (Alternatives).
- EBIT, D&A, capex and working capital are not scanned for a change of meaning; only revenue is (as in v0.9.46).
- Stored runs are not re-noted; the note appears on new runs and backfills.
