# Backlog #477 item 2: a fast answer

Issue: https://github.com/sonderbot-ar/warren/issues/477 (item 2 of 4; also comment item 7) · Branch `backlog-477-speed` · Version v0.10.17 when merged.

## Problem

The first screen (F2 Step 4b, part 1) makes three engine calls for one answer: the ranges and their track record (`run_ranges`), the inputs behind the four revenue figures (`inputs_behind`) and the sources (`run_sources`). On the nov.19 snapshot, Apple's answer on 2026-10-30 took about 8 s: 4.4 s for the ranges, 3.9 s for the inputs, 0.01 s for the sources. A value-per-share answer's inputs took 3.3 to 8.6 s across the 2026-10-30 runs. The design critic counted a first load of about 10 s with nothing on screen. The issue asks for under 2 s if the screen needs it; it does.

Profiling (cProfile, Apple 2026-10-30) showed where the time goes, and none of it is arithmetic:

- **Inputs.** `reported_period` is called once per period (27 times for a Q5 answer). Each call re-read the company's newest-filing disagreements for its line names (`newest_filing_disagreements`, 26 calls, 2.3 s), although that list depends only on the company, the date and the names. The series notes (`_series_meaning_notes`, `_series_recast_notes`, 6 calls, 2.3 s) re-read the company's views, recasts, version dates and filings every time, although `reported_period` had already read the same views.
- **Ranges.** The track record (`scored_origin_rows`, 4.4 s) rebuilds the baseline range of every scored origin since 2021 (550 subjects, 8,730 percentiles over 10,000 samples) on every call. Those rows depend on the origin, every past miss and the sample count, never on the date asked: the date only picks which rows count.

## What changes

No number, note, field or output changes. Two kinds of reuse:

1. **Reads kept between periods** (`domains/analysis/reported.py`). `reported_period(..., _shared=...)` (kept since #471 for views, filings, meaning changes, sign flips and parts) now also keeps the newest-filing disagreements per set of line names. `_series_meaning_notes` and `_series_recast_notes` take the same optional `_shared` and keep the views, filings, meaning changes, recasts and version dates under the same keys `reported_period` uses, so a view read for a period serves the notes. Every key starts with the company's CIK and the date (`("views", cik, as_of, quarterly)`, `("filings", cik, as_of)`, `("changes", …)`, `("recasts", …)`, `("versions", …)`, and `("newest", cik, as_of, names)` beside the existing `("flips", …)` and `("parts", …)`), so a kept read can only serve the same company on the same date. `inputs.py` passes its reader's dict, which lives for one `inputs_behind` call and is dropped with it, so a database change between two calls is always read. Without `_shared`, every call reads afresh as before. A small `_once(shared)` helper replaces the closure `reported_period` had.
2. **The track record's origin rows built once per process** (`domains/evaluation/run_ranges.py`). `_origin_rows(subject, pairs, n)` keeps each origin's `subject_rows` in a module dict. The kept rows are used only while the misses (compared as a tuple of every `ErrorPair` field, exact equality, not a hash), the sample count and the origin (kind, id, ticker, date, run and its forecasts and actuals, as sorted JSON) equal the ones they were built from; a change to any of them builds afresh, and a change to the misses or the count drops every origin's kept rows, not only the affected one (any origin's range draws from all misses known on its date). The misses and origins are read from the database on every call (`R.load_pairs`, `R.origin_subjects`, as before), so a new origin, a changed miss or a new forecast stored while the app runs is seen on the next call. The date asked is not in the key because it is not an input to the rows: each origin's range uses only the misses known on the origin's own date (`R.known(..., on=subject.as_of)`), and the asked date's filters (origin dated before it, actual filed by it) run on the kept rows afterwards, as they ran on fresh rows before (professor). The rule is the memoisation rule: a function may be remembered only if it is pure, and the key must hold every input it reads (Michie 1968). Callers get copies, so changing a returned row cannot change the kept one. One lock covers the check, the build and the read, because the app serves requests on worker threads: without it, a request with newer misses could reset the kept rows while another was building, and the first would then write rows built from the old misses under the new ones (analyst). `forget_kept_rows()` empties it, and every test starts and ends with it (`tests/conftest.py`).
3. **The past-the-history warning on every period.** `reported_period` now calls `warn_if_beyond_history` itself. With every read kept, a later period made no read that warned, so its `warnings` lost `beyond_history` (analyst, Exxon on 2026-10-30); the warning is deduplicated, so a first period still carries it once.

## Plan

**Step 0. Profile and this doc.** Exit: the time is placed (above).

**Step 1. Kept reads in the inputs call.** Tests in `tests/analysis/test_shared_reads.py` on Test Corp across a recast and a change of meaning (both notes fire): every period of five years and five quarters read with kept reads equals the period read afresh (`asdict`); both series notes with kept reads, read again from what was kept, and read afresh are equal; the kept dict holds the new keys, so the test reaches them; on a date past the company's history every period, kept or fresh, carries `beyond_history` once. This is also #477's comment item 7 (the gatekeeper's `_shared` equality test). Exit: tests green.

**Step 2. The track record kept per process.** Tests in `tests/evaluation/test_run_ranges_kept.py`: kept rows equal a cold build; kept rows serve another date as a cold build would; changed misses or a changed count build afresh; a changed origin (its forecast moved in the database) builds afresh and differs; a caller editing its rows leaves the kept ones alone; a request with other misses waits while another builds, and each gets the rows of its own misses (fails without the lock). Exit: tests green.

**Step 3. Real check.** On the nov.19 snapshot, 24 stored baselines (the eight companies on 2026-10-30 and 16 drawn at random, seed 477, from 2019 to 2026): `run_ranges`, `inputs_behind` for the first four revenue quarters, and `inputs_behind` for value per share, dumped to JSON (`sort_keys`) from `main` and from this branch in two separate processes, each starting cold, one after another in run order (AAPL, CAT, JNJ, KO, MSFT, PG, WMT, XOM on 2026-10-30, then PG 2023-04-01, KO 2024-08-15, AAPL 2022-12-01, JNJ 2024-08-15, WMT 2021-10-01, CAT 2023-04-01, PG 2019-05-01, PG 2020-08-01, PG 2020-04-01, PG 2024-02-15, CAT 2024-04-01, AAPL 2020-11-01, PG 2026-02-01, CAT 2023-10-01, KO 2026-09-15, KO 2022-11-01, each `_1`), and the parsed dumps compared for equality. Exit: the two dumps are equal, and the times are recorded.

## Results (nov.20.2026, 4-CPU cloud machine, nov.19 snapshot)

- **Same answers.** The 24 runs' three calls dump 9.6 MB of JSON on `main` and on this branch; the files are equal, before and after the review's changes. Exxon's periods on 2026-10-30, kept and fresh, carry `beyond_history` as on `main`.
- **Faster.** The 24 runs' calls took 296 s on `main` and 106 s on this branch, each total including one cold track-record build. The table is a second script, one process, the four runs in the order shown, so only AAPL's ranges call is cold.

| 2026-10-30 run | ranges before | ranges after | inputs Q5 before | after | inputs value per share before | after |
|---|---|---|---|---|---|---|
| AAPL (first call) | 4.59 s | 4.48 s | 3.80 s | 1.21 s | 7.25 s | 2.01 s |
| MSFT | 4.51 s | 1.19 s | 4.44 s | 1.88 s | 7.46 s | 2.63 s |
| XOM | 4.20 s | 0.99 s | 4.05 s | 0.60 s | 8.59 s | 1.42 s |
| CAT | 4.36 s | 1.17 s | 2.05 s | 0.95 s | 3.33 s | 1.69 s |

The track record still costs about 4.4 s the first time a process asks for it; every later answer in that process, on any company and any date, pays about 1 s (the three warm rows of the table; what is left is the change-of-basis count on the run's own company, `basis_flags`, 0.85 s in the profile). A Q5 answer after the first takes 1.6 to 3.1 s for ranges and inputs together on these runs (was 6.3 to 9 s).

**Not done here.** The first track-record build (a cold app start) is still 4.4 s: the percentiles themselves are most of it (1.8 s in numpy's partition). Making that faster without changing a digit means computing the same order statistics another way, which is a method question, not a reuse one; it is left for backlog #492 if the app's warm-up does not hide it. The rest of an inputs call is the per-name fact reads (`_rows_by_period`, 0.9 s), shared by three functions in `facts.py`; a joint read is a larger change.

## Alternatives considered

- **Read the track record from the stored M9 build (`range_results`).** Rejected for now: a stored build is tied to the code version and the misses known on its own date, so it rarely matches a live call, and `reproduce` would need to vouch for it each time.
- **Keep the track record in the database.** Rejected: a cache table that must be invalidated by hand is a new piece of state; the process memory is enough for one app session.
- **Vectorise the percentiles.** Not taken: the partition cost stays, and a different call path risks a last-digit change the reproduce rule would have to absorb.
- **Let the app cache each answer.** The app already keeps each stored run's bundle (F2 Step 4b part 1), which helps a second look at the same run, not the first look at any run.

## Files

`domains/analysis/reported.py`, `domains/analysis/inputs.py`, `domains/evaluation/run_ranges.py`, `tests/analysis/test_shared_reads.py`, `tests/evaluation/test_run_ranges_kept.py`, `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves every brief question whose answer shows ranges or input charts (Q3, Q4, Q5, Q8): an answer that took 6 to 9 s takes 1.6 to 3.1 s once the app has built the track record once. No output, field, code or name is added, renamed or removed. For the front-end team: the first answer in a fresh app process still pays about 4.4 s for the track record, so the app can warm it at start (one `run_ranges` call on a recent stored run: a call builds only the origins dated before its own date, so a recent date builds them all) while it shows *Inicio*; nothing needs changing for the speed-up itself.

## Reviews

- **Explainer**: 20 gaps. Taken: the kept keys and that each starts with the CIK and date; the reader's dict lives for one call; a change to the misses drops every origin's rows; why the date asked is not a key; how the dumps were compared, the 24 runs named, which timings are cold; where the 1 s left comes from; the warm-up date. Not changed: brief codes and the F2 step names are defined in `docs/product/brief.md` and `docs/designs/f2-web-app.md`.
- **Analyst**: NO-GO on one blocker, taken: the kept rows were not safe across the app's threads (a reset between one request's check and its write); now one lock, and a test that fails without it. Suggestions taken: `beyond_history` on every period (What changes 3, a test); every test clears the kept rows. Noted, no change: `run_ranges` and the track-record report both use 10,000 samples, so the one kept count does not churn.
- **Professor**: PASS. Memoising a pure function is sound (Michie 1968), the two-process dump is the reproducibility evidence (Peng 2011), and rejecting a hand-invalidated cache table is right. Taken: the sentence on why the date is not a key (What changes 2). Idea for the lesson: this change as a worked memoisation example.

