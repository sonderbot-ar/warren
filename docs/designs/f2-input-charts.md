# F2 design: chart every input behind an answer

Front-end team, nov.19.2026. Branch `f2-input-charts`, stacked on the first screen's mockup (`f2-first-screen`, PR #456, F2 Step 4a), because the charts are added to that screen.

## Problem

The owner asked (nov.19.2026): for any question, the answer shows charts for every cell involved in computing it. For each cell: how its value changed over past years (not only last year), the drivers behind those changes (for revenue, the inputs or components behind its movements), and what the current assumption says, drawn so it is easy to compare with the history. All of it in the same answer, beside everything the screen already shows, not on another page.

Today the answer shows the forecast, its range, the coverage and a formula bar; the side panel's *Fuente* tab lists the filings behind one figure. A student sees that the forecast uses 1.9% growth, but not that Apple's last three quarters grew about 16%, which is the comparison that teaches what an assumption is.

## What a "cell" is

A cell is an assumption row of the run that an answer's outputs reach. The engine already knows them: `domains.analysis.sources.output_trace(rows)` gives each output's formula and direct inputs, and `sources.reaches(trace, key)` follows outputs back to rows. Rows of one name are one cell (one chart), whatever their periods. For brief Q5 on the stored run `AAPL_2026-10-30_1` (checked on the restored snapshot), revenue for FY2026Q4 to FY2027Q3 reaches exactly two cells:

- **B, `revenue_seed`**: the same quarter a year earlier, four reported quarters (FY2025Q4 102,466; FY2026Q1 143,756; Q2 111,184; Q3 109,417, millions of US$).
- **C, `revenue_growth`**: 1.88% in each of the four quarters, the three-year same-filing average of FY2023–FY2025 (−2.8%, 2.0%, 6.4%). From the second year it fades toward terminal growth (4.98%); the answer does not reach those rows, so the chart only mentions them.

The letters are the formula bar's (`=B5*(1+PROMEDIO(C2:C4))`), so the cards, the formula bar and the *Fuente* tab name a cell the same way.

A DCF answer (Q3) reaches many more cells (six drivers per period, the WACC's parts, net debt, shares). The same rule applies; the cards are grouped as the formula is (revenue, margin, cash flow, discount rate, the bridge to equity) and ordered by the formula, not by size.

## How many years

Five fiscal years by default, with a 3 / 5 / 10 switch on the screen. Reasons: the growth rule averages three years, so five shows the averaged years and two before them; filings go back to 2009, so ten is available for a student who wants a cycle. The owner left the number open; five is the team's default and can be changed in one place.

## Plan

**Step 0. Mockup (this step; static, no app code).** In `docs/product/mockups/f2-screen1-q5.html`, states *Respuesta* and *Fuente*: a section "Las celdas detrás de la respuesta" below everything the answer already shows, nothing removed. One card per cell:

- **B**: four small charts, one per fiscal quarter (T1 to T4), each with five years of that quarter, the base point (the seed) and the forecast. Small multiples, not one line, because the rule compares a quarter with the same quarter a year earlier; a single line would mix the holiday quarter with growth. A dashed "Próximamente" box says that revenue by product and region is not read yet (#472).
- **C**: annual growth for five fiscal years, the three averaged years in the accent colour and the others grey, and the assumption as a dashed bar; then quarterly growth against the same quarter a year earlier for 20 quarters, with the assumption as a dashed reference line across them. The note says the plain fact the chart shows: the last three quarters grew 15.7–16.6% and are not in the assumption, because Warren averages whole fiscal years and Apple has not yet filed its FY2026 annual report.
- Each card has its numbers as a table under "Ver las cifras", each value marked when derived (Q4 = the year minus three quarters); every value opens the side panel as any figure does (design principle 2); each mark has a tooltip.

Every figure is the engine's output: `series --ticker AAPL --as-of 2026-10-30 --json` (revenue lines and `revenue_growth_yoy`, annual and quarterly) and the stored run's rows and outputs. The generator lives outside the repo; the mockup holds the figures as drawn. Reviews: `design-critic` READY FOR OWNER and `student-reviewer` without blockers, then the owner's card. Exit: the owner approves the cards or asks for changes.

**Step 1. Built with the first screen (F2 Step 4b), once #471 is merged.** A template partial per cell kind (a quarterly seed, a driver ratio, a single value), fed only by the engine's call from #471; the app draws, it computes no number. Tests: every row the answer's outputs reach has a card (from `reaches`), no card for a row it does not reach, the year switch changes only the history, Playwright screenshots at 1440 and 390 px in both themes. Exit: the built screen signed off with the rest of Step 4b.

## Alternatives considered

- **One chart with every input.** Rejected: different units (millions and percent) would need two axes.
- **The charts in the side panel only.** Rejected: the owner asked for them in the same answer; the panel shows one figure at a time.
- **The app assembling history from `series`.** It works for Q5 today, but the app would choose which history matches each assumption and compute contributions, against "every number comes from the engine". Filed as #471 instead.

## Engine needs

- **#471** Inputs behind an answer: for a run and the outputs an answer shows, each reached row with its history over N fiscal years in the assumption's own measure, the parts behind each change, the forecast values and which history points they used. Blocks Step 1, not Step 0.
- **#472** Revenue by product and region from the filings' segment notes (XBRL dimensions, which companyfacts drops). Fills the "Próximamente" box; the screen ships without it.

## Design review

Mockup review, nov.19.2026, two passes each.

- **Student reviewer**, first pass, five blockers, all taken: the small charts' axis was in thousands of millions while the figures were in millions (axis numbers dropped, one common scale in a caption, "millones" beside each base); the 1.9% against the last quarters' 16% read as a broken model (the note now says the base is a fixed simple rule that does not claim recent growth will stop, that FY2026 enters the average once Apple files its 10-K, and points to "¿Qué tan seguro?"); a sentence on the years after the first confused (dropped); phone labels on the quarterly chart (now "T1 ’22", the 1.9% a point on the dashed line); the small charts' years unexplained (each says "años fiscales 2021 a 2025"). Terms taken: "Se usa en el promedio / No se usa", "contra el mismo trimestre del año anterior", "ingresos" throughout, "trimestre fiscal", "Ver los datos de las gráficas", the formula "pronóstico = B × (1 + C)" in the intro, a line that the 3/5/10 switch changes only the charts. Not taken: marking 2021 as atypical, a judgement about a cause the filings do not give. Second pass: no blockers.
- **Design critic**, first pass NOT READY, four blockers, all fixed: chart labels rendered at 10.7–12.7 px (separate laptop and phone drawings sized to the pane; measured 13.5–15.7 px at 390, 768, 1024, 1280 and 1440 px); h3 at 18 px, off the scale (16 px); grey bars at 2.4:1 in light (full `--muted`, about 6:1); table figures not buttons (every one a `button.fig`). Polish taken: true minus on axes, base point ringed, "Hace 4 años" headings, the assumption as a line and point instead of 8 px bars, the link 44 px tall, the crowded phone tick. Second pass: READY FOR OWNER. Left: a y label on the small charts (the caption carries the scale), a gap of about 120 px under card B at 1440, keep the "promedio" bracket when the year switch changes the chart.
