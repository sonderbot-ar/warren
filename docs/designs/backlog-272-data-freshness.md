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
  - New `fundamentals_freshness(conn, cik, on)` in `domains/evaluation/past_events.py`, for the CIK `universe.csv` pins (else the stored company's):
    - `downloaded_at`: the newest `ingest_runs.companyfacts_fetched_at` over all of the CIK's ingests (when the company-facts file was downloaded from EDGAR; a re-ingest from the cache keeps the old time). Facts are upserted and never removed, so the copy is at least that fresh, and a later ingest with no time can't hide a dated one. `null` when no ingest has a time. `downloaded_on` is its date in New York.
    - `fresh`: `downloaded_at >= known_by(D)`, the instant D ends in New York: the pipeline's own rule (`domains/orchestration/nodes.py`), so the two never disagree on a download made in the evening of D.
    - `last_filed`: the newest original 10-Q or 10-K (`financial_facts.form`, amendments left out: an amendment does not report a new quarter) filed on or before D. `last_quarter`: the newest fiscal quarter (`FYyyyyQn`, the same company-calendar labels the hindsight reads) with revenue in such a filing (a year or year-to-date figure counts for the quarter it ends).
    - `downloaded_at` is read without a date filter on purpose: it is a fact about Warren's copy, not the company, and only decides whether a note is shown; it never changes a number. `last_filed` and `last_quarter` read nothing filed after D.
  - `quarters_after_copy`: for each company, the `{case_id, period}` of every quarter of its listed cases (counted and context) whose revenue carries the hindsight's `not_reported` code and whose label is later than `last_quarter` (all of them when `last_quarter` is `null`). An unreported quarter at or before `last_quarter` is a gap in the data, not the download's age.
  - Note `downloaded_before`, for each company in the answer (the question's company first, then case companies by ticker; the same companies as `beyond_history`), only when the copy is not `fresh` (or its time is unknown) **and** `quarters_after_copy` is not empty: a stale copy that changes nothing shown says nothing (on the snapshot every download is 2026-10-31, so without this every recent answer would carry one per company). Params: `ticker`, `cik`, `role` (`question` or `case`; the text is the same for both), `as_of`, `downloaded_at`, `downloaded_on`, `last_filed`, `last_quarter`, `quarters_after_copy`. After every other note. English text, in three branches:
    - known time: "Warren's copy of CAT's SEC filings was downloaded on 2026-10-31 (New York time), before the question's date (2026-11-07) ended; the newest 10-Q or 10-K in that copy was filed on 2026-08-05, and its newest quarter with revenue is FY2026Q2. Anything CAT filed after the download is missing here, so these quarters, shown as not reported, may in fact have been reported by then: FY2026Q3 (CAT_…)."
    - unknown time: "Warren's copy of CAT's SEC filings was loaded from a file of unknown date, so it may not hold everything filed by the question's date (2026-11-07); …" and the same ending.
    - no filing by D: "…; that copy holds no 10-Q or 10-K filed by the question's date. …"
  - `history_cut.params` gains `last_filed`; its text is unchanged.
  - `history_cut` takes a quarter as missing when its revenue item's code is `not_reported`. The hindsight writes that code exactly when revenue is absent (`hindsight.py`, the `revenue is None` branch); other revenue codes (`basis_change`, `zero_base`) carry an actual, so the quarters are the same as before.
  - Tests: freshness reads only filings by D; an amendment doesn't move `last_filed`; a dated download wins over a later undated ingest; a copy downloaded before D ended names its later unreported quarters, with every param and the text; 23:59 on D in New York gives a note, midnight none; an unknown time has its own text; a stale copy whose unreported quarters are all at or before its newest quarter gives none; a case company's note has `role` `case`; a context case's quarters count; `history_cut.params.last_filed`; a revenue gap of another code is never missing. The v0.9.39 exact `history_cut.params` assertion gains `last_filed`; nothing else changes.
  - Exit: tests pass, ruff clean.
- **Step 2. Real data** (snapshot `warren-20261105T101750Z`): `python -m domains.evaluation past-events --ticker T --event-type E --as-of D --json` on main and on this branch, for MSFT `m_and_a` and XOM `macro` (brief Q10 and Q14), and every askable type for CAT, on 2026-11-07 and on 2025-06-01. Expect: identical apart from `history_cut.params.last_filed` and any `downloaded_before` notes; none on 2025-06-01 (every download is 2026-10-31).

**Point in time.** `last_filed` reads only filings on or before D. The download date is a fact about Warren's copy, not about the company: it never changes a number, only says whether the copy can be complete for D. **LLMs.** None. **Decision 11.** Nothing is named in code; the companies come from the answer, the CIK from `universe.csv`.

## Alternatives considered

- **Change `hindsight._not_reported`'s text when the download is older than D.** Not now: the hindsight also feeds the pipeline report and the run ranges, whose stored outputs must reproduce byte for byte; past runs are dated long before any download, so the gap only matters on recent dates, where past events is the call that meets it. The note on the answer says it without touching stored text.
- **Guess each quarter's filing deadline (period end plus 40 or 60 days) and call a quarter "due but missing".** Rejected: a guessed lag is a number Warren would invent; large filers file at different points of the window. `last_filed` and the download date are facts; the screen can show them.
- **A note on every answer, whatever the dates.** Rejected: on a past question every download is later than D, and a note that says nothing new teaches students to skip notes.

## Files to change

`domains/evaluation/past_events.py`, `tests/evaluation/test_past_events.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). `past_events(...).notes` gains a code, `downloaded_before`, zero or more, last: params `ticker`, `cik`, `role`, `as_of`, `downloaded_at` (ISO UTC time or `null`), `downloaded_on` (New York date or `null`), `last_filed` (the newest original 10-Q or 10-K by D, or `null`), `last_quarter` (`FYyyyyQn` or `null`), `quarters_after_copy` (`[{case_id, period}]`, never empty). The engine decides which quarters it covers: for each `{case_id, period}` listed, the screen must not show that quarter's `not_reported` text ("not yet in a 10-Q or 10-K by D", which may be false here) and should say instead that it may have been reported after Warren's download (a hint: "puede haberse presentado después de la descarga de Warren"). Other `not_reported` quarters keep their usual text. Build the Spanish from the code and params, as for `beyond_history` and `history_cut`, with the company's name, and keep `text` as the English fallback. `history_cut.params` gains `last_filed`. Nothing renamed or removed; no existing text changes. Translation stays with the front-end team.

## Design review (nov.08.2026)

Explainer, analyst, professor and product lead in parallel, on the first draft. Four NO-GOs, each on a point the doc now fixes.

- **Analyst, blocker: "newest filing" is false to a practitioner.** `financial_facts` holds only 10-Q and 10-K forms; Caterpillar's earnings 8-K carries its revenue weeks earlier. Taken: the text and params say "newest 10-Q or 10-K". Also taken: amendments left out of `last_filed` (KO's 10-Q/A of 2024-05-30 would look like a new quarter); the newest download over all ingests, not the newest ingest's; the note only when it changes something shown (on the snapshot every download is 2026-10-31, so MSFT, KO, PG and JNJ, whose September quarter is stored, would carry a note that adds nothing); the doc's example date (CAT downloaded 2026-10-31, not 11-03).
- **Professor, blocker: the day boundary.** The draft compared the download's UTC date with D; the pipeline's rule is `fetched >= known_by(as_of)`, the end of D in New York (`shared_kernel/calendar.py`). Taken, with tests at 23:59 and 00:00 New York. Sources for the method: data vintages and real-time data sets (Croushore and Stark 2001, *J. Econometrics* 105; Orphanides 2001, *AER* 91); filing dates rather than an assumed lag (Fama and French 1992, *J. Finance* 47, assumed six months only for want of dates). Idea kept for the lesson: name the concept "vintage".
- **Product lead, blockers: which quarters, and the contradicting old text.** A per-company note left the screen to guess which `not_reported` quarters it covers (a 2023 gap would get the caveat too). Taken: the engine lists them in `quarters_after_copy` (later than the copy's newest quarter with revenue; no guessed lag), and Product impact says the screen must not show the old text for those. Also taken: three text branches written out, "before the question's date ended" instead of a double negative, `role` uses the same text.
- **Explainer.** Taken: which ingest row counts, why `downloaded_at` has no date filter, the no-ingest case (`null`, the unknown-time text), why the `not_reported` switch picks the same quarters, how `last_filed` reaches `history_cut`, the Step 2 commands. Rejected: a separate "no copy at all" text: every company in an answer has been ingested (`past_events` refuses an un-ingested question company, and cases come from stored runs).

## Results (nov.08.2026)

Snapshot `warren-20261105T101750Z` (schema 21). Before = main at `3e5474f`, after = this branch, `past-events --json`.

- **The copy, as of 2026-11-07** (`fundamentals_freshness`): every company was downloaded on 2026-10-31, so none is fresh for that date. Newest 10-Q or 10-K and newest quarter with revenue: AAPL 2026-07-31 FY2026Q3, MSFT 2026-10-28 FY2027Q1, KO 2026-10-28 FY2026Q3, PG 2026-10-22 FY2027Q1, JNJ 2026-10-21 FY2026Q3, CAT 2026-08-05 FY2026Q2, WMT 2026-08-28 FY2027Q2, XOM 2026-05-04 FY2026Q1 (its old CIK stops there).
- **15 answers compared** (CAT on all eight types, MSFT `m_and_a`, XOM `macro`, AAPL and WMT `guidance` on 2026-11-07; MSFT `m_and_a`, XOM `macro`, CAT `guidance` on 2025-06-01): identical to main apart from `history_cut.params.last_filed` on Exxon's three cases (2026-05-04). No `downloaded_before` note anywhere: no listed case has a quarter shown as not reported (the newest non-control case is from 2024), so today's stale copy changes nothing a student sees. The note will matter once newer cases or M10's dates reach quarters after the copy's newest (CAT's FY2026Q3, for example); until then it is covered by the hand-made tests.
- Full suite and ruff: see the PR.

Exit met.

## PR review (nov.08.2026)

Gatekeeper: **GO**, no blockers (`tests/evaluation` 322 passed; ruff clean). Ideas taken before merge: a copy with filings but no quarter with revenue now says "it has no quarter with revenue" instead of "is none" (a fourth text branch, tested); the `history_cut` docstring says "newest original 10-Q or 10-K". The desk entry says plainly that no real answer carries the note yet.
