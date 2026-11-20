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

**The fourth-quarter gap.** A point with `value` `None`, `used` `false`, no parts, and `missing` = `not_computable` with `reason` `no_fourth_quarter_count` (added to `MISSING_REASONS`), params `fiscal_year` and `annual_period` (`FY2024`, the yearly series' point; `None` when Warren read no count for that year: the 10-K may hold one under a tag the concept map does not read, as Exxon's FY2009 and FY2010 do, so the text never says the company did not file it), `period_end` the year's end when the annual count is there, else `None`. It is emitted for a fiscal year that has a Q1, Q2 or Q3 count in the window and no Q4 count, once the year has ended in the filings: its annual count is read, or a count (quarterly or annual) of a later year is. An open year (its 10-K not out) gets no gap, and the series never opens on a gap.

**The window.** Both diluted series keep a count when its period ends after `as_of` − `years` × 365.25 days, as the quarterly series did; a yearly point may so cover months before the window (FY2021 on a window opening 2021-10-30). Split adjustment is the existing rule: diluted counts by their filing date, cover counts by their date.

**One used point.** A 10-K may file a three-month fourth-quarter count beside the year's, under the same accession number and end date (a `Q4` count is a three-month duration ingest places as Q4). The engine then takes the quarter's count (its quarterly counts come first in a stable sort, `math_engine.py`), and the used test now also matches the stored source's `fiscal_period`, so only that one is used. All 909 stored shares sources carry `fiscal_period`; a source without it would match on the other three keys, as before.

## Plan

**Step 0. Design doc and review (this doc).** Explainer, analyst, professor; the front-end lead on *Product impact*.

**Step 1. The yearly series and the gap.** `single_values._shares` and `_fourth_quarter_gaps` (reviewers' changes in a second commit); `MISSING_REASONS` gains `no_fourth_quarter_count`. Tests (`tests/analysis/test_single_values.py`): on Test Corp the yearly series has FY2015 to FY2019 at 100 from 10-Ks, and the quarterly series has a coded gap at each of FY2015Q4 to FY2019Q4 and none at the open FY2020; with no cover page and a run dated between the 10-K and the next 10-Q, the yearly series is primary and its FY2019 point is the used one, equal to the row; a 10-K that also files a Q4 count gives a real Q4 point and no gap (FY2015Q4 stays a gap: its 10-K is older than the fixture's filings), exactly one used point across the two diluted series, and it is the Q4 one; a year with only its annual count in the window opens no gap, and a year with no annual count read gets `annual_period` `None`; the existing split test reads three series. Exit: tests green. Done.

**Step 2. Real check.** Every company's newest stored run, and every tenth of the 909 stored runs by run id (91 runs): exactly one used point on the card, gaps by kind, any filed Q4 count. Exit: results below. Done.

## Real check (Step 2)

Newest stored run of each company (2026-10-30): all eight use a cover-page count, and that point is the only used one. Each has four or five yearly points, 13 to 15 quarterly counts and a coded fourth-quarter gap for each ended year (4 for Apple, 5 for the others), every one with its annual count. No company files a three-month fourth-quarter count.

Every tenth stored run (91 runs, all eight companies, 2019 to 2026): every card has exactly one used point (91 of 91, all cover-page counts; no stored run uses the diluted fallback); no filed fourth-quarter count; 439 fourth-quarter gaps, every one with its annual count. The analyst's sweep, every 30 days from 2012 to 2026 for all eight companies, found 107 gaps with no annual count read, all Exxon (FY2009 and FY2010: the 10-Ks were filed, but neither mapped diluted tag carries an annual value; the first is FY2011, filed 2014-02-26), and no tie of dates on the engine's newest count. Fiscal labels hold on 52/53-week and odd calendars (Apple FY2023 ending 2023-09-30, J&J FY2022 ending 2023-01-01, Walmart FY2026 ending 2026-01-31).

## Alternatives considered

- **Put the annual counts in the quarterly series as `FY` points** (the issue's wording, "add the annual counts to the diluted series"). Rejected: a chart of quarters with a year's point among them mixes two measures (a three-month and a twelve-month weighted average) on one axis. A series of its own keeps `frequency` honest and is the shape every other card already uses (one frequency per series).
- **Derive Q4 as 4 × FY − (Q1 + Q2 + Q3).** Rejected. For basic shares the year is the day-weighted mean of its quarters, so buybacks alone would not break it (professor); unequal quarters would (Apple's 14-week quarter in a 53-week year). For diluted counts it is not exact at all: each period is tested for anti-dilution on its own and a loss quarter counts no potential shares (ASC 260-10-45-20; IAS 33.41–44), and IFRS computes the year's dilution on its own (IAS 33.37; KPMG, *EPS Handbook*, 2022, 4.6.20). The engine never derives a weighted count (`test_weighted_average_shares_are_never_derived`); a gap with its reason teaches more.
- **The generic `not_reported` code for Q4.** Rejected: Q4 is not unreported; the count exists, as the year's. The code points to the yearly point that holds it.

## Files to change

`domains/analysis/single_values.py`, `tests/analysis/test_single_values.py`, `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (none: a backlog item).

## Product impact

Serves brief Q3 (the bridge from equity value to value per share), Q5 and Q8 (every value per share, brief "Los datos de partida") and every per-share figure's `shares` card, under "Los datos de partida".

- **Added:** a third series on the `shares` cell (`diluted_shares`, `frequency` `year`); `missing.reason` `no_fourth_quarter_count` (params `fiscal_year`, `annual_period`) for the Spanish catalogue. Suggested Spanish (front-end lead and professor; the app owns the final text in its catalogue): "El informe anual del ejercicio {año} da solo el promedio ponderado de acciones diluidas de todo el año, no el del cuarto trimestre. Warren no lo saca restando los tres trimestres al año, porque es un promedio y no una suma, y cada periodo se calcula por separado. La cifra del año está en la serie anual." Without `annual_period`: "No hay un número propio de acciones diluidas para el cuarto trimestre, y Warren no encontró la cifra anual de ese ejercicio en los informes." The app draws a gap as a break, never as zero, draws the yearly series in its own panel (a twelve-month average beside three-month ones), and picks the headline series by `primary`.
- **Changed:** `primary` on the quarterly diluted series now means "holds the used point" (identical on every stored run). The card's series list grows from two to three, so code that unpacks exactly two breaks.
- **Removed or renamed:** nothing.
- **Breaks:** no brief question.

## Review notes

Design review, nov.20.2026.

- **Explainer** (13 points): the doc now defines the window, the Q4 count, `period_end` and parts of a gap, the tie-break, the default on a source without `fiscal_period`, the FY2015Q4 fixture exception, and Step 2's sample. Brief Q3 is cited by section.
- **Analyst** (accept with changes): (1) the no-annual-count text said the year's count "is not filed", false for Exxon FY2009 and FY2010: reworded in code and Spanish. A separate reason was considered and not taken: the app's words are the same either way and `annual_period` `None` already tells them apart. (2) Step 2's results were missing: filled in. (3) a gap could open the quarterly series: gaps now need a Q1–Q3 count in the window (test added); the yearly point reaching before the window is documented. (4) the tie-break is asserted (`used[0].period == "FY2019Q4"`).
- **Professor** (GO): the Q4 reason is corrected (anti-dilution per period, loss quarters, IAS 33.37), in the doc and the code's docstring; the Spanish is tightened ("informe anual", "promedio ponderado", the reason). The idea of a twelve-month note beside the quarterly chart is the app's.
- **Front-end lead** (accept): cite Q5 and Q8 (done); no app code reads the card today; the Spanish rewritten as above; the app's catalogue test against `MISSING_REASONS` is front-end work.
