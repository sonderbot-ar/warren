# Backlog #604: the unpinned-download tests check every market card, and read the newest download by symbol

Issue: https://github.com/sonderbot-ar/warren/issues/604 (from the #603 gatekeeper) · Branch `backlog-604-unpinned-tests` · Version v0.10.52 when merged.

Status: Done (v0.10.52, nov.26.2026; PR #607, merge `f46d114`, after CI green and a gatekeeper GO).

## Problem

Backlog #601 (v0.10.51) added the `download_not_pinned` series note. Its design doc says the no-later-date rule is checked in every case, but the test helper `_no_market_date_after_the_run` (`tests/analysis/test_single_values.py`) looked only at the primary risk-free and beta series. The ERP points (year ends) and the three share series were never checked, and nothing stopped the helper from passing on a card whose points were all refused. A second helper, `_newest_fetch_time`, picked the newest download by source only, so a second FRED series in the fixture would have broken the yield test for the wrong reason. Tests only; no engine code is wrong.

## Plan

**Step 0. This doc.**

**Step 1. Stronger helpers, with tests.**
- `_no_market_date_after_the_run` walks every series (primary and not) of the risk-free, beta, ERP and share cards. Each dated point must be on or before the run's date; a point with no date must have no value (a refused point reads nothing); each card must have at least one point with a value, so the check cannot pass on a wholly refused chart.
- `_newest_fetch_time(conn, source, symbol)` filters by symbol as well, as `selected_fetch` does; the yield test also asserts the note names `DGS10`.
- The two-downloads test now runs the no-later-date check too.
- Checked by mutation: with the bound moved 200 days before the run's date, the three tests that call the helper on a refreshed yield or price fail on the risk-free series, so the helper is not vacuous. On the price download made before the run's date, the beta card still has valued points (the months its download covers), so the gatekeeper's concern that it might be checked vacuously does not hold, and the new per-card assertion keeps it that way.
- Exit: full suite, `ruff check`, `ruff format --check` green.

## Alternatives considered

- **Check only the primary series of each card.** The share card's quarterly and yearly series are the ones a later filing date could leak into; checking every series costs nothing.
- **A `refused` argument naming cards expected to be blank.** Tried; no test needs it (every card has values in every case), so it was dropped.

## Files to change

`tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. Tests only; no output, code or stored number changes.

## Review notes

Explainer, analyst, professor: not run. Tests only, no method or output change, under the gatekeeper's own non-blocking notes.

Gatekeeper GO on PR #607: 2962 passed, 10 skipped, ruff clean; no assertion removed or weakened; four mutations (the bound moved for every card, for ERP and shares only, for shares only, and the valued floor raised) each fail the four callers, so the ERP and share checks really run.
