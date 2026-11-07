# Backlog #252 (part 1): past events say when Exxon's filings stop, warn about merger shocks, and answer in seconds

Issue: https://github.com/sonderbot-ar/warren/issues/252 · Branch `backlog-252-past-events-speed` · Status: in review (nov.07.2026).

## Problem

The design review of #146 (v0.9.34, the past-events call) left five ideas. This item takes the three the app needs before the event screens; items 3 and 4 stay open on the issue.

1. **Exxon's coverage note** (product lead; brief Q14, #126). Exxon's filings on its old CIK stop on 2026-08-03 (`universe.csv`). A run says so with a `beyond_history` note (v0.9.22), but `past_events` has no such field: an Exxon answer dated after August silently has fewer reported quarters and a shorter usual set, and the student is not told why. Exxon also appears as a *case* company in other answers (the Pioneer deal in every `m_and_a` answer).
2. **The merger caveat** (product lead; brief Q10). The Phase 1 review found Warren's AI news shocks mis-size mergers (`docs/phase1-review.md`, "Mergers": a shock's size comes from how much revenue usually moves, not from the size of the company bought). An `m_and_a` answer says only `baseline_only`, which a student could read as "the AI is fine on deals".
3. **Speed.** A `guidance` question takes 36 s on the restored snapshot (measured: MSFT `m_and_a` 16 s, WMT `guidance` 36 s). The profile: 47 of 48 s are in `run_ranges.basis_flags`, which calls `hindsight.against_actuals` for each of a company's ~90 monthly forecasts, and each call reads the company's filings again: 553 runs made 4,427 fact reads (`harness._quarterly`), almost all the same (company, date, mode) over and over. The reads depend only on the company, the date and the mode, never on the run.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Two notes.**
  - `universe.coverage_gap(cik, as_of)` returns the coverage warning's text and fields (the same eight fields as `CoverageWarning`: `ticker`, `cik`, `as_of`, `history_ends`, `reason`, `successor_cik`, `successor_name`, `note`), or None; `warn_if_beyond_history` now calls it, so the warning and the note can't drift.
  - `past_events` adds one `beyond_history` note per company in the answer (the question's company and every listed case's company) whose filings stop on or before D, sorted by ticker. Same code, params and English text as a run's note, so the app's sentence for `beyond_history` serves both.
  - An `m_and_a` answer adds `merger_shocks_missized` (params `{"event_type": "m_and_a"}`). Its text names no deal: a question dated before Activision closed must not learn of it (point in time).
  - Both go after the existing notes, so the existing notes keep their order.
  Tests: the note's params and text on a company whose filings stopped before D; none the day before they stop; a case company's note on another company's question; the merger caveat on `m_and_a` only and naming no deal; `coverage_gap` gives exactly the warning's text and fields, and None before the end, for an unpinned CIK and for None.
  Exit: tests pass; every existing past-events test unchanged.
- **Step 2. Shared filing reads.** New `hindsight.FactReads(conn)`: keeps `_quarterly(cik, date, mode)` and the company's filing list per key. `against_actuals(conn, run_id, actuals_on, reads=None)` uses it (a fresh one when none is given, so every existing caller behaves as before). `run_ranges.basis_flags` makes one per call and passes it to every origin. Nothing else changes: the same functions read the same rows; they are read once instead of ~8 times. A `FactReads` lives only for one call, so it never holds data across a write.
  Tests: two runs of one company through one `FactReads` give the same `to_dict()` as without it, on the recast fixture (so a `restated_basis` flag is in the answer); each (company, date, mode) is read once with sharing, and more than once without.
  Exit: tests pass; `basis_flags` unchanged on real data.
- **Step 3. Real data** (snapshot `warren-20261105T101750Z`). Before (main) and after (branch):
  - `basis_flags` for all 8 companies on 2022-06-30, 2024-11-15 and 2026-11-07, the old per-run reads against the shared ones: identical sets, with timings.
  - `past-events --json` for the five brief questions (Q10 MSFT `m_and_a`, Q12 AAPL `supply_chain`, Q13 JNJ `policy`, Q14 XOM `macro`, Q15 WMT `guidance`), D = 2026-11-07: identical once the new notes are taken out, with timings.
  - `track-record --json` for all 8 companies and `ranges run --json` on each company's newest baseline: identical byte for byte (both call `basis_flags`).
  Exit: all identical; the slowest question under 10 s.

**Point in time.** Nothing new is read. The coverage note uses D, the question's date; the merger caveat names no deal. **LLMs.** None. **Decision 11.** The cut-off stays data in `universe.csv`; no new source, company or currency; the cache is a library object, not a service.

## Alternatives considered

- **Catch the coverage warning while reading, as `reported_period` does.** Rejected: the evaluation reads (`harness._quarterly`) silence it on purpose (coverage is a hard error in the guard), and catching it would depend on which reads happened to run. Asking the universe file for D and each company in the answer is direct and testable.
- **Cache `basis_flags` per company and date across calls** (the issue's first idea). Rejected for now: a cache that outlives a call must be dropped when new filings or monthly forecasts land, which is a new failure mode; sharing reads within one call gets most of the gain with none of that risk.
- **Check only each group's first origin** (the issue's second idea). Rejected: the flag depends on each origin's own history rows (`hindsight._basis_change` compares the filing with the run's basis), so skipping origins could change which quarters leave the usual set.
- **Name the two deals in the merger caveat.** Rejected: point in time (above). The app can link the Phase 1 review for a student who wants the cases.
- **Items 3 (pro forma revenue, ASC 805-10-50-2(h)) and 4 (a shared 2020 window).** Left on #252: each changes what the answer compares, so each needs its own design and review.

## Files to change

`domains/fundamentals/universe.py`, `domains/evaluation/past_events.py`, `domains/evaluation/hindsight.py`, `domains/evaluation/run_ranges.py`, `tests/fundamentals/test_universe.py`, `tests/evaluation/test_past_events.py`, `tests/evaluation/test_hindsight.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q10–Q15 ("Eventos"). Two new note codes on `past_events(...).notes`, both after the existing ones: `beyond_history` (the run note's code, params and English text; zero or more, one per company whose filings stop by D) and `merger_shocks_missized` (on `m_and_a` only; params `event_type`). The app needs a Spanish sentence for `merger_shocks_missized`; `beyond_history` reuses the run note's. No field, name or other output changes. Speed: the five brief questions now take 1–3 s instead of 1–36 s; `track-record` and `ranges run` drop from about 9.5 s to about 4 s. The loading state stays (cold start), but no longer needs a "this can take half a minute" line.
