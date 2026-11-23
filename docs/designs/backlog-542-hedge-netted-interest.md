# Backlog #542: a coded note when J&J's interest is net of swap gains

Issue: https://github.com/sonderbot-ar/warren/issues/542 (from the #540 review; front-end ask in its first comment) · Branch `backlog-542-hedge-netted-interest` · Version v0.10.35 when merged.

Status: Done (nov.23.2026), v0.10.35, merge `bbe95f6` (PR #547).

## Problem

Since FY2018 Johnson & Johnson books what its cross-currency swaps earn inside "Interest (income) expense": the net-investment-hedge component excluded from effectiveness testing (spot method under ASU 2017-12, which J&J early adopted from its fiscal second quarter of 2018, FY2018 10-K 0000200406-19-000009) and the cash-flow-hedge gains reclassified out of other comprehensive income (derivatives tables, net of tax: 56 + 133 FY2018, 153 + 370 FY2020, 174 + 402 FY2021, 148 + 247 FY2024, 193 + 326 FY2025, millions; 0000200406-19-000009, 0000200406-22-000022, 0000200406-26-000016). FY2017 already carries 83M of cash-flow-hedge gains, smaller and before the spot method. So the interest Warren divides by its debt (D8, `math_engine.cost_of_debt_year`) is net of roughly 0.2 to 0.6 billion dollars a year after tax (more before tax), and J&J's cost of debt reads 0.67% to 1.33% in FY2019 to FY2022 and about 2.4% to 2.6% in FY2023 to FY2025, against the 2.85% to 3.36% weighted average effective rate J&J states on its long-term debt (`us-gaap:DebtInstrumentInterestRateEffectivePercentage`, see the table in `docs/designs/backlog-540-jnj-capitalised-interest.md`).

Today a student who opens J&J's cost-of-debt chart sees about 2.5% and, below the Treasury yield, the generic `below_risk_free` note: "the average rate on debt raised in past years, often when rates were lower … so it is common, not a mistake". For J&J that points at the wrong cause. The front-end team keeps J&J's cost of debt off screen until the engine says so in a coded note (#542, first comment): a note on the cost-of-debt figure, with J&J's filed effective rate (its filing and period) and the years affected, and `below_risk_free`'s generic sentence not shown beside it.

This item is option 3 of #542: say it, with the evidence. It does not change any number. Options 1 (add the swap gains back, which needs dimensional facts, scout #536) and 2 (use the filed or a market rate, which changes D8's method, an owner decision) stay open on #542.

## Plan

**Step 0. This doc.**

**Step 1. J&J's filed effective rate, read as a reported-only figure.**

- `concepts.UNITS` gains `pure` (and `domains/analysis/reading_rules.md` logs the loader's new fingerprint under version 15: no run reads a different figure) (a ratio, 0.0319 = 3.19%; the unit company facts file it under).
- `concept_map_reported.csv` (the file no valuation reads; outside the map fingerprint runs store, #157) gains `debt_effective_rate`, `us-gaap:DebtInstrumentInterestRateEffectivePercentage`, priority 1, `pure`, `instant`, `optional`, companies `JNJ`. J&J files one undimensioned value per year end in every 10-K from FY2011 to FY2024: the debt note's "Weighted average effective rate" on its long-term debt subtotal, built from each note's own effective rate (coupon adjusted for discount and issue cost), so without the swaps (analyst). Its FY2025 10-K (0000200406-26-000016, Note 7) no longer states the rate at all. Other companies tag it per instrument or with a dimension the facts file drops (#540 doc, item 3), so a figure read for them would be one bond's rate, not the total: JNJ only, and widening it needs that company's filings checked first.
- No stored run moves: the valuation map and its fingerprint are untouched, and `test_no_valuation_or_scoring_step_reads_a_reported_only_item` already guarantees no valuation, score or AI step reads the item.
- J&J's reported view (it lists every mapped item) gains a `debt_effective_rate` line with unit `pure` at each year end.
- Tests (`tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped map has the row scoped to `{JNJ}` with unit `pure`; `load_concept_map` accepts `pure` and still refuses an unknown unit; `extract_facts` keeps a `pure` fact for JNJ and skips it (company scope) for another ticker.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Companies as data: which company's interest is net of what, from which year.**

- New `domains/analysis/interest_caveats.csv` (Decision 11, companies as data): `ticker`, `code`, `from_fiscal_year`, `to_fiscal_year` (empty: still true in the newest filing), `rate_item` (the reported-only item holding the company's own filed rate, or empty), `evidence` (filings and pages a reader can check), `note`. One row: `JNJ`, `interest_net_of_hedge_gains`, 2018, empty, `debt_effective_rate`, the FY2018, FY2019, FY2021 and FY2025 10-Ks' derivatives tables.
- `domains/analysis/interest_caveats.py`: `load_interest_caveats(path=None)` validates the file and reports every problem at once (unknown ticker against the universe, code outside the closed set `CAVEAT_CODES = ("interest_net_of_hedge_gains",)`, years not integers or `to` before `from`, a `rate_item` not in the reported map, two rows for one ticker and code that overlap); `caveat_for(ticker, fiscal_year)` returns the row covering that year or None.
- Tests (`tests/analysis/test_interest_caveats.py`): the shipped file loads and has exactly the J&J row; each validation error is reported with its line; `caveat_for` covers FY2018 and FY2025 for JNJ, not FY2017, and nothing for another ticker.
- Exit: CI green.

**Step 3. The note on the cost-of-debt chart and cell.**

- `single_values.POINT_NOTES` and `CELL_NOTES` gain `interest_net_of_hedge_gains`. On the cost-of-debt chart (`_cost_of_debt`), each computed year a caveat row covers gets the point note, with params:
  - `fiscal_year`, `from_fiscal_year`, `to_fiscal_year` (the years affected; `to` null while open);
  - `cost_of_debt`: the point's value; on the run's own year the run's row, as `below_risk_free` compares (product lead: a stored run's row can differ from today's read, `run_read_differently`);
  - `effective_rate` (a fraction; the app formats it), `effective_rate_period` (ISO date), `effective_rate_fiscal_year`, `effective_rate_older`, `effective_rate_filing` (the same shape as a part's `filing`, `inputs._filing`): the company's stated rate at that year's end as known on the run's `as_of` (the newest filing's version, so a restatement filed by `as_of` replaces the first figure); when that year end has none, the rate at an earlier year end at most one fiscal year older (`RATE_MAX_YEARS_OLDER`), with `effective_rate_older` true (FY2025 shows FY2024's 3.36%, `effective_rate_fiscal_year` 2024); all null when there is none, so a company that stops stating the rate never shows an old one for good (analyst: J&J's 2025 notes at 4.50% to 4.90% likely raised the true rate by about 0.25 points, so even one year is flagged);
  - `below_effective_rate`: whether the cost of debt shown is below that rate (null without a rate), so the app compares nothing itself (product lead);
  - `below_risk_free`: null, or the params `below_risk_free` would have had (`cost_of_debt`, `risk_free`, `risk_free_date`, `against`, …), so the app can still say the figure is below the Treasury yield.
- On such a point `below_risk_free` is not added on its own (the front-end's ask): its comparison moves inside the new note's `below_risk_free` param. Years outside the caveat keep `below_risk_free` as today.
- The cell: when the run's own cost-of-debt year (its interest source's fiscal year) is covered, the cost-of-debt cell carries the same note with the used point's params, so a screen that shows only the run's figure has it too. A what-if child whose cost of debt is floored at the risk-free rate (`floored_at_risk_free`) carries no hedge note on the cell: its value is not the book figure.
- Point-in-time: the rate is read with `get_facts(conn, cik, ["debt_effective_rate"], as_of)`; the years come from the data file, and a point exists only for a year whose filings are known on `as_of`, so a note never cites a filing after `as_of`. The note's filing is the rate's own 10-K.
- English fallback text, built from the params (professor's framing: the swaps turn dollar debt into lower-rate foreign-currency debt, so the issue is a foreign rate inside a dollar WACC): "the interest expense is net of what the company's currency swaps earn (booked in its interest line since FY2018): the swaps turn part of its dollar debt into lower-rate foreign-currency debt, so this cost of debt (2.30%) reads below the 3.36% weighted average effective rate it states on its long-term debt (at the 2024-12-29 year end, a year older, the newest it states; long-term debt only); a valuation in dollars needs a dollar cost of debt, and Warren cannot yet separate the two".
- A what-if child's chart points are book years and keep the note; only a floored child's cell does not.
- `test_no_valuation_or_scoring_step_reads_a_reported_only_item` stays as it is: a display read in `single_values` is allowed (as `debt_fair_value`'s, #481); no valuation, score or AI step reads the item.
- Tests (`tests/analysis/test_single_values.py`, Test Corp with a caveat row for TST injected): every covered year's point has the note (Test Corp's conftest files a `…Percentage` tag as `pure`) and no separate `below_risk_free`; the note carries the year's own filed rate, or the newest earlier one with its period, or null; a rate filed after `as_of` is never read; the `below_risk_free` param is filled when the point is below the yield and null when not; years before `from_fiscal_year` keep `below_risk_free` and get no hedge note; the cell carries the note when the used year is covered and not otherwise; a floored what-if child's cell has no hedge note; every code stays inside the closed lists. Without a caveat row, every chart and cell is identical to today's.
- Exit: CI green.

**Step 4. Real data.** On the restored snapshot (`warren-20261123T003850Z`): `reproduce --all` before; `fundamentals ingest --all` (only J&J should gain facts, the `debt_effective_rate` ones); `fundamentals report --all` (0 unexplained gaps); `reproduce --all` after, same count. Then the inputs behind the newest J&J run and one run per year from 2020: list each cost-of-debt year with its note and rate, and check no other company's chart gains or loses a note. Save a snapshot.

## Alternatives considered

- **A run note, fixed when a run is stored.** Run notes are written at build time, so only fresh runs would carry it, and stored J&J runs (every one of them reads the same netted line) would stay silent; it would also change what a rebuild compares. The chart and cell notes are read when an answer is built, so every J&J run, stored or fresh, says it. Rejected.
- **Hard-code J&J in `single_values.py`.** Breaks Decision 11 (companies as data). Rejected for the CSV.
- **Write J&J's filed rates into the data file by hand.** A number typed by hand has no filing date, so it cannot be read point-in-time, and it would be wrong the day J&J restates. Rejected for the reported-only map item, read like every other filed figure.
- **Start in FY2019 (the first draft) or FY2017.** J&J early adopted ASU 2017-12 in its second quarter of 2018 and put 189M after tax of swap gains in the line that year (analyst), so FY2018 is covered. FY2017's 83M of cash-flow-hedge gains is smaller and before the spot method; left out, said in the data file.
- **Keep `below_risk_free` as well.** The front-end asked not to: its sentence ("common, not a mistake", old rates) gives the wrong cause for J&J. Its comparison is kept inside the new note's params, so no information is lost.
- **Read the rate for every company.** Only J&J files one undimensioned total; Coca-Cola and P&G tag a different concept (`LongtermDebtWeightedAverageInterestRate`), and Exxon's is dimensional. That is #543's plausibility check, which can reuse the `pure` unit and add its own rows.

## Files to change

`domains/fundamentals/concepts.py`, `domains/fundamentals/concept_map_reported.csv`, `domains/analysis/reading_rules.md`, `tests/analysis/conftest.py`, `domains/analysis/interest_caveats.csv` (new), `domains/analysis/interest_caveats.py` (new), `domains/analysis/single_values.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, `tests/analysis/test_interest_caveats.py` (new), `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` are unchanged: no decision, no method and no number changes. The reading rules version is unchanged: no run reads a different figure.

## Product impact

Serves the front-end's ask on #542 and the brief's cost-of-debt section ("What the cost of debt counts as interest", `docs/product/brief.md` line 191, whose Spanish is ready and uses `{tasa_efectiva}`): J&J's cost of debt can go on a screen (Q3, Q4, Q7, Q8 and Q9 for J&J) with the warning beside it.

- **Added:** one note code, `interest_net_of_hedge_gains`, as a point note on the cost-of-debt chart and a cell note on the `cost_of_debt` cell of `inputs_behind`; params `fiscal_year`, `from_fiscal_year`, `to_fiscal_year`, `cost_of_debt`, `effective_rate`, `effective_rate_period`, `effective_rate_fiscal_year`, `effective_rate_older`, `effective_rate_filing`, `below_effective_rate`, `below_risk_free`. `{tasa_efectiva}` is `effective_rate`; when `effective_rate_older` is true the app says which fiscal year the rate is from (`effective_rate_fiscal_year`; FY2025's point shows FY2024's rate). The brief's sentence ("se ve más bajo") fits `below_effective_rate` true; it needs variants for false (FY2018: 3.35% against 3.19%) and for a null rate. `below_risk_free`'s inner `cost_of_debt` equals the outer one.
- **Changed:** on a J&J year from FY2018, `below_risk_free` no longer appears as its own point note; its params are inside the new note's `below_risk_free`. Every other company and every J&J year before FY2018 is unchanged.
- **Added to J&J's reported view:** a `debt_effective_rate` line (unit `pure`, a fraction) at each year end. It needs a Spanish label ("Tasa de interés efectiva promedio de su deuda de largo plazo", the product lead's wording) or the app can leave it off the reported screen.
- No number, run row, run note, refusal or reading-rules version changes; stored runs are untouched.

## Results (Step 4, nov.23.2026)

On the restored snapshot `warren-20261123T003850Z`.

- `reproduce --all` before: 909 of 909 stored runs reproduced to the cent.
- `fundamentals ingest --all`: J&J gains 26 facts (`DebtInstrumentInterestRateEffectivePercentage`, FY2011 to FY2024 year ends, each 10-K's version); no other company gains any. `fundamentals report --all`: 0 unexplained gaps for all eight.
- `reproduce --all` after: 909 of 909 to the cent.
- The inputs behind the last stored J&J run of each year (5-year window): every computed cost-of-debt year from FY2018 carries the note and none carries `below_risk_free` on its own; the cell carries it on every run.

| Run | Run's own year | Cost of debt (run's row) | Stated rate (year) | Below the yield (inside the note) |
|---|---|---|---|---|
| JNJ_2019-12-01_1 | FY2018 | 2.91% | 3.19% (FY2018) | no |
| JNJ_2020-12-01_1 | FY2019 | 1.05% | 3.19% (FY2019) | no |
| JNJ_2021-12-01_1 | FY2020 | 0.64% | 2.85% (FY2020) | yes |
| JNJ_2022-12-01_1 | FY2021 | 0.50% | 2.89% (FY2021) | yes |
| JNJ_2023-12-01_1 | FY2022 | 0.72% | 3.04% (FY2022) | yes |
| JNJ_2024-12-01_1 | FY2023 | 2.14% | 2.98% (FY2023) | yes |
| JNJ_2025-12-01_1 | FY2024 | 2.18% | 3.36% (FY2024) | yes |
| JNJ_2026-10-30_2 | FY2025 | 2.30% | 3.36% (FY2024, one year older, flagged) | yes |

  (Stored runs built before v0.10.34 keep their rows, so the cell's figure is the run's; today's read of the same year is on the chart point.) On today's read FY2018 is 3.35% against 3.19%, the one covered year not below the stated rate (`below_effective_rate` false).
- The other seven companies (one run each from 2021 and 2026 checked): no hedge note; their `below_risk_free` notes are as before (the code path without a caveat is unchanged).
- Snapshot saved after the ingest.

## Design review (nov.23.2026)

- **Analyst, two blockers, both taken.** (1) FY2019 was the wrong first year: J&J early adopted ASU 2017-12 from Q2 2018 and put 56 + 133M after tax of swap gains in the interest line in FY2018 (0000200406-19-000009); the caveat now starts in FY2018, FY2017's 83M noted. (2) The fallback had no age limit and J&J dropped the rate from its FY2025 10-K entirely: a fallback is now at most one fiscal year older and flagged, else null; the map note says J&J stopped stating it. Confirmed: the stated rate is built from each note's own effective rate, without the swaps, so it is the right comparison; it is a year-end rate on long-term debt only (said in the text). Taken: amounts are after tax; the evidence cites the FY2018 10-K first. No look-ahead (each year-end rate is in that year's own 10-K). P&G's low figure is not hedge netting (interest paid about equals expense), so no other row.
- **Professor, GO, no blockers.** Flagging without correcting is defensible (Koller et al.; Damodaran: a dollar valuation needs a dollar cost of debt); FY2018/2019 timing matches ASU 2017-12 guidance (Deloitte). Taken: the text now says the swaps turn dollar debt into lower-rate foreign-currency debt (the issue is mixing currencies, not that the rate is "wrong"), and drops "the rate it pays". Ideas (student app): a lesson on cross-currency swaps with J&J FY2020; the evidence filings as a "check it yourself" link.
- **Product lead, two blockers, both taken.** The cell's `cost_of_debt` is the run's own row (a stored run's row can differ from today's read); `effective_rate_fiscal_year` added so the app never derives a fiscal year from a date. Ideas taken: `below_effective_rate`; the filing's shape named. For the front-end: the brief's Spanish needs variants for `below_effective_rate` false and a null rate; confirm every screen showing the cost of debt reads `inputs_behind`'s cell.
- **Explainer.** Fifteen gaps. Taken: the fallback text is built from params; which filing supplies a rate (newest version known on `as_of`); the FY2025 source; what-if chart points; the display read and the reported-only test; units; the start-year evidence. The rest (`below_risk_free`'s full params, defined in `docs/designs/backlog-481-single-value-notes.md`) is in the linked file.
