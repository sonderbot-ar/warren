# Backlog #140: reported figures and named ratios, with provenance (front-end R1)

Status: In progress (nov.03.2026) · Elephant: agent team · Branch `backlog-140-reported-figures`
Serves brief questions 1 and 2 (`docs/product/brief.md` §3) and F2's first screen. Takes over #128 item 2.

## Problem

Every number on a student's screen must come from the engine and show its source (Decision 13). The facts have been stored point in time with their filing since M1 (`financial_facts`), and `domains/fundamentals/facts.py` can select them, but no call or command returns one period's figures with their provenance, and no ratio exists outside a valuation run, where it is a three-year driver, not a period's figure. So the app can't answer "how much did Apple sell last quarter, and from which filing?" (Q1) or "how has Coca-Cola's operating margin moved against P&G's?" (Q2) without computing something itself, which the brief forbids.

## What the call returns

`reported.reported_period(conn, ticker, period, as_of) -> ReportedPeriod` in a new module `domains/analysis/reported.py`, where `period` is a fiscal quarter (`FY2025Q4`) or a fiscal year (`FY2025`), and the words `latest-quarter` / `latest-year` resolve to the newest period with revenue reported by `as_of`. Fiscal years and quarters are the company's own labels from its filing calendar (M1); the period's start and end dates are always returned, so Coca-Cola's FY2025 (to December) and P&G's FY2025 (to June) are never silently aligned.

Everything is as known on `as_of` (inclusive): the facts query takes only rows filed on or before it (`facts.QUERY`, `f.filed_at <= ?`), exactly as a valuation run does. A period not reported by `as_of` is an error that says so, never an empty answer.

**Lines.** One per canonical item of the concept map (`concept_map.csv`) that the period reports, under its own name (`interest_expense` and `interest_paid` are two lines when both are reported). An item the period doesn't report is left out, not shown as zero. Share counts are averages or cover-page counts, so a quarter is never derived for them (`facts.DERIVABLE_UNITS`): a fiscal Q4 has a share line only if the company reported one. Each line has:

- the **latest** value known on `as_of` (`get_facts(..., mode="latest")`), with its XBRL tag, its filing (accession, form 10-Q / 10-K / amendment, filing date, and the filing's folder in the EDGAR archive, built from the accession with no download), period start and end, fiscal labels and unit (currency stated, Decision 11 guardrail 3). Values are raw and unrounded, in the line's unit (US dollars, not millions); the app rounds for display;
- the **first-reported** value (`mode="first_reported"`), with its own tag, accession and filing date, and `changed` when the two differ. The engine says *that* it changed, not why (brief Q1);
- `derived` with its input filings when Warren computed it (Apple's fiscal Q4 = the 10-K year minus nine months; a cash-flow Q2 or Q3 from year-to-date figures; `facts._derive`), and `mixed_vintage` when a derivation mixes restated and first-reported inputs.

Flows use the quarterly view for a quarter and the annual view for a year (`get_facts(frequency=...)`); balance-sheet items are the balance at the period's end (Q4 and FY: the year-end balance).

**Newest filing disagrees.** The quality report's rows (`facts.newest_filing_disagreements`, which returns every period of the items asked) filtered to the period's lines (`reported._in_scope`): a reported flow line takes rows with its own start and end; a balance line, rows on its date; a derived line, rows on any duration of the same fiscal year ending on or before its end (the periods a derivation can be built from). They are informational, as in the quality report.

**Named ratios.** Computed by the engine, never by the app, from the latest lines, "as reported" (one-off charges included, and the output says so). Each ratio carries a stable `name` and `formula_id`, its value as a fraction (0.2 = 20%; net debt in the currency), its formula in words, `uses` (each entry names a line by item and period, so the app can open its source and build the spreadsheet formula) and, when it can't be computed, `value` None with a coded `missing` (`not_reported` with the items, or `base_not_positive` with the item and value). Notes are coded too (below). When a line it uses has `changed`, a `uses_changed_line` note says the ratio uses the latest value. The definitions reuse the valuation engine's own, so a student sees the same operating margin, D&A and debt that a run uses:

| Ratio | Formula | Reuses |
|---|---|---|
| Gross margin | (revenue − cost of revenue) ÷ revenue, on total revenue as tagged; the formula says that a company's own gross margin may use net sales (Walmart) or exclude a finance arm's revenue (Caterpillar), and that cost of revenue includes D&A for some companies | — |
| Operating margin | operating income ÷ revenue (`formula_id` `ebit_over_revenue`); when operating income isn't reported (JNJ, XOM), (pretax income + interest expense) ÷ revenue, with its own `formula_id` `pretax_plus_interest_over_revenue` and a note that this EBIT keeps other income such as interest and equity-company income, so a series can tell a definition change from a trend | `math_engine.CHAINS["ebit"]` (Build Plan D8, fallbacks) |
| Revenue growth, year on year | revenue ÷ revenue of the same fiscal period a year earlier − 1, both as known on `as_of`; the prior period's line is returned with its provenance, and coded notes when the two periods differ in length by 7 days or more (a 53-week year or a 14-week quarter, backlog #23), when the two use different XBRL tags, and when either is a derived quarter of mixed vintage | — |
| Capex share of revenue | capex ÷ revenue | `CHAINS["capex"]` |
| D&A share of revenue | D&A ÷ revenue, with the engine's fallback (depreciation + amortisation of intangibles) | `CHAINS["d_and_a"]` |
| Effective tax rate | income tax ÷ pretax income, with the engine's pretax fallbacks (domestic + foreign pretax; net income including minority interests + tax), each with its own `formula_id`; not clipped (the valuation clips to 0–50%, a reported rate is shown as it is); `None` when pretax income is at or below zero; on a quarter, a note that interim tax follows an estimated annual rate plus the quarter's one-off items (ASC 740-270) | `CHAINS["pretax"]`, `CHAINS["tax"]` |
| Net debt | debt (Build Plan D3: current and non-current debt, short-term borrowings or commercial paper, finance leases unless a debt tag includes them; operating leases excluded, their cost is in operating income) − (cash + marketable securities, current **and non-current**, + other short-term investments), at the period's end. As in the valuation (`History.latest_before`), a balance not dated at the period's end is carried from up to 370 days before (a `carried_forward` note names it and its date), and one older or absent counts as zero (`counted_as_zero` note); missing cash gives `None`. Negative means net cash (a `net_cash` note) | `math_engine.debt_parts` (renamed from `_debt`), `math_engine.CASH_ITEMS` (moved out of `_balance`) |

The divisions and the subtraction are new functions in `financial_math.py` (`ratio`, `growth`, `net_debt`), each raising `FinancialMathError` on a meaningless input instead of returning infinity, so every number still comes from that module.

**Net margin is left out** (analyst and professor review). The only net income the concept map stores is `ProfitLoss` (net income including minority interests and discontinued operations, `concept_map.csv`), which is not the textbook net margin (net income to the parent's shareholders; CFA Level I, Penman ch. 8), would be far off for Johnson & Johnson in 2023 (the Kenvue exit) and missing for Apple and Microsoft. It needs `NetIncomeLoss` in the concept map and a re-ingest: a follow-up backlog issue.

**Codes, not sentences** (front-end review). The app is Spanish first and keeps reader-facing text apart from logic (`docs/product/brief.md` §1, `design-principles.md`), so the engine owns no labels: every `missing`, note, warning and the as-reported note is `{code, params, text}`, where `text` is an English fallback. Company name, the fiscal-year end (MMDD) and `history_ends` (where a CIK's filings stop, from `universe.csv`) come with the answer.

**Warnings.** The facts query warns through Python's `warnings` (`universe.warn_if_beyond_history`); the call records them as `math_engine.build_inputs` does (`warnings.catch_warnings`) and returns each as a coded warning (`beyond_history` with `history_ends`, else `data_warning`).

**Output.** `ReportedPeriod.to_dict()` gives plain JSON types (dates as ISO text, numbers as unrounded floats), the shape the app reads. The prior year's revenue that growth uses is returned in `prior_lines` with the same provenance as a line. Nothing is stored: it is a query, so there is no migration and no stored number changes.

**Command.** `python -m domains.analysis reported --ticker AAPL --period latest-quarter --as-of 2026-11-02 [--period FY2024Q4 ...] [--json]` prints each period's lines, ratios and disagreements as text, or JSON with `--json`. Several `--period` flags answer Q2 (five fiscal years). `--as-of` is required here; defaulting to the latest ended day is #128 item 1.

## Steps

- **Step 0.** This design doc.
- **Step 1.** `financial_math.ratio`, `growth`, `net_debt`. Tests (`tests/analysis/test_financial_math.py`, properties): a zero or negative denominator raises; growth of x over x is 0; net debt is debt − cash for any non-negative pair and can be negative (net cash); arrays work as for the other functions.
- **Step 2.** `domains/analysis/reported.py`: `parse_period`, `latest_period`, `reported_period`, the dataclasses and `to_dict`. Tests (`tests/analysis/test_reported.py`, on the synthetic Test Corp of `tests/analysis/conftest.py`, whose ratios are known by construction): operating margin 20%, effective tax 25%, D&A 5%, capex 6% of revenue, growth 10% on FY2019 and on FY2019Q4 (a derived quarter, flagged with its input filings and their forms); net debt 140 with leases counted as zero; gross margin `None` with a coded gap (not reported); no net margin; a restated comparative (edited fixture) gives `changed` with both filings, and the first-reported value is the one public first; as-of one day before a 10-Q's filing date returns the previous quarter for `latest-quarter` and refuses the new one; a disagreement row appears on its period and not on another; operating margin through the pretax + interest fallback says so; `to_dict` round-trips through `json`; a negative pretax income gives a tax rate of `None`; quarters 7 days apart in length carry the note (analyst: 97 against 90 days); the first year has no growth.
- **Step 3.** The `reported` command. Tests (in `tests/analysis/test_reported.py`): text and `--json` outputs on Test Corp; an unknown period is an error that names the accepted forms; several periods in one call.
- **Step 4.** Real data: on the restored snapshot, Apple's fiscal Q4 2025 (derived, with its 10-K), Apple's 14-week quarter, Coca-Cola and P&G operating margins FY2021–FY2025, and a check that for each company's newest stored run, the operating margin, capex share, D&A share and effective tax rate of each of its three `history:` fiscal years (the reported annual values a run stores, `math_engine._history_rows`) equal the ratios this call returns for the same year and as-of date. Written below.

**Exit criterion:** all tests pass with the existing suite; the Step 4 checks agree with the stored runs; `docs/team-sync.md` names the call and its fields for the front-end team.

## Alternatives considered

- **Net margin on `ProfitLoss`, labelled "including minority interests".** Rejected: the name students read first would still differ from every textbook and data vendor, and discontinued operations would make it wrong for some years. Done properly in a follow-up.
- **Put it in `domains/fundamentals`.** That domain holds the facts and their selection, and is the natural home for the lines. But the ratios must reuse the valuation engine's EBIT, D&A, pretax and debt rules, which live in `domains/analysis/math_engine.py`; putting ratios in fundamentals would either copy those rules (two definitions that drift) or make fundamentals import analysis (a cycle). The lines use only `facts.py`, so the module sits in analysis, which already depends on fundamentals.
- **Read a stored run's `history:` rows.** Exists only for dates someone ran, holds three fiscal years of a few items, and no first-reported value. A query answers any period.
- **Revenue growth from one filing's two years** (`same_filing_annual_comparisons`, as the valuation's growth driver does), so both years sit on one restatement basis. Better for a trend, but it exists only for fiscal years and a 10-K's own comparative; a student asking "how much did revenue grow" expects the two figures on screen to be the ones the growth is computed from. Both figures shown here are the latest known; when either was changed after first report, the line's `changed` flag shows it.
- **Store the answers.** Nothing to reproduce: the query is deterministic on the stored facts and an as-of date.

## Files to change

New: `domains/analysis/reported.py`, `tests/analysis/test_reported.py`. Changed: `domains/analysis/financial_math.py`, `domains/analysis/math_engine.py` (`_debt` renamed `debt_parts`, `CASH_ITEMS` named; no rule changes), `domains/analysis/__main__.py`, `tests/analysis/test_financial_math.py`, `tests/analysis/test_financial_math_properties.py`, `docs/team-sync.md`, at merge `docs/versions.md`.

## Product impact

Serves brief Q1 (revenue for the last quarter, its 10-Q or 10-K, first-reported and latest, the derived fiscal Q4) and Q2 (operating margin by fiscal year with filings, the formula, the "as reported" note and the period ends side by side): both move from **En parte** to **Sí** once merged. The issue's net margin is not delivered (see above) and goes to a follow-up issue. For Q2's five years, the app asks five periods (`--period` repeats; `latest-year` names the newest); fiscal-year labels are the company's own. The `formula` text is in words; the front-end team builds the spreadsheet formula a student would type (design principle 5) from `uses`. Adds one call, `domains.analysis.reported.reported_period`, and one command, `reported`; their field names (below) are new and nothing existing is renamed or removed. Q3–Q15 are unaffected.

Fields (`to_dict`):

- top: `ticker`, `cik`, `company_name`, `fiscal_year_end` (MMDD), `history_ends`, `period` (`FY2025Q4`), `fiscal_year`, `fiscal_period`, `period_start`, `period_end`, `as_of`, `lines[]`, `prior_lines[]`, `ratios[]`, `disagreements[]`, `as_reported_note`, `warnings[]`;
- a line: `name`, `unit`, `period_start` (None for a balance), `period_end`, `fiscal_year`, `fiscal_period`, `value`, `latest` and `first_reported` (each a *version*), `changed`, `derived`, `mixed_vintage`;
- a version: `value`, `xbrl_concept` (for a derived value, the tags used, joined by " − "), `filed_at`, `filing` (a *filing*, or None when derived), `inputs[]` (the filings a derived value used);
- a filing: `accession_no`, `form`, `filed_at`, `url`;
- a ratio: `name`, `formula_id`, `formula`, `value`, `unit` (`fraction` or a currency), `uses[]` ({`line`, `period`}, plus `balance_date` for net debt), `missing` (a *coded*, or None), `notes[]` (coded);
- a disagreement: `name`, `period_start`, `period_end`, `selected` and `newest` (versions);
- a coded: `code`, `params`, `text` (English fallback). Codes: `as_reported`, `not_reported`, `base_not_positive`, `uses_changed_line`, `ebit_from_pretax_plus_interest`, `period_length_differs`, `tag_differs`, `mixed_vintage`, `interim_tax_rate`, `carried_forward`, `counted_as_zero`, `finance_leases_in_debt_tag`, `net_cash`, `beyond_history`, `data_warning`.

## Design review (nov.03.2026)

Explainer, analyst, professor and the front-end `product-lead` (on *Product impact*), in parallel. Analyst NO-GO on the first draft (4 blockers); professor 2 blockers; explainer 3; product lead 4. All accepted except where noted.

- **Analyst.** (1) The length note at "more than 7 days" never fires on a 53-week year or Apple's 14-week quarter (371 vs 364, 98 vs 91 days): now 7 days or more, with a test. (2) Net margin on `ProfitLoss` is wrong (minority interests, discontinued operations; JNJ 2023) and missing for AAPL and MSFT: dropped, follow-up issue. (3) Net debt at a quarter end counted absent items as zero, unlike the valuation, so a lease tagged only in the 10-K would swing it: now carried forward up to a year, as `_balance` does, and named. (4) Gross margin's base differs from the company's own for CAT and WMT: stated in the formula, no per-company rule. Ideas taken: the fallback EBIT has its own formula id and note; a note when the two years use different tags or a mixed-vintage derived quarter. Idea left for later: a note on Exxon's tax rate (it reports one including equity companies' taxes).
- **Professor.** (1) Net margin name (as analyst 2). (2) The doc's net debt left out non-current securities, which the code subtracts: fixed in the doc and the formula. Ideas taken: operating leases excluded and why, in the formula; interim tax note on quarters; net cash allowed and noted; a note when a ratio uses a changed line; cost of revenue and D&A in the gross-margin formula; the spreadsheet formula is the front-end's, from `uses`. Scope: the extra ratios stay, because issue #140 asks for them by name and they reuse engine definitions.
- **Explainer.** (1) Net debt's carry-forward and required cash (as analyst 3). (2) How warnings are captured: `catch_warnings`, now said. (3) The disagreement filter had no spec: now `_in_scope`, described above. Gaps answered: interest lines; cost of revenue is in the concept map; share lines are never derived; an unreported line is left out; the getters (`History.quarter`, `year`, `latest_before`); the tax fallbacks; which view feeds the prior year (the same view, latest); Step 4's years named; D3 and D8 are Build Plan decisions.
- **Product lead.** (1) Codes instead of English sentences: every missing value, note and warning is `{code, params, text}`. (2) The form type on every filing. (3) Nested shapes spelled out (Fields, above); `uses` names lines; the prior year's revenue in `prior_lines`. (4) Units and scaling stated. Ideas taken: company name, fiscal-year end, `history_ends`, the EDGAR folder link, unrounded floats. Left for the app: asking five periods for Q2 (no range form yet).

## Results (nov.03.2026)

On the restored snapshot of nov.03 (filings ingested to 2026-07-31; as-of 2026-11-02 unless said):

- **Match with the valuation.** For each company's newest stored run (seven on 2026-10-15, Exxon on 2025-12-01), the operating margin, capex share, D&A share and effective tax rate of each of its three history years equal this call's for the same year and as-of date: **96 of 96 equal** (to 1e-12).
- **Apple fiscal Q4 2025** (Q1 of the brief): revenue $102,466m, derived from the FY2025 10-K and the 10-Q of 2026-07-31 (which repeats the nine months as a comparative), both named with form, accession and link; operating margin 31.6%, growth 7.9%; net cash $32.5bn (non-current securities $77.7bn included).
- **Apple FY2024 Q1** (the 14-week quarter of FY2023 as base): growth 2.1% with the `period_length_differs` note (91 against 98 days).
- **Coca-Cola and P&G, FY2021–FY2025** (Q2 of the brief), each fiscal year with its own end (December and June): Coca-Cola 26.7%, 25.4%, 24.7%, 21.2%, 28.7%; P&G 23.6%, 22.2%, 22.1%, 22.1%, 24.3%. As reported: Coca-Cola's 2024 dip includes its one-off charges, which the as-reported note warns of.
- **Johnson & Johnson and Exxon** take the pretax + interest EBIT with its own formula id; Exxon's answer as of 2026-11-02 carries the `beyond_history` warning; Exxon has no gross margin (`not_reported`: cost_of_revenue).

## Where the work stopped

- nov.03.2026: Steps 0–4 done; PR next.
