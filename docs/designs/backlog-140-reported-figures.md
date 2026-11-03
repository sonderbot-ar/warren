# Backlog #140: reported figures and named ratios, with provenance (front-end R1)

Status: In progress (nov.03.2026) · Elephant: agent team · Branch `backlog-140-reported-figures`
Serves brief questions 1 and 2 (`docs/product/brief.md` §3) and F2's first screen. Takes over #128 item 2.

## Problem

Every number on a student's screen must come from the engine and show its source (Decision 13). The facts have been stored point in time with their filing since M1 (`financial_facts`), and `domains/fundamentals/facts.py` can select them, but no call or command returns one period's figures with their provenance, and no ratio exists outside a valuation run, where it is a three-year driver, not a period's figure. So the app can't answer "how much did Apple sell last quarter, and from which filing?" (Q1) or "how has Coca-Cola's operating margin moved against P&G's?" (Q2) without computing something itself, which the brief forbids.

## What the call returns

`reported.reported_period(conn, ticker, period, as_of) -> ReportedPeriod` in a new module `domains/analysis/reported.py`, where `period` is a fiscal quarter (`FY2025Q4`) or a fiscal year (`FY2025`), and the words `latest-quarter` / `latest-year` resolve to the newest period with revenue reported by `as_of`. Fiscal years and quarters are the company's own labels from its filing calendar (M1); the period's start and end dates are always returned, so Coca-Cola's FY2025 (to December) and P&G's FY2025 (to June) are never silently aligned.

Everything is as known on `as_of` (inclusive): the facts query takes only rows filed on or before it (`facts.QUERY`, `f.filed_at <= ?`), exactly as a valuation run does. A period not reported by `as_of` is an error that says so, never an empty answer.

**Lines.** One per item of the concept map that the period reports (revenue, cost of revenue, operating income, pretax income, tax, net income including minority interests, interest, D&A, capex, the balance-sheet items, shares). Each line has:

- the **latest** value known on `as_of` (`get_facts(..., mode="latest")`), with its XBRL tag, accession, period start and end, fiscal labels, filing date and unit (currency stated, Decision 11 guardrail 3);
- the **first-reported** value (`mode="first_reported"`), with its own tag, accession and filing date, and `changed` when the two differ. The engine says *that* it changed, not why (brief Q1);
- `derived` with its input filings when Warren computed it (Apple's fiscal Q4 = the 10-K year minus nine months; a cash-flow Q2 or Q3 from year-to-date figures; `facts._derive`), and `mixed_vintage` when a derivation mixes restated and first-reported inputs.

Flows use the quarterly view for a quarter and the annual view for a year (`get_facts(frequency=...)`); balance-sheet items are the balance at the period's end (Q4 and FY: the year-end balance).

**Newest filing disagrees.** The quality report's rows (`facts.newest_filing_disagreements`) for that company and period: for a reported line, its own period; for a derived line, the periods of the same fiscal year ending on or before its end (the periods a derivation can be built from). They are informational, as in the quality report.

**Named ratios.** Computed by the engine, never by the app, from the latest lines, "as reported" (one-off charges included, and the output says so). Each ratio carries its value, its formula in words, the lines it used (so each traces to filings) and, when it can't be computed, `None` with the reason (an item not reported, or a denominator at or below zero). The definitions reuse the valuation engine's own, so a student sees the same operating margin, D&A and debt that a run uses:

| Ratio | Formula | Reuses |
|---|---|---|
| Gross margin | (revenue − cost of revenue) ÷ revenue | — |
| Operating margin | EBIT ÷ revenue; EBIT is operating income, or pretax income + interest when operating income isn't reported, and the formula says which | `math_engine.CHAINS["ebit"]` (D8) |
| Net margin | net income including minority interests ÷ revenue (the only net income the concept map stores; said in the formula) | — |
| Revenue growth, year on year | revenue ÷ revenue of the same fiscal period a year earlier − 1, both as known on `as_of`; the prior period's line is returned with its provenance, and a note when the two periods differ in length by more than 7 days (a 53-week year, backlog #23) | — |
| Capex share of revenue | capex ÷ revenue | `CHAINS["capex"]` |
| D&A share of revenue | D&A ÷ revenue, with the engine's fallback (depreciation + amortisation of intangibles) | `CHAINS["d_and_a"]` |
| Effective tax rate | income tax ÷ pretax income, with the engine's pretax fallbacks; not clipped (the valuation clips to 0–50%, a reported rate is shown as it is); `None` when pretax income is at or below zero | `CHAINS["pretax"]`, `CHAINS["tax"]` |
| Net debt | debt (D3: current and non-current debt, short-term borrowings or commercial paper, finance leases unless a debt tag includes them) − (cash + marketable securities + other short-term investments), at the period's end; items not reported there count as zero and are named | `math_engine._debt`, the cash items of `_balance` |

The divisions and the subtraction are new functions in `financial_math.py` (`ratio`, `growth`, `net_debt`), each raising `FinancialMathError` on a meaningless input instead of returning infinity, so every number still comes from that module.

**Warnings.** Anything the facts query warns about (a date beyond a company's history, as for Exxon after 2026-08-03) is returned in `warnings`, as a run does.

**Output.** `ReportedPeriod.to_dict()` gives plain JSON types (dates as ISO text, numbers as floats), the shape the app reads. Nothing is stored: it is a query, so there is no migration and no stored number changes.

**Command.** `python -m domains.analysis reported --ticker AAPL --period latest-quarter --as-of 2026-11-02 [--period FY2024Q4 ...] [--json]` prints each period's lines, ratios and disagreements as text, or JSON with `--json`. Several `--period` flags answer Q2 (five fiscal years). `--as-of` is required here; defaulting to the latest ended day is #128 item 1.

## Steps

- **Step 0.** This design doc.
- **Step 1.** `financial_math.ratio`, `growth`, `net_debt`. Tests (`tests/analysis/test_financial_math.py`, properties): a zero or negative denominator raises; growth of x over x is 0; net debt is debt − cash for any non-negative pair; arrays work as for the other functions.
- **Step 2.** `domains/analysis/reported.py`: `parse_period`, `latest_period`, `reported_period`, the dataclasses and `to_dict`. Tests (`tests/analysis/test_reported.py`, on the synthetic Test Corp of `tests/analysis/conftest.py`, whose ratios are known by construction): operating margin 20%, effective tax 25%, D&A 5%, capex 6% of revenue, growth 10% on FY2019 and on FY2019Q4 (a derived quarter, flagged with its two input filings); net debt 140; gross and net margin `None` with the reason (not reported); a restated comparative (edited fixture) gives `changed` with both filings, and the first-reported value is the one public first; as-of one day before a 10-Q's filing date returns the previous quarter for `latest-quarter` and refuses the new one; a disagreement row appears on its period and not on another; operating margin through the pretax + interest fallback says so; `to_dict` round-trips through `json`; a negative pretax income gives a tax rate of `None`.
- **Step 3.** The `reported` command. Tests (`tests/analysis/test_report_cli.py` style): text and `--json` outputs on Test Corp; an unknown period is an error that names the accepted forms; several periods in one call.
- **Step 4.** Real data: on the restored snapshot, Apple's latest quarter (a derived fiscal Q4 with its 10-K), Coca-Cola and P&G operating margins FY2021–FY2025, and a check that the operating margin, D&A and capex shares of three fiscal years match the ratios a stored run's `history:` rows give for the same years. Written below.

**Exit criterion:** all tests pass with the existing suite; the Step 4 checks agree with the stored runs; `docs/team-sync.md` names the call and its fields for the front-end team.

## Alternatives considered

- **Put it in `domains/fundamentals`.** That domain holds the facts and their selection, and is the natural home for the lines. But the ratios must reuse the valuation engine's EBIT, D&A, pretax and debt rules, which live in `domains/analysis/math_engine.py`; putting ratios in fundamentals would either copy those rules (two definitions that drift) or make fundamentals import analysis (a cycle). The lines use only `facts.py`, so the module sits in analysis, which already depends on fundamentals.
- **Read a stored run's `history:` rows.** Exists only for dates someone ran, holds three fiscal years of a few items, and no first-reported value. A query answers any period.
- **Revenue growth from one filing's two years** (`same_filing_annual_comparisons`, as the valuation's growth driver does), so both years sit on one restatement basis. Better for a trend, but it exists only for fiscal years and a 10-K's own comparative; a student asking "how much did revenue grow" expects the two figures on screen to be the ones the growth is computed from. Both figures shown here are the latest known; when either was changed after first report, the line's `changed` flag shows it.
- **Store the answers.** Nothing to reproduce: the query is deterministic on the stored facts and an as-of date.

## Files to change

New: `domains/analysis/reported.py`, `tests/analysis/test_reported.py`. Changed: `domains/analysis/financial_math.py`, `domains/analysis/__main__.py`, `tests/analysis/test_financial_math.py`, `docs/team-sync.md`, at merge `docs/versions.md`.

## Product impact

Serves brief Q1 (revenue for the last quarter, its filing, first-reported and latest, the derived fiscal Q4) and Q2 (operating margin by fiscal year with filings, the formula, the "as reported" note and the period ends side by side): both move from **En parte** to **Sí** once merged. Adds one call, `domains.analysis.reported.reported_period`, and one command, `reported`; their field names (below) are new and nothing existing is renamed or removed. Q3–Q15 are unaffected.

Fields: `ticker`, `cik`, `period` (`FY2025Q4`), `fiscal_year`, `fiscal_period`, `period_start`, `period_end`, `as_of`, `lines[]` (`name`, `value`, `unit`, `xbrl_concept`, `accession_no`, `filed_at`, `period_start`, `period_end`, `derived`, `inputs`, `mixed_vintage`, `first_reported` {`value`, `xbrl_concept`, `accession_no`, `filed_at`}, `changed`), `ratios[]` (`name`, `value`, `unit`, `formula`, `uses`, `missing_reason`, `note`), `disagreements[]` (`name`, `period_start`, `period_end`, `selected` {…}, `newest` {…}), `as_reported_note`, `warnings`.
