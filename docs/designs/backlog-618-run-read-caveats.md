# Backlog #618: say when an older run's cost of debt holds more than the charges note says

Issue: https://github.com/sonderbot-ar/warren/issues/618 (from the #613 items 2-3 analyst) · Branch `backlog-618-run-read-caveats` · Version v0.10.58 when merged.

Status: In progress (nov.27.2026).

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
- When the two differ, the text says so: "… so Warren cannot take it out and today's reading, 2.29%, reads a little high; this run's own figure, 3.36%, was read differently and may hold more (run_read_differently)". Otherwise the text is unchanged.
- Tests: the param on every covered point equals the point's value; on an older run's used year it differs from `cost_of_debt`, the text names both, and the cell's copy is identical to the point's; a fresh run's text is unchanged.
- Exit: as Step 1.

**Step 3. A guard so nobody widens the extinguishment item to Walmart unchecked.**

- New test in `tests/fundamentals/` that every `debt_extinguishment_in_interest` row in `concept_map.csv` is limited to `KO`, its failure message citing Walmart's EDGAR figures (FY2018 −3,136M, its own line outside interest; FY2019 −8,368M) and the rule: check a company's figure against its interest line first.
- Not a change to the row's note text: the map's bytes are its version (`concept_map_sha256`, the archived copy in `concept_maps/`, reading rules), so a note-only edit would make a new map version for no change in what runs read.
- Exit: as Step 1.

**Step 4. Real data.** On the restored snapshot: the cost-of-debt cell of every Coca-Cola run and the newest run of each other company. Expected: the 30 Coca-Cola cells with `hedge_reclass_in_interest` (16 FY2020, 14 FY2021) open with `run_read_differently` and their charges note names both figures; no newest run gets `run_read_differently`; any other stored run that gets it (Caterpillar's older runs) listed; no value changes; `reproduce --all` to the cent. Exit: as stated.

## Alternatives considered

- **Only a param on the charges note, no cell note.** Fixes Coca-Cola's sentence but leaves every other cell note (J&J's hedge note, `far_from_stated_rate`) unable to tell a screen that the run's figure is not today's. The cell note is one code the app already translates.
- **Rebuild Coca-Cola's older runs under today's rules.** Stored runs are the record of what Warren said on a date; they reproduce from their stored assumptions by invariant. A fresh run for those dates is #485's pattern and can follow; it does not fix what the stored ones say.
- **Edit the map row's note for Walmart.** See Step 3: a new map version for a comment.

## Files to change

`domains/analysis/single_values.py` (cell notes, charges notes), `tests/analysis/test_charges_caveats.py`, `tests/analysis/test_single_values.py` (if a shared helper is needed), new `tests/fundamentals/test_extinguishment_scope.py`, `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q3 (where each assumption comes from) on older runs: the cost-of-debt card no longer says "a little high" beside a figure that holds the whole early-payoff charge. Adds one cell note code on `cost_of_debt` (`run_read_differently`, already in the Spanish catalogue as a point note) and one param (`todays_cost_of_debt`) on the two charges notes; their text changes only where the run's figure was read differently. Nothing renamed or removed; no number changes.
