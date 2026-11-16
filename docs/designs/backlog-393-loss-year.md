# Backlog #393: a loss year inside the tax rate's three-year window

Issue: https://github.com/sonderbot-ar/warren/issues/393 (from the #385 review) · Branch `backlog-393-loss-year` · Version v0.9.75, merged nov.15.2026 (PR #401, merge `55fa116`, after CI green and a gatekeeper GO).

## Problem

`math_engine._drivers` sets the forecast's `tax_rate` (and the WACC's `debt_tax_rate`) to Σ income tax / Σ pretax income over the run's three fiscal years, clipped to `TAX_RATE_BOUNDS` (0% to 50%). Since v0.9.73 (#385), a window whose Σ pretax is at or below 1% of Σ revenue takes the US federal statutory rate instead.

A window above that floor can still hold a loss year. A loss year books a tax *benefit* (a negative tax on a negative pretax), and adding it to the sums mixes two different things: the rate the company pays on profits, and the refund rate on its loss (which depends on carrybacks, valuation allowances and where the loss fell). Exxon is the live case: its runs from 2021-03-01 read FY2018–FY2020, a 3.0% three-year pretax margin, and keep Σ tax / Σ pretax = 41.5%, built on a 2020 loss with a small benefit. The rate is high because the benefit on the loss was small relative to the loss, not because Exxon's profits pay 41.5%; it passes only because it sits under the 50% clip.

No textbook prescribes "drop the loss years"; it is Warren's own working rule, built from two things the books do say. Damodaran (*Investment Valuation*, ch. 10, "the tax effect") uses the effective rate for the near years and the marginal rate later, models a loss-maker with carryforwards at 0% rising to the marginal rate, and leaves firms with negative effective rates out of his industry tables. Koller, Goedhart and Wessels (*Valuation*, on operating taxes) take the tax on one-off items (impairments, restructuring) out of the operating rate. Exxon's 2020 loss came mostly from an upstream impairment; companyfacts does not tag the impairment reliably, so Warren cannot remove the item and keeps the year out instead, a coarser version of the same idea. The lesson calls the rule Warren's own.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. Leave the loss years out.**
  - In `_drivers`, after the #385 floor test (unchanged, and checked first): when one or more of the window's fiscal years has `history:pretax` ≤ 0, the rate is Σ tax / Σ pretax over the other years (the *profitable years*), clipped to `TAX_RATE_BOUNDS` as usual (with `tax_rate_clipped` when it clips). A year with pretax of exactly 0 counts as a loss year: it has no rate of its own, and its tax line is left out with it. A profitable year with a tax benefit (positive pretax, negative tax) stays in; the clip still bounds the result.
  - The profitable years always exist and are above the floor on their own: the window's Σ pretax is above 1% of Σ revenue (else the floor fires), losses only lower the sum, so Σ pretax over the profitable years ≥ Σ pretax over the window (equal when the only "loss" is a zero year) > 1% × Σ revenue ≥ 1% × their own revenue, given non-negative yearly revenue (a negative revenue year is refused earlier). The kept-years ratio still goes through `_ratio`, so a zero divisor could only ever refuse with a code. No new refusal and no division by zero; a test pins this.
  - The run gets note `tax_rate_loss_year_left_out` (group `assumption`). Params: `period` (the window, e.g. `FY2018-FY2020`), `loss_years` (list of `FY2020`-style labels), `kept_years` (the rest), `pretax_sum` and `tax_sum` (the window's, unscaled), `effective_rate` (the window's Σ tax / Σ pretax before any clip; it can be above 50% or below 0), `kept_pretax_sum` and `kept_tax_sum` (unscaled), `rate` (the kept years' ratio, before any clip), `rate_used` (after the clip) and `clipped` (bool; product lead), `currency` (the unit of the last year's pretax filing, as in `tax_rate_statutory`) and `assumptions` (`["tax_rate", "debt_tax_rate"]`). English from the params, kept years always as a list (they can have a gap): "FY2020 was a loss year, so the tax rate is read from FY2018, FY2019 only: 29.0% instead of 41.5% over FY2018-FY2020" (Exxon's real figures, Step 2); two loss years say "were loss years". When the kept rate clips, this note comes before `tax_rate_clipped` in the run's notes.
  - The `tax_rate` and `debt_tax_rate` rows' method says "Σ income tax / Σ pretax income, FY2018, FY2019 (FY2020, a loss year, left out)"; their sources stay the derived Σ tax and Σ pretax rows of all three years (the loss year's pretax is why it was left out, so it stays a source).
  - A lesson in `text.WARNING_LESSONS["tax_rate_loss_year_left_out"]`, no params: why a loss year's tax benefit is not the rate profits pay, what Warren does, and what it leaves out (a loss can also be deducted from later profits, 26 U.S.C. §172, which Warren does not model, as in the statutory lesson). References Damodaran ch. 10 and Koller, Goedhart and Wessels; `warren_rule`: "a year with pretax income of zero or below is left out of the three-year tax rate".
  - `coded.RUN_NOTE_CODES` gains the code.
  - `READING_RULES_VERSION` 3 → 4 (a run with a loss year in its window reads a different rate), with its row in `reading_rules.md`.
  - Tests (`tests/analysis/test_loss_year_tax.py`, on the shared fixture with one year's pretax and tax scaled): a loss year above the floor leaves that year out, with the rate equal to the other two years' Σ tax / Σ pretax and the note's exact params; two loss years read the one profitable year; a year at exactly 0 pretax is left out; no loss year gives no note and the same rate as before; a window at or below the floor still takes the statutory rate and no loss-year note (the floor wins); a kept-years rate above 50% is clipped and both notes appear; the kept years' margin is above the floor whenever the window's is (a Hypothesis property over three years' pretax and revenue); the lesson catalogue covers the new code.
  - Exit: a run with a loss year in its window above the floor reads the profitable years' rate with the note; every other run reads what it read before; full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot: list every stored run whose window has a loss year, with its old and new `tax_rate` and its value per share rebuilt both ways; `reproduce --all` must still reproduce every stored run to the cent (stored assumptions are untouched), and `reproduce --all --rebuild` must differ from `main` only on the runs listed. Exit: the list, the counts, and no other run moving.

## Alternatives considered

- **The statutory rate whenever any year is a loss.** Simple, and consistent with #385, but it throws away what Exxon's profitable years say: its upstream profits pay foreign rates above 21%, and its kept-years rates are 29.0%, 25.2% and 25.5% (Step 2), so 21% would understate its tax by four to eight points.
- **Remove the one-off item and keep the year** (Koller, Goedhart and Wessels). The better method, but companyfacts does not tag impairments and restructuring charges reliably enough to subtract them.
- **The median of the three yearly rates.** With three years the median is one year's rate, and a loss year's own "rate" (benefit / loss) is a refund rate that can land in the middle by chance. Not robust in the way the word suggests.
- **Weight by revenue, or keep the loss year and only clip harder.** Neither removes the mixing of a refund rate with a profit rate.
- **Widen the window to five years when a year is a loss.** Better information in principle, but the run's history is built around three fiscal years everywhere (the other ratios read the same window), and a wider window for one ratio only is a bigger change than this item.
- **Model the loss carryforward** (0% until the loss is used up, then the full rate). The right answer for a company coming out of losses, but it needs the NOL balance from the tax footnote, which company facts do not give reliably. Named in the lesson; not built.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `reading_rules.md`, tests under `tests/analysis/`, and `docs/versions.md`, `docs/team-sync.md` on merge.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8 and value per share, under "Supuestos fuera de lo habitual", brief line 128): a company with a loss year in its three-year window gets a tax rate read from the years it made money, with a note that names the year left out and both rates. Added: run-note code `tax_rate_loss_year_left_out` (group `assumption`) with the params above, and its lesson. Nothing renamed or removed. Changed: fresh runs of a company with a loss year in the window read a different `tax_rate` and `debt_tax_rate` (Step 2 lists them); stored runs keep their stored assumptions and reproduce as before, and runs stored before reading rules v4 never carry the note. The note shows in the side panel of the rows in `assumptions`, as `tax_rate_statutory` does. The brief is the front-end team's to update (the line "the window that mixes a loss year … is #393" becomes this note).

## Design review (nov.15.2026)

- **Explainer.** Fourteen gaps; taken: a zero year's tax leaves with it, a profitable year with a benefit stays in, the kept-years ratio goes through `_ratio`, `effective_rate` is unclipped, the kept sums are unscaled, the two-loss-year wording, the note order with `tax_rate_clipped`, the Spanish (below). The rest are in the tests (`tests/analysis/test_loss_year_tax.py`) and Step 2.
- **Professor, GO, no blockers.** The rule holds as a working rule; no book prescribes it, so the doc's paraphrases of Damodaran and Koller were rewritten (Problem) and the lesson names it as Warren's own (`warren_rule`). Taken: the proof's first inequality is ≥ (a zero year), the Koller alternative added and rejected with its reason, the "about ten points" claim replaced by Step 2's numbers. Not taken here: a profitable year whose own rate is distorted (Exxon's FY2017, with the tax-reform benefit) stays in; filed as a backlog idea.
- **Analyst, GO, no blockers.** Exxon's yearly pretax and tax in the database match SEC company facts to the dollar (FY2020: pretax −$28.9bn, tax −$5.6bn, accession 0000034088-21-000012); the kept-years rates (29.0%, 25.2%) sit with Exxon's later profitable years (25.9% to 29.2%, FY2022–FY2025). Ideas filed as one backlog issue: profitable years whose own rate is outside 0% to 50% (Exxon's FY2016–FY2017 negative tax; the 2017 tax-reform charges of JNJ, KO, CAT and MSFT, which put their FY2016–FY2018 windows at 32% to 43%) stay in with no note; Exxon's pretax includes equity-company income taxed inside those companies, so its consolidated rate understates its burden; the lesson could say a single kept year is noisy.
- **Product lead, BLOCKING, accepted.** In the clip case the note's `rate` was not the rate the run uses: added `rate_used` and `clipped`, and pinned this note before `tax_rate_clipped`. Taken: kept years written as a list, never a range. Suggested Spanish, kept for the app: "En los años fiscales {primer_año} a {último_año}, {empresa} no tuvo utilidad antes de impuestos en {años_sin_utilidad} (perdió dinero o quedó en cero). En un año así, el impuesto que registra es un beneficio por la pérdida, no lo que pagan sus ganancias. Por eso Warren calcula la tasa efectiva (impuestos entre utilidad antes de impuestos) solo con {años_con_utilidad}: {rate}, en lugar del {effective_rate} de los tres años juntos." When `clipped`: "Como supera el máximo de {max_rate} que Warren acepta, usa {max_rate}." Stored runs before reading rules v4 never carry this note.

## Results (Step 2, nov.15.2026)

On the restored snapshot (`warren-20261110T202538Z`), all 903 stored baseline runs:

- **Only Exxon has a loss year in a window**, always FY2020 (pretax a loss, a small tax benefit), in 44 runs. No other Phase 1 company's window holds one.

| Exxon runs dated | Window | Tax rate now → with this rule | Value per share, rebuilt |
|---|---|---|---|
| 2021-03-01 to 2022-02-15 (15 runs) | FY2018–FY2020 | 41.5% → 29.0% | +28% to +55% (e.g. $4.94 → $7.47 on 2021-03-01; $9.43 → $12.43 on 2022-02-15) |
| 2022-03-01 to 2023-02-01 (13 runs) | FY2019–FY2021 | 32.5% → 25.2% | +7.6% to +9.2% |
| 2023-03-01 to 2024-02-15 (16 runs) | FY2020–FY2022 | 27.7% → 25.5% | +2.5% |

  The 2021 values are small because the run's forecast starts from Exxon's 2020 trough; the tax rule moves them a lot in percent and little in dollars. Revenue and EBIT forecasts do not use the tax rate, so the forecast-error scores (M3, M8, M9) do not move.
- **Stored runs** keep their stored rows: `python -m domains.analysis reproduce --all --rebuild` gives 903 of 903 reproduced to the cent, and 777 of 903 rebuilt to identical rows against 821 on `main`. The 44 fewer are exactly the Exxon runs above (their `tax_rate` and `debt_tax_rate` values differ, as expected under reading rules v4); the other 82 differences are the older runs whose reading rules weren't recorded, as in #385's results.
