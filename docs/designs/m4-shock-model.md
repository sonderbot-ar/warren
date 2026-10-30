# M4 design: shock model and Monte Carlo (manual shocks)

Status: In progress (oct.30.2026) · Elephant: agent team · Branch `m4-shock-model`
Implements Structure Guide Decisions 4 (Monte Carlo) and 6 (simulation step), and Build Plan M4.

## Problem

Warren's forecast is one path: one growth rate, one margin, one value per share (v0.2), scored against what companies later reported (v0.3). Decision 6 says news should change named drivers for a while, with a range rather than a point. M4 builds the deterministic half of that: a shock record, its shape over time, sampling its size, and a Monte Carlo run that reports p10/p50/p90 next to the baseline, period by period. Shocks are entered by hand here; M6 later lets an LLM *propose* them in the same schema. Nothing in M4 calls an LLM.

## The shock

```text
Shock
  shock_id, run_id (the baseline run it applies to), event_id (NULL for manual shocks)
  driver        : revenue_growth | operating_margin | capex_intensity | risk_premium
  low, base, high : p10 / p50 / p90 of the magnitude, low ≤ base ≤ high
                    percentage points for growth, margin and capex; basis points for risk premium
  start_period  : the first affected forecast quarter, as h (1 = the first forecast quarter)
  horizon       : quarters the shock can last, 1–20
  decay         : 0 < decay ≤ 1, share of the effect left each quarter (1 = constant within horizon)
  source        : user | llm_proposed
  rationale     : text, with the evidence it relies on (a URL or an accession number)
```

- **Unit of time is the quarter.** The forecast grid is 8 quarters, then Y3–Y5 (Build Plan M2). The shape is computed on a 20-quarter grid, h = 1…20; quarters 1–8 map one to one, and each of Y3, Y4, Y5 takes the **mean** of its four quarters' effects (quarters 9–12, 13–16, 17–20). A shock that ends inside a year therefore moves that year by the share of the year it covers. The Build Plan's "number of periods" is read as quarters; this is the only reading under which a decay rate means the same thing across the grid.
- **Time shape** (Build Plan M4): effect at quarter h = magnitude × decay^(h − start) for start ≤ h < start + horizon, else 0. Several shocks on one driver add up.
- **Drivers map onto the run's rows:**
  - `revenue_growth` → `revenue_growth` (quarters grow from the same quarter a year earlier, so a growth shock is a *level* shock that stays: a 5-point cut for one quarter leaves that quarter 5% lower, and the same quarter next year grows from the lower base. This is stated in the report.)
  - `operating_margin` → `operating_margin` (adds margin points to EBIT / revenue that quarter).
  - `capex_intensity` → `capex_pct`.
  - `risk_premium` → added to the cost of equity, in basis points, quarter by quarter. The discount rate of each period is the WACC rebuilt with that period's cost of equity (`financial_math.discount_factors` already takes one rate per period). The terminal value uses Y5's rate, so only a shock still active in Y5 moves it.
- **Invalid shocks are refused before any sampling:** unknown driver, low > base or base > high, start outside 1–20, start + horizon − 1 beyond 20 (clipped is silent, so it is refused), decay outside (0, 1].

## Sampling the magnitude

Each shock's magnitude is drawn from a **split normal fitted to the quantiles**: below the median it is a normal with σ_low = (base − low) / z₀.₉, above it a normal with σ_high = (high − base) / z₀.₉, and each side carries half the probability. z₀.₉ = 1.2815515655446004. Then low, base and high are exactly the p10, p50 and p90, which is what the Build Plan asks for (asymmetric ranges allowed). A draw is `base + z × (σ_low if z < 0 else σ_high)` with z standard normal.

This is not Wallis's (2014) continuous two-piece normal: that one has a continuous density but its mode, not its median, is the joining point, so its p10/p50/p90 would not equal low/base/high when the range is asymmetric. Matching the three numbers the user gave is worth the kink in the density at the median. low = base = high gives a constant: the shock becomes deterministic.

- **Independence.** Shocks are sampled independently (Build Plan M4, a stated Phase 1 simplification). One draw per shock per sample: the whole path of a shock scales together, so a sample is "a bigger or smaller version of the same event", never noise that changes sign from quarter to quarter.
- **Seed.** A stored integer seed feeds `numpy.random.Generator(PCG64(seed))`. z values are drawn as one N × (number of shocks) block, shocks in their stored order. numpy is pinned (requirements.txt), so the same seed, shocks and rows give the same percentiles on any machine.
- **The baseline is not sampled.** Only shocks carry uncertainty in M4. With no shocks, every sample equals the baseline. Sampling the baseline drivers or the ERP is left to M8 (calibration needs both).

## The Monte Carlo run

- `financial_math` gains two pure functions: `shock_shape(start, horizon, decay, quarters=20)` and `split_normal(low, base, high, z)`. No randomness inside `financial_math`: z comes in as an argument.
- `dcf.value` is split so the arithmetic runs on a dict of driver paths whose values can be floats or numpy arrays (the same code path for the baseline and for N samples, so a zero shock reproduces the baseline to the cent by construction, and a test proves it). `value(assumptions)` keeps its signature and outputs.
- `domains/analysis/montecarlo.py`: `simulate(rows, shocks, n=10_000, seed)` → per output (revenue, ebit, fcff per period; value per share, enterprise value) the p10, p50, p90 and mean over samples, next to the baseline value.
- **A sample that can't be valued stops the run.** If any sample puts WACC at or below terminal growth, or makes the share count or debt invalid, `FinancialMathError` is raised with the number of such samples. Dropping them silently would bias the percentiles; the user narrows the range instead.
- **Storage** (migration `0008_shocks.sql`):

```sql
shocks(shock_id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs, event_id TEXT NULL, driver TEXT,
       low REAL, base REAL, high REAL, start_period INTEGER, horizon INTEGER, decay REAL,
       source TEXT CHECK (source IN ('user', 'llm_proposed')), rationale TEXT NOT NULL)
simulations(sim_id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs, created_at TEXT, seed INTEGER,
            n_samples INTEGER, code_version TEXT, shocks_sha256 TEXT, notes TEXT)
simulation_shocks(sim_id TEXT, shock_id TEXT, position INTEGER)   -- order fixes the z columns
simulation_outputs(sim_id TEXT, name TEXT, period TEXT, baseline REAL,
                   p10 REAL, p50 REAL, p90 REAL, mean REAL, PRIMARY KEY (sim_id, name, period))
```

  A simulation points at its baseline run (whose rows already reproduce to the cent) and at its shocks; `reproduce-sim` re-runs it from those rows and the seed and checks every percentile to the cent. `shocks_sha256` hashes the shocks' fields in order, so an edited shock can't pass as the one simulated. The `runs.seed` column (0005) stays NULL: a baseline run has no seed; the simulation has it.
- **Comparison output.** The CLI `python -m domains.analysis simulate RUN_ID --shocks FILE [--n] [--seed]` stores the simulation and writes a Markdown report: per period, baseline vs p10/p50/p90 for revenue, EBIT and FCF, plus the shocked-minus-baseline p50 as a share of baseline, so the reader sees *when* the effect appears and *how fast it fades*; and value per share as a range. The report names each shock, its source and its rationale.

## The terminal value (owner decision, oct.30.2026)

Value per share as a range is new in M4, and the Build Plan (M2.1 B) said the terminal rule is decided before M4 reports it. The owner chose the **value-driver form with new investment earning its cost of capital** (Koller, Goedhart & Wessels, *Valuation*, 7th ed., ch. 10): TV = NOPAT₆ × (1 − g / RONIC) / (WACC − g), with RONIC = WACC, which reduces to TV = NOPAT_Y5 × (1 + g) / WACC. Reinvestment is tied to growth (g / RONIC of NOPAT is reinvested), growth past Y5 adds no value, and the near-zero spread for low-beta companies (Build Plan risks: 85-92% terminal shares for JNJ, PG, KO, XOM) no longer drives the value. g stays = R_f (Decision 4, D7); it only scales next year's NOPAT. The discount rate is Y5's, as before.

- It is a method row, `terminal_method` (`value_driver_ronic_wacc` for new runs). A run stored without it is valued with the old Gordon rule on Y5's FCFF, so every stored run still reproduces to the cent.
- New baseline runs change value per share (not revenue, EBIT or FCF), so the M3 errors are unchanged.
- Step 5 implements it; until then Steps 1–4 use the old rule.

## Shocks for the exit criterion: where the numbers come from

LLMs never produce financial numbers, and agents are LLMs, so no agent picks a magnitude. The three exit cases are the **guidance cases** in the M3 library, because there the company itself published the number:

- MSFT_2022-06-02 (fiscal Q4 2022 revenue guidance lowered for foreign exchange),
- WMT_2022-07-25 (profit outlook cut),
- CAT_2019-10-23 (2019 outlook lowered).

The case librarian transcribes, from the dated filing or press release only, the old and new guided figures (range ends, the period they cover, the accession number). Code then converts them with one rule: base = (new midpoint − old midpoint) / old midpoint, low and high = the new range's ends on the same basis (a point guide gives low = base = high), start = the first guided quarter, horizon = the guided quarters, decay = 1; revenue guidance goes to `revenue_growth`, operating-margin or operating-income guidance to `operating_margin` (operating income guidance divided by guided or baseline revenue, stated per case). The transcription file is `domains/evaluation/shocks.csv`, checked in with its sources before the first scored batch, and its SHA-256 is stored with the batch, as with `cases.csv`. If a case's guidance is in EPS only (no revenue or operating figure), it is not used and the next guidance case is taken; the report says which.

This measures plumbing, not skill: three cases can't show shocks help. M8 owns that question.

## The harness: `with_shocks`

- A new variant `with_shocks` in `eval_results`: forecast = p50 of the shocked revenue or EBIT for the quarter; `p10`, `p50`, `p90` and `seed` are filled (the columns exist since 0007). It is scored with the same errors as the baseline, so the M3 tables gain a row.
- A case with no shocks in `shocks.csv` has no `with_shocks` rows (never a copy of the baseline under another name).
- The shocks are point-in-time like everything else: a shock whose source is dated after the case date fails the case (`guard_shock_dates`, a test).
- `--shocks FILE` on `python -m domains.evaluation run`; the default is no shocks, so M3 batches are unchanged.

## Steps

- **Step 0.** This design doc; M4 "In progress" in the build plan.
- **Step 1.** `financial_math.shock_shape` and `split_normal`. Tests: decay = 1 is constant over the horizon and zero after; decay 0.5 halves; zero outside; property tests that the quantiles of `split_normal` on a fixed z grid are low/base/high, that it is monotone in z, that low = base = high is constant.
- **Step 2.** `dcf` split into the row index and an array-ready valuation; `Shock` schema and validation; driver paths with shocks (`apply_shocks`). Tests: every existing dcf and reproduce test still passes unchanged; a zero-magnitude shock reproduces the baseline to the cent; a revenue growth shock is a lasting level shift; a year takes the mean of its quarters; risk premium moves only the discount rate; invalid shocks refused.
- **Step 3.** `montecarlo.simulate`, migration 0008, storage, `reproduce-sim`, the CLI and report. Tests: same seed gives identical outputs; sampled p10/p50/p90 of a single shock's magnitude match low/base/high within 1% at N = 10,000; an invalid sample stops the run; the migration applies to an existing database; reproduce-sim checks to the cent; the CLI end to end on Test Corp.
- **Step 4.** `shocks.csv` (transcribed guidance, with sources), the conversion rule, `guard_shock_dates`, the `with_shocks` variant and report row. Tests on Test Corp: a shock dated after the case date fails the case; with_shocks rows carry p10/p50/p90 and seed; no shocks, no rows.
- **Step 5.** The value-driver terminal value (owner decision), as a `terminal_method` row. Tests: TV = NOPAT × (1 + g) / WACC by hand; a run without the row reproduces under Gordon; the spread warning is not raised under the new rule; the Structure Guide records the decision.
- **Step 6.** Real run on the three cases (SEC EDGAR, Yahoo Finance, FRED), results in the build plan, M4 Done on merge.

Steps 1–4 change no existing number and can merge as an engine-only PR, as M3 did.

## Exit criterion (Build Plan)

For three eval cases, hand-entered shocks run end to end and appear in the harness as a `with_shocks` variant.

## Alternatives considered

- **Wallis two-piece normal.** Rejected: its median is not the joining point, so low/base/high would not be p10/p50/p90 for an asymmetric range (see Sampling).
- **Triangular or PERT on low/base/high.** Rejected: they read the ends as bounds, not as the 10th and 90th percentiles the Build Plan defines, and cut off the tails.
- **Horizon in forecast periods (mixed quarters and years).** Rejected: decay per period would mean a quarter's decay in year 1 and a year's decay in Y3–Y5.
- **New random noise each quarter.** Rejected: a shock is one event of uncertain size; independent per-quarter draws would average the uncertainty away over the horizon.
- **Sampling the baseline drivers too.** Deferred to M8: M4 isolates the effect of shocks, as the Build Plan's "with and without shocks" comparison asks.
- **Shock magnitudes picked by an agent "by judgment".** Rejected: that is an LLM producing a financial number.

## Files

New: `domains/analysis/{shocks,montecarlo}.py`, `shared_kernel/migrations/0008_shocks.sql`, `domains/evaluation/shocks.csv`, `tests/analysis/test_{shocks,montecarlo}.py`, `tests/evaluation/test_shocks.py`.
Changed: `domains/analysis/{financial_math,dcf,__main__,report}.py`, `domains/evaluation/{harness,__main__,report}.py`, `docs/build-plan.md`.

## Review log

(Filled in after the design review.)

## Where the work stopped

(Updated at the end of each run.)
