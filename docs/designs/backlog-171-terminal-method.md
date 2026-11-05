# Backlog #171, part 2: the terminal formula switched on a what-if

Issue: https://github.com/sonderbot-ar/warren/issues/171 · Branch `backlog-171-terminal-method` · Version v0.9.21 when merged. Part 1 (WACC set directly) merged as v0.9.20: `docs/designs/backlog-171-wacc-set.md`.

## Problem

Brief §2 (`docs/product/brief.md`) lists the terminal value method among the inputs a student may change ("Warren's, or Gordon's for contrast"). It is the owner's choice under Decision 4 (`terminal_method`, a `user` row on every run since M4), so it waited for a card. **Owner decision (nov.05.2026, decision card):** yes, on what-ifs only; every stored run keeps the owner's choice. Recorded in `docs/structure-guide.md`, Decision 4.

## What changes

1. **`Change("terminal_method", method="gordon_fcff")`** (or `value_driver_ronic_wacc`). `Change` gains an optional `method` (text); exactly one of `value`, `delta` and `method`, and `method` only for `terminal_method` (`method_on_number` / `value_and_delta` otherwise). A choice outside `dcf.GORDON`, `dcf.VALUE_DRIVER` is `unknown_terminal_method`; the parent's own choice is `same_terminal_method` (nothing would change).
2. **The child's row.** The parent's `terminal_method` row is replaced by a `user` row with value None and method `<choice>: what-if on <parent>: switched from <old> (a student's contrast, allowed on what-ifs only, owner decision nov.05.2026)`; `dcf.terminal_method` reads the choice before the first colon, as for every run. A parent stored before M4 has no row (Gordon); the child gets a new row, as part 1 does for `wacc`. Its source is `what_if` with `before` None and `how` `switch`.
3. **What it moves.** Only the terminal value and what follows from it (present value of the terminal value, enterprise value, its terminal share, the value as of the date, equity value, value per share). `driven_by` adds `terminal_method` to those lines. Under Gordon the existing checks apply to the child as to any Gordon run: WACC − g must be positive (`growth_not_below_rate`, now with both rates), and the thin-spread warnings (`thin_terminal_spread`, and at ERP ± 1 SE) are stored on the child.
4. **Notes.** `terminal_method_switched` (params `before`, `after`), and the answer's `terminal_method` and `terminal_formula` are the child's, not the parent's. Switching to Gordon adds `gordon_implied_ronic` (params `implied_ronic`, `reinvestment_rate`, `terminal_growth`; from `fm.reinvestment_rate` on year 5's FCFF and NOPAT and `fm.implied_ronic`, as the sensitivity grid does): the return on new investment the Gordon value quietly assumes. When year 5's reinvestment is zero or negative there is no implied return; the note carries `implied_ronic` None and says growth would come from nothing. `ronic_follows_wacc` (part 1) follows the child's method.
5. **Combined changes.** The switch can go with any other change (a margin, a set WACC, terminal growth). Nothing follows it automatically.

**Point in time.** The child reads only the parent's rows and outputs. **LLMs.** None.

## Steps

- **Step 0.** This design doc and the Decision 4 entry.
- **Step 1.** `whatif` takes the switch; `sources.for_child` and `_child_rows` handle the method row; notes. Tests (`tests/analysis/test_whatif.py`): a switch to Gordon equals `dcf.compute` with `terminal_method` replaced, to the bit; the explicit-period lines and the cost of capital don't move; the child reproduces; its row is `user` with the parent named; switching back from a Gordon child's parent works the other way; a pre-M4 parent (no row) gets a new row; refusals (`unknown_terminal_method`, `same_terminal_method`, `method` on another input, `method` with `value`) store nothing; the Gordon child stores its thin-spread warning when the spread is thin; `gordon_implied_ronic` equals `fm.implied_ronic(g, fm.reinvestment_rate(fcff_Y5, nopat_Y5))`; combined with a set WACC it reproduces; the CLI takes `--switch terminal_method=gordon_fcff`. Exit: green, ruff clean.
- **Step 2.** Real data: the switch on the latest run of each company; each child reproduces; `reproduce --all` passes. Results below.

## Alternatives considered

- **A boolean "contrast" flag instead of a named method.** Rejected: a named method also lets a pre-M4 Gordon run be seen under the value driver.
- **Store nothing, compute the contrast on the fly** (as the grid does). Rejected: the brief asks for a what-if, which is stored and re-checkable.

## Product impact

Serves brief §2's last input ("the terminal value method"). Adds `Change(..., method=…)`; refusal codes `unknown_terminal_method` (params `method`, `allowed`), `same_terminal_method` (params `method`), `method_on_number` (params `name`); note codes `terminal_method_switched` (`before`, `after`) and `gordon_implied_ronic` (`implied_ronic` or None, `reinvestment_rate`, `terminal_growth`); a change row whose `before` and `after` are the method names and `how` `switch`. Label the answer as a hypothetical contrast, never as Warren's value (principle 4). Nothing renamed or removed.
