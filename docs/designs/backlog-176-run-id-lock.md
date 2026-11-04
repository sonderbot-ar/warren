# Backlog #176 design: run ids numbered inside the write transaction

Issue #176 (front-end, from the F2 design review, `docs/designs/f2-web-app.md`, "Rules for sharing the database"). Branch `backlog-176-run-id-lock`.

## Problem

A run's id is its company, date and a sequence number (`AAPL_2024-03-31_3`). `save_run` counted the stored runs and inserted `count + 1` as two separate statements (`domains/analysis/runs.py`), and `whatif.revalue` looked for a stored copy of the same what-if, then numbered the new child the same way (`domains/analysis/whatif.py`). Python's `sqlite3` only opens a transaction at the first insert, so the count ran outside it. Two requests at the same moment both counted the same number: the second hit the primary key (`0005_runs.sql`) and failed, or, for a what-if, both missed the stored copy and stored it twice. On the owner's Mac the app sends every write through one lock, so this is harmless today; a hosted app with several students would hit it.

## Plan

- **Step 0.** This design doc.
- **Step 1.** `runs.write_lock(conn)`: a context manager that opens the transaction with `BEGIN IMMEDIATE`, so SQLite's write lock is taken before the count or lookup, not at the insert; a second writer waits (up to the connection's 10-second timeout) and then counts the first writer's row. It commits on success and rolls back on any error. A transaction the caller left open is committed first, which is what the old `with conn:` commit did anyway. `save_rows` numbers the run inside the lock when given a function for `run_id` (`save_run` passes one); a fixed id still works. The inserts move to `insert_rows`, for callers already under the lock. `revalue` holds the lock around "is this what-if stored?" and "number and insert the new child". The git call that names the code version runs before the lock, so the lock is held only for SQL. Tests (`tests/analysis/test_run_id_lock.py`): six writers on six connections, released together, each pausing 50 ms after every read of `runs` to widen the race far past a real request's: six baseline saves get ids 1 to 6, each reproduces; six identical what-ifs store one child, one answer `reused: false` and five `true`; six different what-ifs are numbered 1 to 6; an error inside the lock leaves nothing behind; a caller's open transaction is kept. **Checked against the old code:** the three race tests fail there with `UNIQUE constraint failed: runs.run_id`. Exit: all tests and ruff pass; no stored id, number or output changes.

## Alternatives considered

- **Retry on a primary-key error.** Hides the race instead of removing it, and doesn't stop a what-if being stored twice.
- **An `AUTOINCREMENT` counter table.** Changes the schema and makes ids depend on a second table; the existing ids are already readable and stable.
- **A process lock in the app.** That is what F2 does for now on one machine; it can't cover two processes or a hosted app.

## Product impact

Serves the F2 rule "two requests at once must not collide" (`docs/designs/f2-web-app.md`, Engine needs) ahead of hosting. Brief questions: none change. No output, name or field is added, renamed or removed: ids are numbered exactly as before, `revalue`'s answer and `reused` keep their meaning. New public helper `domains.analysis.runs.write_lock(conn)` for any engine write that counts before it inserts. The app's own process lock can stay; it is no longer needed for correctness.

## Files to change

`domains/analysis/runs.py`, `domains/analysis/whatif.py`, `tests/analysis/test_run_id_lock.py`, `docs/versions.md`, `docs/team-sync.md`.
