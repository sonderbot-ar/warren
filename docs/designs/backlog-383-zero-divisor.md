# Backlog #383: a zero revenue or pretax sum is refused with a code, not a crash

Issue: https://github.com/sonderbot-ar/warren/issues/383 (from the #376 review) · Branch `backlog-383-zero-divisor` · Version v0.9.70 when merged.

## Problem

`math_engine._drivers` turns the history into the forecast's ratios, and five of them divide by a figure the filings give:

| Ratio | Divisor | Period |
|---|---|---|
| `operating_margin` (quarters) | one quarter's revenue | each of the last 12 quarters, e.g. `FY2018Q3` |
| `operating_margin` (years 3–5) | Σ revenue | the three fiscal years, e.g. `FY2017-FY2019` |
| `tax_rate` | Σ pretax income | the three fiscal years |
| `da_pct`, `capex_pct` | Σ revenue | the three fiscal years |
| `nwc_pct` | one fiscal year's revenue | each of the three years, e.g. `FY2018` |

When a divisor is exactly 0, Python raises `ZeroDivisionError`. That is not an `EngineError`, so it has no code (#376): the CLI prints a stack trace, and the app could only show its generic sentence. A zero sum of pretax income is not absurd (a profit year and a loss year of the same size cancel); a zero quarterly revenue would be a filing error or a shell company. No Phase 1 company reaches either case today (#376 analyst review), so this is a guard: no stored number changes.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. One guarded division, one new code.**
  A helper `_ratio(result, numerator, divisor, ratio, divisor_item, period)` in `math_engine.py` returns `numerator / divisor`, or raises `EngineError` with code `zero_divisor` when the divisor is 0, with params `ticker`, `ratio` (the forecast input: `operating_margin`, `tax_rate`, `da_pct`, `capex_pct`, `nwc_pct`), `divisor` (`revenue` or `pretax`) and `period` (a quarter label `FY2018Q3`, a year `FY2018`, or the span `FY2017-FY2019`). Text: "TST: revenue is zero in FY2018Q3, so operating_margin can't be computed". All six divisions in the table go through it; nothing else changes, and a non-zero divisor gives the same float as today (the same single `/`).
  `zero_divisor` joins `coded.REFUSAL_GROUPS` in group `company_data` (the filings give a figure Warren can't use: try another date or company). The #376 scan tests then require it to be raised somewhere and catalogued, which it is.
  Tests (`tests/analysis/test_refusal_codes.py`, on Test Corp): a zero quarterly revenue in FY2018 Q3 (the 10-Q row and its comparative a year later), and a zero pretax income in every 10-K year row, each refused as `zero_divisor` with the exact params and text; and a unit test of `_ratio` for the years-sum and per-year cases (revenue) and that a non-zero divisor returns `numerator / divisor` unchanged.
  Exit: tests pass; full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot, `python -m domains.analysis reproduce --all`: every stored run reproduces to the cent (a guard changes no number). Results below.

## Alternatives considered

- **Treat a zero pretax sum as a zero tax rate, or clip it.** It invents a number the filings don't support; the tax bounds clip a rate that exists, not one that doesn't. Refusing says what happened.
- **Guard near-zero divisors too** (say |revenue| below 1% of the average). A tiny divisor gives a huge but finite ratio, which the existing clips (tax) and warnings catch or don't; choosing a threshold is a modelling decision, not a crash fix. Left out.
- **One code per ratio.** Five codes for one cause; the app's sentence needs only the divisor and the period, which the params carry.

## Not taken here

- Revenue growth divides by the prior year's revenue in the fundamentals comparatives (`c.growth`), outside `_drivers`; the same zero would crash there. Filed as a follow-up if the review finds it reachable.
- `_shares` is covered by #364.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `tests/analysis/test_refusal_codes.py`, `docs/versions.md` and `docs/team-sync.md` on merge.

## Product impact

Serves the refusal sentences of brief Q1–Q3 (`docs/product/brief.md`): a run refused for a zero divisor now has a code the app can word ("los reportes dan ingresos de cero en ese trimestre; prueba otra fecha u otra empresa") instead of the generic sentence. Added: refusal code `zero_divisor` in group `company_data`, params `ticker`, `ratio`, `divisor`, `period`. Nothing renamed or removed; no run that works today changes.
