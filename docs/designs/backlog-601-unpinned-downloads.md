# Backlog #601: say when an answer's price, index or yield download is not the run's own

Issue: https://github.com/sonderbot-ar/warren/issues/601 (from the #499 analyst) · Branch `backlog-601-unpinned-downloads` · Version v0.10.51 when merged.

Status: Done (v0.10.51, nov.26.2026; PR #603, merge `1a2f495`, after CI green and a gatekeeper GO).

## Problem

The inputs behind an answer (`inputs_behind`, Q5) draw the history of the market cells (risk-free rate, beta, ERP, share counts) on the run's own downloads: `Singles.pins()` in `domains/analysis/single_values.py` pins the company's prices, the market index and the 10-year yield by the hashes the run stored, as `reproduce` does. When one of those downloads is no longer stored (every run stores all three hashes, `runs.*_fetch_sha256 NOT NULL` in `shared_kernel/migrations/0005_runs.sql`, so the only cause is a download replaced before downloads were kept, migration 0006), `_pin_map` skips it and every read inside `pins()` falls back to the newest download by `fetch_id` (`selected_fetch` → `latest_fetch`, `domains/market/store.py`). Most reads stay point-in-time because `require_coverage` refuses a download made before their date ended; the exception is the share series' split factor (`split_factor`, `domains/market/prices.py`), which reads the newest price download with no coverage check, so a download that stops before the run's date can miss a split silently (analyst). Either way the chart may not be the one the run would draw, and nothing says so. #499 added `yield_fetch_pinned` on the `year_average_yield` variant of `below_risk_free` only; the risk-free, beta, ERP and share series read the same downloads and say nothing.

## Plan

**Step 0. This doc.**

**Step 1. A series note naming each download that was not the run's own, with tests.**
- `Singles.unpinned()` returns, computed once per answer and cached on `Singles`, one entry per download (not per series) the run names that could not be pinned: `{"role": "price" | "index" | "yield", "source": "yahoo" | "fred", "symbol": the ticker, ^GSPC or DGS10, "read_fetched_at", "covers_run_date"}`. `read_fetched_at` is the UTC time of the download read instead (the newest by `fetch_id`, exactly what `selected_fetch` reads); `covers_run_date` is whether that download was made after the run's date ended in New York (`covered_through >= as_of`). A symbol with no stored download at all is left out: its points already carry `market_data_not_loaded` (product lead).
- A new series note `download_not_pinned` (`SERIES_NOTES`, on `Series.notes` of the cell's history), params `downloads`: the entries above for the roles the series reads, on: `risk_free_yield` (yield; also the terminal-growth card, which shows the same series), `beta` (price, index), `erp` (index, yield), and the three share series (price: the split factor). No note when every download the series reads was pinned, so today's answers are unchanged. On the share series the note appears even when every split factor is 1 (nothing can differ then); kept, since the series did read another download.
- The cost-of-debt series gets no `download_not_pinned`: it reads the yield only inside its `below_risk_free` notes (the `year_average_yield` variant), which already carry `yield_fetch_pinned` (#499); the used year reads the run's stored row, not a download.
- Tests in `tests/analysis/test_single_values.py`, on the stored fixture run: no `download_not_pinned` anywhere when all three are stored; with the yield download deleted, the note on the risk-free and ERP series (role `yield`, `not_stored`, `read_fetched_at` equal to the newest yield download) and not on beta or shares; with the price download deleted, on beta and the share series only; with the price download's time set before the run's date, `covers_run_date` false on the share series; with price and index both replaced, both on beta; market points still use no date after the run's date in every case (the rule is on points, not on `read_fetched_at`).
- Exit: full suite, `ruff check`, `ruff format --check` green.

**Step 2. Real-data count.** On the restored snapshot `warren-20261125T103202Z`: for every stored run, which of its three downloads cannot be pinned, and whether the newest download covers its date. Recorded under *Real-data check*; no code. Exit: the counts are in this doc.

## Alternatives considered

- **One note on the whole answer** (the issue's first option). `InputsBehind` has no answer-level notes today, and a screen shows one card at a time, so a card-level reader would have to look elsewhere; the series is where the numbers that may differ are drawn.
- **Name the `fetch_id` read.** An internal row id means nothing to a student or a screen; the download's time does ("una descarga del 20 de noviembre").
- **A `reason` (`not_stored` / `not_recorded`).** Planned first; dropped because the hashes are `NOT NULL` since the runs table was created, so only one cause exists.
- **Refuse the split factor when the price download does not cover the run's date** (analyst's other option). A flag keeps the history and lets the app say it; refusing would blank the whole share card for an old run.
- **A bool per role, like `yield_fetch_pinned`.** Six flags on four series; a list of the downloads that were not pinned is one shape for every series and says why.
- **Refuse the history when a download is not pinned.** Loses true, point-in-time history to protect exact reproduction of a chart; a note is enough.

## Files to change

`domains/analysis/single_values.py` (`Singles.unpinned`, `_monthly`, `_erp`, `_shares`, `SERIES_NOTES`), `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/build-plan.md` (no milestone row; backlog items are recorded in versions), `docs/team-sync.md`.

## Product impact

Serves Q5 (the inputs behind an answer: the risk-free, terminal growth, beta, ERP and share cards). Additive only: one new series note code, `download_not_pinned`, with params `downloads` (list of `{role, source, symbol, read_fetched_at, covers_run_date}`); it appears only when a run's own download is gone (Step 2 gives the count). It sits on the risk-free, terminal-growth (same series), beta, ERP and share cards. Nothing renamed or removed; no stored number or reproduce check changes (the notes are read live).

Wording (product lead), shown above the chart like every series note (brief §3, "Notes on a series"), date only, in the region's format: "Este gráfico usa {roles} descargados el {fecha}, no los de la estimación original. Esa descarga ya no está guardada. Las fechas son las mismas, así que no entra ningún dato posterior a la fecha de corte. Algún valor puede diferir levemente del original." Roles: price "los precios de la acción de {empresa}", index "los valores del índice S&P 500", yield "los rendimientos del bono del Tesoro de EE. UU. a 10 años"; several roles in one sentence. When `covers_run_date` is false (share cards only can be affected in practice), the engine team suggests replacing the third sentence with "Esa descarga es anterior a la fecha de corte, así que puede faltar una división de acciones reciente."

## Review notes

Explainer: 13 guesses. Taken: once per answer and per download (Step 1); sources and symbols per role; where the note sits; what the cost-of-debt card does; the point-in-time rule is on points, not on `read_fetched_at`; Step 2's exit and snapshot. `not_recorded` dropped (the hashes are `NOT NULL`, so the question of a null hash is moot). Not taken: `math_engine._shares` is the valuation's own share step and is not read here; backlog items have no build-plan row (versions only, as for every backlog item).

Analyst: GO with changes. Roles confirmed (risk-free: yield; beta: price and index; ERP: index and yield; shares: price via `split_factor`; no other read under `pins()`). Taken: `split_factor` has no coverage check (`domains/market/prices.py`, `split_factor` uses `selected_fetch`, not `require_coverage`), so a price download that stops before the run's date can miss a split; the entry says `covers_run_date`, with a test; the Problem no longer says every read is covered; "newest by `fetch_id`"; the share-series note can appear with every factor 1, said above; Step 2 counts downloads that do not cover the run's date.

Product lead: changes needed, all taken: above the chart, not under it; the terminal-growth card gets it; one sentence per case (now one reason plus `covers_run_date`); an entry with no stored download is left out (the points already say `market_data_not_loaded`); date only, no time or UTC.

Real-data check (Step 2, snapshot `warren-20261125T103202Z`): all 936 stored runs (every company's newest is dated 2026-10-30) can pin all three of their downloads, so no answer carries `download_not_pinned` today and none has a price download that stops before its date. The note is a guard for a download replaced or pruned later.

Gatekeeper GO on PR #603: 2962 passed, 10 skipped, ruff clean; with `main`'s `single_values.py` the four note tests fail and the no-note test passes, as expected; no test lines removed. Non-blocking, filed as #604: the no-later-date helper checks only risk-free and beta points; `_newest_fetch_time` filters by source, not symbol.

Professor: not run. No method, formula or estimate changes; the item only says which stored download a chart was drawn on.
