# Backlog #540: J&J's cost of debt counts the interest it capitalises, and a trace line for a left-out figure

Issue: https://github.com/sonderbot-ar/warren/issues/540 (from the #533 review and gatekeeper) · Branch `backlog-540-jnj-capitalised-interest` · Version v0.10.34 when merged.

Status: In progress (nov.23.2026).

## Problem

#533 (v0.10.33) made ExxonMobil's cost of debt (D8: a fiscal year's interest over the average of its two year-end debts, `math_engine.cost_of_debt_year`) read interest incurred on debt: the expense, less interest the filing says is not on debt, plus the interest capitalised (ASC 835-20, IAS 23). Its review left three follow-ups:

1. **J&J and Apple** also tag something that looks like capitalised interest. Check each company's tag, its non-debt interest and its debt basis before extending the rule.
2. **A trace line** when `_incurred` leaves out a non-debt figure (below zero, or not below the interest) or a negative capitalised figure: today it is dropped without a word.
3. **The 10-K's own average rate beside D8**, as a plausibility check.

### What the filings say (company facts, nov.23.2026; 10-K annual figures, millions of US$)

**Apple: no change.** Apple's `InterestCostsIncurred` (2,200 to 3,700, FY2017 to FY2023, rounded to $0.1 billion) is not a capitalised amount: it is the interest it recognised on its term debt (the debt note), equal to its `InterestExpenseDebt` in every year both are filed (2,200, 3,000, 3,200, 2,800, 2,600 for FY2017 to FY2021). Apple tags no capitalised interest. Its D8 (interest expense over average debt, 2.29% to 3.37%) is unchanged.

**J&J: capitalised interest, filed every year.** J&J's income statement line is "Interest expense, net of portion capitalized" (FY2021 10-K, 0000200406-22-000022), and its property note says "The Company capitalizes interest expense as part of the cost of construction of facilities and equipment. Interest expense capitalized in fiscal years 2021, 2020 and 2019 was $49 million, $63 million and $70 million". It is tagged `us-gaap:InterestCostsCapitalized` in every 10-K, and cash paid before and after capitalising differ by exactly it (`InterestPaid` − `InterestPaidNet`: 904 − 841 = 63 in FY2020, 1,977 − 1,863 = 114 in FY2025). J&J tags no `InterestPaidCapitalized` and no `InterestExpenseOther`. Its debt in Warren is long-term debt plus loans and notes payable (`debt_noncurrent`, `short_term_borrowings`); it counts no finance-lease liability and J&J tags no finance-lease interest, so the capitalised interest (on borrowings, ASC 835-20-30-2) is on the same basis as the debt it is divided by.

| FY | Interest expense | Capitalised | Average debt | D8 today | Expense + capitalised | J&J's own weighted average effective rate on long-term debt, year end (`DebtInstrumentInterestRateEffectivePercentage`) |
|---|---|---|---|---|---|---|
| 2017 | 934 | 94 | 30,854 | 3.03% | 3.33% | 3.19% |
| 2018 | 1,005 | 86 | 32,531 | 3.09% | 3.35% | 3.19% |
| 2019 | 318 | 70 | 29,088 | 1.09% | 1.33% | 3.19% |
| 2020 | 201 | 63 | 31,481 | 0.64% | 0.84% | 2.85% |
| 2021 | 183 | 49 | 34,508 | 0.53% | 0.67% | 2.89% |
| 2022 | 276 | 49 | 36,697 | 0.75% | 0.89% | 3.04% |
| 2023 | 772 | 70 | 34,487 | 2.24% | 2.44% | 2.98% |
| 2024 | 755 | 79 | 32,983 | 2.29% | 2.53% | 3.36% |
| 2025 | 971 | 114 | 42,284 | 2.30% | 2.57% | not tagged |

(Average debt and D8 today: `cost_of_debt_year` through today's map as known on 2026-10-30, in memory. FY2017 and FY2018 from the first 10-K that reported them.)

**The bigger gap at J&J is not capitalising: it is hedge accounting.** From FY2019 J&J's interest line collapses (1,005 → 318) while its debt and its filed effective rate do not. The FY2021 10-K says why: for its cross-currency swaps designated as net investment hedges, "the portion excluded from effectiveness testing is recorded through interest (income) expense using the spot method" (ASU 2017-12, adopted 2019), and gains on cross-currency swaps designated as cash flow hedges are reclassified from other comprehensive income into interest (income) expense. Its derivatives table puts 174M (FY2021) and 153M (FY2020) of excluded-component gains, and 402M and 370M of cash-flow-hedge gains, in that line. So J&J's interest expense is net of about half a billion dollars a year of swap gains: in effect J&J borrows in dollars and swaps part of the debt into lower-rate currencies, and the line shows the swapped cost. For a valuation in dollars that carry is not a cheaper cost of borrowing: the discount rate must be in the cash flows' currency (Koller et al., *Valuation*; Damodaran), and the hedge's counterpart sits in the currency translation adjustment in other comprehensive income (ASC 815-35), not in the interest line's economics. Those amounts are tagged only with a dimension (the income-statement line), which the SEC's company facts file leaves out, so Warren cannot read them through its source today.

So adding J&J's capitalised interest is right (it is interest incurred on J&J's debt, ASC 835-20, the same principle as #533), but it closes only 0.1 to 0.3 points of a gap of up to 2.4 points in FY2019 to FY2022 and 0.7 to 1.1 points in FY2023 and FY2024 (FY2025's filed rate is not tagged yet). The rest needs either the swap amounts (a dimensional-facts source) or a different method (the company's filed effective rate, or a market rate): the first is a data source question, the second would change D8's method ("cost of debt from interest expense over average debt", `docs/build-plan.md` line 196, an M2 decision), which needs an owner card. This item does neither; both are filed with this evidence (Follow-ups, below). After this merge J&J's cost of debt is still understated in FY2019 to FY2025, and the desk entry says so.

## Plan

**Step 0. This doc.**

**Step 1. J&J joins the interest-incurred rule; a trace line for a left-out figure.**

- Map: `interest_capitalized`'s two rows (`InterestPaidCapitalized` priority 1, `InterestCostsCapitalized` priority 2) widen from `XOM` to `JNJ;XOM`. J&J files only the second today; if it ever files the cash-flow statement's figure, it is the same amount by meaning (as at Exxon). `interest_not_on_debt` stays XOM only: J&J tags none. Notes say why, with the filings. Map copy `concept_maps/<sha>.csv` and its `CHANGES.md` line.
- `math_engine._incurred` is unchanged for a used figure. When it leaves one out, the method text says so, with the fact's trace: `<method> (interest not on debt left out, below zero: <trace>)`, `(… not below the interest: <trace>)`, `(interest capitalised left out, below zero: <trace>)`. A left-out fact is not added to the row's facts (its sources stay the figures used). Docstrings of `CAPITALISED`, `_incurred` and `d8_interest` name J&J.
- `reading_rules.md` row and `READING_RULES_VERSION` 14 → 15 (a fresh J&J run reads a different figure).
- Tests (`tests/analysis/test_capitalised_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped map scopes both capitalised rows to `{JNJ, XOM}` and the non-debt row to `{XOM}`; `extract_facts` keeps `InterestCostsCapitalized` for JNJ and XOM and skips it for the other six, and keeps `InterestExpenseOther` for XOM only; J&J's FY2021 figures give (183 + 49) / 34,508 = 0.67%; J&J's FY2025 (971 + 114) / 42,284 = 2.57%; each left-out case names the figure and the reason in the method and keeps it out of the facts; a used figure's method is unchanged; Exxon's, Microsoft's and Walmart's cases unchanged.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot (`warren-20261122T203459Z`): `reproduce --all` and `--rebuild` before; `fundamentals ingest --all` (only J&J should gain facts); `fundamentals report --all`; `reproduce --all` and `--rebuild` after, with as many identical rebuilds as before. Then every stored run date built fresh in memory through main's map and the new one, with the same pinned market data and choices, none stored; list cost of debt, WACC, value per share and `below_risk_free` by year. Exit: only J&J moves, only its `cost_of_debt` row and what follows (WACC, value per share); no run note added or removed except `below_risk_free`, listed. Check that no fresh run's method gains a "left out" clause (Exxon's only left-out figure is FY2013's −123M, older than any run's cost-of-debt year). Save a snapshot.

## Results (Step 2, nov.23.2026)

On the restored snapshot `warren-20261122T203459Z`.

- **Before anything changed.** `reproduce --all`: 909 of 909 stored runs reproduced to the cent; `--rebuild`: 698 of 909 rebuilt to identical rows.
- **Ingest.** `fundamentals ingest --all`: J&J gains 48 facts (`InterestCostsCapitalized`, years and quarters, every filing's version); no other company gains any. `fundamentals report --all`: 0 unexplained gaps for all eight companies.
- **Stored runs after the ingest.** 909 of 909 reproduced to the cent; 698 of 909 rebuilt to identical rows, the same as before.
- **Fresh runs.** Every stored run date (899 company-dates) built twice in memory with today's code, pinned market data and choices, through #533's map (`e43ad83d2331`) and the new one (`43fc39b6929e`); none stored, none refused. **The other seven companies do not move (784 dates, 0 moved, no method text changed).** J&J moves on all 115 of its dates, and on each only the `cost_of_debt` row; no run note is added or removed:

| Runs dated | Moved | Cost of debt (last run of the year) | WACC | Value per share (range over the year's runs; last run) |
|---|---|---|---|---|
| 2019 | 12 of 12 | 3.09% → 3.35% (FY2018) | 4.81% → 4.83% | −0.30% to −0.39%; $164.19 → $163.61 |
| 2020 | 14 of 14 | 1.09% → 1.33% (FY2019) | 3.73% → 3.75% | −0.31% to −0.52%; $190.63 → $189.71 |
| 2021 | 16 of 16 | 0.64% → 0.84% (FY2020) | 4.29% → 4.31% | −0.26% to −0.44%; $177.56 → $177.04 |
| 2022 | 15 of 15 | 0.53% → 0.67% (FY2021) | 6.25% → 6.26% | −0.12% to −0.27%; $156.82 → $156.62 |
| 2023 | 14 of 14 | 0.75% → 0.89% (FY2022) | 6.74% → 6.75% | −0.12% to −0.25%; $156.69 → $156.50 |
| 2024 | 14 of 14 | 2.24% → 2.44% (FY2023) | 6.51% → 6.53% | −0.12% to −0.29%; $150.50 → $150.13 |
| 2025 | 14 of 14 | 2.29% → 2.53% (FY2024) | 6.16% → 6.18% | −0.22% to −0.39%; $136.43 → $136.04 |
| 2026 | 16 of 16 | 2.30% → 2.57% (FY2025) | 6.63% → 6.64% | −0.23% to −0.35%; $168.53 → $168.15 |

  `below_risk_free` neither starts nor stops on any J&J run or chart year: FY2018 was above that year's average 10-year yield (2.91%) before and after, and FY2019 to FY2025 stay below theirs (2.14%, 0.89%, 1.45%, 2.95%, 3.96%, 4.21%, 4.29%). So a debt what-if on a J&J run floors at the risk-free rate as before. No fresh run's cost-of-debt method gains a "left out" clause: the only stored figure below zero or not below the interest is Exxon's FY2013 non-debt −123M, older than any run's cost-of-debt year. Revenue and EBIT forecasts do not read the cost of debt, so no forecast-error score moves.
- Snapshot `warren-20261123T003850Z` saved after the ingest.

## Alternatives considered

- **J&J's cash paid before capitalising (`InterestPaid`), as #527 did for Microsoft.** It tracks J&J's filed rate in FY2019 to FY2022 (2.7% to 3.4%), but jumps to 4.7% to 6.0% in FY2023 to FY2025 (1,836 to 1,990 paid on about 33 to 42 billion of debt), above every rate in J&J's debt table. The likelier cause (analyst) is borrowing during the year that the two year-end balances miss (the Shockwave deal, May 2024, and Intra-Cellular, April 2025, financed with commercial paper and new debt; 6.5 billion of paper at the FY2025 year end), and cash paid is gross of the swap gains. Either way, a cash figure over a year-end average that fits some years and not others mixes bases. Rejected.
- **J&J's filed weighted average effective rate as its cost of debt.** Closest to the debt table by construction, but it is a year-end rate on long-term debt only (no commercial paper), not tagged for FY2025, and it changes D8's method (`docs/build-plan.md` line 196). Owner decision; filed as a follow-up with this evidence, not done here.
- **Add back the swap gains.** The right accrual fix, but the amounts are tagged only with a dimension that the company facts file drops. Needs a source for dimensional facts (the SEC's Financial Statement and Notes data sets, scout issue #536, are the free candidate). Follow-up.
- **Leave J&J alone until the hedge question is settled.** Keeps a figure Warren knows leaves out interest J&J incurred and filed. Adding it is right on its own and does not stand in the way of either fix.
- **Item 3 (the 10-K's average rate beside D8) in this item.** Only three of the eight companies tag a long-term rate without a dimension (J&J's effective rate, Coca-Cola's and P&G's `LongtermDebtWeightedAverageInterestRate`); Exxon's 3.43% is dimensional. It needs pure-unit map items, a new run note with its lesson and a front-end label. Its own track, with J&J as its first case; filed as a follow-up.

## Files to change

`domains/fundamentals/concept_map.csv`, `domains/fundamentals/concept_maps/<sha>.csv` and `CHANGES.md`, `domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md`, `domains/analysis/reading_rules.py` (version 15), `tests/analysis/test_capitalised_interest.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` is unchanged (no milestone). `docs/structure-guide.md` and `docs/build-plan.md` line 196 are unchanged: D8's method (interest over average book debt) is the same; only which filed lines make up J&J's interest, as in #497, #527 and #533.

## Product impact

J&J is in brief Q3, Q4, Q7, Q8 and Q9's kinds of screen (value per share, WACC and its parts, a rate shock, a margin what-if, the sensitivity grid) once a student can pick it. A fresh J&J run's cost-of-debt row reads interest incurred, slightly higher (FY2025 2.30% → 2.57%); WACC moves by a few basis points at most (J&J's debt is a small part of its capital) and value per share slightly down. No new part code: J&J's cost-of-debt chart gains the existing `interest_capitalized` part ("intereses capitalizados", team-sync's v0.10.33 entry), and J&J's reported view (Q1 and Q2 shapes, brief lines 54 and 60) gains it as a line, since it lists every mapped item. `below_risk_free` neither starts nor stops on any J&J run or chart year (Step 2). WACC moves by 1 to 2 basis points and value per share by −0.1% to −0.5% (newest run $168.53 → $168.15). Stored runs keep their rows. The version goes to 15 for every company's fresh runs, so beside a stored run of the same date under 14 any company (not only J&J) shows the "reading rules changed" note (brief line 107) though only J&J's values differ, or the "either NULL" case (line 108) for runs with no recorded rules. The trace line adds English text to a row's method only when a figure is left out; no code, param or output is added, renamed or removed. Not fixed and worth a sentence in the app's *Fuente* tab one day: J&J's interest line is net of swap gains since 2019, so its book cost of debt reads below its debt table's rates.

## Follow-ups

- #542: J&J's interest line is net of cross-currency swap gains since FY2019 (the add-back via dimensional facts, scout #536; or the filed or a market rate, an owner card first; at least a J&J sentence beside `below_risk_free`).
- #543: item 3, a plausibility check against the company's own filed average rate on its debt.

## Design review (nov.23.2026)

- **Analyst, GO, no blockers.** J&J's capitalised interest is on the same debt and the line is net of it (FY2025 10-K 0000200406-26-000016: 114, 79 and 70M for FY2025 to FY2023; no restatements across filings; no finance-lease tags; `InterestPaid` − `InterestPaidNet` = capitalised); no non-debt interest (interest on tax positions sits in the tax provision); the swap claim checked in the derivatives tables (FY2024 148 + 247, FY2025 193 + 326); Apple confirmed; no silent wrong number (the `interest_paid` fallback returns first; FY2023 continuing operations exclude Kenvue's interest and debt). Taken: the reason for rejecting cash paid reworded (borrowing within the year). Ideas filed in #542: a J&J sentence beside `below_risk_free`, and checking whether the cash-flow-hedge reclass is partly offset before any add-back. Noted, not acted on: FY2023's 70M may hold some Kenvue capitalised interest before the split; small, not broken out.
- **Professor, GO, no blockers.** ASC 835-20, IAS 23 and Kieso et al. support expensed + capitalised; a dollar cost of debt excludes the swap carry (Koller et al.; Damodaran). Taken: D8's method cited at `docs/build-plan.md` line 196, not the Structure Guide; "pay for taking currency risk" reworded (a net investment hedge reduces an existing exposure, ASC 815-35); a Follow-ups section with issue numbers; the follow-up says J&J stays understated. Ideas (student app): a *Fuente* note on hedge-netted interest; a lesson on book vs filed vs market cost of debt with J&J FY2021.
- **Explainer.** Fourteen gaps. Taken: the FY2023 to FY2025 gap stated from the table (0.7 to 1.1 points, FY2025 untagged), the cash-paid rates sourced. The rest are terms defined in #533's doc, `CLAUDE.md` and the linked files (priority, map copies named by SHA-256, `reproduce --rebuild`, `below_risk_free`, the snapshot commands), which a reader of those files has.
- **Product lead, two blockers, taken.** The version change affects every company's fresh runs beside a stored run under 14 (brief line 107), not only J&J's; said now. J&J's reported view gains the line; Step 2 lists `below_risk_free` by J&J year. Ideas for the front-end team: add `interest_capitalized` and `interest_not_on_debt` to the brief's catalogue and update brief line 106's reading-rules number; a Spanish *Fuente* sentence on J&J's hedge-netted interest.
