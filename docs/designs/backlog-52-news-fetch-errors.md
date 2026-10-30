# Backlog #52: news downloads, errors apart from gaps, polite retries, a sliding window

Issue: https://github.com/sonderbot-ar/warren/issues/52 · Branch `backlog-52-news-fetch-errors` · Version v0.4.1 when merged.

## Problem

The first real M5 ingest (oct.30.2026) showed three faults in how GDELT files are downloaded:

1. **A download error looks like a GDELT gap.** A network drop marked 184 files in a row `missing`, the status of a 15-minute slot GDELT never published. The next run read them fine. The coverage report can't tell "GDELT has no file" from "we failed to fetch it", so a window that is only short because of our network looks like a hole in the source.
2. **No back-off.** An HTTP 429 (too many requests) or 503 from GDELT is recorded at once as a failure. A server that asks us to slow down should be retried after a pause.
3. **Each chunk waits for its slowest file.** `store.ingest_window` downloads eight files, waits for all eight, stores them, then starts the next eight. One slow file stalls seven idle workers.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. A `fetch_error` status and retries in the adapter.**
- `gdelt.http_download` (the only code that speaks HTTP to GDELT, guardrail 1) retries a *transient* failure up to `ATTEMPTS = 3` times in all: a connection error, a timeout, or HTTP 429, 500, 502, 503, 504. The pause before attempt *n* + 1 is 2^*n* seconds (2 s, then 4 s), or the server's `Retry-After` in seconds when it sends one, capped at `MAX_WAIT_SECONDS = 60`. The sleep and the HTTP call are parameters, so tests run without a network or a clock.
- HTTP 404 or 410 means the file is gone from the server: `http_download` raises `gdelt.FileGone`, no retry.
- `store.ingest_file` records `missing` for `FileGone` (GDELT's gap, as today) and the new `fetch_error` for any other request failure after the retries. A slot the master list has no file for stays `missing`.
- A file that was read fine before and can't be fetched now keeps its rows and its `ok` row, as today; the call now returns `fetch_error` instead of `missing`, so the run's printout is honest.
- `ingest` already reads again any file whose status isn't `ok` (`_needs_read`), so a `fetch_error` is retried on the next run with no new flag.
- **Migration 0011** widens the `news_files.status` check to `ok | missing | bad_md5 | fetch_error`. SQLite can't change a check in place, so the table is rebuilt (create, copy, drop, rename) inside the migration's transaction with `PRAGMA defer_foreign_keys = ON`, so sightings that reference the table are checked at commit, after the rename. Rows from before 0011 keep their status: a past `missing` can't be split after the fact, and a re-run reads every non-`ok` file again anyway.
- Tests: a 503 then a 200 returns the file after one 2 s pause; a 429 with `Retry-After: 7` pauses 7 s; `Retry-After: 600` is capped at 60; three 503s raise; a 404 raises `FileGone` at once, no pause; `ingest_file` records `missing` for a 404 and `fetch_error` for a connection error; a file read before keeps its rows and returns `fetch_error`; a `fetch_error` file is read on the next run; migration 0011 on a database with news rows keeps every row and sighting, and accepts `fetch_error`.
- Exit: `pytest`, `ruff check`, `ruff format --check` green.

**Step 2. Report and printout.**
- `report.coverage` returns `fetch_error` beside `missing` and `bad_md5`; the coverage table gets a "Fetch errors" column, and the footnote says a fetch error is ours (run `ingest` again) while a missing file is GDELT's. The 98% flag is unchanged.
- The `ingest` printout counts `fetch_error` too.
- Tests: coverage counts a fetch error apart from a missing slot; the report shows the column.

**Step 3. A sliding window of downloads.**
- `ingest_window` keeps up to `workers` downloads in flight. Files are still stored one at a time in file order, from the main thread; as soon as the oldest download is stored, the next file's download starts. At most `workers` files are downloaded and not yet stored, the same memory bound as now. Files already read under this alias set are still never downloaded.
- Tests: the existing parallel test (order kept, files read before skipped) passes unchanged; a new test with one slow first file shows the later downloads start before it finishes (a counter of downloads started while the first is held, using a `threading.Event`), and that at most `workers` are in flight.
- Exit: green checks; the docstring says what the bound is.

**Step 4. Docs.** The M5 design doc's "Coverage" bullet names `fetch_error`; README unchanged (no new command). After merge, v0.4.1 in `docs/versions.md` with its merge commit.

## Alternatives considered

- *Keep `missing` and add an `error` column.* Rejected: every reader of `status` would have to know to look at a second column, and the report's counts by status would still lump the two.
- *Retry inside `ingest_file` instead of the adapter.* Rejected: HTTP status codes and `Retry-After` are GDELT's transport, which guardrail 1 keeps in `gdelt.py`.
- *More attempts or longer waits.* Not now: a failed file is retried on the next run anyway, so three attempts over about six seconds is enough to ride out a blip without stalling a 670-file window.
- *`asyncio` downloads.* Rejected: threads already overlap the network wait; parsing and SQLite writes stay on one thread either way.

## Files

`domains/news/gdelt.py`, `domains/news/store.py`, `domains/news/report.py`, `domains/news/__main__.py`, `shared_kernel/migrations/0011_news_fetch_error.sql` (new), `tests/news/test_gdelt.py`, `tests/news/test_store.py`, `tests/news/test_report.py`, `docs/designs/m5-news-ingestion.md`, `docs/versions.md`.

## Coordination

M5's real run is going on in another thread on `m5-news-ingestion`. This branch touches only the download path and the report's coverage table; it doesn't change matching, clustering or event runs, so the real run's results stand.

## Where the work stopped

- Started oct.30.2026.
