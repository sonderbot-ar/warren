# Backlog #550: one cost-of-debt year's notes without building the whole answer

Issue: https://github.com/sonderbot-ar/warren/issues/550 (from the #547 review, front-end ask) · Branch `backlog-550-cost-of-debt-notes` · Version v0.10.38 when merged.

Status: In progress (nov.23.2026).

## Problem

The app sometimes needs only the notes on one cost-of-debt figure: a run's own cost of debt on the answer screen, or one bar of its chart (`below_risk_free`, `interest_net_of_hedge_gains`, `run_read_differently`, `floored_at_risk_free`). Today it must call `inputs_behind`, which builds every cell the answer reaches: the fiscal calendar, every driver chart, the market series (beta's 104-week regressions, the ERP), the balances, and every year of the cost-of-debt chart. That is seconds of work for one sentence.

## Plan

**Step 0. This doc.**

**Step 1. One function builds a year's point; the chart and a new call both use it.**

- `single_values._cost_of_debt_point(singles, year, used)`: the body of the chart's per-year loop, moved as is (the year's `cost_of_debt_year`, its parts with filings, `below_risk_free`, the caveat's note in its place, or the `not_computable` reason). `_cost_of_debt` now loops over it, so the chart's output does not change.
- `_cost_of_debt_used_year(singles)`: the run's own year (from its stored interest source), None on a what-if child whose cost of debt is not a book year.
- `_cost_of_debt_cell_notes(singles, used_hedge_note)`: the cell's notes (`floored_at_risk_free`, else the used year's caveat note), now one function used by `single_cell` and the new call.
- `_read_differently(point, run_value)`: the `run_read_differently` check `_checked` applies to the used point, now one function used by both.
- New public call `single_values.cost_of_debt_notes(conn, run_id, fiscal_year=None) -> CostOfDebtNotes(run_id, fiscal_year, point, cell_notes)`:
  - `point` is the year's `inputs.Point`, equal to the chart's point for that year (value, used, parts, notes, missing). `fiscal_year=None` means the run's own year; on a floored what-if child, which has none, `fiscal_year` and `point` are None.
  - `cell_notes` equals the `cost_of_debt` cell's `notes` from `inputs_behind`.
  - It reads the run, its stored sources, the company's history as known on the run's date, the filing index and, for a year other than the run's own, the 10-year yields over that fiscal year (as the chart's `below_risk_free` does, pinned to the run's downloads); no fiscal calendar, no beta or ERP series, no other cell. It computes the used year as well as the one asked, since the cell's notes come from it. The caveat file (`interest_caveats.csv`) is read as today's file, as the chart reads it.
  - `CostOfDebtNotes.to_dict()` gives plain JSON as `InputsBehind.to_dict()` does, so the app parses both the same way (product lead).
  - Valid years are the chart's and the run's own. Any other year is answered by the same rule, so a year after the newest filing known on the run's date reads `not_computable`, `no_interest_reported` ("not known yet", not "reported none"); the docstring says so, and the app asks only for chart years (product lead). Nothing after `as_of` is read, since the history is the run's.
  - A floored what-if child has no own year: with no year asked, `fiscal_year` and `point` are None and the cell notes hold `floored_at_risk_free`; with a year asked, that year's point (not used), as on its chart.
  - Refusals, the same codes as `inputs_behind`: `run_not_found`, `concepts_not_synced`.
- Tests (`tests/analysis/test_single_values.py`):
  - For every year of the chart, the call's point equals the chart's point and its cell notes equal the cell's notes, on: the plain test company; a book cost below the yield (`below_risk_free`); a hedge caveat, above and below the yield (the note on three years and on the cell); a run whose stored cost of debt differs from today's read (`run_read_differently`); a floored what-if child (no own year, `floored_at_risk_free`).
  - No year asked gives the run's own year.
  - A year with no interest gives its `not_computable` reason.
  - A what-if child that raises only the risk-free rate: equal to its chart, and its own year compared with the child's own 5% row (analyst).
  - `to_dict()` is strict JSON.
  - With the fiscal calendar reader and every other single-value builder (`_balances`, `_balance_series`, `_debt_fair_value`, `_derived_cell`, `_risk_free`, `_beta`, `_erp`, `_shares`, the chart's `_cost_of_debt`) made to fail, the call still answers.
  - An unknown run and a stale concepts table are refused with their codes.
- Exit: the new tests fail on `main` (no such call) and pass here; the existing chart tests pass unchanged; full suite, `ruff check` and `ruff format --check` green.

**Step 2. Real data.** On the restored snapshot (`python -m shared_kernel.snapshot restore`), read-only: for the newest baseline run of each of the eight companies and the first J&J run of 2020, the call's point and cell notes equal `inputs_behind`'s for every chart year, and the call's time against `inputs_behind`'s for an answer on value per share. Nothing is written, and no stored number can move, so no reproduce check is needed.

Result (snapshot `warren-20261123T052122Z`, nov.23.2026): equal on all nine runs, every year (5 each). Time: 0.10–0.25 s for the call against 1.4–3.3 s for the whole answer, about 15 times faster. Notes seen: `below_risk_free` (all but J&J), `run_read_differently` (MSFT, WMT, XOM, J&J: runs stored before this week's interest fixes), `interest_net_of_hedge_gains` on J&J's points and cell in 2020 and 2026. Apple's newest run's own year is FY2023, as on its chart (its interest line is not tagged after FY2023); not changed here.

## Design review (nov.23.2026)

- **Explainer:** restated it correctly; its gaps are fixed above: the yields read for other years, the floored child with a year asked, the full list of builders made to fail, Step 2's runs and the snapshot. The type of `point` is `object` in code to avoid an import cycle (`inputs` imports `single_values`); it is an `inputs.Point`. `_read_differently` compares with the `assumptions` row, which is the row `_checked`'s `cell_rows[0]` holds (analyst confirmed, `inputs.py:989`).
- **Analyst: GO.** No way for the two paths to differ (one point builder; `reader` and `years` only set the chart's window; the cache value is recomputed from the same used point); every read bounded by `as_of`. Suggestions taken: a risk-free what-if test, and the docstring on runs with no `cost_of_debt` row or an owner-choice one (neither exists today). Step 2's result is in the PR.
- **Product lead: GO.** The whole point serves the *Fuente* panel better than a bare list; every code already exists. Asked for `to_dict()` (done) and for the out-of-window year to be refused or documented (documented; the app asks only for chart years).
- **Professor:** not run; no method changes.

## Alternatives considered

- **A flag on `inputs_behind` to build only one cell.** It would still build the fiscal calendar for the chart's window and the whole series; and the app asks for one figure, not one chart. Rejected.
- **Cache the whole answer per run.** Speeds a second call, not the first; and the app's question is one sentence. Left for #492 (the track record's first build).
- **Return only the notes (a list), as the issue words it.** The point also carries the value, the parts and the missing reason, which the app shows beside the note, and comparing whole points makes the no-drift test stronger. The notes are `point.notes`.

## Files to change

- `domains/analysis/single_values.py`
- `tests/analysis/test_single_values.py`
- `docs/designs/backlog-550-cost-of-debt-notes.md`; on merge `docs/versions.md`, `docs/team-sync.md`

## Product impact

- Serves brief Q3 (where a number comes from) on the cost of debt: the answer screen can show a run's own cost-of-debt notes without the chart being built.
- Adds one call, `cost_of_debt_notes`; nothing in `inputs_behind` is renamed, removed or changed. No new code for the Spanish catalogue: every note and refusal code is an existing one.
