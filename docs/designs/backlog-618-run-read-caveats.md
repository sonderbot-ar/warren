# Backlog #618: say when an older run's cost of debt holds more than the charges note says

Issue: https://github.com/sonderbot-ar/warren/issues/618 (from the #613 items 2-3 analyst) · Branch `backlog-618-run-read-caveats` · Version v0.10.58 when merged.

Status: Done (nov.27.2026), merged as v0.10.58 in `e3f4bbf` (PR #625).

## Problem

1. **An older Coca-Cola run's cell note understates what its figure holds.** Since v0.10.54 (#610) Warren takes Coca-Cola's tagged early-payoff charges out of its interest: FY2020 reads 2.29%, not 3.36%. Runs stored before that merge keep their own `cost_of_debt` row (they reproduce to the cent), so a run dated in 2021 still stores 3.36% for FY2020, which holds the whole 484M charge. Since v0.10.56 (#613) the `cost_of_debt` cell carries `hedge_reclass_in_interest` on those runs, saying FY2020's interest "still holds" hedge losses (25M in the quote) and the cost of debt "reads a little high", with `cost_of_debt` 3.36%, the run's row. The chart's used point carries `run_read_differently` (run 3.36%, today 2.29%); the cell, which a screen showing only the run's figure reads, does not. On the nov.27 snapshot this is 30 Coca-Cola runs (the #613 Results: cells whose own year is FY2020, 16, or FY2021, 14).
2. **Walmart's extinguishment tag looks wrong.** EDGAR shows Walmart's `GainsLossesOnExtinguishmentOfDebt` at −3,136M for FY2018 (its own loss-on-extinguishment line, outside interest) and −8,368M for FY2019 (no such charge that year; looks like another line mis-tagged). The map item `debt_extinguishment_in_interest` is Coca-Cola only today; nothing stops someone widening it to Walmart without checking.

## Plan

**Step 0. This doc.**

**Step 1. The cost-of-debt cell says when the run read its year differently.**

- `_cost_of_debt_cell_notes` puts `run_read_differently` first among the cell's notes when the used year's point carries it (same code, params `period`, `run_value`, `value`, and text as the point's). `inputs_behind` caches the used point before `_checked` marks it, so the cell builder applies `_read_differently` with the run's row itself; `cost_of_debt_notes` already passes the marked point. A floored what-if child keeps only `floored_at_risk_free` (no point is used there).
- `run_read_differently` joins `CELL_NOTES` (it is already in `POINT_NOTES`). It is not specific to Coca-Cola: any run whose row differs from today's reading of its used year (Caterpillar's older runs, #485) gets it on the cell too.
- Tests: Test Corp with a stored `cost_of_debt` row edited to differ from today's reading gets the cell note first, equal to the used point's, from `inputs_behind` and from `cost_of_debt_notes`; a fresh run gets none; a floored child gets only `floored_at_risk_free`; the code is in `CELL_NOTES`.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. The charges notes give today's reading beside the run's.**

- `extinguishment_not_tagged` and `hedge_reclass_in_interest` gain param `todays_cost_of_debt`, the point's own value (today's reading of the year). It equals `cost_of_debt` except on the used year of a run whose row was read differently, where `cost_of_debt` stays the run's row (as `below_risk_free` and `far_from_stated_rate` do).
- When the two differ, the English text says so, with the direction said straight (analyst, product lead: a gap can go either way, e.g. Caterpillar's older runs): "… so Warren cannot take it out and today's reading, 2.29%, reads a little high; this run used 3.36%, read under older rules or before a later filing, higher than today's reading (interest_caveats.csv)". No code name in the sentence (professor). Otherwise the text is unchanged. The app words this branch from `cost_of_debt` and `todays_cost_of_debt` alone and merges it with the `run_read_differently` paragraph, so the student does not read the same thing twice (product lead).
- `interest_net_of_hedge_gains` (J&J) and `far_from_stated_rate` keep comparing the run's own row, as `below_risk_free` does; on an older run the cell's `run_read_differently`, now first, tells the screen that figure is not today's (analyst).
- Tests: the param on every covered point equals the point's value; on an older run's used year it differs from `cost_of_debt`, the text names both and says "higher" or "lower" by the figures, and the cell's copy is identical to the point's; a fresh run's text is unchanged.
- Exit: as Step 1.

**Step 3. A guard so nobody widens the extinguishment item to Walmart unchecked.**

- New test in `tests/fundamentals/` that every `debt_extinguishment_in_interest` row in `concept_map.csv` is limited to exactly `KO` and that no other universe company reads it (`ConceptRow.applies_to`, the gate the history loader uses for `math_engine.EXTINGUISHMENT`), its failure message citing Walmart's figures from EDGAR's company-concept API (FY2018 −3,136M, its own line outside interest; FY2019 −8,368M; read from the API, not checked against the 10-K text, and said so) and the rule: check a company's interest line in its own 10-K before widening. The module docstring cites ASC 470-50 (professor).
- Not a change to the row's note text: the map's bytes are its version (`concept_map_sha256`, the archived copy in `concept_maps/`, reading rules), so a note-only edit would make a new map version for no change in what runs read.
- Exit: as Step 1.

**Step 4. Real data.** On the restored snapshot: the cost-of-debt cell (`cost_of_debt_notes`, ten years) of every stored baseline run of every company, newest run by `as_of`. Expected: the 30 Coca-Cola cells with `hedge_reclass_in_interest` (16 FY2020, 14 FY2021) open with `run_read_differently` and their charges note gives both figures; every other cell that gets `run_read_differently` listed by company and year (the analyst expects other Coca-Cola payoff years, e.g. FY2015's 320M, and Caterpillar's older runs); no newest run gets it; no value changes; `reproduce --all` to the cent. Exit: as stated.

## Results (Step 4, nov.27.2026)

On the restored snapshot `warren-20261127T002823Z` (936 stored runs, all baselines), `cost_of_debt_notes` at ten years on every run, no errors:

- **The 30 Coca-Cola cells** whose own year is FY2020 (16) or FY2021 (14) open with `run_read_differently` and then `hedge_reclass_in_interest`, whose `cost_of_debt` is the run's row and `todays_cost_of_debt` today's reading, the text saying "higher than today's reading".
- **The note is far wider than Coca-Cola's charges: 696 of 936 cells get it.** Every company but Apple: Caterpillar 113 runs (0.47 to 1.16 points apart), J&J 116 (0.17 to 0.45), Coca-Cola 99 (0.02 to 1.31; FY2018 to FY2025 used years), Microsoft 67 (0.05 to 1.02), P&G 114 (0.001 to 0.73; 35 under half a point), Walmart 87 (0.51 to 0.82), ExxonMobil 101 (0.02 to 2.90). These are the runs stored before the cost-of-debt reading changes of v0.10.29 to v0.10.54 (lease interest, capitalised interest, early payoffs, current debt); the chart's used point already carried the note on each, the cell did not. The design's expectation that no newest run gets it was wrong: the newest runs (2026-10-30, stored nov.04 and nov.19) of J&J, Microsoft, Walmart and ExxonMobil predate those changes and get it too. That is the cell telling the truth the chart already told; fresh runs under today's rules (#485's pattern) would clear it, a separate item.
- No value changes: `python -m domains.analysis reproduce --all` gives 936 of 936 to the cent.

## Design review (nov.27.2026)

Explainer, analyst, professor and product lead, each GO with changes; no NO-GO.

- **Taken.** The direction said straight, "higher" or "lower" by the figures (analyst blocker, product lead); no code name in the sentence (professor); Step 4 lists every cell with the note, not only the 30 (analyst blocker); the guard test checks the reader's gate too and says the Walmart figures were read from the API (analyst); the cell and the J&J or stated-rate notes compare the run's row (analyst); Product impact names Q4 and Q8 and the catalogue work (product lead); ASC 470-50 in the guard's docstring (professor).
- **Rejected, with reason.** A `reason` param on `run_read_differently` naming the rule change (analyst): the engine cannot tell a rule change from a later restatement without rebuilding the run under each rule set, which is #485's job; the app words it from the two figures. Splitting Step 3 into its own item (professor): it is one test, from the same issue.
- **Explainer's guesses** answered in the steps: `_read_differently` compares the run's stored row with the used point's value; a floored child is a what-if whose cost of debt was floored at the risk-free rate; the new clause replaces the sentence's ending only on the used year of an older run.

## Alternatives considered

- **Only a param on the charges note, no cell note.** Fixes Coca-Cola's sentence but leaves every other cell note (J&J's hedge note, `far_from_stated_rate`) unable to tell a screen that the run's figure is not today's. The cell note is one code the app already translates.
- **Rebuild Coca-Cola's older runs under today's rules.** Stored runs are the record of what Warren said on a date; they reproduce from their stored assumptions by invariant. A fresh run for those dates is #485's pattern and can follow; it does not fix what the stored ones say.
- **Edit the map row's note for Walmart.** See Step 3: a new map version for a comment.

## Files to change

`domains/analysis/single_values.py` (cell notes, charges notes), `tests/analysis/test_charges_caveats.py`, `tests/analysis/test_single_values.py` (if a shared helper is needed), new `tests/fundamentals/test_extinguishment_scope.py`, `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q3, Q4 and Q8 (the cost-of-debt card) on older runs: the cost-of-debt card no longer says "a little high" beside a figure that holds the whole early-payoff charge. Adds one cell note code on `cost_of_debt` (`run_read_differently`, already in the Spanish catalogue as a point note) and one param (`todays_cost_of_debt`) on the two charges notes; their text changes only where the run's figure was read differently. The front-end team needs a cell title and sentences for `run_read_differently` on the cost-of-debt cell in both catalogues, and the brief's charges-note sentence needs the branch above. Nothing renamed or removed; no number changes.
