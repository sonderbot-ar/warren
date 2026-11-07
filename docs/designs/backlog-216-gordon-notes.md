# Backlog #216: one Gordon reinvestment helper for the grid and the what-if, and the terminal switch's test gaps

Issue: https://github.com/sonderbot-ar/warren/issues/216 · Branch `backlog-216-gordon-notes`.

## Problem

The gatekeeper's review of PR #215 (v0.9.21, the terminal formula switch on a what-if) left three gaps. All of today's outputs are correct.

1. **No test for two switches.** `_shape_rows` (`domains/analysis/whatif.py`, the `TERMINAL` branch) refuses a request that switches `terminal_method` twice with `duplicate_change`, and no test covers it. Deleting the check would let the second switch silently win.
2. **A test with a branch it never takes.** `test_a_switch_to_gordon_names_what_it_assumes_with_the_grids_codes` has `if reinvest > 0: … else: …`, and the test company always reinvests in year 5, so the `else` (the `gordon_reinvestment_not_positive` note) is never exercised through `revalue`. Only a unit test on `_gordon_notes` covers it.
3. **The same logic twice.** What a Gordon value assumes about year 5 (the reinvestment rate 1 − FCFF ÷ NOPAT, "no rate" when NOPAT is not positive, "reinvests nothing" when the rate is at or below zero, and the implied return on new investment g ÷ rate) is written once in `sensitivity._block` / `_cell` / `_notes` and again in `whatif._gordon_notes`. The two give the front end the same codes (`gordon_holds_reinvestment`, `gordon_reinvestment_not_positive`) with the same params, so one screen sentence serves both (product lead, v0.9.21). If one copy changes its condition and the other doesn't, the grid and the what-if would tell a student different things about the same run.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. One helper.** New module `domains/analysis/gordon.py` with:
  - `year5_reinvestment(fcff, nopat)`: `financial_math.reinvestment_rate`, or None when NOPAT is at or below zero or either cash flow is not a finite number;
  - `reinvests(rate)`: the rate is not None and above zero;
  - `implied_ronic(growth, rate)`: `financial_math.implied_ronic` when `reinvests(rate)`, else None;
  - `reinvestment_notes(rate, held_text, not_positive_text)`: the `gordon_holds_reinvestment` note, then `gordon_reinvestment_not_positive` when the rate doesn't reinvest, with the codes and params in one place and each caller's own English sentence (the grid speaks of "its table", the what-if of "its value"; both texts stay byte for byte).
  The grid (`_block`, `_cell`, `_notes`) and the what-if (`_gordon_notes`) call it; nothing else changes. The math stays in `financial_math.py`.
  Tests: `tests/analysis/test_gordon.py` (positive, zero and negative reinvestment; NOPAT zero and negative; the implied return only when reinvesting; the notes' codes, params and order); a test that on the same parent the what-if's Gordon switch and the grid's Gordon table give the same `gordon_holds_reinvestment` params, and the same `implied_ronic` at the run's own WACC and growth.
  Exit: every existing grid and what-if test passes unchanged.
- **Step 2. The two test gaps.** A `duplicate_change` case for two `terminal_method` switches (code, params `name` and `period`, nothing stored). The if/else test splits into two tests, each asserting the branch it takes: the reinvesting test company (implied return note, no not-positive note), and one `revalue` request that sets year 5's capex share to 0 beside the switch, so year 5 takes capital out (rate below zero, asserted): the switch to Gordon gives `gordon_holds_reinvestment` and `gordon_reinvestment_not_positive` and no `gordon_implied_ronic`, and the child reproduces.
  Exit: tests pass; deleting the `duplicate_change` check, or the `not reinvests` branch, each fails a test.
- **Step 3. Real data, bit for bit.** On the restored snapshot, before (main) and after (branch): the sensitivity grid's JSON for each company's latest baseline, and the notes of a Gordon switch what-if on the same runs (on a throwaway copy of the database, so nothing is stored), compared byte for byte; plus `reproduce --all`.
  Exit: identical JSON and every run reproduces.

**NaN.** Before this change a NaN reinvestment rate (only possible from a NaN cash flow, which no stored run has: the what-if refuses NaN inputs with `invalid_input`) was read two ways: the what-if gave no not-positive note and a NaN implied return, the grid gave no not-positive note and no implied return in its cells. Now both say "no rate". No real output can change; the real-data check in Step 3 confirms it.

**Exit criterion:** all tests pass, ruff clean, no request changes outcome, no stored number or text changes, the real-data comparison is identical.

**Point in time.** Nothing new is read. **LLMs.** None. **Decision 11.** No new source, company or currency; the helper is a library function.

## Alternatives considered

- **Put the helper in `sensitivity.py` and import it from the what-if.** Rejected: `sensitivity` already imports `whatif`, so the what-if importing back would be circular; a small module both import is cleaner.
- **Put it in `financial_math.py`.** Rejected: the two formulas are already there; the rest (None for no rate, which note to give) is about what a Gordon value assumes, not arithmetic, and `financial_math` returns numbers only.
- **One English sentence for both.** Rejected for this item: the grid's sentence speaks of a table and adds a line about each cell; changing the text is a wording change the front end would see. The codes and params are what must not drift, and they now live in one place.
- **A hand-saved parent that doesn't reinvest.** Rejected after review (analyst): a what-if can't be a parent, so it would need rows and sources written by hand; one request with year 5's capex at 0 beside the switch goes through `revalue` end to end with nothing built by hand.
- **Test the non-reinvesting branch by patching `reinvestment_rate`.** Rejected: the issue asks for a fixture that takes the branch end to end through `revalue`; a patched function proves less.

## Files to change

`domains/analysis/gordon.py` (new), `domains/analysis/sensitivity.py`, `domains/analysis/whatif.py`, `tests/analysis/test_gordon.py` (new), `tests/analysis/test_whatif.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No code, param, output or English text added, renamed or removed; no request changes outcome. Brief questions 7 and 8 (what-if) and 9 (sensitivity) unchanged. The grid and the what-if now share one rule for when a Gordon value "reinvests nothing", so the app's sentence for `gordon_reinvestment_not_positive` can't be true on one screen and false on the other.

## Design review (nov.07.2026)

Explainer, analyst and professor in one fresh-context panel. GO, no blockers, on one condition: pin how NaN is read (analyst A1: `reinvestment_rate` lets a NaN through, `financial_math.py:222`, and the old grid and what-if read it differently). Taken: a NaN or infinite cash flow means no rate, in both, with test cases. Also taken: the single-request fixture instead of a hand-saved parent (A4), and exact equality in the grid-against-what-if test (A2: outputs are stored unrounded). The professor found the method defensible (g = reinvestment rate × RONIC; Koller, Goedhart and Wessels ch. 14; Damodaran ch. 12) and no scope creep. The explainer's other guesses are answered above (`gordon_implied_ronic` stays in the what-if; the grid has no such note).

## Results (nov.07.2026)

- Full suite: 1,530 passed, 10 skipped (browser tests without Chromium here; CI runs them). Ruff clean.
- Mutations: deleting the two-switch check fails the new refusal test; dropping the "doesn't reinvest" branch in `gordon.reinvestment_notes` fails 7 tests across the grid, the what-if and the helper.
- Real data (snapshot of nov.05, 903 stored baselines): the sensitivity grid's JSON on every baseline, and the notes of a switch to Gordon on every baseline (on a throwaway copy of the database), are identical byte for byte before and after (903 and 903 lines). Of the 903 switches, 380 imply a return on new investment and 523 reinvest nothing in year 5, the same split in the grid's notes. 903 of 903 runs reproduce to the cent.
