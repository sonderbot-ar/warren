# Backlog #269: per case, what a company's filings cut takes from it

Issue: https://github.com/sonderbot-ar/warren/issues/269 · Branch `backlog-269-cut-effect` · Version v0.9.39, merged nov.08.2026 (PR #273, merge `e6a4640`; gatekeeper GO).

## Problem

Since v0.9.38 the `thin_evidence` note on `past_events(...)` names each counted case whose company's filings stop by D (`cut`: `case_id`, `ticker`, `role`, `history_ends`). It doesn't say what the cut takes from that case. Two things can stop at `history_ends`:

1. the company's typical forecast errors (the usual-miss set), always; and
2. some of the case's own quarters, when they would have been filed from `history_ends` on.

The Pioneer case today (Exxon cut from 2026-08-03) has every quarter filed by 2024, so only (1) applies; a future case whose quarters fall after the cut-off would lose some of its own quarters too. The product lead's review of #262 asked for a per-case flag so the screen can say which without reading the note text, and the analyst asked for a test of a case with quarters after its company's cut-off (none exists in `cases.csv` today, so the test is on hand-made cases).

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A `history_cut` flag on each case of a cut company, and two keys on each `cut` entry.** `past_events` builds the coverage notes first (as since v0.9.36), then sets `PastCase.history_cut` (new, default `None`) on every case, counted, uncounted or context (`same_company_other_type`), whose company has a `beyond_history` note on this answer. It is a coded note `history_cut` with params `ticker`, `role` and `history_ends` (the coverage note's), `effect` and `quarters_missing`:
  - `quarters_missing`: the periods, in horizon order, of the case's quarters (within its horizon, as shown) whose revenue is not reported in the data by D; each equals a `quarters[].period` of the same case. "Reported" is the revenue line, the same test `reported_quarters` counts (`Quarter.reported` reads revenue, the first item), so a quarter with revenue and no EBIT is reported.
  - `effect`: `no_stored_run` when the case has no stored baseline run (`missing` is `not_scored`: nothing of its own is in the data, cut or not; `quarters_missing` is `[]`); `usual_only` when every quarter is reported; `own_quarters_missing` otherwise.
  - Text, always: "TST's filings from 2020-12-31 on are missing in Warren's data, so its typical forecast errors stop at that date", then for `usual_only` "; every quarter of this case is in the data, only the yardstick it is compared with is shorter"; for `own_quarters_missing` "; this case's quarters FY2021Q2, FY2021Q3 are not in the data by the question's date either (not yet filed, or filed after that date), so they can't be compared while its filings stop there" (singular "quarter … is" for one); for `no_stored_run` "; this case has no stored forecast, so none of its own quarters are compared".
  - Every filing before `history_ends` is in the data (true while the company's download is newer than `history_ends`; for Exxon its newest stored filing is the Q1 2026 10-Q of 2026-05-04, and the Q2 10-Q of 2026-08-03 is the first one missing), so an unreported quarter was filed on or after `history_ends`, or not yet by D. Warren can't tell which without guessing a filing date, so the flag says the quarter is missing, not that the cut removed it. It stays missing until the predecessor and successor CIKs are linked (`universe.csv`'s note: "a later task").

  Each `thin_evidence.params.cut` entry gains the same `effect` and `quarters_missing`. With `own_quarters_missing`, that case's part of the English sentence gains "; its own quarters … are not in the data either" before its closing parenthesis. With `usual_only` the text is byte for byte v0.9.38's (a counted case always has a stored run, so it is never `no_stored_run`). `n`, `cut_cases`, `cut_case_ids`, the order and every other note are unchanged. The text report (`render`) shows a "Filings cut:" line after a flagged case's source and scope-change lines, before its table or its no-run note.
  Tests: a complete case is `usual_only` with the yardstick text; a counted case with one reported and two unreported quarters is `own_quarters_missing` naming both, stays in `n`, and its `cut` entry and sentence say so, and render shows the line; an uncounted case is flagged but not in `cut`; a case with no stored run is `no_stored_run` with `[]` and its own text, never the complete-case text; a context case is flagged and never in `cut`; before the cut-off no case is flagged and render has no line; the v0.9.38 exact `cut` assertion gains the two keys.
  Exit: tests pass; the other past-events tests unchanged.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`): `past-events --json` for Q10 (MSFT `m_and_a`) and Q14 (XOM `macro`) on 2026-11-07, main against this branch. Exxon is the only `universe.csv` row with a `history_ends` (2026-08-03), so only its cases can be flagged; expect identical output apart from `history_cut` on Exxon's cases and the two new keys on `cut`; the thin-evidence text unchanged if every Exxon case is `usual_only`.

**Point in time.** Nothing new is read: the cut is the coverage note's, as of D, and the quarters are the hindsight already cut at D. **LLMs.** None. **Decision 11.** Which companies are cut comes from `universe.csv`'s `history_ends`; nothing is named in code.

## Alternatives considered

- **Call an unreported quarter "removed by the cut" only when its expected filing date (period end plus a typical 10-Q or 10-K lag) falls between `history_ends` and D.** Rejected for now: unreported quarters have no period end in the hindsight (it comes from the filing), and a guessed lag is a number Warren would be inventing. Saying "missing" is true either way, and `history_ends` sits beside it.
- **Only the two keys on `cut`, no field on `PastCase`.** Rejected: the screen renders case by case, and uncounted and context cases, which are never in `cut`, can lose quarters too.
- **Drop the case's missing quarters from the comparison.** Not needed: an unreported quarter already has no miss and is never compared; the flag only says why it may stay that way.

## Files to change

`domains/evaluation/past_events.py`, `tests/evaluation/test_past_events.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). Every case on `past_events(...).cases` and `same_company_other_type` gains `history_cut`: `null`, or `{code: "history_cut", params: {ticker, role, history_ends, effect, quarters_missing}, text}`. `effect` is `usual_only` (the screen can say the case is complete, "el caso está completo", and only its company's typical errors stop early), `own_quarters_missing` (mark the rows whose `quarters[].period` is in `quarters_missing`, and say they won't appear while the company's filings stop at `history_ends`), or `no_stored_run` (the case's own `missing`, `not_scored`, already says it has no forecast; never call it complete). Each `thin_evidence.params.cut` entry gains `effect` and `quarters_missing`. As since v0.9.36, the screen builds its Spanish sentence from `effect`, `role` and the params, with the company's name rather than its ticker, and keeps `text` as the English fallback. The English fallback text of the thin-evidence note changes only for a counted case with missing quarters. No field is renamed or removed.

## Design review (nov.08.2026)

Explainer, analyst, professor and product lead in parallel, after Step 1's first version was committed.

- **Blocker, raised by all four: a case with no stored run was called whole.** It had `effect` `usual_only` and the text "the case is whole", printed above its own "no stored run" note. Taken: a third effect, `no_stored_run`, with its own text, and a test that it never gets the complete-case text.
- **Analyst: GO once the blocker is fixed.** On the snapshot all 12 quarters of Exxon's three cases have revenue reported, so all are `usual_only`. Taken: the doc says the rule that every filing before `history_ends` is in the data holds only while the download is newer (true for Exxon: newest stored filing 2026-05-04), and that "missing" lasts until the two CIKs are linked. Filed as #272: other companies' stale downloads (CAT's newest filing 2026-08-05, AAPL's 2026-07-31) read as "not yet filed"; a freshness note per company against D; `last_filed` on the flag; deciding a missing quarter from the `not_reported` code.
- **Professor: GO once the blocker is fixed.** Flagging, rather than dropping or imputing, is the standard guard against survivorship and delisting bias (Brown, Goetzmann, Ibbotson and Ross 1992, *RFS* 5(4); Shumway 1997, *JF* 52(1)); imputing quarters lost to a data cut is missing-not-at-random (Rubin 1976, *Biometrika* 63(3)) and would invent numbers. Taken: "the case is whole" became "every quarter of this case is in the data, only the yardstick it is compared with is shorter"; the missing-quarter text says "not yet filed, or filed after that date".
- **Product lead: GO once the blocker is fixed.** Taken: each `quarters_missing` entry is a `quarters[].period` (tested); the Spanish-sentence rule repeated; "may never appear" became "won't appear while the company's filings stop at `history_ends`".
- **Explainer.** Taken: "reported" defined (the revenue line, as `reported_quarters`), the render line's place, and how Step 2 knows only Exxon is cut.

## Results (nov.08.2026)

Snapshot `warren-20261105T101750Z` (schema 21). Before = main at `7b98f64`, after = this branch, `past-events --json`. Full suite: 1,832 passed, 10 skipped.

- Q10, MSFT `m_and_a`, D = 2026-11-07: the Pioneer case `XOM_2023-10-11` carries `history_cut` `usual_only`, `quarters_missing` `[]`, and its `cut` entry the same two keys. Every other field, and the thin-evidence text, identical to main.
- Q14, XOM `macro`, D = 2026-11-07: Exxon's three cases (the counted `XOM_2020-03-09`, the context `XOM_2023-10-11` and `XOM_2020-11-30`) are all `usual_only`. Everything else identical. The same holds for XOM `m_and_a`.
- MSFT `m_and_a`, D = 2026-06-01 (before Exxon's cut-off): byte for byte main's output apart from `history_cut: null` on every case.

No real case loses any of its own quarters today, so `own_quarters_missing` and `no_stored_run` are covered by the hand-made tests only, as the analyst's #262 idea asked. Exit met.
