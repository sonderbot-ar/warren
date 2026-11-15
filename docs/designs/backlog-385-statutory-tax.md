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
  - A new module `domains/analysis/statutory_tax.py` holds the statutory rates as data: one row per jurisdiction and law, `(jurisdiction, rate, enacted_on, law, source)`. Rows: US 35% (26 U.S.C. §11(b) before 2018, the top bracket that applies to every Phase 1 company's size) and US 21% (Tax Cuts and Jobs Act, Pub. L. 115-97 §13001, enacted 2017-12-22, 26 U.S.C. §11(b) as amended). `statutory_rate(jurisdiction, as_of)` returns the newest row enacted on or before `as_of` (point-in-time: a law signed after the run's date is not known to it). It is federal only; state taxes are left out and the lesson says so.
  - In `_drivers`, before the division: when Σ pretax ≤ `PRETAX_MARGIN_FLOOR` × Σ revenue (`PRETAX_MARGIN_FLOOR = 0.01`, a 1% three-year pretax margin; a working rule), the rate is `statutory_rate("US", as_of)` instead of the ratio, and the clip is not applied. The test is a multiplication, so a zero Σ pretax never reaches a division. Every run under SUPPORTED_FROM (2019-03-01) gets 21%; the 35% row exists so the rule is right for any date and is unit-tested directly.
  - The run gets note `tax_rate_statutory` (group `assumption`), params: `tax_sum`, `pretax_sum`, `revenue_sum` and `currency` (the pretax line's unit), `pretax_margin` (null when Σ revenue is 0), `effective_rate` (null when Σ pretax is 0), `floor` (0.01), `rate`, `jurisdiction`, `law`, `enacted_on` (ISO). English: "Pretax income over FY2017-FY2019 is 0.4% of revenue, at or below 1%, so the effective tax rate means little; the US federal statutory rate of 21% is used instead".
  - The `tax_rate` and `debt_tax_rate` rows' method says "US federal statutory rate (…)" and their sources are the new rule `statutory_tax_rate` plus the derived Σ tax, Σ pretax and Σ revenue rows that triggered it.
  - A lesson in `text.WARNING_LESSONS["tax_rate_statutory"]` with params `floor`; reference Damodaran ch. 10 and 26 U.S.C. §11(b); `warren_rule`: the 1% floor is a working rule, `math_engine.PRETAX_MARGIN_FLOOR`.
  - `coded.RUN_NOTE_CODES` gains the code. `zero_divisor` stays in the refusal catalogue (revenue divisors still raise it); `tax_rate`/`pretax` stays in its closed sets, since stored code and the app's catalogue name it, but this path no longer raises it.
  - `READING_RULES_VERSION` 2 → 3 (a run can read a different tax rate), with its row in `reading_rules.md`.
  - Tests: on Test Corp, a zero Σ pretax (was refused) now builds with 21% and the note's exact params; a small positive Σ pretax under 1% of revenue and a negative Σ pretax take 21% with no `tax_rate_clipped`; a Σ pretax just above the floor keeps the ratio; `statutory_rate` returns 35% before 2017-12-22, 21% on and after, and refuses an unknown jurisdiction; the #383 test for a zero pretax sum becomes the fallback test (the refusal no longer happens, and that is the point of the issue, not a weakened test); the warning-lesson catalogue covers the new code.
  - Exit: tests pass; full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot: the three-year pretax margin of every company at every stored run's date, to show none is at or below the floor; `reproduce --all --rebuild` gives the same counts as on `main` (the fallback fires nowhere, so nothing moves).

## Alternatives considered

- **Keep refusing at zero, fall back only below zero.** Leaves the +$1 case on the clip, the inconsistency the issue is about.
- **Replace every clipped rate with the statutory rate** (outside 0%–50%, not just near-zero pretax). Bigger change: it would move runs that clip today for one-off items (a tax reform charge), where a normalised effective rate may be better. Not asked here; the clip stays for a meaningful but extreme ratio.
- **A threshold in dollars, or on |Σ tax| / Σ pretax.** Dollars don't scale across companies; a test on the ratio itself is circular. A pretax margin is scale-free and reads the way an analyst would ("the company barely made money").
- **A marginal rate including state taxes** (about 25% for the US, Damodaran's country table). Better as a number, but its source changes every January and isn't a law with a date; the federal statutory rate is exact, dated and point-in-time. The lesson names the gap; a combined rate can be a later item.
- **Use the statutory rate always.** Throws away company information (foreign profits, credits) the effective rate carries when it is meaningful.

## Files to change

`domains/analysis/statutory_tax.py` (new), `domains/analysis/math_engine.py`, `domains/analysis/sources.py` (the rule), `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `reading_rules.md`, tests under `tests/analysis/`, and `docs/versions.md`, `docs/team-sync.md` on merge.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 and value per share): a company with near-zero or negative profits over three years now gets a run with a tax rate a student can defend, instead of a refusal (Σ pretax exactly 0) or a rate stuck at 0% or 50%. Added: run-note code `tax_rate_statutory` (group `assumption`) with the params above, its lesson (`floor`), and source rule `statutory_tax_rate`. Changed: a Σ pretax of exactly zero no longer refuses with `zero_divisor` (ratio `tax_rate`); the code and its value sets stay in the catalogue. Nothing renamed or removed. No stored or fresh run of today's companies changes.
