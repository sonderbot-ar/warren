# Backlog #352: say when a newer report is in but its quarter wasn't read, and the late-filing notice

Issue: https://github.com/sonderbot-ar/warren/issues/352 · Branch `backlog-352-underived-q4` · Status: In progress (nov.13.2026)

## Problem

The review of backlog #349 (PR #351, v0.9.62) left three follow-ups on the stale warning.

1. **The wrong advice when the 10-K is in.** A run starts from the newest quarter whose revenue Warren has (`math_engine._last_actual_quarter`). A fourth quarter exists only as a derivation, year minus the first three quarters (`domains/fundamentals/facts.py`). If the 10-K is loaded but that derivation fails (the year's revenue is missing, or sits under a tag the concept map doesn't read), the newest quarter stays Q3. Then two things go wrong:
   - Past 161 days, `fundamentals_stale` tells the student to "check that the newest filings are ingested". They are. The fault is that the quarter could not be read or derived.
   - Before 161 days, nothing is said at all, although the run starts one report behind what is public. That silent case is the more common one: a 10-K lands about 60 days after the year ends, so for the next 100 days every run quietly ignores it.
   The same can happen after a 10-Q whose revenue line isn't read: the run starts from the quarter before, and says nothing until 135 days.
2. **The late-filing notice.** Exchange Act Rule 12b-25 lets a company file Form NT 10-K or NT 10-Q and get 15 or 5 more days; a report filed within them counts as on time (17 CFR 240.12b-25(b)). The lesson says "or the company filed late", which misnames that case.
3. **A clearer failure for the rule test** (gatekeeper, PR #351). `test_the_stale_rule_names_each_line_with_its_own_parts` reads the rule with a regex; a wording edit gives an empty list and a failure that doesn't say why.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A note when a newer report is in but its quarter wasn't read.** In `_last_actual_quarter`, after picking the newest revenue quarter, look for any *duration* figure (a flow over a period, `period_start` set) in the run's history, quarterly or annual, that ends after that quarter. Balances (instants) are left out because the cover page's share count is dated after the quarter by design. If one exists, a newer report is loaded:
  - New run-note code `newer_report_not_read`, params `last_quarter_end`, `newer_period_end` (the latest such end) and `days` (as-of minus `last_quarter_end`). English: "The newest quarter with revenue ended {last}, but figures for a period ended {newer} are loaded: that period's revenue could not be read or derived, so the run starts one report behind (check that filing's revenue line)."
  - It fires whatever the age, and it **replaces** `fundamentals_stale` in that run: both point at the same fault, and only this one names the right fix. A run without a newer duration figure is unchanged.
  - `coded.RUN_NOTE_CODES` gains the code; `text.WARNING_LESSONS` gains its lesson (group `data`, no params, a Warren rule: "Warren's own check (math_engine._last_actual_quarter): a figure for a period that ends after the newest revenue quarter means a newer report is loaded; balances are not counted, since the cover page's share count is dated after the quarter").
  - Tests (`tests/analysis/test_build_warning_codes.py`): the #349 fixture (FY2019 10-K in, its revenue row dropped) now gives `newer_report_not_read` at 2020-03-09 (161 days, before the stale line) and at 2020-03-10 (162 days), with `newer_period_end` 2019-12-31, and no `fundamentals_stale` in either; the existing stale tests (10-K not filed yet, 10-Q late) still give `fundamentals_stale` and no new note; a 10-Q whose revenue row alone is dropped gives the new note with the quarter's end; the fresh fixture gives neither. The lesson tests cover the new code by the existing "every code has a lesson" rule.
  - Exit: tests pass; dropping the replacement (both notes fire) fails the 162-day test; dropping the instant filter makes the fresh fixture fire (checked by hand).
- **Step 2. The late-filing notice in the lesson.** `math_engine` gains `NT_EXTENSION_10Q_DAYS = 5` and `NT_EXTENSION_10K_DAYS = 15` beside the deadlines, documented as law (Rule 12b-25(b)) that the lines do **not** add. The `fundamentals_stale` lesson's second sentence becomes "Warren may be missing a filing, or the company filed late or filed a late-filing notice, which allows {nt_10q} more days for a quarterly report and {nt_10k} for an annual one: check the company's list of filings." Params gain `nt_10q` and `nt_10k`; the reference gains "Exchange Act Rule 12b-25(b) (Form NT 10-K and NT 10-Q)"; the Warren rule adds "the late-filing notice's 5 and 15 extra days are not added to either line". Tests: `THRESHOLDS` gains both; the lesson stays two sentences.
  - Exit: lesson tests pass.
- **Step 3. The rule test fails clearly.** Assert the regex finds exactly two clauses, with a message quoting the rule, before comparing them. Exit: replacing "plus the" with "and the" in the rule fails with that message (checked by hand, not committed).
- **Step 4. Real data.** On the restored snapshot, for each company in the universe, the new check on every Friday from 2019-03-01 to 2026-11-09: how often it fires, on which companies and periods, and whether each one is a real unread quarter (checked against the filing list). Stored runs: none changes a number; the note on stored runs is not rewritten (rebuild compares outputs, not notes: `runs.Rebuild.notes`, `compare=False`). Exit: counts and a reading of each company's cases in this doc.

## Alternatives considered

- **A param on `fundamentals_stale` (`annual_report_ingested`)**, the issue's first option. Rejected: the warning would still fire only after 161 days, so the common case (a run in the 100 days after the 10-K) would stay silent, and the lesson the student reads would still say "check the filings are ingested".
- **Keep both notes when both apply.** Rejected: two warnings for one fault, one of them with the wrong fix.
- **Only the 10-K case** (last quarter Q3, a newer annual figure). Rejected: the same check costs nothing for a 10-Q whose revenue wasn't read, and the advice is the same.
- **Add the notice's extra days to the lines.** Rejected: a company that files the notice is still late against its normal deadline, and Warren does not read NT filings; the lesson names the case instead.

## Known limits

- The check sees only the items Warren reads (`math_engine.ITEMS`). A newer report from which Warren reads nothing at all looks like no report, and falls back to the stale line as today.
- Changing the stale advice does not change stored runs' note text; a stored run keeps the note it was made with.

**Point in time.** The check reads only the history the run already loaded as of its date. **LLMs.** None. **Decision 11.** No source, company or currency change. **Numbers.** No value, assumption or output changes; only which note a run carries.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `tests/analysis/test_build_warning_codes.py`, `tests/analysis/test_warning_lessons.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the warnings beside a run (Q3–Q5 screens, the "Datos" group, v0.9.60). Added: run-note code `newer_report_not_read` (params `last_quarter_end`, `newer_period_end`, `days`) and its lesson; lesson params `nt_10q` (5) and `nt_10k` (15) on `fundamentals_stale`. Changed: a run that has a newer report loaded but not read now carries `newer_report_not_read` instead of `fundamentals_stale`; the stale lesson's second sentence names the late-filing notice. Nothing renamed or removed. For the front-end team: add the new code and the two params to the Spanish catalogue (#344).
