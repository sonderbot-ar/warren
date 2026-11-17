# Backlog #408: JNJ's current debt, counted twice

Issue: https://github.com/sonderbot-ar/warren/issues/408 (from the #341 design review) · Branch `backlog-408-jnj-current-debt` · Version v0.9.78, merged nov.16.2026 (PR #413, merge `6dfbe29`, after CI green and a gatekeeper GO).


## Problem

Johnson & Johnson (JNJ) shows "Loans and notes payable" on its balance sheet, tagged `us-gaap:ShortTermBorrowings` and counted by Warren as `short_term_borrowings`. That line already includes the current portion of long-term debt. In some 10-Ks JNJ also tags the current portion on its own in the debt note, as `us-gaap:LongTermDebtCurrent`, which is priority 1 for `debt_current`. `math_engine.debt_parts` adds both, so the current portion is counted twice.

The proof is JNJ's own total, `us-gaap:DebtCurrent` ("total debt due within one year"), which equals the short-term line alone, not the short-term line plus the current portion (company facts, CIK 0000200406, every 10-K year end where all three are tagged):

| Year end | DebtCurrent | ShortTermBorrowings | LongTermDebtCurrent | Short-term + current |
|---|---|---|---|---|
| 2011-01-02 | 7,600M | 7,617M | 13M | 7,630M |
| 2017-01-01 | 4,700M | 4,684M | 1,700M | 6,384M |
| 2017-12-31 | 3,900M | 3,906M | 1,500M | 5,406M |
| 2018-12-30 | 2,800M | 2,796M | 2,600M | 5,396M |
| 2021-01-03 | 2,600M | 2,631M | 1,799M | 4,430M |
| 2022-01-02 | 3,800M | 3,766M | 2,131M | 5,897M |
| 2023-01-01 | 12,800M | 12,771M | 1,551M | 14,322M |
| 2023-12-31 | 3,500M | 3,451M | 1,469M | 4,920M |
| 2024-12-29 | 6,000M | 5,983M | 1,749M | 7,732M |
| 2025-12-28 | 8,500M | 8,495M | 2,000M | 10,495M |

The FY2018 10-K (0000200406-19-000009) confirms it in words: "Total borrowings at the end of 2018 and 2017 were $30.5 billion and $34.6 billion", which is Loans and notes payable plus non-current long-term debt with nothing added (2,796 + 27,684; 3,906 + 30,675); with the current portion outside, they would be 33.1bn and 36.1bn (analyst).

**The issue's dates were partly wrong, its count right.** It named the year ends 2017-01-01, 2017-12-31 and 2018-12-30. The stored runs that carry `balance:debt_current` read it from 2018-12-30 (17 runs dated 2019-04-01 to 2020-04-01) and from the year ends 2022-01-02 to 2025-12-28 (70 runs dated 2022-03-01 to 2026-10-30): 87 runs, as the issue said. The 2017 year ends are older than every JNJ run (the first is 2019-04-01), and 2021-01-03's current portion was first filed in the FY2021 10-K (2022-02-17), so a run dated in 2021 never saw it.

**Effect.** Those 87 runs overstate debt by $1.5bn to $2.6bn. In the 2019 quarter runs the year-end 2,600M is also carried forward beside the quarter's own Loans and notes payable (1,708M at 2019-03-31), which already include the current portion again (Q1 2019 10-Q, 0000200406-19-000033, Note 4: "Current Debt" 1,708M equals Loans and notes payable). The same double count reaches working capital: `_operating_nwc` takes both `debt_current` and `short_term_borrowings` out of current liabilities, so it takes the current portion out twice and working capital comes out too high. And the cost of debt divides interest by average debt at two year ends, so it comes out too low.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. Judge from the filing's own total, for every company (companies as data, Decision 11).**
  - New concept map item `debt_current_total` = `us-gaap:DebtCurrent`, priority 1, instant, gate `optional` (most companies never tag it, or only in some filings). It is never counted as debt: `DebtCurrent` bundles short-term borrowings, commercial paper and the current portion, which is why it was left unmapped before. The `debt_current` row's note now says this. The map's copy in `concept_maps/` and its `CHANGES.md` line, in the same commit.
  - `math_engine.current_debt_inside(current, short_term, on)`: at the current portion's own date, the filing's total debt due within one year is (a) strictly nearer short-term borrowings alone than short-term borrowings plus the current portion (a tie is not inside), and (b) within half the current portion of short-term borrowings alone (a total far below the short-term line is a broken figure, not proof of either presentation; analyst). It needs all three figures on that date, each filed by the run's as-of date (`load_history`'s point-in-time query), a current portion above zero, and the short-term figure counted to be no older than the current portion. No tolerance to tune: it picks whichever presentation the filing's own total fits, and JNJ's total is off by 4M to 49M from the short-term line alone against 1,469M or more from the sum. The check only means something when the current portion is larger than the total's rounding (JNJ rounds `DebtCurrent` to 100M): at 2011-01-02 (current portion 13M, 17M from the short-term line) condition (b) fails and the portion is kept, an immaterial 13M that no run reads.
  - When it holds, `debt_parts` leaves the current portion out (debt row's method says why), and `_operating_nwc` takes it out of current liabilities only once (the history row's method says why). The cost of debt reads `debt_parts` at each year end, so it follows.
  - A run's balance sheet that is a quarter end can carry a year-end current portion forward beside the quarter's own short-term borrowings (JNJ's 2019 quarters). The check is made at the year end and applies to the later short-term figure too: it takes the company to present its short-term line the same way within the year. JNJ's quarterly filings say so (`known_gaps.csv` line 23: the current portion is "within 'Loans and notes payable'" each quarter). A current portion left out is no longer listed in `balance_carried_forward`.
  - Run note `debt_current_inside_short_term` (group `data`; params `period_end` (ISO, the date judged), `debt_current`, `short_term_borrowings`, `debt_current_total` (unscaled, in `currency`), `currency`, `accession_no` (the current portion's filing), `assumptions` (the rows it touches)) and its lesson in `text.WARNING_LESSONS`. The reported view (`reported._net_debt`) reads debt the same way and carries the same code with the same params but `assumptions`, so a run and the reported view agree (#290).
  - `load_history` reads `debt_current_total` only when the map in force (the `concepts` table, which `concept_map_in_force` shadows with a run's own map during a rebuild) has it, so a rebuild through a map made before this item reads what that map read.
  - `READING_RULES_VERSION` 5 → 6, with its row in `domains/analysis/reading_rules.md`.
  - Tests (`tests/analysis/test_debt_current_inside.py`): inside at the balance date (debt 230, not 250; note and params; no `balance_counted_zero` for the item); a total that holds both parts keeps the current portion; no total, no judgement; commercial paper in place of borrowings keeps it; a year-end portion carried beside quarter-end borrowings is left out and not listed as carried forward; history working capital takes it out once; JNJ's 2018 figures; three edge cases (no current portion, a total equally near both, a short-term figure older than the current portion); the code and lesson are catalogued; the reported view agrees; a rebuild through #341's map reads as before.
  - Exit: full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot (`warren-20261115T202938Z`): `fundamentals ingest --all` (so no fresh run carries `concept_map_changed`); `fundamentals report --all` passes the gate; `reproduce --all --rebuild`: every stored run reproduces to the cent, and rebuilds as before through its own map. Build every stored run date of every company with `DebtCurrent` facts fresh (same pinned market data and choices) with and without the check, none stored, and list what moves. Exit: only JNJ moves.

## Alternatives considered

- **A JNJ-only rule in the concept map** (the issue's first idea, using #341's `companies` column). The column can only *add* a tag for named companies; dropping `LongTermDebtCurrent` for JNJ alone would need an exclusion list, and a priority-1 tag can't be scoped (#341's rule). It would also hard-wire one company's presentation, while the check reads it from each filing.
- **Compare short-term borrowings with `DebtCurrent` within a fixed tolerance** (the issue's second idea). Needs a tolerance (JNJ rounds `DebtCurrent` to 100M), and a tight one misses 2023-12-31 (49M off). Comparing the two presentations needs none.
- **Drop `debt_current` whenever `short_term_borrowings` is present.** Wrong for every company that presents them apart (Exxon, P&G at the dates where both are tagged: `DebtCurrent` is far from short-term borrowings alone).
- **Count `DebtCurrent` as the whole current debt.** It bundles commercial paper too, which `debt_parts` counts only when no short-term borrowings exist; and most companies don't tag it every period.

## Design review (nov.16.2026)

- **Analyst, GO, no blockers.** Checked JNJ's FY2018 10-K and Q1 2019 10-Q (Problem, quoted above): the current portion is inside Loans and notes payable at year ends and at quarter ends, so carrying the year-end judgement to a later quarter is sound; working capital is right; Exxon (17 year ends) and P&G (2 dates) are never judged inside, the other five companies don't tag `DebtCurrent`. Taken: condition (b), a total far below short-term borrowings is not inside (test); the rounding caveat (Step 1). Filed: P&G drops $7.8bn of commercial paper at 2018-06-30, because its 800M of short-term bank loans stand in for commercial paper in `debt_parts` (existing, not caused here), and a test for a restated short-term figure on the same date (#412).
- **Professor, GO, no blockers.** Defensible (Koller, Goedhart and Wessels count each claim once; the taxonomy defines `ShortTermBorrowings` as debt with initial terms under a year, so the fault is JNJ's presentation, not the arithmetic). Taken: the lesson says "is closer to", not "matches"; Koller and the taxonomy definitions are now its main references, ASC 470-10-45 secondary (it governs classification, not how lines are combined); one clause on why value per share moves much less than debt.
- **Explainer.** One possible blocker: whether the reported view's quarter lookup sees a year-end total. It does: a test now covers the carried year-end case in the reported view, and it agrees with the run. Taken: the tie rule, the as-of filter, the rounding caveat, what "the map in force" means, accession numbers for the filings quoted. The one-year carry-forward limit is unchanged (`COMPONENT_MAX_AGE`). Not taken: the note and lesson texts in the doc (they are in `text.py` and `math_engine.py`, which the catalogue reads).
- **Product lead.** Two blocking wording fixes, both taken: the two-runs case is "Either version NULL" for every stored run, and Q4 is served (Product impact). Also taken: the reported note's group, the `history:nwc` method, the Spanish needs, and an `assumptions` param naming the rows the side panel repeats the note on.

## Files to change

`domains/fundamentals/concept_map.csv`, `concept_maps/<new sha>.csv` and `CHANGES.md`; `domains/analysis/math_engine.py`, `domains/analysis/reported.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `.md`; `tests/analysis/test_debt_current_inside.py`; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8, value per share) and Q4 (where each part of the WACC comes from: JNJ's cost of debt and debt weight move, Step 2): fresh JNJ runs count each piece of debt once. Fresh JNJ runs move (Step 2 gives the numbers); stored runs keep their rows.

- **Added:** run-note code `debt_current_inside_short_term`, group `data` (the app's "Los datos de partida"), with params `period_end` (ISO, the date judged), `debt_current`, `short_term_borrowings`, `debt_current_total` (unscaled amounts in `currency`, shown in millones de US$ like every other amount), `currency`, `accession_no` (the current portion's filing, for a link) and `assumptions` (`["debt", "cost_of_debt", "nwc_pct"]`, the rows the side panel repeats the note on, as the tax notes do), and its lesson in `text.WARNING_LESSONS` (no params).
- **Reported view:** the `net_debt` ratio (`reported._net_debt`) carries the same code with the same params except `assumptions`; it belongs in group 2 of the reported-figure notes ("why it comes from where it does").
- **Changed on a JNJ run that carries the note:** no `balance:debt_current` row; the `debt` row's method names the check; and the `history:nwc` rows of the years whose year end has the current portion inside name it too (working capital moves on all 115 fresh JNJ dates). A current portion left out is not listed in `balance_carried_forward`.
- **Two runs of the same date.** Runs now record reading rules v6. Every stored JNJ run (all 903 stored runs) has no recorded rules version, so beside one of them a fresh JNJ run falls in the brief's "Either version NULL" case (no "usa esa"). Only a JNJ run stored from v0.9.67 to v0.9.77 beside a fresh one would be the "both recorded and different" case; none is stored today.
- Nothing renamed or removed. For the front-end team: the code and lesson in the Spanish catalogue (#344's list); the brief's "Hoy" line on the current rules version moves from 5 to 6.

## Results (Step 2, nov.16.2026)

On the restored snapshot (`warren-20261115T202938Z`):

- **Ingest.** `fundamentals ingest --all`: the only new facts are `DebtCurrent`: JNJ 26, P&G 140, Exxon 138; every other company files none. `fundamentals report --all`: 0 unexplained gaps for all eight companies.
- **Stored runs.** `reproduce --all --rebuild`: 903 of 903 reproduced to the cent; 692 of 903 rebuilt to identical rows, the same count #341 found on `main` (the other 211 were made by older code and differ from today's rebuild as they did before). No stored run moves, by design: each is rebuilt through its own map, which never read `DebtCurrent`.
- **Fresh runs.** Every stored run date of JNJ, P&G and Exxon built twice in memory (same pinned market data and choices), with and without the check; none stored. P&G (114 dates) and Exxon (100 dates): nothing moves. JNJ: all 115 dates move, 87 in debt (exactly the 87 the issue counted, each now carrying the note) and all 115 in working capital, through the history years whose year end has the current portion inside. Per year of run date (the year's last run for the rates):

| Runs dated | Runs | Debt moves | Debt removed | Cost of debt | WACC | Working capital / revenue | Value per share |
|---|---|---|---|---|---|---|---|
| 2019 | 12 | 12 | 2.6bn | 2.91% → 3.09% | 4.78% → 4.81% | 1.6% → −0.9% | +0.1% to +0.2% |
| 2020 | 14 | 5 | 2.6bn | 1.05% → 1.09% | 3.73% → 3.73% | −3.5% → −5.2% | −0.1% to +0.2% |
| 2021 | 16 | 0 | | 0.64% → 0.64% | 4.29% → 4.29% | −8.9% → −10.0% | 0.0% |
| 2022 | 15 | 12 | 2.1bn | 0.50% → 0.53% | 6.22% → 6.25% | −12.0% → −13.4% | 0.0% to +0.2% |
| 2023 | 14 | 14 | 1.6bn to 2.1bn | 0.72% → 0.75% | 6.72% → 6.74% | −11.4% → −13.4% | +0.1% to +0.2% |
| 2024 | 14 | 14 | 1.5bn to 1.6bn | 2.14% → 2.24% | 6.49% → 6.51% | −12.0% → −14.1% | +0.1% to +0.2% |
| 2025 | 14 | 14 | 1.5bn to 1.7bn | 2.18% → 2.29% | 6.14% → 6.16% | −12.0% → −13.8% | +0.2% to +0.3% |
| 2026 | 16 | 16 | 1.7bn to 2.0bn | 2.20% → 2.30% | 6.61% → 6.63% | −11.3% → −13.2% | +0.2% to +0.3% |

  For example, as of 2026-10-30: debt $46.65bn → $44.65bn, value per share $168.01 → $168.53; as of 2019-04-01: debt $33.08bn → $30.48bn, $148.46 → $148.72. Value per share barely moves: $2bn is about 0.5% of JNJ's market value, and the higher cost of debt and lower debt weight raise the WACC slightly, which takes back part of it. The error was in the debt itself, which a student reads line by line, not mainly in the value. Revenue and EBIT forecasts don't read debt or working capital, so the forecast-error scores (M3, M8, M9, and M10's batch) do not move.

## Gatekeeper (nov.16.2026)

GO, no blockers: 2,367 passed, ruff clean; the new reads are point-in-time; the map copy is byte-identical; `JNJ_2026-10-30_1` rebuilds to identical rows through its own map; the reading-rules row matches (v6). Ideas added to #412: `History.on` takes the first fact on a date; a check at a quarter-end short-term figure's own date when a total exists there; a fallback when the `concepts` table is missing.
