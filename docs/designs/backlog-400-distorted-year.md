# Backlog #400: a profitable year with a distorted tax rate inside the three-year window

Issue: https://github.com/sonderbot-ar/warren/issues/400 (from the #393 review) · Branch `backlog-400-distorted-year` · Version v0.9.76 (planned).

## Problem

Since v0.9.75 (#393) the forecast's `tax_rate` (and the WACC's `debt_tax_rate`) is Σ income tax / Σ pretax income over the run's three fiscal years, leaving out loss years (pretax ≤ 0), clipped to `TAX_RATE_BOUNDS` (0% to 50%); a window at or below `PRETAX_MARGIN_FLOOR` takes the statutory rate (#385).

A *profitable* year whose own rate (its tax / its pretax) is far outside 0% to 50% still stays in, silently. The 2017 US tax reform (Pub. L. 115-97) is the live case: companies booked a one-off charge on untaxed foreign earnings (the transition tax) and a remeasurement of deferred taxes, which either added a huge charge or a huge benefit to that one year. From the stored runs' `history:tax` / `history:pretax` rows (the #393 analyst checked them against SEC company facts):

- JNJ FY2017 92.6%, KO FY2017 82%, CAT FY2017 82% and FY2016 138%, MSFT FY2018 54.6%: their windows holding those years come to roughly 32% to 43% after summing, so they pass under the 50% clip although the companies' profits pay 15% to 25% (the analyst's figures, Design review: CAT 43.4% and 34.4%, JNJ 40.3% and 40.2%, KO 37.8% and 35.4%, MSFT 32.0%, 26.1% and 24.9%).
- Exxon FY2016 (tax −$406M on $7,969M pretax) and FY2017 (−$1,174M on $18,674M, the reform's benefit): its stored rate is 13.8% for runs reading FY2016–FY2018 and 19.6% for FY2017–FY2019, then steps to 29.0% when the window moves on.

The sum over three years dilutes a one-off year, but does not remove it: one 92.6% year among two 20% years still gives about 40%. Koller, Goedhart and Wessels (*Valuation*, on operating taxes) take the tax on one-off items out of the operating rate; Damodaran (*Investment Valuation*, ch. 10) uses a normal effective rate near term and the marginal rate later. Company facts do not tag the transition tax or the remeasurement reliably (some filers use `IncomeTaxReconciliationTaxCutsAndJobsAct...` tags, many don't), so, as #393 did with loss years, Warren leaves the whole year out instead of the item: a coarser version of the same idea, and Warren's own working rule.

## Decision among the issue's options

The issue asks for one of (a) a note only, (b) the same exclusion as #393, (c) a lesson only. **(b), with a note.** A note alone leaves a 40% rate in the forecast that the run itself says is wrong; a lesson alone says nothing on the run that has the problem. (b) is the practitioner's normalisation done the only way company facts allow, and it uses the bound the run already applies to the window (`TAX_RATE_BOUNDS`), so no new constant.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. Leave out a profitable year whose own rate is outside the bounds.**
  - New pure helper `math_engine.tax_years(pretax_tax: dict[int, tuple[float, float]]) -> TaxYears` (`loss`, `outside`, `kept`, `outside_left_out`), so the rule is tested on its own. After the #385 floor test (unchanged, first) and the #393 loss test (unchanged): a profitable year (pretax > 0) whose tax / pretax is below `TAX_RATE_BOUNDS[0]` or above `TAX_RATE_BOUNDS[1]` is *outside*. Exactly 0% or 50% is inside. The outside years are left out and the rate is Σ tax / Σ pretax over the rest, clipped as usual.
  - **When every profitable year is outside**, none is left out (there would be nothing to read): the rate is the profitable years' Σ tax / Σ pretax as before (#393), clipped as usual, and the note says `outside_left_out: false`. No Phase 1 window falls there (Step 2 checks).
  - The kept years always exist and have pretax > 0: either some profitable year is inside (kept), or all profitable years are kept; the #393 proof gives at least one profitable year. Their ratio still goes through `_ratio`. A Hypothesis property pins both.
  - The run gets note `tax_rate_outside_year_left_out` (group `assumption`). Params: `period` (the window), `outside_years` (list of `FY2017`-style labels), `outside_rates` (list of the same years' own rates, as fractions, same order), `low` and `high` (the bounds), `outside_left_out` (bool), `kept_years`, `tax_sum`, `pretax_sum`, `effective_rate` (the window's Σ tax / Σ pretax, unclipped), `kept_tax_sum`, `kept_pretax_sum`, `rate` (the kept years', before the clip), `rate_used`, `clipped`, `currency`, `assumptions` (`["tax_rate", "debt_tax_rate"]`): the same shape as `tax_rate_loss_year_left_out`, so the app reuses its layout. English (an illustration; the real figures are in Step 2): "FY2017's own tax rate was 92.6%, outside 0% to 50%, so the tax rate is read from FY2015, FY2016 only: 21.4% instead of 40.3% over FY2015-FY2017"; two years: "FY2016, FY2017's own tax rates were 138.0%, 82.0%, …"; none left out: "FY2015, FY2016, FY2017's own tax rates were …, all outside 0% to 50%, so none is left out: the tax rate is read from all of them, …".
  - With a loss year as well, both notes appear, loss note first (its English adds "(FY2017 is also left out, see the next note)", product lead), then this one, then `tax_rate_clipped`; both carry the same final `kept_years`, kept sums and rates. The rows' method lists each reason: "Σ income tax / Σ pretax income, FY2016 (FY2018, a loss year, left out; FY2017, own rate outside 0% to 50%, left out)". Sources unchanged (all three years' derived Σ tax and Σ pretax rows).
  - Lesson `text.WARNING_LESSONS["tax_rate_outside_year_left_out"]`, params `low` and `high`: a year whose own rate is that far out was hit by a one-off (the 2017 US tax reform's charge on foreign earnings or its remeasurement of deferred taxes, a settlement, a write-off that isn't deductible), not by the rate profits pay; Warren leaves the year out rather than the item because filings don't tag the item reliably; when only one year is left, the rate rests on that year alone, a thinner base. References Koller, Goedhart and Wessels and Damodaran ch. 10; `warren_rule`: "a profitable year whose own tax rate is outside 0% to 50% is left out of the three-year tax rate, unless every profitable year is".
  - The #393 lesson gains the same one-year sentence (the issue's smaller note): "When only one profitable year is left, the rate rests on that year alone, a thinner base."
  - `coded.RUN_NOTE_CODES` gains the code. `READING_RULES_VERSION` 4 → 5, with its row.
  - Tests (`tests/analysis/test_outside_year_tax.py`, on the shared fixture with years' pretax and tax set): a year above 50% is left out (exact params, text, both rows' value and method, sources unchanged); a profitable year with negative tax is left out; exactly 0% and exactly 50% stay in with no note; two outside years read the third; all three outside: none left out, the clip and both notes in order; a loss year and an outside year: both notes, loss first, the one kept year; the floor still wins (statutory, neither note); `tax_years` property (kept non-empty, kept pretax > 0, kept ∪ loss ∪ left-out = window); lesson catalogued. The #393 tests stay as they are.
  - Exit: a run with an outside year in its window reads the other years' rate with the note; every other run reads what it read before; full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot: list every stored run whose window has an outside year, with old and new `tax_rate` and value per share rebuilt both ways; `reproduce --all` must reproduce all stored runs to the cent, and `reproduce --all --rebuild` must differ from `main` only on the runs listed. Exit: exactly the analyst's 148 runs in 11 window groups move (Design review), none in the "all outside" case, no other run moving.

## Alternatives considered

- **(a) A note only.** Honest but leaves a rate the run calls distorted in the forecast and the WACC.
- **(c) A lesson only.** Says nothing on the run that has the problem.
- **Remove the one-off item and keep the year** (Koller). Better, but the reform's tags are filed by some companies and not others, and settlements and non-deductible write-offs have no common tag.
- **Tighter per-year bounds (say 5% to 40%).** Would also catch smaller one-offs, but a new constant with no source, and normal foreign-heavy rates (Exxon's 30%+ upstream years) come close to 40%. The run already uses 0% to 50% as "a rate no profit pays"; reusing it keeps one line.
- **The statutory rate whenever any year is outside.** Throws away the two clean years, as #393's alternatives said for loss years.
- **When every profitable year is outside, use the statutory rate.** Arguable, but no Phase 1 window falls there, and a company with persistently odd rates (big credits) would get 21% that its filings contradict; the clip and the note leave the call visible instead.

## Not taken from the issue

- **Exxon's equity-company income** (its pretax includes its share of affiliates' profits, taxed inside them, so the consolidated rate understates its burden). True for every Exxon run, with or without this note, so it doesn't belong in a lesson about distorted years; it is a company fact for the reported-figures notes. Filed as a backlog follow-up.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `reading_rules.md`, `tests/analysis/test_outside_year_tax.py`, and `docs/versions.md`, `docs/team-sync.md` on merge.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 and value per share, "Supuestos fuera de lo habitual", brief line 135; the note shows in the side panel of the two rows its `assumptions` names): a company whose window holds a year with a one-off tax rate (the 2017 reform, for JNJ, KO, CAT, MSFT and Exxon) gets a rate read from its normal years, with a note naming the year, its own rate and both window rates. Added: run-note code `tax_rate_outside_year_left_out` (group `assumption`, params above, the same shape as `tax_rate_loss_year_left_out` plus `outside_years`, `outside_rates`, `low`, `high`, `outside_left_out`) and its lesson (params `low`, `high`). Changed: the English of the `tax_rate_loss_year_left_out` lesson (one sentence added). Nothing renamed or removed. Fresh runs of the listed windows read a different `tax_rate` and `debt_tax_rate` (Step 2); stored runs keep their rows, and runs stored before reading rules v5 never carry the note.

## Design review (nov.15.2026)

- **Explainer.** Eleven gaps. Taken: `tax_years` replaces the loss-only selection and `_tax_without_losses` becomes `_tax_kept_years`, which writes both notes (Step 1); with every profitable year outside and a loss year too, `outside_years` and `kept_years` are the profitable years; the "all outside" case was checked by the analyst on every stored window (none); Step 2 now has a target (below). The rest (exact English for each case, the method for the outside-only case, the reading rules row) are pinned in `tests/analysis/test_outside_year_tax.py` and `reading_rules.md`.
- **Professor, GO, no blockers.** Taken: Koller cited by edition and chapter (7th ed., 2020, ch. 20 and 21) in the lesson; the lesson says the rule is a screen, not a cure (a smaller one-off inside the range stays in); the 2017 items named in plain words (a one-time tax on profits kept abroad, a revaluation of deferred tax balances when the rate fell from 35% to 21%). Idea not taken here: the WACC's debt tax shield at the marginal rather than the effective rate (Damodaran); filed as a backlog idea.
- **Analyst, GO, no blockers.** Every profitable year outside 0%–50% in the 903 stored runs: CAT FY2016 138.1% and FY2017 81.8%, JNJ FY2017 92.6%, KO FY2017 81.4%/82.5% (two vintages), MSFT FY2018 54.6%, Exxon FY2016 −5.1% and FY2017 −6.3%; none for AAPL, PG or WMT. Checked against SEC company facts: JNJ FY2017 (accession 0000200406-18-000005), Exxon FY2016 (0000034088-17-000017) and FY2017 (0000034088-18-000015) match. Expected: 148 runs in 11 window groups move, none in the "all outside" case. Taken: the Problem's range corrected, the example labelled, Step 2's target. Ideas filed as one backlog issue: one-offs inside the range pass through (PG FY2019 34.7% after a mostly non-deductible goodwill impairment, WMT FY2019 37.4%), the sharp cut-off (MSFT FY2018 is 4.6 points over), a filer whose normal rate sits near 0% could flip in and out. Not taken: a kept-years count param (it is `len(kept_years)`).
- **Product lead, no blocking objection.** Taken: the loss note says where a missing outside year went; Product impact cites the brief line. The front-end team updates the Spanish of the loss-year lesson by hand until #344. Suggested Spanish, kept for the app: "En los años fiscales {primer_año} a {último_año}, la tasa efectiva propia (impuestos entre utilidad antes de impuestos) de {empresa} fue de {años_y_tasas}, fuera del rango de {low} a {high} que Warren acepta. Una tasa así suele venir de un cargo o un beneficio que ocurre una sola vez, no de lo que pagan sus ganancias normales. Por eso Warren calcula la tasa efectiva solo con {años_conservados}: {rate}, y esa es la tasa que usa en la proyección y en el costo de la deuda. Con los tres años juntos daría {effective_rate}." (`{años_y_tasas}`: "92,6 % en 2017", or "138,0 % en 2016 y 82,0 % en 2017"; for a negative rate add "(un beneficio fiscal, aunque tuvo utilidad)".) When `outside_left_out` is false: "En los años fiscales {primer_año} a {último_año}, la tasa efectiva propia de {empresa} quedó fuera del rango de {low} a {high} en todos sus años con utilidad ({años_y_tasas}). Como no queda ningún año normal del que leerla, Warren no deja ninguno fuera y calcula la tasa con todos ellos: {rate}. Léela con reserva: puede incluir cargos o beneficios que ocurren una sola vez." When `clipped`: the loss note's clip sentence.

## Results (Step 2, nov.15.2026)

On the restored snapshot (`warren-20261110T202538Z`), all 903 stored baseline runs, rebuilt on `main` (v0.9.75) and on this branch and compared row by row:

- **Exactly the analyst's 148 runs in 11 window groups move**, and in each only `tax_rate` and `debt_tax_rate` change; every one carries the new note, and no run without the note moves. None falls in the "every profitable year outside" case.

| Company, runs dated | Window | Tax rate now → with this rule | Value per share, rebuilt |
|---|---|---|---|
| CAT 2019-04-01 to 2020-02-15 (15) | FY2016–FY2018 | 43.4% → 21.7% (FY2018 only) | +39% to +43% (e.g. $88.57 → $126.19) |
| CAT 2020-03-01 to 2021-02-01 (14) | FY2017–FY2019 | 34.4% → 22.0% | +16% to +19% |
| JNJ 2019-04-01 to 2020-02-15 (15) | FY2016–FY2018 | 40.3% → 15.8% | +40% (e.g. $106.16 → $148.46) |
| JNJ 2020-03-01 to 2021-02-01 (13) | FY2017–FY2019 | 40.2% → 13.9% | +42% to +43% |
| KO 2019-04-01 to 2020-02-15 (15) | FY2016–FY2018 | 37.8% → 19.5% | +41% to +48% |
| KO 2020-03-01 to 2021-02-01 (13) | FY2017–FY2019 | 35.4% → 18.7% | +32% to +37% |
| MSFT 2019-04-01 to 2019-07-01 (5) | FY2016–FY2018 | 32.0% → 17.1% | +19% |
| MSFT 2019-08-01 to 2020-07-01 (14) | FY2017–FY2019 | 26.1% → 12.0% | +17% |
| MSFT 2020-08-01 to 2021-07-01 (14) | FY2018–FY2020 | 24.9% → 13.7% | +14% |
| Exxon 2019-04-01 to 2020-02-15 (15) | FY2016–FY2018 | 13.8% → 30.8% (FY2018 only) | −19% to −20% (e.g. $101.80 → $81.86) |
| Exxon 2020-03-01 to 2021-02-01 (15) | FY2017–FY2019 | 19.6% → 29.0% | −12% |

  The rule works both ways: the four companies whose 2017 reform year was a big charge get a lower rate and a higher value; Exxon, whose reform year was a benefit, gets a higher rate and a lower value. Revenue and EBIT forecasts do not use the tax rate, so the forecast-error scores (M3, M8, M9) do not move. MSFT's kept-years rates (12% to 17%) are low but are its own filed rates for FY2019 and FY2020 (10.2% and 16.5%, the analyst's figures), not an artefact.
- **Stored runs** keep their stored rows: `python -m domains.analysis reproduce --all --rebuild` gives 903 of 903 reproduced to the cent on both, and 692 of 903 rebuilt to identical rows against 777 on `main`. The 85 fewer are all among the 148 above (the other 63 already differed on `main`, being older runs whose reading rules weren't recorded); no run that differed on `main` now matches.
