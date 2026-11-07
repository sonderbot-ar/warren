# Backlog #252 (part 1): past events say when Exxon's filings stop, warn about merger shocks, and answer in seconds

Issue: https://github.com/sonderbot-ar/warren/issues/252 · Branch `backlog-252-past-events-speed` · Version v0.9.35, merged nov.07.2026 (PR #255, merge `780b964`; gatekeeper GO).

## Problem

The design review of #146 (v0.9.34, the past-events call) left five ideas. This item takes the three the app needs before the event screens; items 3 and 4 stay open on the issue.

1. **Exxon's coverage note** (product lead; brief Q14, #126). Exxon's filings on its old CIK are missing from 2026-08-03 on (`universe.csv`: the Q2 10-Q filed that day went to the new CIK only). A run says so with a `beyond_history` note (v0.9.22), but `past_events` has no such field: an Exxon answer dated after August silently has fewer reported quarters and a shorter usual set, and the student is not told why. Exxon also appears as a *case* company in other answers (the Pioneer deal in every `m_and_a` answer).
2. **The merger caveat** (product lead; brief Q10). The Phase 1 review found Warren's AI news shocks mis-size mergers (`docs/phase1-review.md`, "Mergers": a shock's size comes from how much revenue usually moves, not from the size of the company bought). An `m_and_a` answer says only `baseline_only`, which a student could read as "the AI is fine on deals".
3. **Speed.** A `guidance` question takes 36 s on the restored snapshot (measured: MSFT `m_and_a` 16 s, WMT `guidance` 36 s). The profile: 47 of 48 s are in `run_ranges.basis_flags`, which calls `hindsight.against_actuals` for each of a company's ~90 monthly forecasts, and each call reads the company's filings again: 553 runs made 4,427 fact reads (`harness._quarterly`), almost all the same (company, date, mode) over and over. The reads depend only on the company, the date and the mode, never on the run.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Two notes.**
  - `universe.coverage_gap(cik, as_of)` returns the coverage warning's text and fields (the same eight fields as `CoverageWarning`: `ticker`, `cik`, `as_of`, `history_ends`, `reason`, `successor_cik`, `successor_name`, `note`), or None; `warn_if_beyond_history` now calls it, so the warning and the note can't drift.
  - `past_events` adds one `beyond_history` note per company in the answer (the question's company and every listed case's company) whose pinned CIK's filings are missing from a `history_ends` on or before D, sorted by ticker. The CIK is the one `universe.csv` pins (`get_universe_company(t).cik`), not a lookup by ticker in `companies`, so a successor ingested under the same ticker can't hide the note. Same code, params and English text as a run's note, so the app's sentence for `beyond_history` serves both.
  - An `m_and_a` answer adds `merger_shocks_missized` (params `event_type` `m_and_a`, `backtest_cases` 2). The text says the finding rests on two cases, that these baseline forecasts don't carry the shock-sizing error, and that they carry another: they leave out the bought company's revenue, so after a close part of the gap is the added revenue (Warren marks those quarters `scope_change` and doesn't compare them). It names no deal: a question dated before Activision closed must not learn of it.
  - Both go after the existing notes, so the existing notes keep their order.
  Tests: the note's params and text on a company whose filings stopped before D; none the day before they stop; a case company's note on another company's question; the merger caveat on `m_and_a` only and naming no deal; `coverage_gap` gives exactly the warning's text and fields, and None before the end, for an unpinned CIK and for None.
  Exit: tests pass; every existing past-events test unchanged.
- **Step 2. Shared filing reads.** New `hindsight.FactReads(conn)`: keeps `_quarterly(cik, date, mode)` (as a read-only mapping, so one run can't change what the next reads) and the company's filing list per key. `against_actuals(conn, run_id, actuals_on, reads=None)` uses it (a fresh one when none is given, so every existing caller behaves as before). `run_ranges.basis_flags` makes one per call and passes it to every origin. Nothing else changes: the same functions read the same rows; they are read once instead of ~8 times. A `FactReads` lives only for one call, so it never holds data across a write.
  Tests: two runs of one company through one `FactReads` give the same `to_dict()` as without it, on the recast fixture (so a `restated_basis` flag is in the answer); each (company, date, mode) is read once with sharing, and more than once without.
  Exit: tests pass; `basis_flags` unchanged on real data.
- **Step 3. Real data** (snapshot `warren-20261105T101750Z`). Before (main) and after (branch):
  - `basis_flags` for all 8 companies on 2022-06-30, 2024-11-15 and 2026-11-07, the old per-run reads against the shared ones: identical sets, with timings.
  - `past-events --json` for the five brief questions (Q10 MSFT `m_and_a`, Q12 AAPL `supply_chain`, Q13 JNJ `policy`, Q14 XOM `macro`, Q15 WMT `guidance`), D = 2026-11-07: identical once the new notes are taken out, with timings.
  - `track-record --json` for all 8 companies and `ranges run --json` on each company's newest baseline: identical byte for byte (both call `basis_flags`).
  Exit: all identical; the slowest question under 10 s.

**Point in time.** Nothing new is read. The coverage note uses D, the question's date; the merger caveat names no deal. The caveat is shown on any D, including dates before the 2026 backtest that found it: it describes Warren's method today, which is what produced the forecasts on screen, not anything about a company that wasn't public on D (the rule covers data that feeds an analysis). **LLMs.** None. **Decision 11.** The cut-off stays data in `universe.csv`; no new source, company or currency; the cache is a library object, not a service.

## Alternatives considered

- **Catch the coverage warning while reading, as `reported_period` does.** Rejected: the evaluation reads (`harness._quarterly`) silence it on purpose (coverage is a hard error in the guard), and catching it would depend on which reads happened to run. Asking the universe file for D and each company in the answer is direct and testable.
- **Cache `basis_flags` per company and date across calls** (the issue's first idea). Rejected for now: a cache that outlives a call must be dropped when new filings or monthly forecasts land, which is a new failure mode; sharing reads within one call gets most of the gain with none of that risk.
- **Check only each group's first origin** (the issue's second idea). Rejected: the flag depends on each origin's own history rows (`hindsight._basis_change` compares the filing with the run's basis), so skipping origins could change which quarters leave the usual set.
- **Name the two deals in the merger caveat.** Rejected: point in time (above). The app can link the Phase 1 review for a student who wants the cases.
- **Items 3 (pro forma revenue, ASC 805-10-50-2(h)) and 4 (a shared 2020 window).** Left on #252: each changes what the answer compares, so each needs its own design and review.

## Files to change

`domains/fundamentals/universe.py`, `domains/evaluation/past_events.py`, `domains/evaluation/hindsight.py`, `domains/evaluation/run_ranges.py`, `tests/fundamentals/test_universe.py`, `tests/evaluation/test_past_events.py`, `tests/evaluation/test_hindsight.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). Two new note codes on `past_events(...).notes`, both after the existing ones: `beyond_history` (the run note's code, params and English text; zero or more, one per company whose filings stop by D) and `merger_shocks_missized` (on `m_and_a` only; params `event_type`). The app needs a Spanish sentence for `merger_shocks_missized`; `beyond_history` reuses the run note's. No field or name changes, and every other output is identical; the notes list is longer by those notes, so a consumer that counts notes sees more. Speed: the five brief questions now take 1–3 s instead of 1–36 s; `track-record` and `ranges run` drop from about 9.5 s to about 4 s. The loading state stays (cold start), but no longer needs a "this can take half a minute" line.

## Design review (nov.07.2026)

Explainer, analyst and professor in parallel, after Steps 0–2 were committed.

- **Professor: one blocker, taken.** The merger caveat overclaimed: "they do not carry that error" is true of shock sizing only, and the baseline has its own, larger error on a deal (it leaves out the bought company's revenue; `docs/phase1-review.md` "Mergers": Microsoft's first full quarter with Activision about 3% above the baseline). The text now names that error, says Warren marks those quarters as scope changes, and says the finding rests on two cases. Ideas: a timing clause (the shock can start before the close) only matters beside shocked forecasts, filed; a `role` param (question company or case company) for the coverage note, filed; the student sentence for `beyond_history` should avoid "CIK" and "registrant" (front-end, in `docs/team-sync.md`); MacKinlay (1997) on confounding events in the window supports the scope rule.
- **Explainer: one blocker, rejected with a reason.** It read the caveat on a 2021-dated question as citing a 2026 finding. The point-in-time rule is about data that feeds an analysis; the caveat describes the method that made the forecasts on screen, and names no deal. Recorded under *Point in time* (the analyst reached the same view). Gaps taken: "stop" wording now says "missing from" the date on; the notes list grows (Product impact); timings below are measured, not targets; the cached facts are read-only.
- **Analyst: GO, no blockers.** Checked the shared reads against fresh reads on XOM, WMT, MSFT and CAT on three dates (identical; 43 XOM flags). The note starts on 2026-08-03 and not the day before. Ideas taken: the coverage note uses the CIK `universe.csv` pins instead of a ticker lookup (a successor under the same ticker could have hidden it); a read-only mapping in `FactReads`. Filed: a test that the universe file's `note` text names no date after `history_ends` (it is shown on any D from the cut-off).

## Results (nov.07.2026)

Snapshot `warren-20261105T101750Z` (schema 21). Before = main at `6427366`, after = this branch.

- **`basis_flags`:** old per-run reads against shared reads, all 8 companies on 2022-06-30, 2024-11-15 and 2026-11-07: 24 of 24 sets identical (KO 68, XOM 43, JNJ 87 on the later dates, PG 6, others 0). Per company: 1.2–7.0 s before, 0.1–0.5 s after.
- **The brief's questions** (D = 2026-11-07), `past-events --json`: identical once the new notes are taken out. MSFT `m_and_a` 16.3 → 1.7 s (adds `merger_shocks_missized` and Exxon's `beyond_history`, from the Pioneer case); AAPL `supply_chain` 5.5 → 0.9 s; XOM `macro` 3.5 → 0.9 s (adds `beyond_history`); WMT `guidance` 36.4 → 3.1 s; JNJ `policy` 6.5 → 1.1 s. On D = 2026-08-02, MSFT `m_and_a` has the merger caveat and no coverage note.
- **`track-record --json`** for all 8 companies and **`ranges run --json`** on each company's newest baseline: 16 of 16 identical byte for byte; each about 9.5 s → 4 s.
- Tests: 1,783 passed, 10 skipped (browser tests run in CI); ruff clean; CI green.
