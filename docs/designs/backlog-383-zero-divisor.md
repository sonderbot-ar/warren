# Backlog #383: a zero revenue or pretax sum is refused with a code, not a crash

Issue: https://github.com/sonderbot-ar/warren/issues/383 (from the #376 review) · Branch `backlog-383-zero-divisor` · Version v0.9.70, merged nov.14.2026 (PR #386, merge `1ea1a91`, after CI green and a gatekeeper GO).

## Problem

`math_engine._drivers` turns the history into the forecast's ratios, and five of them divide by a figure the filings give:

| Ratio | Divisor | Period |
|---|---|---|
| `operating_margin` (quarters) | one quarter's revenue | each of the last 12 quarters, e.g. `FY2018Q3` |
| `operating_margin` (years 3–5) | Σ revenue | the three fiscal years, e.g. `FY2017-FY2019` |
| `tax_rate` | Σ pretax income | the three fiscal years |
| `da_pct`, `capex_pct` | Σ revenue | the three fiscal years |
| `nwc_pct` | one fiscal year's revenue | each of the three years, e.g. `FY2018` |
| `revenue_growth` (added at review) | the prior year's revenue in each 10-K comparative (`AnnualComparison.growth`) | e.g. `FY2017` |
| `revenue_seed` (added at review) | a seed year's revenue, and the sum of its four quarters, when the quarters are checked against the year (`_revenue_seed`) | e.g. `FY2019` |

When a divisor is exactly 0, Python raises `ZeroDivisionError`. That is not an `EngineError`, so it has no code (#376): the CLI prints a stack trace, and the app could only show its generic sentence. A zero sum of pretax income is not absurd (a profit year and a loss year of the same size cancel); a zero quarterly revenue would be a filing error or a shell company. No Phase 1 company reaches either case today (#376 analyst review), so this is a guard: no stored number changes.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. One guarded division, one new code.**
  *As built, after the design review:* a check `_nonzero(result, divisor, ratio, divisor_item, period, period_kind)` raises the refusal, and `_ratio` calls it and divides. The two sites the analyst found before `_drivers`' ratios (the seed's check against its year, and growth) call `_nonzero` before their own unchanged arithmetic. Params gain `period_kind` (`quarter`, `year`, `quarters_sum`, `years_sum`), and the value sets of `ratio`, `divisor` and `period_kind` are closed constants in `coded.py` (`ZERO_DIVISOR_RATIOS`, `ZERO_DIVISOR_ITEMS`, `ZERO_DIVISOR_PERIOD_KINDS`), asserted by `_nonzero`.
  The first draft: a helper `_ratio(result, numerator, divisor, ratio, divisor_item, period)` in `math_engine.py` returns `numerator / divisor`, or raises `EngineError` with code `zero_divisor` when the divisor is 0, with params `ticker`, `ratio` (the forecast input: `operating_margin`, `tax_rate`, `da_pct`, `capex_pct`, `nwc_pct`), `divisor` (`revenue` or `pretax`) and `period` (a quarter label `FY2018Q3`, a year `FY2018`, or the span `FY2017-FY2019`). Text: "TST: revenue is zero in FY2018Q3, so operating_margin can't be computed". All six divisions in the first draft's table went through it (the seed and growth rows, added at review, call `_nonzero` directly); nothing else changes, and a non-zero divisor gives the same float as today (the same single `/`).
  `zero_divisor` joins `coded.REFUSAL_GROUPS` in group `company_data` (the filings give a figure Warren can't use: try another date or company). The #376 scan tests then require it to be raised somewhere and catalogued, which it is.
  Tests (`tests/analysis/test_refusal_codes.py`, on Test Corp): a zero quarterly revenue in FY2018 Q3 (the 10-Q row and its comparative a year later), and a zero pretax income in every 10-K year row, each refused as `zero_divisor` with the exact params and text; and a unit test of `_ratio` for the years-sum and per-year cases (revenue) and that a non-zero divisor returns `numerator / divisor` unchanged.
  Exit: tests pass; full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot, `python -m domains.analysis reproduce --all`: every stored run reproduces to the cent (a guard changes no number). Results below.

## Alternatives considered

- **Treat a zero pretax sum as a zero tax rate, or clip it.** It invents a number the filings don't support; the tax bounds clip a rate that exists, not one that doesn't. Refusing says what happened.
- **Guard near-zero divisors too** (say |revenue| below 1% of the average). A tiny divisor gives a huge but finite ratio, which the existing clips (tax) and warnings catch or don't; choosing a threshold is a modelling decision, not a crash fix. Left out.
- **One code per ratio.** Five codes for one cause; the app's sentence needs only the divisor and the period, which the params carry.

## Not taken here

- A statutory or marginal tax rate when Σ pretax is at or near zero (analyst, note 2): a modelling change, filed as #385.
- The period-end date and the filing link for the quarter and year cases (product lead, note 4): added to #381, the app's refusal follow-ups.
- `_shares` is covered by #364.

## Design review (nov.14.2026)

- **Analyst, BLOCKING, accepted.** A zero annual revenue still crashed before the new guards: in `_revenue_seed` (`gap = … / abs(annual.value)`, then `/ total`) and in growth (`AnnualComparison.growth`, `facts.py:640`). Both now call `_nonzero` first, with a test that zeroes one 10-K year's revenue (FY2017 reaches growth, FY2019 the seed). The guard sits at the call site in `math_engine.py`, since `facts.py` has no `EngineResult`.
- **Analyst, notes.** `company_data` is right (a zero pretax sum is consistent, not broken); no number changes for a non-zero divisor (same single division, same order; a NaN still passes as before); every other division on the `build_inputs` path is already guarded (`_cost_of_debt`, `share_scale`, `_snapshot`'s margin check, `_meaning_note`). A statutory-rate fallback for Σ pretax ≤ 0 is a backlog issue.
- **Product lead, BLOCKING, accepted.** `period` mixed three kinds, and a pretax sum can be zero with no report showing a zero, so a sentence about "the quarter" would be false (brief: "a wrong cause would mislead more than none"). Added `period_kind`, and the Product impact sentence now covers each kind.
- **Product lead, notes.** Citation corrected (estimates, not reported figures); the value sets are closed constants, so the app's catalogue test can cover every value; period-end date and filing link deferred to the app follow-ups (a sum has no single filing).

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/reading_rules.md`, `tests/analysis/test_refusal_codes.py`, `docs/versions.md` and `docs/team-sync.md` on merge.

## Product impact

Serves the refusal sentences of the brief's estimate questions (`docs/product/brief.md`: Q3, Q5, Q8 and every value per share, the set the share-count refusal names), not the reported-figure questions Q1 and Q2, which don't build a run. A run refused for a zero divisor now has a code the app can word instead of the generic sentence. Added: refusal code `zero_divisor` in group `company_data`, params `ticker`, `ratio` (closed set `coded.ZERO_DIVISOR_RATIOS`), `divisor` (`revenue` or `pretax`), `period` and `period_kind`. Wording by kind, for example: `quarter` "los reportes dan ingresos de cero en el trimestre {period}"; `year` "… en el año fiscal {period}"; `quarters_sum` "los cuatro trimestres de {period} suman cero"; `years_sum` "la utilidad antes de impuestos de {period} suma cero: las ganancias y las pérdidas de esos años se cancelan". Then "prueba otra fecha u otra empresa". Nothing renamed or removed; no run that works today changes.

## Results (Step 2, nov.14.2026)

On the restored snapshot (`warren-20261110T202538Z`), with the Step 1b code: `python -m domains.analysis reproduce --all --rebuild` gives 903 of 903 stored runs reproduced to the cent, and 821 of 903 rebuilt to identical rows. The same command on `main` (b59d162) gives the same two counts and, apart from the commit id printed per run, byte-identical output: the 82 rebuild differences are older runs whose reading rules weren't recorded, and none comes from this change. No stored run reaches a zero divisor. Took about 3 minutes.
