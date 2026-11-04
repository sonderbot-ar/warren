# Backlog #175: a structured source for every assumption of a run

Issue: https://github.com/sonderbot-ar/warren/issues/175 · Branch `backlog-175-assumption-sources` · a patch version when merged.

## Problem

The front-end's design principle 2 (`docs/product/design-principles.md`): every figure on screen opens a *Fuente* tab. For a model output that tab shows the run, its *fecha de corte* (as-of date) and the source of each assumption. Today a run's assumptions carry their sources only as English text in `assumptions.method`, written by `trace()` and friends in `domains/analysis/math_engine.py` (for example `revenue [Revenues] 2024-03-31 0000320193-24-000069`). The app would have to parse that text to link a number to its filing, and the text changes whenever the code that writes it does. Only `reported.reported_period` (#140) gives filings as fields today. This serves brief questions 3, 4 and 5 (`docs/product/brief.md`) and F2's first screen (one company and date, the forecast with its range, every number traced to its source).

## What changes

1. **A list of typed sources per assumption row, written when the row is made.** `EngineResult.add(name, value, method, period, sources=[...])` takes the sources beside the method text; every place in `math_engine.py` that adds a row passes them from the same objects it already uses for the text (the `Fact`, the `PricePoint`, the risk-free point, the beta's weeks, the ERP's years, the owner's `UserChoice`). The method text is unchanged, so `reproduce` and `rebuild` are untouched. Five kinds (`domains/analysis/sources.py`):
   - `filing`: one fact from EDGAR: `item` (Warren's name, e.g. `revenue`), `concept` (the XBRL tag), `unit`, `period_start` (None for a balance), `period_end`, `fiscal_year`, `fiscal_period`, `value`, `filed_at`, `accession_no` (None when Warren derived the fact, e.g. Q4 = year − nine months), `inputs` (the accessions a derived fact used), `derived`, `restated`.
   - `market`: one downloaded series: `provider` (`yahoo` or `fred`), `series` (the ticker, `^GSPC`, `DGS10`), `measure` (`close`, `weekly_total_return`, `annual_total_return`, `yield`, `splits`), `start` and `end` (ISO dates; equal for one day; for the ERP's calendar years, Jan 1 of the first and Dec 31 of the last), `fetch_sha256` (the download the run used, the same hash `runs` stores).
   - `owner_choice`: a row of `domains/analysis/user_assumptions.csv`: `choice`, `value`, `set_by`, `set_on`.
   - `derived`: computed from other rows of the same run: `inputs` as `[{name, period}]`, each a row the run stores. The app follows them to their own sources.
   - `rule`: a value set by a fixed rule with no data behind it: `code` (`not_reported_zero`: an item not reported within a year, counted as zero; `no_debt`: no debt, so the cost of debt is not used).
   A row may have several sources (revenue growth: the three 10-K comparatives and terminal growth; the cost of debt: the interest and the debt facts of two years).
2. **Stored in a new table**, migration `0020_assumption_sources.sql`: `assumption_sources (run_id, name, period, position, kind, detail)`, primary key `(run_id, name, period, position)`, a foreign key to `assumptions (run_id, name, period)`, `kind` checked against the five names, `detail` the kind's fields as JSON. Written by `runs.insert_rows` in the run's own transaction, so a run and its sources are stored together or not at all. (Numbered 0020: M10's branch holds 0018 and #141 took 0019; the runner applies any unrecorded version.)
3. **What-ifs.** A child copies its parent's sources for every row it copies. A changed row gets one source of kind `what_if`: `parent_run_id`, `before`, `how` (`set`, `add`, `follows_risk_free`, `follows_terminal_growth`), and its parent row's sources are kept under it as `parent_sources`, so the tab can say "you changed this; it was X, from this filing". That is a sixth kind, only on children.
4. **A call and a command.** `domains.analysis.sources.run_sources(conn, run_id) -> RunSources` and `python -m domains.analysis sources --run-id R [--name N] [--json]`. `to_dict()`: `run_id`, `parent_run_id`, `ticker`, `as_of` (the *fecha de corte*), `recorded` (whether the run stored sources), `rows[]` with `name`, `period`, `value`, `sources[]` and `gap`. A `filing` source in the answer adds `filing`: the #140 `Filing` shape (`accession_no`, `form`, `filed_at`, `url` to the EDGAR folder), and `inputs` become `Filing`s too, read from `filings` with the same helper `reported` uses; a `market` source adds `label` (`Yahoo Finance`, `FRED`). A row with no stored source has `sources: []` and `gap` `{code: "not_recorded", params: {}, text}` (runs made before this version). Point in time: the call reads only the run's stored rows and the `filings` table by accession; every filing named was public on the run's as-of date because the row was built from a point-in-time query.
5. **Older runs: a backfill.** `python -m domains.analysis sources --backfill (--run-id R | --all)` rebuilds a baseline's rows from its pinned data (`runs.rebuild`, M2.1) and stores the rebuilt sources only when every rebuilt row equals the stored row exactly, value and method (`Rebuild.ok`); otherwise it skips the run and says why (`rebuild_differs`, or the rebuild's own error). What-ifs are backfilled from their parent. Nothing else in a stored run changes.
6. **A completeness check.** `sources.check(rows, sources)`: every row has at least one source, every `derived` input names a row of the run, every `what_if` is on a child. `save_rows` refuses a run that fails it, so a new kind of row can't be added later without its source.

**LLMs.** None. **Numbers.** None change: sources describe rows, they don't move them.

## Steps

- **Step 0.** This design doc.
- **Step 1.** `domains/analysis/sources.py` (the kinds, `check`, JSON in and out), migration 0020, `EngineResult.add(..., sources=)` and the sources on every row `build_inputs` makes; `runs.insert_rows` stores them; `save_rows` refuses an incomplete set. Tests (`tests/analysis/test_sources.py`, `tests/shared_kernel/test_migration_0020.py`): every row of the test company's run has a source and every derived input resolves; the seed quarter names its 10-Q accession and tag; a rescaled seed names the year and the quarter; `risk_free` names `DGS10` on its date and the run's yield hash; `beta` names the weeks of both series; `erp` names the index and the yield over its years; `terminal_growth` is derived from `risk_free` plus the owner's method; a minority interest not reported is `rule not_reported_zero`; an incomplete set is refused and nothing is stored; the table and its keys exist after 0020 and old runs keep their rows. `reproduce` still passes on every stored test run. Exit: green.
- **Step 2.** What-ifs (item 3), `run_sources` and the command (item 4). Tests: a child's unchanged rows have the parent's sources; a changed row is `what_if` with `before` and `parent_sources`; terminal growth that followed the risk-free rate says so; `filing` sources carry the form and the EDGAR folder URL; a run without stored sources returns `recorded: false` and `not_recorded` on every row; `--json` is plain JSON. Exit: green.
- **Step 3.** The backfill (item 5). Tests: a run whose sources are deleted gets the same sources back; a run whose rebuilt rows differ is skipped with `rebuild_differs` and nothing stored; a what-if gets its parent's. Exit: green.
- **Step 4.** Real data, if the snapshot restores: one new run per company; every row sourced and every filing's accession found in `filings`; `reproduce --all` passes; the backfill over every stored baseline, with counts of filled and skipped runs and why. Results written below.

**Exit criterion:** all tests and ruff pass; every row of a new run has a structured source; `reproduce` is exact; `docs/team-sync.md` names the fields.

## Alternatives considered

- **Parse `method` on read.** Rejected: the issue asks not to, and the text is English prose that changed between versions (rebuild's `values_ok` exists because it did).
- **Rebuild on every read.** Rejected as the default: it needs the full data, takes seconds, and fails when a concept map changes. Kept as the one-time backfill, with the exact-match guard.
- **Wide columns instead of JSON.** Rejected: six kinds with different fields would leave most columns empty; the kind is a checked column and the fields are validated in code, both ways.
- **One source per row.** Rejected: revenue growth and the cost of debt really have several, and the tab should show all of them.

## Product impact

Serves brief questions 3, 4 and 5 and F2's first screen; the *Fuente* tab of design principle 2 can now be built for model outputs. Adds a call `domains.analysis.sources.run_sources(conn, run_id)`, a command `python -m domains.analysis sources`, and a table `assumption_sources`. Fields as in items 1, 3 and 4. Nothing renamed or removed; `method` stays as it is (English, for the trace). An output (value per share, WACC, FCFF) is not an assumption: the tab for an output shows the run and its rows' sources, following `dcf`'s formula. The app asks for sources by run id; `recorded: false` means an older run (show the method text, or ask the engine to backfill).

## Files to change

`domains/analysis/sources.py` (new), `domains/analysis/math_engine.py`, `domains/analysis/runs.py`, `domains/analysis/whatif.py`, `domains/analysis/__main__.py`, `shared_kernel/migrations/0020_assumption_sources.sql`, tests as above, `docs/versions.md`, `docs/team-sync.md`.
