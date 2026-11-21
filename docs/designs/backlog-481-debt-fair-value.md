# Backlog #481 (part 2b): the fair value of long-term debt beside its book value

Issue: https://github.com/sonderbot-ar/warren/issues/481 (item 3) · Branch `backlog-481-debt-fair-value` · Version v0.10.22 when merged.

Status: In progress (nov.21.2026).

## Problem

The `debt` card of an answer (v0.10.14, #476) shows the balance sheet's book debt on each balance date, with the series note `book_value` ("not a market value"). The professor asked on the #476 review (#481 item 3): where the filing gives the fair value of its long-term debt at the balance date, show it beside the book value, so a student sees how far the two drift apart when rates move (a bond issued at 2% is worth less than its face value when rates are 5%, or when the company's credit weakens). Only the figure the filing names; no estimate of Warren's own.

Nothing in the valuation changes. The valuation keeps book debt (the balance step `math_engine._balance`; one row is both the WACC's debt weight and the debt subtracted on the way to equity, `whatif.py`). Textbooks prefer the market value of debt and accept book value as a proxy while the two are close (Koller, Goedhart and Wessels 2020; Damodaran 2012); the card shows when they are not. The fair value is context only. No stored number moves and `reproduce` is untouched.

## What the filings tag (checked on SEC company facts, nov.21.2026)

| Company | `LongTermDebtFairValue` | `DebtInstrumentFairValue` | Note |
|---|---|---|---|
| MSFT | 64 dates, 2010-06 to 2026-09 | none | 29.3B at 2026-09-30 against 35.5B carrying (`LongTermDebt`, current portion included) |
| KO | 63 dates, 2010-10 to 2026-10 | 7 dates to 2017 (2.6B at 2017-03-31: one instrument, not the total) | 35.4B at 2026-10-02 |
| PG | 28 dates, 2015-06 to 2026-09 | none | 26.7B at 2026-09-30 against 21.9B non-current: includes the current portion |
| WMT | none | 8 dates, 2010-01 to 2012-01 only | |
| XOM | none | 35 dates to 2018-09 | |
| AAPL, JNJ, CAT | none | none | the fair value is in the note's text or tagged only by segment or instrument (dimensional), which company facts drop |

So the map reads **`LongTermDebtFairValue` only**. `DebtInstrumentFairValue` is excluded for two reasons (analyst): Coca-Cola uses it for figures that are not totals (2.6B at 2017-03-31, 5,009M at 2016-09-30, and 34M and −47M in an 8-K), and every fact under it ends by 2018-09, so nothing recent would be read. Walmart's and Exxon's figures under it are totals, but too old to help. Three of the eight companies get a series today (Microsoft, Coca-Cola, P&G); the others get an empty series with a note that says Warren reads none, never that the company does not disclose it.

## What changes

1. **Concept map:** a new optional item `debt_fair_value`, `us-gaap:LongTermDebtFairValue`, priority 1, `instant`, `optional`, for every company, in **`concept_map_reported.csv`**, the file for items no valuation reads (#157). It is outside the fingerprint runs store, so no stored run's map changes, no archive copy is needed, and `test_no_valuation_or_scoring_step_reads_a_reported_only_item` guarantees no valuation, score or AI step reads it. (The first draft put it in `concept_map.csv`; the reported-only file fits better.) Ingest stores its facts like any mapped tag.
2. **The `debt` card gains a second series** after the book one:

| Series | `measure` | `frequency` | `basis` | `primary` | Points |
|---|---|---|---|---|---|
| book (unchanged) | `debt` | `quarter` | `latest` | true | each balance date in the window |
| fair value (new) | `debt_fair_value` | `quarter` | `latest` | false | each date in the window with a filed `LongTermDebtFairValue`, as known on the run's date |

A fair-value point exists only on a **balance date of the book series** (analyst's blocker: Coca-Cola filed 9,345M at 2010-10-02, the day the CCE deal closed and not one of its quarter ends, most likely the debt it took on, not its total; such a figure is left out and its date listed in the note's `left_out_dates`). The facts are read with `get_facts(conn, cik, ["debt_fair_value"], as_of)` (every period as filed, latest version known on `as_of`), one per date, the newest filing's. A point: `period` the ISO date, `fiscal_year` and `fiscal_period` null (as the book points), `period_end`, `value` the filed figure, `used` false (the valuation never uses it), one part `debt_fair_value` with its filing. Same window as the book series (`as_of − round(365.25 × years)` days to `as_of`, shared helper `_window_start`), point-in-time through `get_facts(..., as_of)`: a later filing's restatement replaces the first figure, as for book debt.

3. **Two series notes, new in `SERIES_NOTES`:**
   - `fair_value_as_filed` (params `known_on` = the run's `as_of`, `tag` = `us-gaap:LongTermDebtFairValue`, `left_out_dates`): "the filing's own estimate of what its long-term debt (with the part due within a year) would be worth on that date, which moves when interest rates or the company's credit change; textbooks prefer it to book value, and the valuation uses book value as a proxy, which is fine while the two are close. It leaves out short-term borrowings and commercial paper, and often leases, so it is not the same debt as the book line: compare how the two move, not their gap. Many filings round it (to $0.1B), so a small move between dates means little."
   - `fair_value_not_read` (same params) on a series with no point in the window (also when the company tags it only outside the window): "Warren reads no fair value of long-term debt for this company in the window; the filing may give it in its text or tagged by instrument, which Warren does not read."

## Plan

- **Step 0. The map item.** Add the row to `concept_map_reported.csv`; `test_shipped_maps_load_together` lists it among the reported-only items. Re-ingest the eight companies. Exit: CI green, the tag's facts stored for MSFT (125), KO (119) and PG (56), none for the others; `reproduce --all` clean.
- **Step 1. The series.** `single_values._debt_fair_value(singles)`; the `debt` builder returns the book series first and the fair-value series second (exactly one `primary` series per card); the two notes. Tests (Test Corp, `tests/analysis/test_single_values.py`): an empty series with `fair_value_not_read` when nothing is filed, cash and minority cards unchanged; points on the book dates with parts and filings, `used` and `primary` false, the book series and every row and output identical with and without the tag; a restatement filed before `as_of` replaces the first figure and one filed after is never read; a figure off the balance dates is left out and listed. Exit: CI green.
- **Step 2. Real check.** On a fresh Microsoft, Coca-Cola and P&G run, and on a stored Apple run: the series' last point against the 10-Q's fair-value note; Apple's empty series with its note. Results in *Real check* below.

## Real check (Step 2, nov.21.2026, snapshot of nov.19 re-ingested)

| Run | Fair-value points (5 years) | Last point | Book debt used | Note |
|---|---|---|---|---|
| `MSFT_2026-10-30_1` | 20, every book date | 29,300M at 2026-09-30 (10-Q 0001193125-26-436133) | 106,454M | `fair_value_as_filed` |
| `KO_2026-10-30_2` | 20, every book date | 35,398M at 2026-10-02 (10-Q 0001628280-26-067844) | 41,619M | `fair_value_as_filed` |
| `PG_2026-10-30_2` | 12; none at 2021-12-31 to 2024-03-31 (8 book dates) | 26,700M at 2026-09-30 (10-Q 0000080424-26-000256) | 38,925M | `fair_value_as_filed` |
| `AAPL_2026-10-30_1` | 0 | none | 85,574M | `fair_value_not_read` |

Coca-Cola point-in-time (series built on three dates): at `as_of` 2012-01-15 the 2010-12-31 point is 15,346M from the 10-Q filed 2011-10-27; at 2012-03-01 it is 16,218M from the 10-K filed 2012-02-23; the 2010-10-02 figure (9,345M) is never a point and appears in `left_out_dates` once its 10-K is public. `reproduce --all`: 909 of 909 runs to the cent. Each answer takes 1.7 to 2.6 s, as before. The book debt lines differ from the fair value by short-term borrowings, leases and, for Microsoft, much more (106B book against 29B fair), which is why the note says to compare how the two move.

## Alternatives considered

- **`DebtInstrumentFairValue` as a fallback.** Rejected: an instrument's figure, not the total (KO 2017), so it would put a wrong total on the card for Walmart and Exxon.
- **A point note on each book point instead of a series.** Rejected: the dates differ (some fair values are year-end only), and a chart draws a second line from a series, not from notes.
- **A gap figure (fair minus book) per point.** Rejected for now: the two cover different debt (short-term borrowings, leases), so the gap would mislead; the note says to compare the moves. A like-for-like carrying amount (`LongTermDebt`) could be a later item if the front-end asks.
- **Use the fair value in the valuation (market value of debt in the WACC weights).** Out of scope: that changes D8 and every number, a decision for the owner.

## Files to change

`domains/fundamentals/concept_map.csv`, `domains/fundamentals/concept_maps/<sha>.csv` and `CHANGES.md`; `domains/analysis/single_values.py`; tests under `tests/analysis/` and `tests/fundamentals/`; `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` at merge.

## Product impact

Serves brief Q3 (value per share: the bridge from enterprise value to equity, where debt is subtracted) and Q4 (the debt weight in the WACC), where the `debt` card appears. Adds, removes or renames nothing existing: the `debt` card's history gains a second series (`debt_fair_value`, `primary` false), always after the book series, and each card keeps exactly one `primary` series, so code that assumes the debt card has exactly one series must take the primary one. Fair-value dates are a subset of the book dates, with gaps (P&G has none from 2021-12-31 to 2024-03-31): draw a gap as a break, not a joined line. Two new series-note codes for the Spanish catalogue: `fair_value_as_filed` and `fair_value_not_read` (English above; the front-end owns the Spanish in `webapp/text/es.json`, and will say "valor razonable"). How the series is drawn is the front-end's choice.

## Review notes

Design review nov.21.2026, all four in parallel on the first draft.

- **Explainer** (11 gaps): the read path (now `get_facts`, named), the window (now the code's), the empty case, the params' values, one series becoming two in the builder, the Step 0 exit (counts): all fixed in the text. Item 8 (what the book line holds per company) is answered by the note: the two are different debt by design.
- **Analyst, GO with changes.** Blocker: Coca-Cola's 2010-10-02 figure is not its total; **accepted**: points only on the book's balance dates, off-date figures listed (`left_out_dates`), test `test_a_fair_value_off_the_balance_dates_is_left_out_and_listed`. The reason for excluding `DebtInstrumentFairValue` rewritten (Walmart's and Exxon's are totals): accepted. Coca-Cola's 2010-12-31 restatement in the real check: accepted. P&G's missing dates in *Product impact*: accepted. Rounding to $0.1B in the note: accepted.
- **Professor, GO with changes.** D8 was the wrong cite (it is data sources): fixed to the balance step and `whatif.py`. Why book is used, in the note: accepted. Credit as well as rates move the fair value: accepted. `sources.py`'s WACC text says "weighted by market equity and debt": a separate wording fix, filed as a backlog issue, not in this PR.
- **Front-end lead, accept with wording.** Cite Q4 too, one primary series with book first, drop the drawing rule and the Spanish rule from the engine doc, shorten the note: all accepted.

