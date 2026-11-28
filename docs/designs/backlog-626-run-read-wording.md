# Backlog #626 items 2 and 3: the charges note never says "higher" for figures that print the same, and the cost-of-debt note says which reading rules each figure came from

Issue: https://github.com/sonderbot-ar/warren/issues/626 (from the #618 review) · Branch `backlog-626-run-read-wording` · Version v0.10.59 when merged.

Status: In progress (nov.28.2026).

Item 1 of #626 (fresh runs under today's rules for the 696 stored runs whose cost-of-debt cell reads differently) is not in this item: it builds runs on the real snapshot and belongs with #485's pattern. It stays open on #626.

## Problem

1. **Rounding in the charges note's wording** (gatekeeper, #618). Since v0.10.58 the charges notes (`extinguishment_not_tagged`, `hedge_reclass_in_interest`, `domains/analysis/single_values.py`, `_charges_notes`) say, on an older run whose figure differs from today's reading, "today's reading, X%, reads a little high; this run used Y%, … higher than today's reading". The branch fires on `_differs`, a gap above about 10^-9. When the two figures are under 0.005 points apart they print the same at two decimals ("today's reading, 2.29% … this run used 2.29%, … higher"), which reads as a contradiction. Not visible today: only Coca-Cola gets charges notes and its gaps start at 0.02 points (#618 Results), but a later reading change could make it so.
2. **No hint at why a run read differently** (analyst, rejected for #618 as a `reason` param). The single-value cells' `run_read_differently` (risk-free, beta, ERP, cost of debt, shares, balances, debt; `single_values._read_differently`) carries `period`, `run_value` and `value` only. The history cells' copy of the same code (`inputs._with_run_reads`, since #477) already carries `run_rules_version` (the run's stored `reading_rules_version`, null before v0.9.67) and `rules_version` (today's `READING_RULES_VERSION`). The two copies of one code disagree on params, and the cost-of-debt card, the one that shows the note on 696 cells, gets the poorer one.

## Plan

**Step 0. This doc.**

**Step 1. The charges note says "higher" or "lower" only when the figures print differently.**

- In `_charges_notes`, the two-figure branch is taken when `f"{kd:.2%}" != f"{today:.2%}"` (both known), not on `_differs`. When the figures differ but print the same, the note keeps the plain text (the run's figure and today's are the same to the shown precision, and the plain text is true of both). The params are unchanged: `cost_of_debt` and `todays_cost_of_debt` still carry the two raw values, so the app can still word its own branch from them; the brief will say to compare them as the Spanish screen prints them (see Product impact). The plain text is kept word for word ("… so Warren cannot take it out and this cost of debt reads a little high (interest_caveats.csv)").
- Tests (`tests/analysis/test_charges_caveats.py`): an older run whose row is 0.0001 points (a fraction of 0.000001) above today's reading (differs, prints the same) gets the plain text, no "higher" or "lower", with both raw params; a gap of 0.0001 that crosses a rounding edge (today 4.00% against a run row of 4.01%, 0.01 points apart) gets the two-figure text; the existing 6% and 3.5% cases (`test_the_charges_note_gives_todays_reading_beside_the_runs`) are unchanged.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. `run_read_differently` on a single-value cell carries the reading rules versions.**

- New `single_values.run_reading_versions(run)` (and `reading_versions(singles)`, cached per answer) gives three stored facts: `run_rules_version` (the run's `reading_rules_version`, null on runs stored before v0.9.67), `rules_version` (today's `READING_RULES_VERSION`) and `run_concept_map_same` (the run's stored `concept_map_sha256` equals today's map's; analyst blocker). `_read_differently` and `_checked` take them as an argument from `Singles`; `inputs._with_run_reads` takes them instead of the bare version, so both copies of `run_read_differently` carry the same params. The `cost_of_debt` cell's copy (`_cost_of_debt_cell_notes`) stays identical to the used point's.
- Both copies keep their own English text (they already differ, and the app words the code from params), and neither states a cause. The hint is one-sided and the docstring says so: different versions or maps mean the reading changed since the run (the gap may also hold a later filing); equal versions and the same map rule out a change to the versioned code (`reading_rules.py`), to `misdated_facts.csv` (in `RULES_DATA`) and to the map, leaving a later filing or download. `interest_caveats.csv` is not a cause: it only adds notes and never moves a figure (analyst). A null run version means unknown, never "the same" (professor). The version is one number for every rule, so on a market cell a different version does not say the rules changed that cell (analyst).
- Tests (`tests/analysis/test_single_values.py`): Test Corp with its beta row and its FY2018 working-capital row edited gets `run_read_differently` on both, with the same param names and today's version and map; with the run's stored version set to 9 and to NULL and its map fingerprint changed, both copies follow (`run_concept_map_same` false). The cost-of-debt cell's copy stays equal to the point's (`test_charges_caveats.py`, existing).
- Exit: as Step 1.

**Step 3. Real data.** On the restored snapshot, every stored run's cost-of-debt cell (`cost_of_debt_notes(conn, run_id, years=10)`, every run in `runs`): the 696 cells (one per run) with `run_read_differently` carry the three params; count them by (run version, same map), the null versions apart; count charges notes whose two printed figures are equal and confirm none says "higher" or "lower"; `python -m domains.analysis reproduce --all` to the cent. Exit: those counts in Results below, no figure changed, reproduce 936 of 936.

## Design review (nov.28.2026)

Explainer, analyst, professor and product lead: professor GO, the other three GO with changes; no NO-GO.

- **Taken.** A stored-fact flag `run_concept_map_same` on both copies, since the map is not in the version (analyst blocker, `reading_rules.py` line 36, `math_engine.py` line 2644); `interest_caveats.csv` dropped from the causes equal versions leave open, as it never moves a figure (analyst blocker); the version is global, so a market cell's gap says little (analyst); null means unknown, in the docstring (professor); one unit in the test gaps (professor, explainer); "the brief says" corrected to what the brief will need, and "as printed" defined as the Spanish screen's own format (product lead); how the versions reach `_read_differently`, which copy is the cell's, the texts left as they are, the test files, ten years and the run list in Step 3 (explainer).
- **Not taken.** None rejected. The professor's idea, a student gloss of the version pair, goes to the front-end team with the Product impact.

## Alternatives considered

- **Round both figures before comparing in the text (gatekeeper's first option).** Same outcome as Step 1's comparison of printed strings; the printed comparison is what the reader sees, so it is the one that cannot contradict itself.
- **A `reason` code on `run_read_differently`** (analyst, #618). Still rejected: the engine cannot tell a rule change from a restatement without rebuilding under each rule set. Two versions are facts the run stored; a reason would be a guess.
- **The run's concept map fingerprint as a param.** A student cannot read a hash, and comparing it is the engine's job; `run_concept_map_same` is the comparison, a stored fact (analyst).

## Files to change

`domains/analysis/single_values.py`, `tests/analysis/test_charges_caveats.py`, `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (none: backlog items are not in Section 2).

## Product impact

Serves brief Q3, Q4 and Q8 (the cost-of-debt card) and every single-value card on older runs. No number, code, field or text the app shows is renamed or removed. Three params join `run_read_differently` on single-value points and on the `cost_of_debt` cell (`run_rules_version`, `rules_version`, `run_concept_map_same`), and `run_concept_map_same` joins the history cells' copy, so the app reads one shape for the code. Read them as the brief's "Two runs of the same date" rules (§3): a null version says nothing; equal versions and the same map leave a later filing or download; a different version on a market cell does not mean the rules changed that cell. The charges notes' English text keeps the plain wording when the two figures print the same at two decimals. For the front-end team (product lead): the brief has no Spanish yet for `run_read_differently` on the cost-of-debt cell nor for the charges notes' two-figure branch (v0.10.58); when it adds them, the Spanish branch should compare the figures exactly as the Spanish screen prints them (its precision and decimal comma), so it never says "más alto" between figures that look the same. Nothing for the first screen (PR #510) changes.
