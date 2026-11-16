# Backlog #171, part 2: the terminal formula switched on a what-if

Issue: https://github.com/sonderbot-ar/warren/issues/171 · Branch `backlog-171-terminal-method` · Version v0.9.21 when merged. Part 1 (WACC set directly) merged as v0.9.20: `docs/designs/backlog-171-wacc-set.md`.

## Problem

Brief §2 (`docs/product/brief.md`) lists the terminal value method among the inputs a student may change ("Warren's, or Gordon's for contrast"). It is the owner's choice under Decision 4 (`terminal_method`, a `user` row on every run since M4), so it waited for a card. **Owner decision (nov.05.2026, decision card):** yes, on what-ifs only; every stored run keeps the owner's choice. Recorded in `docs/structure-guide.md`, Decision 4.

## What changes

1. **`Change("terminal_method", method="gordon_fcff")`** (or `value_driver_ronic_wacc`). `Change` gains an optional `method` (text); exactly one of `value`, `delta` and `method`, and `method` only for `terminal_method` (`method_on_number` / `value_and_delta` otherwise). A choice outside `dcf.GORDON`, `dcf.VALUE_DRIVER` is `unknown_terminal_method`; the parent's own choice is `same_terminal_method` (nothing would change).
2. **The child's row.** The parent's `terminal_method` row is replaced by a `user` row with value None and method `<choice>: what-if on <parent>: switched from <old> (a student's contrast, allowed on what-ifs only, owner decision nov.05.2026)`; `dcf.terminal_method` reads the choice before the first colon, as for every run. A parent stored before M4 has no row (Gordon); the child gets a new row, as part 1 does for `wacc`. Its source is `what_if` with `before` the parent's method name and `how` `switch`; the change row's `before` and `after` are method names (strings), every other change row's are numbers.
3. **What it moves.** Only the terminal value and what follows from it (present value of the terminal value, enterprise value, its terminal share, the value as of the date, equity value, value per share). `driven_by` adds `terminal_method` to those lines. Under Gordon the existing checks apply to the child as to any Gordon run: WACC − g must be positive (`growth_not_below_rate`, now with both rates), and the thin-spread warnings (`thin_terminal_spread`, and at ERP ± 1 SE) are stored on the child.
4. **Notes.** `terminal_method_switched` (params `before`, `after`), and the answer's `terminal_method` and `terminal_formula` are the child's, not the parent's. Switching to Gordon adds the sensitivity grid's own codes with its params (product lead: one screen string serves both): `gordon_holds_reinvestment` (`reinvestment_rate`), and, when year 5 reinvests nothing or takes capital out, or NOPAT is not positive (`fm.reinvestment_rate` refuses; reinvestment rate None), `gordon_reinvestment_not_positive` (`reinvestment_rate`: read the value as a formula, not a valuation; analyst: JNJ and AAPL today). Otherwise `gordon_implied_ronic` (`implied_ronic`, `reinvestment_rate`, `terminal_growth`, `wacc`; `fm.implied_ronic`): the return on new investment the Gordon value assumes, beside WACC so the app can say how far above it is. `ronic_follows_wacc` (part 1) follows the child's method.
5. **Combined changes.** The switch can go with any other change (a margin, a set WACC, terminal growth). Nothing follows it automatically.

**Point in time.** The child reads only the parent's rows and outputs. **LLMs.** None.

## Steps

- **Step 0.** This design doc and the Decision 4 entry.
- **Step 1.** `whatif` takes the switch; `sources.for_child` and `_child_rows` handle the method row; notes. Tests (`tests/analysis/test_whatif.py`): a switch to Gordon equals `dcf.compute` with `terminal_method` replaced, to the bit; the explicit-period lines and the cost of capital don't move; the child reproduces; its row is `user` with the parent named; switching back from a Gordon child's parent works the other way; a pre-M4 parent (no row) gets a new row; refusals (`unknown_terminal_method`, `same_terminal_method`, `method` on another input, `method` with `value`) store nothing; the Gordon child stores its thin-spread warning when the spread is thin; `gordon_implied_ronic` equals `fm.implied_ronic(g, fm.reinvestment_rate(fcff_Y5, nopat_Y5))`; combined with a set WACC it reproduces; the grid's codes on a Gordon child, and the notes for negative reinvestment and negative NOPAT; `ronic_follows_wacc` absent on a Gordon child and present on a switch back to the value driver; the CLI takes `--switch terminal_method=gordon_fcff`. Exit: green, ruff clean.
- **Step 2.** Real data: the switch on the latest run of each company; each child reproduces; `reproduce --all` passes. Results below.

## Alternatives considered

- **A boolean "contrast" flag instead of a named method.** Rejected: a named method also lets a pre-M4 Gordon run be seen under the value driver.
- **Store nothing, compute the contrast on the fly** (as the grid does). Rejected: the brief asks for a what-if, which is stored and re-checkable.

## Product impact

Serves brief §2's last input ("the terminal value method"). Adds `Change(..., method=…)`; refusal codes `unknown_terminal_method` (params `method`, `allowed`), `same_terminal_method` (params `method`), `method_on_number` (params `name`); note codes `terminal_method_switched` (`before`, `after`), `gordon_implied_ronic` (`implied_ronic`, `reinvestment_rate`, `terminal_growth`, `wacc`), and the grid's `gordon_holds_reinvestment` and `gordon_reinvestment_not_positive` (`reinvestment_rate`, None when NOPAT is not positive) with the grid's params; a change row whose `before` and `after` are the method names (strings) and `how` `switch`. The parent's value per share is the line's `before`, so a screen can always show Warren's formula beside the contrast. Label the answer as a hypothetical contrast, never as Warren's value (principle 4). Nothing renamed or removed.

## Design review (nov.05.2026)

Explainer, analyst, professor and product lead in one fresh-context panel; the analyst ran Gordon on every run as of 2026-10-30: JNJ $168 → $658 (year-5 reinvestment −17.7%, no implied return), XOM $116 → $406 (implied RONIC 100%), PG $104 → $265 (226%), KO $37 → $114 (77%), CAT $218 → $358 (105%), AAPL $95 → $143 (reinvestment −3.1%), MSFT $204 → $209 (12%), WMT $31 → $39 (11%). Accepted:

- **Negative NOPAT (analyst; must-fix).** `fm.reinvestment_rate` refuses it; the note now handles it (reinvestment rate None) and a test covers it.
- **The grid's codes (analyst, product lead; must-fix).** `gordon_holds_reinvestment` and `gordon_reinvestment_not_positive`, with the grid's params, so JNJ's $658 always comes with "read it as a formula, not a valuation".
- **The change row's types (explainer, product lead; must-fix).** Stated in item 2 and Product impact.
- **`ronic_follows_wacc` follows the child (analyst).** Tested both ways.
- **RONIC far above WACC (analyst, idea).** `gordon_implied_ronic` carries `wacc` beside the return.
- **A citation in the switch note (professor, idea).** Koller, Goedhart and Wessels, ch. 14.

## Results on real data (Step 2, nov.05.2026)

The switch to Gordon on the latest run of each company (as of 2026-10-30; every one is a value-driver run with terminal growth 4.98%), value per share before → after:

- MSFT $203.55 → $208.92 (+3%, implied return on new investment 12%), WMT $31.24 → $39.26 (+26%, 11%): close, because both reinvest a lot in year 5.
- CAT $218.45 → $357.95 (+64%, 105%), KO $37.37 → $113.63 (+204%, 77%), PG $104.13 → $264.70 (+154%, 226%), XOM $116.23 → $406.48 (+250%, 100%): Gordon rests on returns many times WACC.
- AAPL $95.21 → $143.08 (+50%) and JNJ $168.01 → $658.32 (+292%): year 5 takes capital out, so `gordon_reinvestment_not_positive` fires on both.
- `thin_terminal_spread` is stored on JNJ, KO, PG and XOM (WACC − g under 3 points), and the ERP-bound spread warning on all eight.
- Every child reproduces; `python -m domains.analysis reproduce --all`: 929 of 929 runs to the cent (903 stored, 26 children made on this machine and not saved to the shared snapshot).

## Merged

nov.05.2026 as v0.9.21, PR #215, merge `af485b2`, after the gatekeeper's GO. The review's ideas are in #216. #171 is done.
