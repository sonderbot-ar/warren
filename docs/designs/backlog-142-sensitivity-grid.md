# Backlog #142: sensitivity grid, value per share over WACC and terminal growth

Issue: https://github.com/sonderbot-ar/warren/issues/142 · Branch `backlog-142-sensitivity-grid` · Version v0.9.12 when merged.

## Problem

The front-end team's request R2b (brief question 9, `docs/product/brief.md` §3: "¿Qué tan sensible es el valor de Coca-Cola al WACC y al crecimiento terminal?"). The classroom DCF exercise is a table of value per share over WACC and terminal growth. Today a run stores one value per share and the two ERP ± 1 standard error values (`dcf.outputs_and_gaps`); the what-if (v0.9.9) changes inputs one request at a time and cannot set WACC at all, because WACC is an output of CAPM and the capital weights, not a row (#171).

The brief asks for: the grid with the run's own point marked; the lesson that under Warren's terminal method (value driver, RONIC = WACC, Structure Guide Decision 4, oct.30.2026) the table is almost flat along growth and steep along WACC; the textbook Gordon model beside it for contrast; and cells where growth reaches WACC shown as "no value" with the existing reason, never as zero, under both methods (v0.5.4, #79).

## What changes

A new module `domains/analysis/sensitivity.py` with `grid(conn, run_id, wacc_steps=WACC_STEPS, growth_steps=GROWTH_STEPS) -> Grid`, and a command `python -m domains.analysis sensitivity --run-id R [--wacc-steps -0.02,-0.01,0,0.01,0.02] [--growth-steps -0.01,-0.005,0,0.005,0.01] [--json]`.

1. **The two axes.** Each axis is a list of shifts from the run's own value, in fractions (0.01 = one point): WACC from the run's WACC (`wacc` output), terminal growth from its `terminal_growth` row. Defaults: WACC −2, −1, 0, +1, +2 points; growth −1, −0.5, 0, +0.5, +1 point (5 × 5). A shift of 0 is always on each axis (added if missing), so the run's own point is always in the grid and marked (`run_point`: its row and column). Each axis has 2 to 9 distinct finite shifts, sorted; anything else is refused with a code (`too_few_steps`, `too_many_steps`, `invalid_input`, `duplicate_step`). The grid also lists each axis's absolute values, so the app shows "WACC 9.1%" and never adds.
2. **WACC set directly, as a teaching override, in memory only.** `dcf.Inputs` gains an optional `wacc_override` (default None). When set, it replaces the run's WACC in every period's discount rate and in the roll-forward to the as-of date; the cost of equity, the weights and every cash flow stay as stored. With `wacc_override` None, `dcf.compute` is unchanged, so every stored run reproduces as before (tested: `reproduce --all` on the real data, and a test that override = the run's own WACC gives the stored outputs bit for bit). An override together with a cost-of-equity shift (the Monte Carlo's) is refused (`DCFInputError`): the two are different questions. Nothing is stored: a cell is not a run, and WACC is still not an input of any stored run (that stays #171, which needs to say what a direct WACC means for the cost of equity and the weights).
3. **Terminal growth moves the terminal value only.** On this grid a growth shift changes the `terminal_growth` row and nothing else: the explicit-period revenue growth path keeps its stored values. This is the textbook table (the growth in it is the perpetuity's), and it is what the brief's lesson is about. It differs on purpose from the what-if, which refades the path when terminal growth moves (v0.9.9 item 3); a note says so (`growth_path_held`) and the app can send the student to the what-if for the other reading.
4. **The run's method and the contrast.** Each cell is valued twice: under the run's own terminal method (`method`: `value_driver_ronic_wacc` for every run since M4, `gordon_fcff` for older ones) and under the other one (`contrast`), labelled as a contrast, never as the run's value. The run's method and its stored choice are untouched. Each block carries its formula as the what-if's coded `terminal_formula` (`whatif.TERMINAL_FORMULAS`).
5. **A cell.** `wacc`, `terminal_growth` (absolute), `wacc_step`, `growth_step`, `value_per_share`, `change_pct` (against the run's own point under the same method; `fm.growth`, None when the base is not positive), `terminal_share` (share of enterprise value from the terminal value) and `gap`. A cell with no value (terminal growth at or above WACC: `growth_not_below_rate`; WACC at or below zero: `rate_not_positive`) has `value_per_share` None and `gap` as `{code, params, text}` with the reason code from `financial_math` and `text.REASON_WORDS`; any other `FinancialMathError` is raised, as in `dcf.outputs_and_gaps` (#9 review). The run's own point under the run's method equals the stored `value_per_share` exactly (tested).
6. **What the call returns.** `Grid.to_dict()`: `run_id`, `ticker`, `as_of`, `currency`, `wacc_values`, `growth_values`, `wacc_steps`, `growth_steps`, `run_point` (`{row, column}`; rows are WACC, columns growth), `method` and `contrast` (each `{terminal_method, terminal_formula, cells[row][column]}`), `spread` per block (`value_per_share` at the run's growth across the WACC axis's ends and at the run's WACC across the growth axis's ends, with `change_pct` against the run's point: the two numbers the lesson compares, computed here so the app does no arithmetic; None where an end has no value), and `notes[]` (codeds: `wacc_set_directly`, `growth_path_held`, `contrast_method`). A what-if child (`parent_run_id` set) may be the grid's run: its rows are a run like any other.

**Point in time.** No data is read: the grid revalues the run's stored rows, which were point in time on the run's date. Nothing it computes is newer than the run.

**LLMs.** None. Every number comes from `dcf` and `financial_math`.

**Storage and reproducibility.** Nothing is stored and no migration is needed. The grid is a pure function of the run's stored rows and the two step lists, so the same call returns the same numbers to the cent; a test checks this by calling twice.

## Steps

- **Step 0.** This design doc; no build plan change (a backlog item).
- **Step 1.** `dcf.Inputs.wacc_override` and its use in `discount_rates`, `base_wacc` and the roll-forward. Tests (`tests/analysis/test_dcf.py`, plus a property test in the `financial_math` property suite style): None gives the outputs of today's code on the test company and on random inputs; override = the run's WACC gives the stored outputs exactly; a higher override lowers value per share (value-driver and Gordon); an override with a cost-of-equity shift is refused; `reproduce` on the test company's run still passes. Exit: green.
- **Step 2.** `domains/analysis/sensitivity.py`: `grid`, `Grid.to_dict`, `GridError` (`code`, `params`, `text`), the axis checks, the two blocks, the spreads, the notes. Tests (`tests/analysis/test_sensitivity.py`, on the test company's stored run): the run's point equals the stored value per share under its method; the default grid is 5 × 5 with the point at (2, 2); a missing 0 is added; unsorted steps are sorted; 1 or 10 steps, NaN, and a duplicate are refused; a cell equals `dcf.value` on hand-edited rows with `wacc_override` to the cent; under value-driver the growth spread is smaller than under Gordon on the same run (the brief's lesson, on the test company); a cell with growth at WACC has `growth_not_below_rate` under both methods and None, never 0; a WACC at or below zero gives `rate_not_positive`; the explicit revenue growth path is the stored one in every cell; calling twice gives equal dicts; `to_dict` round-trips through `json`; a what-if child works as the run; an unknown run is refused (`no_run`); nothing is written to the database (row counts before and after). Exit: green.
- **Step 3.** The command `sensitivity` in `domains/analysis/__main__.py`: two tables (the run's method, then the contrast), the run's point marked, gaps as "n/a (WACC ≤ terminal growth)", the spreads, the notes; `--json` prints `to_dict` only. Tests (`tests/analysis/test_report_cli.py`): parsing the step lists, a refusal exits 1 with its message, `--json` is plain JSON. Exit: green; ruff clean.
- **Step 4.** Real data on the restored snapshot: brief Q9 as asked (Coca-Cola, latest stored run) and Microsoft and Walmart on theirs; `reproduce --all` before and after Step 1 still passes. Results written below. Exit: the run's point matches each stored value per share; the numbers are written here.

**Exit criterion:** all tests pass; `reproduce --all` passes on the real data; Step 4's numbers are written here; `docs/team-sync.md` names the call and its fields.

## Alternatives considered

- **Each cell as a stored what-if child** (the issue's "on the what-if revaluation"). Rejected: 25 to 81 stored runs per question, none of them a run anyone would reopen, and a direct WACC cannot be a stored row until #171 decides what it means for the cost of equity and weights. The grid reuses the what-if's pieces that fit (its terminal formulas and coded notes) and stays in memory.
- **Move WACC through an input that is a row** (ERP or beta, solved so WACC moves by the step). Rejected: the student asked about WACC; a hidden ERP that lands on the right WACC is a trick, it moves the weights' cost of equity too, and with no equity weight it cannot reach some WACCs.
- **Refade the revenue growth path with terminal growth, as the what-if does.** Rejected for the grid (item 3): it mixes a change in the explicit forecast into the column, so the table no longer shows the terminal value's sensitivity, which is the textbook object and the brief's lesson. The what-if keeps its rule; the note names the difference.
- **Absolute axis values instead of shifts.** Shifts keep the run's point in the grid by construction and let one default work for every company; absolute values are returned for display.
- **Any two inputs.** The issue says "first use"; the other pairs (margin × growth, beta × ERP) can be added with the same cell code when a brief question asks for them.

## Files to change

New: `domains/analysis/sensitivity.py`, `tests/analysis/test_sensitivity.py`. Changed: `domains/analysis/dcf.py` (`Inputs.wacc_override`), `domains/analysis/__main__.py` (`sensitivity`), `tests/analysis/test_dcf.py`, `tests/analysis/test_report_cli.py`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q9 "Hoy" line).

## Product impact

Serves brief question 9 (Sí once merged): the grid, the run's point, the contrast with Gordon and the "no value" cells. No existing output, name or field changes; nothing is stored; no migration.

Adds `domains.analysis.sensitivity.grid(conn, run_id, wacc_steps, growth_steps)`, `Grid.to_dict()`, `GridError` (`code`, `params`, `text`) and the command `sensitivity`. Fields of `to_dict`:

- top: `run_id`, `ticker`, `as_of`, `currency`, `wacc_steps`, `growth_steps`, `wacc_values`, `growth_values` (fractions), `run_point` (`row`, `column`), `method`, `contrast`, `notes[]` (codeds);
- a block (`method`, `contrast`): `terminal_method`, `terminal_formula` (coded, the what-if's), `cells` (rows by WACC, columns by growth), `spread` (`wacc_low`, `wacc_high`, `growth_low`, `growth_high`, each `value_per_share` and `change_pct`, None where there is no value);
- a cell: `wacc`, `terminal_growth`, `wacc_step`, `growth_step`, `value_per_share` (currency per share, or None), `change_pct` (fraction against the run's point under the same block, or None), `terminal_share` (fraction, or None), `gap` (None, or coded `growth_not_below_rate` / `rate_not_positive` with params `wacc` and `terminal_growth`);
- refusal codes: `no_run`, `too_few_steps`, `too_many_steps`, `duplicate_step`, `invalid_input`;
- note codes: `wacc_set_directly` (WACC set directly here, a teaching override: in the company's own valuation WACC comes from CAPM and the capital weights), `growth_path_held` (the explicit forecast is unchanged; the what-if refades it), `contrast_method` (params `terminal_method`: the contrast block is the other method, not the run's value).

The screen's sentence "casi plano a lo largo del crecimiento" is the app's words for the two `spread`s; the engine gives the numbers. Under the value-driver method, a growth step still moves value a little (NOPAT × (1 + g) in the numerator), and a WACC step moves it through every discount factor and the terminal value.
