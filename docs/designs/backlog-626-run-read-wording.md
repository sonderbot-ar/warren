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

- In `_charges_notes`, the two-figure branch is taken when `f"{kd:.2%}" != f"{today:.2%}"` (both known), not on `_differs`. When the figures differ but print the same, the note keeps the plain text (the run's figure and today's are the same to the shown precision, and the plain text is true of both). The params are unchanged: `cost_of_debt` and `todays_cost_of_debt` still carry the two raw values, so the app can still word its own branch from them (it formats with its own rule; the brief says to round before comparing, see Product impact).
- Tests (`tests/analysis/test_charges_caveats.py`): an older run whose row is 0.00001 above today's reading (differs, prints the same) gets the plain text, no "higher" or "lower", with both raw params; a gap of 0.0001 that crosses a rounding edge (today 4.00% against a run row of 4.01%, 0.01 points apart) gets the two-figure text; the existing 6% and 3.5% cases are unchanged.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. `run_read_differently` on a single-value cell carries the reading rules versions.**

- `single_values._read_differently` adds `run_rules_version` (the run's `reading_rules_version`, null on runs stored before v0.9.67) and `rules_version` (today's `READING_RULES_VERSION`) to the note's params, the same names and meaning as the history cells' copy in `inputs._with_run_reads`. Every caller passes the run (`_checked`, the cost-of-debt cell, `cost_of_debt_notes`); the cell's copy stays identical to the point's.
- The text is unchanged and states no cause. The hint is one-sided and the docstring says so: different versions mean the reading code changed since the run (the gap may also hold a later filing); equal versions rule out a change to the versioned code and `misdated_facts.csv` only, not a concept map change (the run's `concept_map_sha256` is separate) nor `interest_caveats.csv` nor a later filing or download. A null run version says nothing.
- Tests: an older run (row edited) gets the two params on the point's and the cell's copy (`tests/analysis/test_charges_caveats.py`), and `run_rules_version` follows the run's stored column (set to 9 and to NULL); the single-value and history cells' copies have the same param names (a test that builds both on Test Corp with an edited row each).
- Exit: as Step 1.

**Step 3. Real data.** On the restored snapshot, every stored run's cost-of-debt cell (`cost_of_debt_notes`, ten years): the 696 cells with `run_read_differently` carry both versions; count them by (run version, today's version), the null ones apart; no charges note says "higher" or "lower" between figures that print the same; `reproduce --all` to the cent. Exit: as stated.

## Alternatives considered

- **Round both figures before comparing in the text (gatekeeper's first option).** Same outcome as Step 1's comparison of printed strings; the printed comparison is what the reader sees, so it is the one that cannot contradict itself.
- **A `reason` code on `run_read_differently`** (analyst, #618). Still rejected: the engine cannot tell a rule change from a restatement without rebuilding under each rule set. Two versions are facts the run stored; a reason would be a guess.
- **Add the run's concept map fingerprint too.** The history cells' copy does not carry it, and fingerprints are not something a student reads; the report's Data snapshot section already shows both. Left out to keep the two copies equal.

## Files to change

`domains/analysis/single_values.py`, `tests/analysis/test_charges_caveats.py`, `docs/versions.md`, `docs/team-sync.md`, `docs/build-plan.md` (none: backlog items are not in Section 2).

## Product impact

Serves brief Q3, Q4 and Q8 (the cost-of-debt card) and every single-value card on older runs. No number, code, field or text the app shows is renamed or removed. Two params join `run_read_differently` on single-value points and on the `cost_of_debt` cell (`run_rules_version`, `rules_version`), already on the history cells' copy, so the app reads one shape for the code. The charges notes' English text keeps the plain wording when the two figures print the same at two decimals; the app's own Spanish branch should compare the figures as it prints them, for the same reason. Nothing for the first screen (PR #510) changes.
