# Backlog #262: the "few cases" line says when a counted case's filings stop early

Issue: https://github.com/sonderbot-ar/warren/issues/262 · Branch `backlog-262-cut-cases` · Status: In progress (nov.08.2026).

## Problem

Since v0.9.36 a case company whose filings stop by D (Exxon from 2026-08-03) gets a `beyond_history` note with `role: case` on `past_events(...).notes`. The answer's `thin_evidence` note (reason `few_cases` or `direction_not_recorded`) counts the cases with at least one quarter reported by D (`n`), but it doesn't say whether one of them belongs to a company whose history is cut. The product lead's review of #256 asked for a param so the app can say "including one whose history ends early" (brief Q10–Q15, "Eventos").

A counted case of a cut company is still a real case: the Pioneer deal's quarters were all filed by 2024. What is cut is its company's typical forecast errors (the usual-miss set), which stop at the cut-off, so its "more than usual" comparisons rest on fewer quarters, and any of its case quarters reported after the cut-off. So the case stays counted, and the note says so.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Three params and one clause on `thin_evidence`.** `past_events` builds the coverage notes (`coverage_notes`, as since v0.9.36) before the thin-evidence note, and maps each of their `params.ticker` to its `role` and `history_ends`. `thin_evidence.params` gains `cut_cases` (int), `cut_case_ids` (case ids, ascending) and `cut` (one `{case_id, ticker, role, history_ends}` per such case, same order): the counted cases (`reported_quarters > 0`, the same ones `n` counts) whose company has a `beyond_history` note on this answer. `role` is that note's: `question` when the case is the question's own company's (Q14, Exxon's own 2020 case), `case` otherwise (Q10, the Pioneer case in a Microsoft question). All three are always present, `0`, `[]`, `[]` when none. When `cut_cases > 0`, the English text gains a last sentence; with one case: ". Counted, though its company's filings are missing in Warren's data from a date before this question: XOM_2020-03-09 (XOM, the question's company, from 2026-08-03 on). Its typical forecast errors stop at that date (see the coverage note)"; with several, "their companies'" and "Their", the cases joined by "; ", and ", the question's company" only on the question's own. With none, the text is byte for byte what `_thin(n, reason)` gave before. `n`, `thin_evidence`, `reason` and the note's place in the list are unchanged. Context cases (`same_company_other_type`) and cases with no reported quarter are never in `cut`, because `n` doesn't count them.
  Tests: a counted case of a cut company is named with its role, date and the singular sentence, a listed case with no reported quarter is not; the case's `role` is `case` when the question names another company, and the text does not say "the question's company"; before the cut-off `0`, `[]`, `[]` and the old text; two cases sorted by id with the plural sentence; the two existing exact-params assertions (`test_n_counts_cases_with_a_reported_quarter_and_stays_thin_without_directions`) now include the three keys at their empty values.
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

Brief Q10–Q15 ("Eventos"). `thin_evidence` on `past_events(...).notes` gains `cut_cases`, `cut_case_ids` and `cut` (`case_id`, `ticker`, `role`, `history_ends`), always present. The app can add "including one case whose company's history ends early" to its "few cases" sentence and link it to the `beyond_history` note with the same `ticker`. A cut case can be the question's own company's (`role` `question`, Q14: Exxon's own 2020 case) or another's (`role` `case`, Q10: the Pioneer deal in a Microsoft question), and the sentence should say which. The English fallback text changes only when `cut_cases > 0`. No other field, code or note changes.

## Design review (nov.08.2026)

Explainer, analyst, professor and product lead in parallel, after Step 1's first version was committed.

- **Analyst: GO, no blockers.** On D = 2026-11-07: Q10 (MSFT `m_and_a`) gives n = 3 with the Pioneer case cut; Q14 (XOM `macro`) n = 1 with Exxon's own 2020 case cut; keeping both in `n` is right (the Pioneer quarters were all filed by 2024). Taken: the sentence said "a company" even when it was the question's own (Q14), so it now names each case, its ticker, "the question's company" when it is, and the date; `cut` carries `role` and `history_ends`. Not taken: the count of usual quarters behind each comparison in the note, because each compared quarter already carries its own (`Usual.n_quarters`, per horizon and item), and `history_ends` gives the size of the cut. Idea: a test once a case has quarters after its company's cut-off (none today).
- **Professor: GO, no blockers.** Keeping a truncated case and saying so, rather than dropping it, is the standard guard against selection bias (Brown, Goetzmann, Ibbotson and Ross 1992, "Survivorship bias in performance studies", RFS 5(4)). Taken: "1 of the 1 counted case is of a company" and "stop early here" are gone; the sentence says "Counted, though its company's filings are missing in Warren's data from …".
- **Product lead: GO, no blockers.** Taken: the doc says a cut case can be the question's own company's, and `role` comes with each case so the app need not match notes itself. Taken for the merge: the team-sync entry names brief Q10 and Q14. Idea, filed: a per-case flag saying whether the cut removed any of the case's own quarters or only its typical errors.
- **Explainer: no blockers.** Gaps taken: the helper named (`coverage_notes`), the singular and plural forms given, the sort key (case id, ascending), the existing assertions named, how the app links a case to its note (`cut[].ticker` and `role`), and the unchanged text defined as `_thin(n, reason)`'s.
