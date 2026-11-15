# Backlog #385: the statutory tax rate when three years of pretax income are at or near zero

Issue: https://github.com/sonderbot-ar/warren/issues/385 (from the #383 review) · Branch `backlog-385-statutory-tax`.

## Problem

`math_engine._drivers` sets the forecast's `tax_rate` (and the WACC's `debt_tax_rate`) to Σ income tax / Σ pretax income over the run's three fiscal years, clipped to `TAX_RATE_BOUNDS` (0% to 50%) with the note `tax_rate_clipped`. Since v0.9.70 (#383) a Σ pretax of exactly $0 is refused with `zero_divisor`. Three neighbouring cases are handled badly:

| Σ pretax | Today | Why it is wrong |
|---|---|---|
| exactly 0 | refused (`zero_divisor`) | a run that could be built isn't |
| +$1 (any tiny positive sum) | Σ tax / $1, clipped to 0% or 50% | the rate is noise; the clip picks a limit at random by the sign of the tax line |
| negative (losses outweigh profits) | a negative rate clipped to 0%, or a tax *benefit* on a loss read as a normal positive rate | the sign of the ratio says nothing about the rate future profits will pay |

A practitioner uses the marginal or statutory rate when the effective rate is not meaningful, above all when the company is losing money (Damodaran, *Investment Valuation*, 3rd ed., ch. 10, "the tax effect": the effective rate can be used for the near years, but the marginal rate is the one future operating income will pay; a firm with losses pays no tax now and the marginal rate later). No Phase 1 company reaches these cases on any stored run (checked in Step 2), so this is a rule for the edge, not a change to today's numbers.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. The fallback.**
  - A new module `domains/analysis/statutory_tax.py` holds the statutory rates as data: one row per jurisdiction and law, `(jurisdiction, rate, enacted_on, applies_from, law, source)`. Rows: US 35% (Pub. L. 103-66 §13221, enacted 1993-08-10, applies from 1993; 26 U.S.C. §11(b) before 2018 taxed taxable income above $18,333,333 at a flat 35%, which covers every Phase 1 company) and US 21% (Pub. L. 115-97 §13001, popularly the Tax Cuts and Jobs Act, enacted 2017-12-22, applies to tax years beginning after 2017-12-31). `statutory_rate(jurisdiction, as_of)` returns the newest row *enacted* on or before `as_of`, whatever the run's fiscal years: a law signed after the run's date is not known to it, and a law signed but not yet applying is the rate future profits will pay (deferred taxes are remeasured on the enactment date, ASC 740-10-35-4). An unknown jurisdiction, or a date before every row, raises `StatutoryRateError` (no Phase 1 run reaches it: every company is US and every date is after 2019-03-01). Federal only; state taxes are left out and the lesson says so.
  - In `_drivers`, before the division: when Σ pretax ≤ `PRETAX_MARGIN_FLOOR` × Σ revenue (`PRETAX_MARGIN_FLOOR = 0.01`, a 1% three-year pretax margin; a working rule), the rate is `statutory_rate("US", as_of)` instead of the ratio, and the clip is not applied. The test is a multiplication, so a zero Σ pretax never reaches a division. Every run under SUPPORTED_FROM (2019-03-01) gets 21%; the 35% row exists so the rule is right for any date and is unit-tested directly.
  - The run gets note `tax_rate_statutory` (group `assumption`), params: `tax_sum`, `pretax_sum` and `revenue_sum` (the sums of the run's `history:tax`, `history:pretax` and `history:revenue` rows for the three fiscal years, unscaled, in the filings' unit), `currency` (the unit of the last year's pretax filing), `pretax_margin` (Σ pretax / Σ revenue; null when Σ revenue is 0), `effective_rate` (Σ tax / Σ pretax, also when negative; null when Σ pretax is 0), `floor` (0.01), `period` (the span, e.g. `FY2017-FY2019`), `rate`, `jurisdiction` (closed set `coded.TAX_JURISDICTIONS`), `law`, `enacted_on` and `applies_from` (ISO), `source` (the statute) and `assumptions` (`["tax_rate", "debt_tax_rate"]`, the rows the note belongs to). English, from the params: "Pretax income over {period} is {margin} of revenue (or "with no revenue"), at or below 1%, so the effective tax rate means little; the US federal statutory rate of 21% is used instead". The sign of `pretax_sum` tells a loss from a thin profit.
  - The `tax_rate` and `debt_tax_rate` rows' method says "US federal statutory rate (…)" and their sources are the new rule `statutory_tax_rate` plus the derived Σ tax, Σ pretax and Σ revenue rows that triggered it.
  - A lesson in `text.WARNING_LESSONS["tax_rate_statutory"]` with param `floor`; two sentences that also name its three simplifications (federal only, state taxes add a few points; profits abroad pay other rates; past losses can be deducted from later profits, 26 U.S.C. §172, which Warren does not model); reference Damodaran ch. 10, 26 U.S.C. §11(b) and §172, Koller, Goedhart and Wessels; `warren_rule`: the 1% floor is a working rule, `math_engine.PRETAX_MARGIN_FLOOR`.
  - `coded.RUN_NOTE_CODES` gains the code. `zero_divisor` stays in the refusal catalogue (revenue divisors still raise it); `tax_rate`/`pretax` stays in its closed sets, since stored code and the app's catalogue name it, but this path no longer raises it.
  - `READING_RULES_VERSION` 2 → 3 (a run can read a different tax rate), with its row in `reading_rules.md`.
  - Tests (`tests/analysis/test_statutory_tax.py`; the fixture's pretax margin is scaled to the case): a zero Σ pretax (was refused) now builds with 21% and the note's exact params; a small positive Σ pretax under 1% of revenue and a negative Σ pretax take 21% with no `tax_rate_clipped`; a margin of 1.01% keeps the ratio and 0.99% takes 21%; zero revenue with a loss gives a null `pretax_margin`; `statutory_rate` returns 35% before 2017-12-22, 21% on and after, and refuses an unknown jurisdiction; `test_a_zero_pretax_sum_is_refused_with_a_code` in `tests/analysis/test_refusal_codes.py` becomes `test_a_zero_pretax_sum_is_no_longer_refused` (the refusal no longer happens, and that is the point of the issue, not a weakened test); the warning-lesson catalogue covers the new code.
  - Exit: a run whose three-year pretax margin is at or below 1% builds on 21% with the note and no clip, one above keeps its effective rate, and nothing else changes; full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot: the three-year pretax margin of every company at every stored run's date, to show none is at or below the floor; `reproduce --all --rebuild` gives the same reproduced and rebuilt-identical counts as on `main` (the fallback fires nowhere, so nothing moves). Exit: no stored run at or below the floor and the same counts; if a stored run were at or below it, its new rate and value would be listed here before merging.

## Alternatives considered

- **Keep refusing at zero, fall back only below zero.** Leaves the +$1 case on the clip, the inconsistency the issue is about.
- **Replace every clipped rate with the statutory rate** (outside 0%–50%, not just near-zero pretax). Bigger change: it would move runs that clip today for one-off items (a tax reform charge), where a normalised effective rate may be better. Not asked here; the clip stays for a meaningful but extreme ratio.
- **A threshold in dollars, or on |Σ tax| / Σ pretax.** Dollars don't scale across companies; a test on the ratio itself is circular. A pretax margin is scale-free and reads the way an analyst would ("the company barely made money").
- **A marginal rate including state taxes** (about 25% for the US, Damodaran's country table). Better as a number, but its source changes every January and isn't a law with a date; the federal statutory rate is exact, dated and point-in-time. The lesson names the gap; a combined rate can be a later item.
- **Use the statutory rate always.** Throws away company information (foreign profits, credits) the effective rate carries when it is meaningful.

## Not taken here

- **A loss year inside a window above the floor** (analyst). XOM's FY2018–FY2020 runs have a 3.0% three-year margin and keep a 41.5% effective rate, built on a 2020 loss with a small tax benefit: the same kind of distortion, but above any floor this item would set. Filed as #393 (for example the median of the yearly rates, or a loss year excluded).
- **Net operating losses** (analyst, professor). A loss-maker pays about 0% until its carryforwards are used, then the marginal rate (Damodaran ch. 10). A flat 21% from year one overstates tax; the lesson names the gap, and no Phase 1 run reaches it.
- **The `tax_rate_clipped` lesson** (professor) says an analyst would use a normal or marginal rate while Warren clips. It stays: for a meaningful but extreme rate Warren keeps the clip on purpose (Alternatives), and the new lesson says when the statutory rate is used.

## Design review (nov.15.2026)

- **Explainer.** Fourteen gaps; taken in the plan above: the 35% row's dates, enacted against applies-from, the error for an unknown jurisdiction or early date, zero revenue, the run date (not the fiscal years) choosing the law, the rows the sums come from, `effective_rate` for a loss, the note text as a template, the source rows, the fixtures and the renamed #383 test, a behavioural exit for Steps 1 and 2. The lesson text and the reading-rules row are in the code.
- **Analyst, GO, no blockers.** XOM checked on SEC companyfacts (3.0% and 3.1% margins in its 2020 windows, the closest to the floor); `debt_tax_rate` following the fallback is right (Damodaran uses the marginal rate for the debt shield); enactment keying is right. Notes taken: report the closest margins (Step 2), the lesson names foreign rates and losses, a zero-revenue test; loss-year distortion above the floor filed (Not taken here).
- **Professor, GO, no blockers.** The fallback is the textbook practice (Damodaran ch. 10; Koller, Goedhart and Wessels; Penman for the debt shield); the citations are right as far as could be checked offline. Notes taken: enacted and applies-from both shown; Pub. L. 115-97 as the citation with the popular name beside it; the NOL and state-tax gaps in the lesson. The size of the state gap ("about 4 points") is left as "a few percentage points": a number in the lesson must be an engine constant with its own rule (`tests/analysis/test_warning_lessons.py`), and a combined rate is the later item in Alternatives.
- **Product lead, BLOCKING, accepted.** The note had no period param, and the app writes its Spanish from params only (brief line 121): added `period`. Notes taken: `assumptions`, `source`, `applies_from`, a closed `jurisdiction` set, unscaled sums. Suggested Spanish, kept for the app: "De {primer_año} a {último_año}, la utilidad antes de impuestos de {empresa} fue apenas el {pretax_margin} de sus ingresos (el límite es {floor}). Con una utilidad tan chica, la tasa efectiva casi no dice nada. Por eso Warren usa la tasa federal de impuestos de EE. UU., {rate} ({law}, vigente desde el {applies_from})." For a loss: "De {primer_año} a {último_año}, las pérdidas de {empresa} superaron sus ganancias, así que la tasa efectiva no sirve para proyectar. Por eso Warren usa…"

## Files to change

`domains/analysis/statutory_tax.py` (new), `domains/analysis/math_engine.py`, `domains/analysis/sources.py` (the rule), `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `reading_rules.md`, tests under `tests/analysis/`, and `docs/versions.md`, `docs/team-sync.md` on merge.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 and value per share): a company with near-zero or negative profits over three years now gets a run with a tax rate a student can defend, instead of a refusal (Σ pretax exactly 0) or a rate stuck at 0% or 50%. Added: run-note code `tax_rate_statutory` (group `assumption`) with the params above, its lesson (`floor`), source rule `statutory_tax_rate`, and the closed set `coded.TAX_JURISDICTIONS`. The front end marks the brief's `years_sum` pretax refusal sentence as no longer reached and adds the note and lesson to the Spanish catalogue (#344). Changed: a Σ pretax of exactly zero no longer refuses with `zero_divisor` (ratio `tax_rate`); the code and its value sets stay in the catalogue. Nothing renamed or removed. No stored or fresh run of today's companies changes.

## Results (Step 2, nov.15.2026)

On the restored snapshot (`warren-20261110T202538Z`):

- **No stored run is at or below the floor.** The three-year pretax margin (Σ `history:pretax` / Σ `history:revenue` over each run's fiscal years) of all 903 stored baseline runs: lowest per company AAPL 25.7%, CAT 8.7%, JNJ 20.1%, KO 21.3%, MSFT 30.9%, PG 16.4%, WMT 3.0%, XOM 3.0%. The closest are XOM's runs from 2021-03-01 (FY2018–FY2020, 3.00%, effective rate 41.5%: #393) and WMT's from 2020-04-01 (3.03%, 29.5%).
- **Nothing moves.** `python -m domains.analysis reproduce --all --rebuild` gives 903 of 903 reproduced to the cent and 821 of 903 rebuilt to identical rows, on this branch and on `main` (8d8ccf5) alike, and the two outputs are identical line for line apart from the commit id printed per run. The 82 rebuild differences are older runs whose reading rules weren't recorded, as in #383's results. About 2 minutes each.
