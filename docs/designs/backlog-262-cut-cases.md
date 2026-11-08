# Backlog #262: the "few cases" line says when a counted case's filings stop early

Issue: https://github.com/sonderbot-ar/warren/issues/262 · Branch `backlog-262-cut-cases` · Status: In progress (nov.08.2026).

## Problem

Since v0.9.36 a case company whose filings stop by D (Exxon from 2026-08-03) gets a `beyond_history` note with `role: case` on `past_events(...).notes`. The answer's `thin_evidence` note (reason `few_cases` or `direction_not_recorded`) counts the cases with at least one quarter reported by D (`n`), but it doesn't say whether one of them belongs to a company whose history is cut. The product lead's review of #256 asked for a param so the app can say "including one whose history ends early" (brief Q10–Q15, "Eventos").

A counted case of a cut company is still a real case: the Pioneer deal's quarters were all filed by 2024. What is cut is its company's typical forecast errors (the usual-miss set), which stop at the cut-off, so its "more than usual" comparisons rest on fewer quarters, and any of its case quarters reported after the cut-off. So the case stays counted, and the note says so.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Two params and one clause on `thin_evidence`.** `past_events` builds the coverage notes before the thin-evidence note and reads from them which companies' filings stop by D. `thin_evidence.params` gains `cut_cases` (int) and `cut_case_ids` (sorted list of case ids): the counted cases (`reported_quarters > 0`, the same ones `n` counts) whose company has a `beyond_history` note on this answer, whatever its `role`. Always present, `0` and `[]` when none. When `cut_cases > 0`, the English text gains a last sentence: ". K of the N counted case(s) is/are of a company whose filings stop early here: still counted, but its typical forecast errors end at that date (see the coverage note)". With none, the text is byte for byte what it was. `n`, `thin_evidence`, `reason` and the note's place in the list are unchanged. Cases listed for context (`same_company_other_type`) and cases with no reported quarter are never in `cut_case_ids`, because `n` doesn't count them.
  Tests: a counted case of a cut company is named, a listed case with no reported quarter is not; the same when the question names another company (the case's `role` is `case`); before the cut-off `0`, `[]` and the old text; the plural sentence and the sort; the two existing exact-params assertions now include the two keys at `0` and `[]`.
  Exit: tests pass; the other past-events tests unchanged.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`): `past-events --json` for Q10 (MSFT `m_and_a`) and Q14 (XOM `macro`) on 2026-11-07, before (main) and after: identical apart from the two params and, where Exxon's case is counted, the added sentence.

**Point in time.** Nothing new is read: the cut is the `coverage_gap` the coverage note already uses, as of D. **LLMs.** None. **Decision 11.** Which companies are cut comes from `universe.csv`'s `history_ends`, so a new cut-off row needs no code change.

## Alternatives considered

- **Leave a cut company's cases out of `n`.** Rejected: the cases happened and their quarters are reported; dropping them would hide evidence, and change `n` and the `few_cases` threshold on a data cut that has nothing to do with the event.
- **Only a count, no ids.** Rejected: the app can't say which case without matching tickers against the coverage notes itself; the ids cost nothing.
- **A separate note code.** Rejected: the fact qualifies the count the `thin_evidence` note already gives, so it belongs in that note's params; a new code would be one more the app must place next to it.

## Files to change

`domains/evaluation/past_events.py`, `tests/evaluation/test_past_events.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). `thin_evidence` on `past_events(...).notes` gains `cut_cases` and `cut_case_ids`, always present. The app can add "including one case whose company's history ends early" to its "few cases" sentence and link it to that company's `beyond_history` note (`role` tells whose). The English fallback text changes only when `cut_cases > 0`. No other field, code or note changes.
