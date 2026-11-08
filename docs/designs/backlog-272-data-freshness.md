# Backlog #272: say when a company's data were last downloaded

Issue: https://github.com/sonderbot-ar/warren/issues/272 · Branch `backlog-272-data-freshness` · Version v0.9.40 (planned).

## Problem

`past_events(...)` (brief Q10–Q15) shows each past case's quarters against what was reported by the question's date D. A quarter with no revenue reported carries the hindsight code `not_reported`, whose text says it "was not yet in a 10-Q or 10-K by D". That is only true if Warren's copy of the company's filings was downloaded after D. On the stored snapshot it often wasn't: the analyst's review of #269 found Caterpillar's newest stored filing is 2026-08-05 and Apple's 2026-07-31, so for a question dated 2026-11-07 their September quarters are missing because the download is old, not because the companies hadn't filed. Nothing in the answer says so, and the screen would tell a student "not yet filed" about a filing that exists.

Two smaller asks from the same review:

- `history_cut` (v0.9.39) gives `history_ends` but not the newest filing Warren holds for that company, so the screen can't tell "not due yet" from "due but missing" without Warren guessing a filing lag.
- `history_cut` decides a missing quarter from `actual is None`; it should read the hindsight's `not_reported` code, which is what "missing" means (the same quarters today).

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A `downloaded_before` note per company, and `last_filed` on `history_cut`.**
  - New function `fundamentals_freshness(conn, cik, on)` in `domains/evaluation/past_events.py`, returning `{downloaded_at, downloaded_on, last_filed}`:
    - `downloaded_at`: the newest `ingest_runs` row for the CIK, its `companyfacts_fetched_at` (when the company-facts file was downloaded from EDGAR). `null` when the row has none (a file of unknown age was loaded) or there is no row; `downloaded_on` is its date (UTC), or `null`.
    - `last_filed`: the newest `financial_facts.filed_at` for the CIK on or before `on` (point in time: a filing after D is never read), or `null` when none.
  - For each company in the answer (the question's company, then case companies by ticker, the same order and the same pinned CIK as the `beyond_history` notes), `past_events` adds a coded note `downloaded_before` when the download is on or before D, or its date is unknown. A download on D itself counts: a filing made later that day would be missing. Params: `ticker`, `cik`, `role` (`question` or `case`, as `beyond_history`), `as_of`, `downloaded_at`, `downloaded_on`, `last_filed`. English text: "Warren's copy of CAT's SEC filings was downloaded on 2026-11-03, not after the question's date (2026-11-07); its newest filing by then is from 2026-08-05. Anything CAT filed after the download is missing here, so a quarter shown as not yet reported may in fact have been filed." With an unknown download: "… was loaded from a file of unknown date …". The notes go last, after the `beyond_history` notes.
  - `history_cut.params` gains `last_filed` (the same value, for that case's company), so a screen showing the flag has both dates side by side. Its text is unchanged.
  - `history_cut` takes a quarter as missing when its revenue item's `missing` code is `not_reported`, not when its actual is `None`.
  - Tests: a company downloaded before D gets the note with all params and the text; downloaded after D gets none; downloaded on D gets it; an unknown download (`companyfacts_fetched_at` NULL, or no ingest row) gets the unknown text; `last_filed` ignores a filing after D; the question's company's note comes before a case company's, and each carries its `role`; `history_cut.params.last_filed` is set; a hand-made revenue item with an actual and a non-`not_reported` code is not counted missing; `render` prints the note; every existing past-events test unchanged.
  - Exit: tests pass, ruff clean.
- **Step 2. Real data** (latest snapshot): `past-events --json` for Q10 (MSFT `m_and_a`) and Q14 (XOM `macro`) on 2026-11-07 and on 2025-06-01, main against this branch. Expect: identical apart from the new notes and `last_filed`; on 2026-11-07 a note for each company whose download is not after that date; on 2025-06-01 none (every download is later).

**Point in time.** `last_filed` reads only filings on or before D. The download date is a fact about Warren's copy, not about the company: it never changes a number, only says whether the copy can be complete for D. **LLMs.** None. **Decision 11.** Nothing is named in code; the companies come from the answer, the CIK from `universe.csv`.

## Alternatives considered

- **Change `hindsight._not_reported`'s text when the download is older than D.** Not now: the hindsight also feeds the pipeline report and the run ranges, whose stored outputs must reproduce byte for byte; past runs are dated long before any download, so the gap only matters on recent dates, where past events is the call that meets it. The note on the answer says it without touching stored text.
- **Guess each quarter's filing deadline (period end plus 40 or 60 days) and call a quarter "due but missing".** Rejected: a guessed lag is a number Warren would invent; large filers file at different points of the window. `last_filed` and the download date are facts; the screen can show them.
- **A note on every answer, whatever the dates.** Rejected: on a past question every download is later than D, and a note that says nothing new teaches students to skip notes.

## Files to change

`domains/evaluation/past_events.py`, `tests/evaluation/test_past_events.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). `past_events(...).notes` gains a code, `downloaded_before`, zero or more, after `beyond_history`: params `ticker`, `cik`, `role`, `as_of`, `downloaded_at` (ISO UTC time or `null`), `downloaded_on` (date or `null`), `last_filed` (date or `null`). The screen should show it beside any quarter marked `not_reported` for that company and say the quarter may have been filed after Warren's download ("puede haberse presentado después de la descarga"), never "aún no presentado" alone. `history_cut.params` gains `last_filed`. Nothing renamed or removed; no existing text changes.
