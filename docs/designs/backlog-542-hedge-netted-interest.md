# Backlog #542: a coded note when J&J's interest is net of swap gains

Issue: https://github.com/sonderbot-ar/warren/issues/542 (from the #540 review; front-end ask in its first comment) · Branch `backlog-542-hedge-netted-interest` · Version v0.10.35 when merged.

Status: In progress (nov.23.2026).

## Problem

Since FY2019 Johnson & Johnson books gains on its cross-currency swaps inside "Interest (income) expense": the net-investment-hedge component excluded from effectiveness testing (spot method, ASU 2017-12, adopted 2019) and the cash-flow-hedge gains reclassified out of other comprehensive income (derivatives tables: 174 + 402 FY2021, 153 + 370 FY2020, 148 + 247 FY2024, 193 + 326 FY2025, millions; 0000200406-22-000022, 0000200406-26-000016). So the interest Warren divides by its debt (D8, `math_engine.cost_of_debt_year`) is net of about half a billion dollars a year, and J&J's cost of debt reads 0.67% to 1.33% in FY2019 to FY2022 and about 2.4% to 2.6% in FY2023 to FY2025, against the 2.85% to 3.36% weighted average effective rate J&J states on its long-term debt (`us-gaap:DebtInstrumentInterestRateEffectivePercentage`, see the table in `docs/designs/backlog-540-jnj-capitalised-interest.md`).

Today a student who opens J&J's cost-of-debt chart sees about 2.5% and, below the Treasury yield, the generic `below_risk_free` note: "the average rate on debt raised in past years, often when rates were lower … so it is common, not a mistake". For J&J that points at the wrong cause. The front-end team keeps J&J's cost of debt off screen until the engine says so in a coded note (#542, first comment): a note on the cost-of-debt figure, with J&J's filed effective rate (its filing and period) and the years affected, and `below_risk_free`'s generic sentence not shown beside it.

This item is option 3 of #542: say it, with the evidence. It does not change any number. Options 1 (add the swap gains back, which needs dimensional facts, scout #536) and 2 (use the filed or a market rate, which changes D8's method, an owner decision) stay open on #542.

## Plan

**Step 0. This doc.**

**Step 1. J&J's filed effective rate, read as a reported-only figure.**

- `concepts.UNITS` gains `pure` (a ratio, 0.0319 = 3.19%; the unit company facts file it under).
- `concept_map_reported.csv` (the file no valuation reads; outside the map fingerprint runs store, #157) gains `debt_effective_rate`, `us-gaap:DebtInstrumentInterestRateEffectivePercentage`, priority 1, `pure`, `instant`, `optional`, companies `JNJ`. J&J files one undimensioned value per year end in every 10-K (FY2011 to FY2024; FY2025's 10-K does not tag it). Other companies tag it per instrument or with a dimension the facts file drops (#540 doc, item 3), so a figure read for them would be one bond's rate, not the total: JNJ only, and widening it needs that company's filings checked first.
- No stored run moves: the valuation map and its fingerprint are untouched, and `test_no_valuation_or_scoring_step_reads_a_reported_only_item` already guarantees no valuation, score or AI step reads the item.
- J&J's reported view (it lists every mapped item) gains a `debt_effective_rate` line with unit `pure` at each year end.
- Tests (`tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`): the shipped map has the row scoped to `{JNJ}` with unit `pure`; `load_concept_map` accepts `pure` and still refuses an unknown unit; `extract_facts` keeps a `pure` fact for JNJ and skips it (company scope) for another ticker.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Companies as data: which company's interest is net of what, from which year.**

- New `domains/analysis/interest_caveats.csv` (Decision 11, companies as data): `ticker`, `code`, `from_fiscal_year`, `to_fiscal_year` (empty: still true in the newest filing), `rate_item` (the reported-only item holding the company's own filed rate, or empty), `evidence` (filings and pages a reader can check), `note`. One row: `JNJ`, `interest_net_of_hedge_gains`, 2019, empty, `debt_effective_rate`, the FY2021 and FY2025 10-Ks' derivatives tables.
- `domains/analysis/interest_caveats.py`: `load_interest_caveats(path=None)` validates the file and reports every problem at once (unknown ticker against the universe, code outside the closed set `CAVEAT_CODES = ("interest_net_of_hedge_gains",)`, years not integers or `to` before `from`, a `rate_item` not in the reported map, two rows for one ticker and code that overlap); `caveat_for(ticker, fiscal_year)` returns the row covering that year or None.
- Tests (`tests/analysis/test_interest_caveats.py`): the shipped file loads and has exactly the J&J row; each validation error is reported with its line; `caveat_for` covers FY2019 and FY2025 for JNJ, not FY2018, and nothing for another ticker.
- Exit: CI green.

**Step 3. The note on the cost-of-debt chart and cell.**

- `single_values.POINT_NOTES` and `CELL_NOTES` gain `interest_net_of_hedge_gains`. On the cost-of-debt chart (`_cost_of_debt`), each computed year a caveat row covers gets the point note, with params:
  - `fiscal_year`, `from_fiscal_year`, `to_fiscal_year` (the years affected; `to` null while open);
  - `cost_of_debt` (the point's value);
  - `effective_rate`, `effective_rate_period` (ISO date), `effective_rate_filing` (the filing, as every part's filing is given): the company's filed rate at that year's end as known on the run's `as_of` (the newest filing's version); when that year end has none, the newest filed rate at an earlier year end, so `effective_rate_period` says which year it is (FY2025 shows FY2024's 3.36% with period 2024-12-29); all three null when none is known on `as_of`;
  - `below_risk_free`: null, or the params `below_risk_free` would have had (`cost_of_debt`, `risk_free`, `risk_free_date`, `against`, …), so the app can still say the figure is below the Treasury yield.
- On such a point `below_risk_free` is not added on its own (the front-end's ask): its comparison moves inside the new note's `below_risk_free` param. Years outside the caveat keep `below_risk_free` as today.
- The cell: when the run's own cost-of-debt year (its interest source's fiscal year) is covered, the cost-of-debt cell carries the same note with the used point's params, so a screen that shows only the run's figure has it too. A what-if child whose cost of debt is floored at the risk-free rate (`floored_at_risk_free`) carries no hedge note on the cell: its value is not the book figure.
- Point-in-time: the rate is read with `get_facts(conn, cik, ["debt_effective_rate"], as_of)`; the years come from the data file, and a point exists only for a year whose filings are known on `as_of`, so a note never cites a filing after `as_of`. The note's filing is the rate's own 10-K.
- English fallback text: "the interest expense is net of gains on the company's currency swaps (booked in its interest line since FY2019), so this cost of debt reads lower than the rate it pays on its debt (3.36%, the weighted average effective rate it states on its long-term debt at 2024-12-29); Warren cannot yet separate those gains".
- Tests (`tests/analysis/test_single_values.py`, Test Corp with a caveat row for TST injected): every covered year's point has the note and no separate `below_risk_free`; the note carries the year's own filed rate, or the newest earlier one with its period, or null; a rate filed after `as_of` is never read; the `below_risk_free` param is filled when the point is below the yield and null when not; years before `from_fiscal_year` keep `below_risk_free` and get no hedge note; the cell carries the note when the used year is covered and not otherwise; a floored what-if child's cell has no hedge note; every code stays inside the closed lists. Without a caveat row, every chart and cell is identical to today's.
- Exit: CI green.

**Step 4. Real data.** On the restored snapshot (`warren-20261123T003850Z`): `reproduce --all` before; `fundamentals ingest --all` (only J&J should gain facts, the `debt_effective_rate` ones); `fundamentals report --all` (0 unexplained gaps); `reproduce --all` after, same count. Then the inputs behind the newest J&J run and one run per year from 2020: list each cost-of-debt year with its note and rate, and check no other company's chart gains or loses a note. Save a snapshot.

## Alternatives considered

- **A run note, fixed when a run is stored.** Run notes are written at build time, so only fresh runs would carry it, and stored J&J runs (every one of them reads the same netted line) would stay silent; it would also change what a rebuild compares. The chart and cell notes are read when an answer is built, so every J&J run, stored or fresh, says it. Rejected.
- **Hard-code J&J in `single_values.py`.** Breaks Decision 11 (companies as data). Rejected for the CSV.
- **Write J&J's filed rates into the data file by hand.** A number typed by hand has no filing date, so it cannot be read point-in-time, and it would be wrong the day J&J restates. Rejected for the reported-only map item, read like every other filed figure.
- **Keep `below_risk_free` as well.** The front-end asked not to: its sentence ("common, not a mistake", old rates) gives the wrong cause for J&J. Its comparison is kept inside the new note's params, so no information is lost.
- **Read the rate for every company.** Only J&J files one undimensioned total; Coca-Cola and P&G tag a different concept (`LongtermDebtWeightedAverageInterestRate`), and Exxon's is dimensional. That is #543's plausibility check, which can reuse the `pure` unit and add its own rows.

## Files to change

`domains/fundamentals/concepts.py`, `domains/fundamentals/concept_map_reported.csv`, `domains/analysis/interest_caveats.csv` (new), `domains/analysis/interest_caveats.py` (new), `domains/analysis/single_values.py`, `tests/fundamentals/test_concepts.py`, `tests/fundamentals/test_ingest.py`, `tests/analysis/test_interest_caveats.py` (new), `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` are unchanged: no decision, no method and no number changes. The reading rules version is unchanged: no run reads a different figure.

## Product impact

Serves the front-end's ask on #542 and the brief's cost-of-debt section ("What the cost of debt counts as interest", `docs/product/brief.md` line 191, whose Spanish is ready and uses `{tasa_efectiva}`): J&J's cost of debt can go on a screen (Q3, Q4, Q7, Q8 and Q9 for J&J) with the warning beside it.

- **Added:** one note code, `interest_net_of_hedge_gains`, as a point note on the cost-of-debt chart and a cell note on the `cost_of_debt` cell of `inputs_behind`; params `fiscal_year`, `from_fiscal_year`, `to_fiscal_year`, `cost_of_debt`, `effective_rate`, `effective_rate_period`, `effective_rate_filing`, `below_risk_free`. `{tasa_efectiva}` is `effective_rate`; when `effective_rate_period` is not the point's own year end, the app should say which year the rate is from (FY2025's point shows FY2024's rate).
- **Changed:** on a J&J year from FY2019, `below_risk_free` no longer appears as its own point note; its params are inside the new note's `below_risk_free`. Every other company and every J&J year before FY2019 is unchanged.
- **Added to J&J's reported view:** a `debt_effective_rate` line (unit `pure`, a fraction) at each year end. It needs a Spanish label ("Tasa efectiva promedio de su deuda de largo plazo", suggestion) or the app can leave it off the reported screen.
- No number, run row, run note, refusal or reading-rules version changes; stored runs are untouched.

## Where the work stopped

(Filled in if a run ends before merge.)
