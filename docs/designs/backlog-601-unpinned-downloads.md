# Backlog #601: say when an answer's price, index or yield download is not the run's own

Issue: https://github.com/sonderbot-ar/warren/issues/601 (from the #499 analyst) · Branch `backlog-601-unpinned-downloads` · Version v0.10.51 when merged.

Status: In progress (nov.26.2026).

## Problem

The inputs behind an answer (`inputs_behind`, Q5) draw the history of the market cells (risk-free rate, beta, ERP, share counts) on the run's own downloads: `Singles.pins()` in `domains/analysis/single_values.py` pins the company's prices, the market index and the 10-year yield by the hashes the run stored, as `reproduce` does. When one of those downloads is no longer stored (or an older run never recorded its hash), `_pin_map` skips it and every read inside `pins()` falls back to the newest download (`selected_fetch`, `domains/market/store.py`). The dates are still point-in-time (`require_coverage` refuses a download made before the date ended), but the chart may not be the one the run would draw, and nothing says so. #499 added `yield_fetch_pinned` on the `year_average_yield` variant of `below_risk_free` only; the risk-free, beta, ERP and share series read the same downloads and say nothing.

## Plan

**Step 0. This doc.**

**Step 1. A series note naming each download that was not the run's own, with tests.**
- `Singles.unpinned()` returns, once per answer, one entry per download the run names that could not be pinned: `{"role": "price" | "index" | "yield", "source", "symbol", "reason": "not_stored" | "not_recorded", "read_fetched_at"}`. `not_recorded`: the run has no hash for it (an older run); `not_stored`: the hash is recorded but no kept download has it. `read_fetched_at` is the UTC time of the download read instead (the newest, `latest_fetch`), or null when none is stored (then the points carry their own `market_data_not_loaded`).
- A new series note `download_not_pinned` (`SERIES_NOTES`), params `downloads`: the entries above for the roles the series reads, on: `risk_free_yield` (yield; also the terminal-growth card, which shows the same series), `beta` (price, index), `erp` (index, yield), and the three share series (price: the split factor). No note when every download the series reads was pinned, so today's answers are unchanged.
- `yield_fetch_pinned` on `below_risk_free` stays as it is (the cost-of-debt series reads the yield only inside that note, so the note's own flag is the place).
- Tests in `tests/analysis/test_single_values.py`, on the stored fixture run: no `download_not_pinned` anywhere when all three are stored; with the yield download deleted, the note on the risk-free and ERP series (role `yield`, `not_stored`, `read_fetched_at` equal to the newest yield download) and not on beta or shares; with the price download deleted, on beta and the share series only; with the run's index hash set to null, `not_recorded` on beta and ERP; the points still use no date after the run's date in every case.
- Exit: full suite, `ruff check`, `ruff format --check` green.

**Step 2. Real-data count.** On the newest snapshot, each company's newest stored run and a sample of older runs: how many answers carry the note, by role. Recorded below; no code.

## Alternatives considered

- **One note on the whole answer** (the issue's first option). `InputsBehind` has no answer-level notes today, and a screen shows one card at a time, so a card-level reader would have to look elsewhere; the series is where the numbers that may differ are drawn.
- **Name the `fetch_id` read.** An internal row id means nothing to a student or a screen; the download's time does ("una descarga del 20 de noviembre").
- **A bool per role, like `yield_fetch_pinned`.** Six flags on four series; a list of the downloads that were not pinned is one shape for every series and says why.
- **Refuse the history when a download is not pinned.** Loses true, point-in-time history to protect exact reproduction of a chart; a note is enough.

## Files to change

`domains/analysis/single_values.py` (`Singles.unpinned`, `_monthly`, `_erp`, `_shares`, `SERIES_NOTES`), `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/build-plan.md` (no milestone row; backlog items are recorded in versions), `docs/team-sync.md`.

## Product impact

Serves Q5 (the inputs behind an answer: the risk-free, terminal growth, beta, ERP and share cards). Additive only: one new series note code, `download_not_pinned`, with params `downloads` (list of `{role, source, symbol, reason, read_fetched_at}`); it appears only when a run's own download is gone, which on the nov.25 snapshot is never for the newest runs (Step 2 gives the count). Nothing renamed or removed; no stored number or reproduce check changes (the notes are read live). The app can word it as a short line under the chart, e.g. "Calculada con una descarga de {precios | índice | tasa} del {read_fetched_at} (la del cálculo original ya no está guardada)."

## Review notes

(to be filled)
