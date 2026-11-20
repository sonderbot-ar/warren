# Backlog #481 (part 2a): diluted share counts by fiscal year, and a code for the missing fourth quarters

Issue: https://github.com/sonderbot-ar/warren/issues/481 (item 4) · Branch `backlog-481-annual-diluted` · Version v0.10.20 when merged.

Status: In progress (nov.20.2026).

## Problem

The `shares` card of an answer (v0.10.14, #476) shows two histories: the cover-page counts by date and the weighted diluted counts by quarter. The engine's share count (D4, `math_engine._shares`) takes the cover-page count, and when a company files none it falls back on the newest weighted diluted count, reading the quarterly **and the annual** counts, newest first. The card only showed the quarterly ones, so (analyst, #476 review):

1. **The card and the run can disagree.** When the fallback takes a 10-K's annual count (a run dated after the 10-K and before the next 10-Q), no point on the card is the one the run used.
2. **The fourth quarters are silent.** A 10-K files the year's weighted diluted count, not the fourth quarter's, and Warren never derives one (an average of averages is not a weighted average; `test_weighted_average_shares_are_never_derived`). So every quarterly diluted chart skips Q4 with no word on why, and a student reads it as missing data.

No stored number changes; no run's value moves. The history is computed when an answer is read and never stored, so `reproduce` is untouched.

Item 3 of #481 (the fair value of debt beside its book value) needs a new filing tag in the concept map and stays open on #481 for part 2b.

## What changes

`inputs_behind`'s `shares` cell gains a third series, after the two it has:

| Series | `measure` | `frequency` | Points | `primary` |
|---|---|---|---|---|
| cover page (unchanged) | `shares_outstanding` | `date` | each cover count in the window | the run used a cover count (unchanged) |
| diluted by quarter | `diluted_shares` | `quarter` | each quarter's count, plus a valueless `FY…Q4` point per year whose fourth quarter has no count | the run used one of its points |
| diluted by year (new) | `diluted_shares` | `year` | each fiscal year's count in the window (`FY2024`, `fiscal_period` `FY`, the 10-K and its filing as the part) | the run used one of its points |

**`primary` of the quarterly series.** Before, it was "the run did not use a cover count". Now it is "the run used a point of this series", so at most one series of the card is primary and it holds the used point. On every stored run the two rules agree on the quarterly series (all 909 stored runs use a cover count, so it is `false` either way).

**The fourth-quarter gap.** A point with `value` `None`, `used` `false`, and `missing` = `not_computable` with `reason` `no_fourth_quarter_count` (added to `MISSING_REASONS`), params `fiscal_year` and `annual_period` (`FY2024`, the yearly series' point; `None` when that year's count is not filed either), `period_end` the year's end when the annual count is there. It is emitted for a fiscal year that has some count (a quarter or the year) but no Q4 count, once the year has ended in the filings: its annual count is filed, or a count of a later year is. An open year (its 10-K not out) gets no gap. A year with no count at all gets no point.

**One used point.** A 10-K may file a three-month fourth-quarter count beside the year's, under the same accession number and end date. The used test now also matches the stored source's `fiscal_period`, so only one of the two is used.

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor; the front-end lead on *Product impact*.

**Step 1. The yearly series and the gap.** `single_values._shares` and `_fourth_quarter_gaps`; `MISSING_REASONS` gains `no_fourth_quarter_count`. Tests (`tests/analysis/test_single_values.py`): on Test Corp the yearly series has FY2015 to FY2019 at 100 from 10-Ks, and the quarterly series has a coded gap at each of FY2015Q4 to FY2019Q4 and none at the open FY2020; with no cover page and a run dated between the 10-K and the next 10-Q, the yearly series is primary and its FY2019 point is the used one, equal to the row; a 10-K that also files a Q4 count gives a real Q4 point, no gap, and exactly one used point across the two diluted series; the existing split test reads three series. Exit: tests green. Done.

**Step 2. Real check.** Every company's newest stored run, and one run in ten of the 909 stored runs: exactly one used point on the card, gaps by kind, any filed Q4 count. Exit: results below. Done.

## Real check (Step 2)

Newest stored run of each company (2026-10-30): all eight use a cover-page count, and that point is the only used one. Each has four or five yearly points, 13 to 15 quarterly counts and a coded fourth-quarter gap for each ended year (4 for Apple, 5 for the others), every one with its annual count. No company files a three-month fourth-quarter count.

One run in ten (results filled in below).

## Alternatives considered

- **Put the annual counts in the quarterly series as `FY` points** (the issue's wording, "add the annual counts to the diluted series"). Rejected: a chart of quarters with a year's point among them mixes two measures (a three-month and a twelve-month weighted average) on one axis. A series of its own keeps `frequency` honest and is the shape every other card already uses (one frequency per series).
- **Derive Q4 as 4 × FY − (Q1 + Q2 + Q3).** Rejected: it is exact only when every quarter has the same number of days and the count is a plain day-weighted mean; buybacks and dilution from options inside the year break it, and the engine never derives a weighted count (`test_weighted_average_shares_are_never_derived`). A gap with its reason teaches more.
- **The generic `not_reported` code for Q4.** Rejected: Q4 is not unreported; the count exists, as the year's. The code points to the yearly point that holds it.

## Files to change

`domains/analysis/single_values.py`, `tests/analysis/test_single_values.py`, `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (none: a backlog item).

## Product impact

Serves brief Q3 (the bridge from equity value to value per share) and every per-share figure's `shares` card, under "Los datos de partida".

- **Added:** a third series on the `shares` cell (`diluted_shares`, `frequency` `year`); `missing.reason` `no_fourth_quarter_count` (params `fiscal_year`, `annual_period`) for the Spanish catalogue. Suggested Spanish: "El reporte anual trae el promedio del año ({annual_period}), no el del cuarto trimestre; Warren no lo calcula a partir del año." Without `annual_period`: "Este trimestre no trae su propio número de acciones diluidas, y el del año tampoco se ha presentado."
- **Changed:** `primary` on the quarterly diluted series now means "holds the used point" (identical on every stored run). The card's series list grows from two to three, so code that unpacks exactly two breaks.
- **Removed or renamed:** nothing.
- **Breaks:** no brief question.

## Review notes

(filled in at the design review)
