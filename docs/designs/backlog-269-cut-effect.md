# Backlog #269: per case, what a company's filings cut takes from it

Issue: https://github.com/sonderbot-ar/warren/issues/269 · Branch `backlog-269-cut-effect` · Version v0.9.39 (planned).

## Problem

Since v0.9.38 the `thin_evidence` note on `past_events(...)` names each counted case whose company's filings stop by D (`cut`: `case_id`, `ticker`, `role`, `history_ends`). It doesn't say what the cut takes from that case. Two things can stop at `history_ends`:

1. the company's typical forecast errors (the usual-miss set), always; and
2. some of the case's own quarters, when they would have been filed from `history_ends` on.

The Pioneer case today (Exxon cut from 2026-08-03) has every quarter filed by 2024, so only (1) applies; a future case whose quarters fall after the cut-off would lose some of its own quarters too. The product lead's review of #262 asked for a per-case flag so the screen can say which without reading the note text, and the analyst asked for a test of a case with quarters after its company's cut-off (none exists in `cases.csv` today, so the test is on hand-made cases).

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A `history_cut` flag on each case of a cut company, and two keys on each `cut` entry.** `past_events` builds the coverage notes first (as since v0.9.36), then sets `PastCase.history_cut` (new, default `None`) on every case, counted, uncounted or context (`same_company_other_type`), whose company has a `beyond_history` note on this answer. It is a coded note `history_cut` with params `ticker`, `role` and `history_ends` (the coverage note's), `effect` and `quarters_missing`:
  - `quarters_missing`: the periods, in horizon order, of the case's quarters (within its horizon, as shown) whose revenue is not reported in the data by D. `[]` for a case with no stored run (`not_scored`), which has no quarters to lose.
  - `effect`: `usual_only` when `quarters_missing` is empty, `own_quarters_missing` otherwise.
  - Text, `usual_only`: "TST's filings from 2020-12-31 on are missing in Warren's data, so its typical forecast errors stop at that date; every quarter of this case was reported before then, so the case is whole". `own_quarters_missing`: "…stop at that date; this case's quarters FY2021Q2, FY2021Q3 are not reported in the data by the question's date either, so they can't be compared" (singular "quarter … is" for one).
  - Every filing before `history_ends` is in the data, so an unreported quarter was filed on or after `history_ends`, or not yet by D. Warren can't tell which without guessing a filing date, so the flag says the quarter is missing, not that the cut removed it.

  Each `thin_evidence.params.cut` entry gains the same `effect` and `quarters_missing`. With `own_quarters_missing`, that case's part of the English sentence gains "; its own quarters … are not in the data either" before its closing parenthesis. With `usual_only` the text is byte for byte v0.9.38's. `n`, `cut_cases`, `cut_case_ids`, the order and every other note are unchanged. The text report (`render`) shows a "Filings cut:" line under a flagged case's source.
  Tests: a whole case is `usual_only` with the "case is whole" text; a counted case with one reported and two unreported quarters is `own_quarters_missing` naming both, stays in `n`, and its `cut` entry and sentence say so, and render shows the line; an uncounted case is flagged but not in `cut`; a case with no stored run is `usual_only` with `[]`; a context case is flagged and never in `cut`; before the cut-off no case is flagged and render has no line; the v0.9.38 exact `cut` assertion gains the two keys.
  Exit: tests pass; the other past-events tests unchanged.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`): `past-events --json` for Q10 (MSFT `m_and_a`) and Q14 (XOM `macro`) on 2026-11-07, main against this branch: identical apart from `history_cut` on Exxon's cases and the two new keys on `cut`; the thin-evidence text unchanged if every Exxon case is `usual_only`.

**Point in time.** Nothing new is read: the cut is the coverage note's, as of D, and the quarters are the hindsight already cut at D. **LLMs.** None. **Decision 11.** Which companies are cut comes from `universe.csv`'s `history_ends`; nothing is named in code.

## Alternatives considered

- **Call an unreported quarter "removed by the cut" only when its expected filing date (period end plus a typical 10-Q or 10-K lag) falls between `history_ends` and D.** Rejected for now: unreported quarters have no period end in the hindsight (it comes from the filing), and a guessed lag is a number Warren would be inventing. Saying "missing" is true either way, and `history_ends` sits beside it.
- **Only the two keys on `cut`, no field on `PastCase`.** Rejected: the screen renders case by case, and uncounted and context cases, which are never in `cut`, can lose quarters too.
- **Drop the case's missing quarters from the comparison.** Not needed: an unreported quarter already has no miss and is never compared; the flag only says why it may stay that way.

## Files to change

`domains/evaluation/past_events.py`, `tests/evaluation/test_past_events.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). Every case on `past_events(...).cases` and `same_company_other_type` gains `history_cut`: `null`, or `{code: "history_cut", params: {ticker, role, history_ends, effect, quarters_missing}, text}`. `effect` is `usual_only` (the screen can say "its company's history ends early, but this case is complete") or `own_quarters_missing` (say which quarters are missing and that they may never appear here). Each `thin_evidence.params.cut` entry gains `effect` and `quarters_missing`. The English fallback text of the thin-evidence note changes only for a counted case with missing quarters. No field is renamed or removed.
