# Backlog #424: run the test suite in parallel (pytest-xdist)

Issue: https://github.com/sonderbot-ar/warren/issues/424 (scout, nov.16.2026) · Branch `backlog-424-parallel-tests` · Version v0.10.10 (patch, backlog item). Tooling only: no engine module, reading rule, value, run or output changes.

## Problem

Every track runs the whole suite (`python -m pytest -q`) before each push, the gatekeeper runs it again, and CI runs it on every pull request and every push to `main`. It runs one test at a time: on this cloud machine (4 CPUs) the 2,630 tests take **198.6 s** (202 s wall). Warren has merged hundreds of PRs, each with several pushes, so the wait adds up for every team member and for CI.

pytest-xdist (MIT, 3.8.0, pytest-dev) runs tests in several worker processes. It changes where and in which order tests run, not what any test asserts.

## Plan

- **Step 0.** This design doc, with the measurements below.
- **Step 1. Turn it on for every run.**
  - `requirements.txt`: pin `pytest-xdist==3.8.0` and its one hard dependency `execnet==2.1.2`, under "Development".
  - `pyproject.toml` `[tool.pytest.ini_options]`: `addopts = "-ra -n auto --dist loadfile"`. Putting it in `addopts` means every existing command (CLAUDE.md, the run-track and goldfish skills, the gatekeeper and test-writer agents, CI) gets the parallel run without a wording change.
  - `--dist loadfile` keeps each test file on one worker, so a module-scoped fixture (the browser tests' server and Chromium, `tests/webapp/test_browser.py` lines 27–44) starts once, as it does today, and tests inside a file keep their order. The slowest file takes 22 s of a 60 s run, so grouping by file costs little balance.
  - `-n auto` uses one worker per CPU. To debug a single test one at a time: `python -m pytest -n 0 …`, which ignores `--dist` (or `-p no:xdist`, which also drops both options' meaning; pytest then rejects them, so use `-n 0`).
  - Tests: none added; the suite itself is the test. Exit: the full suite passes with the new defaults several times in a row, with the same count as one-at-a-time (`-n 0`) on the same machine (the count includes the ten browser tests only where a Chromium is found, as in CI); `ruff check .` and `ruff format --check .` clean; CI green, and CI's pytest step faster than on `main`.

## Shared-state check (the scout's fit concern)

- **SQLite and files.** Every test database comes from the `db_path` fixture (`tests/conftest.py`), a fresh file under `tmp_path`; a scan of `tests/` for writes (`grep -rn -E "open\(|write_text|to_csv|mkdir" tests`) found only `tmp_path` paths, and no test calls `create_app(` without a `db_path` (the app falls back to the real database only then, `webapp/app.py`). xdist gives each worker its own temporary root, so no two workers share a file. The repository's `data/` is never written by a test.
- **Ports.** The browser tests' server takes a free port from the OS (`webapp/screenshots.py`, `_free_port`, bind to port 0). Two workers asking at once get different ports; the gap between closing the probe socket and uvicorn binding is the same as today and has not collided in the suite's history (the browser tests have run on every CI run since F2 Step 1) or in the five parallel runs below.
- **Hypothesis.** Its example database (`.hypothesis/`) is a directory of files that Hypothesis documents as safe to share between processes (hypothesis.readthedocs.io, "The Hypothesis example database": `DirectoryBasedExampleDatabase`).
- **Environment.** `monkeypatch` changes are per test and per process.

## Measurements (this cloud machine, 4 CPUs, Python 3.13, nov.19.2026)

| Run | Result | Time |
|---|---|---|
| One at a time (today's default) | 2,630 passed (browser tests with a local Chromium) | 198.6 s |
| `-n auto --dist loadfile`, four runs | 2,630 passed each time | 69 s, 60.9 s, 60.7 s, 62.1 s |
| `-n auto` (default `load` distribution) | 2,630 passed | 62.4 s |
| `-n 8 --dist loadfile` | 2,630 passed | 57.2 s |

The first parallel run (69 s) included a cold start (fresh `__pycache__` for the workers). Per-file times from `--durations=0`: `tests/analysis/test_whatif.py` 22.2 s, `test_reported.py` 12.3 s, `tests/orchestration/test_graph.py` 8.9 s; every other file under 8 s. These runs are on Python 3.13; CI runs 3.11, so CI's own times are recorded at the PR.

About **3.2 times faster**. GitHub documents 2 CPUs for its standard Linux runner on a private repository (docs.github.com, "GitHub-hosted runners", standard runners table), so CI should gain less; this is a guess until the PR records CI's real pytest time against the last `main` run's.

## Alternatives considered

- **Leave it serial.** Rejected: about 2 minutes 20 s saved on every local run here, and every agent runs the suite several times per track.
- **Only in CI (`pytest -n auto` in `tests.yml`).** Rejected: the agents' local runs, which happen more often than CI, would stay slow, and the commands would differ between CI and the docs.
- **`--dist load` (default).** About as fast here, but a module-scoped fixture would start once per worker (four Chromiums for the browser tests) and a file's tests would no longer run in their order. Rejected for `loadfile`.
- **Pick tests by changed files (testmon and similar).** Different job and a correctness risk (a missed dependency skips a test that should run). Out of scope.

## Files to change

`requirements.txt`, `pyproject.toml`, this doc; after merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

None. No engine output, value, run, note or name changes; brief questions served or broken: none. The front-end team's tests (`tests/webapp/`) also run in parallel; its screenshots step in CI is unchanged.

## Results

(Filled in at the PR.)

## Review notes

(Filled in after review.)
