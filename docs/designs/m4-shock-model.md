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
  source        : user | computed | llm_proposed
                  (computed = converted by code from transcribed company guidance, Decision 4's vocabulary)
  rationale     : text, with the evidence it relies on (a URL or an accession number)
```

- **Unit of time is the quarter.** The forecast grid is 8 quarters, then Y3–Y5 (Build Plan M2). The shape is computed on a 20-quarter grid, h = 1…20; quarters 1–8 map one to one, and each of Y3, Y4, Y5 takes the **mean** of its four quarters' effects (quarters 9–12, 13–16, 17–20). A shock that ends inside a year therefore moves that year by the share of the year it covers. The Build Plan's "number of periods" is read as quarters; this is the only reading under which a decay rate means the same thing across the grid.
- **Time shape** (Build Plan M4): effect at quarter h = magnitude × decay^(h − start) for start ≤ h < start + horizon, else 0. Several shocks on one driver add up. Positive magnitude means a higher driver: more growth, a higher margin, more capex, a higher risk premium.
- **Permanent.** decay = 1 is "permanent within horizon" (Build Plan). A shock whose horizon reaches quarter 20 is in force in Y5, and the terminal value is built on Y5, so it lasts forever: that is the permanent shock of Decision 6. One that ends earlier is temporary.
- **Years.** Y3–Y5 keep their baseline annual rates (faded to terminal growth, D2); the shocked rate is the baseline rate plus the mean of the year's four quarterly effects. The year then compounds from the year before, as in the baseline.
- **Drivers map onto the run's rows:**
  - `revenue_growth` → `revenue_growth` (quarters grow from the same quarter a year earlier, so a growth shock is a *level* shock that stays: a 5-point cut for one quarter leaves that quarter 5% lower, and the same quarter next year grows from the lower base. This is stated in the report.)
  - `operating_margin` → `operating_margin` (adds margin points to EBIT / revenue that quarter).
  - `capex_intensity` → `capex_pct`.
  - `risk_premium` → added to the cost of equity, in basis points of an annual rate. Each quarter takes its own effect; Y3–Y5 take the mean of their quarters. The period's discount rate is the WACC rebuilt with that cost of equity at the run's fixed market-value weights (`financial_math.discount_factors` already takes one annual rate per period and its length). The terminal value uses Y5's rate, so only a shock still active in Y5 moves it. Rolling the value forward to the as-of date keeps the baseline WACC (it covers days before any shock starts).
- **Invalid shocks are refused before any sampling:** unknown driver, low > base or base > high, start outside 1–20, start + horizon − 1 beyond 20 (clipped is silent, so it is refused), decay outside (0, 1].

## Sampling the magnitude

Each shock's magnitude is drawn from a **split normal fitted to the quantiles**: below the median it is a normal with σ_low = (base − low) / z₀.₉, above it a normal with σ_high = (high − base) / z₀.₉, and each side carries half the probability. z₀.₉ = 1.2815515655446004. Then low, base and high are exactly the p10, p50 and p90, which is what the Build Plan asks for (asymmetric ranges allowed). A draw is `base + z × (σ_low if z < 0 else σ_high)` with z standard normal.

This is not Wallis's (2014) continuous two-piece normal. That one joins its halves at the mode and keeps the density continuous; with three parameters it can match three quantiles only while the quantile skew (p90 − p50) / (p50 − p10) stays between about 0.57 and 1.77, and guidance ranges fall outside it (−5 / −3 / −2.5 has 0.25). Splitting at the median fits any ordered low/base/high exactly; the price is a step in the density at the median (heights φ(0)/σ_low and φ(0)/σ_high). low = base = high gives a constant: the shock becomes deterministic.

- **Independence.** Shocks are sampled independently (Build Plan M4, a stated Phase 1 simplification). One draw per shock per sample: the whole path of a shock scales together, so a sample is "a bigger or smaller version of the same event", never noise that changes sign from quarter to quarter.
- **Seed.** A stored integer seed feeds `numpy.random.Generator(numpy.random.PCG64(seed))`, and z is `rng.standard_normal((N, number of shocks))`, column i for the i-th shock in stored order. numpy is pinned (requirements.txt), so the same seed, shocks and rows give the same percentiles on any machine.
- **The baseline is not sampled.** Only shocks carry uncertainty in M4. With no shocks, every sample equals the baseline. Sampling the baseline drivers or the ERP is left to M8 (calibration needs both). So the p10–p90 band is **shock-size uncertainty only**, and the report and harness label it that way: Decision 7's 80% coverage check would fail on it by construction and is not run on M4 bands.
- **Percentiles don't add.** The p50s of the quarters don't sum to the p50 of the year or of the value; the report says so in one line.

## The Monte Carlo run

- `financial_math` gains two pure functions: `shock_shape(start, horizon, decay, quarters=20)` and `split_normal(low, base, high, z)`. No randomness inside `financial_math`: z comes in as an argument.
- `dcf.value` is split so the arithmetic runs on a dict of driver paths whose values can be floats or numpy arrays (the same code path for the baseline and for N samples, so a zero shock reproduces the baseline to the cent by construction, and a test proves it). `value(assumptions)` keeps its signature and outputs.
- `domains/analysis/montecarlo.py`: `simulate(rows, shocks, n=10_000, seed)` → per output (revenue, ebit, fcff per period; value per share, enterprise value) the p10, p50, p90 and mean over samples, next to the baseline value.
- **A sample that can't be valued stops the run.** Shocks can't change the share count or debt, so the case left is a discount rate that breaks the terminal formula (WACC at or below zero under the new rule, at or below terminal growth under the old one). Samples that give impossible drivers (an operating margin outside (−100%, 100%), or a negative capex share) are counted the same way. If any sample does either, `FinancialMathError` is raised with the number of such samples. Dropping them silently would bias the percentiles; the user narrows the range instead.
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

  A simulation points at its baseline run (whose rows already reproduce to the cent) and at its shocks; `reproduce-sim` re-runs it from those rows and the seed and checks every percentile to the cent. `shocks_sha256` is the SHA-256 of the JSON list of the shocks' fields (sorted keys, in stored order), so an edited shock can't pass as the one simulated. The `runs.seed` column (0005) stays NULL: a baseline run has no seed; the simulation has it.
- **Comparison output.** The CLI `python -m domains.analysis simulate RUN_ID --shocks FILE [--n] [--seed]` stores the simulation and writes a Markdown report: per period, baseline vs p10/p50/p90 for revenue, EBIT and FCF, plus the shocked-minus-baseline p50 as a share of baseline, so the reader sees *when* the effect appears and *how fast it fades*; and value per share as a range. The report names each shock, its source and its rationale.

## The terminal value (owner decision, oct.30.2026)

Value per share as a range is new in M4, and the Build Plan (M2.1 B) said the terminal rule is decided before M4 reports it. The owner chose the **value-driver form with new investment earning its cost of capital** (Koller, Goedhart & Wessels, *Valuation*, 7th ed. (2020), ch. 14): TV = NOPAT₆ × (1 − g / RONIC) / (WACC − g), with RONIC = WACC, which reduces to TV = NOPAT_Y5 × (1 + g) / WACC. Reinvestment is tied to growth (g / RONIC of NOPAT is reinvested), growth past Y5 adds no value, and the near-zero spread for low-beta companies (Build Plan risks: 85-92% terminal shares for JNJ, PG, KO, XOM) no longer drives the value. g stays = R_f (Decision 4, D7); it only scales next year's NOPAT. The discount rate is Y5's, as before.

- It is a method row, `terminal_method` (`value_driver_ronic_wacc` for new runs). A run stored without it is valued with the old Gordon rule on Y5's FCFF, so every stored run still reproduces to the cent.
- New baseline runs change value per share (not revenue, EBIT or FCF), so the M3 errors are unchanged.
- Step 5 implements it; until then Steps 1–4 use the old rule.

## Shocks for the exit criterion: where the numbers come from

LLMs never produce financial numbers, and agents are LLMs, so no agent picks a magnitude. The exit cases use **company guidance**, because there the company itself published the number. The analyst read the three guidance releases in the M3 library (design review):

- **MSFT_2022-06-02** guides fiscal Q4 2022 revenue and operating income in dollars, old and new ranges in one table. Usable.
- **WMT_2022-07-25** guides growth rates and an operating margin for Q2 and the full year. Usable after converting rates to amounts.
- **CAT_2019-10-23** guides profit per share only ("modestly lower sales"). Not usable. The other guidance case (AAPL_2020-02-17) gives no new figure either.

So the third exit case is a **new case**, picked by a rule fixed before any shock is scored: the earliest 8-K exhibit 99 from a Phase 1 company, from 2019-03-01, that revises earlier numeric revenue or operating-margin guidance, and whose date isn't already in the library. It joins `cases.csv` like any case (the library only grows; removing a case is the owner's call). Which case was taken and why is in the report.

**Transcription.** The case librarian copies into `domains/evaluation/shocks.csv`, from the dated release only: the old and new guided figures (range ends, unit, the fiscal period covered), the accession number, and a `quote` column with the exact sentence or table row. A test parses every figure out of its quote, so a typo fails. The file is checked in before the first scored batch, and its SHA-256 is stored with the batch, as with `cases.csv`.

**Conversion (code, at simulation time, from the transcription and the run's rows).** The news is the *revision*, so a shock is added to Warren's own baseline path, never set to the guided level.

1. *Amounts first.* A guided growth rate becomes an amount with the prior-year actual known on the case date (the run's `history:` rows). A full-year guide becomes the amount left for the unreported quarters: full year − the quarters already reported on the case date. Old and new guides are converted the same way.
2. *Level change per quarter.* Δlevel = (new − old) / old on those amounts (midpoints for the base, the new range's ends for low and high; a point guide gives low = base = high, and the report says the range is empty for that reason). A multi-quarter amount is spread over its quarters in proportion to the baseline forecast.
3. *Growth shock that gives that level.* Quarters grow from the same quarter a year earlier, so moving growth by x moves the level by x / (1 + g). The revenue_growth shock for quarter h is Δlevel × (1 + g_h) with g_h the run's growth for h; one shock per guided quarter, horizon 1, decay 1. A guide covering more than 4 quarters is refused (its quarters would compound).
4. *Margin.* The operating_margin shock is new guided margin − old guided margin, with margin = guided operating income / guided revenue in the same release, or the margin as stated. Never the income change over revenue, which counts the revenue cut twice (MSFT: −0.22 points, not −0.57).
5. *Units.* Every converted magnitude is in percentage points (basis points for risk premium), as the shock record; a test pins MSFT's revenue shock to its hand-computed value.
6. *Source* = `computed`, rationale = the accession number and quote.

Reading a guided range's ends as p10 and p90 is an assumption: managers' range midpoints are biased (Ciconte, Kirk & Tucker 2014, *Review of Accounting Studies*) and guidance is walked down to beatable targets (Richardson, Teoh & Wysocki 2004, *Contemporary Accounting Research*). Microsoft's actual fiscal Q4 2022 revenue ($51.87B) landed below its revised low ($51.94B), a first sign the bands are too narrow. M8 calibrates it. This measures plumbing, not skill: three cases can't show shocks help. M8 owns that question.

## The harness: `with_shocks`

- A new variant `with_shocks` in `eval_results`, on the case's own baseline run: forecast = p50 of the shocked revenue or EBIT for the quarter; `p10`, `p50`, `p90` and `seed` are filled (the columns exist since 0007). It is scored with the same errors as the baseline, so the M3 tables gain a row.
- A case with no shocks in `shocks.csv` has no `with_shocks` rows (never a copy of the baseline under another name).
- The shocks are point-in-time like everything else: a shock whose source is dated after the case date fails the case (`guard_shock_dates`, a test).
- `--shocks FILE` on `python -m domains.evaluation run`; the default is no shocks, so M3 batches are unchanged.

## Steps

- **Step 0.** This design doc; M4 "In progress" in the build plan.
- **Step 1.** `financial_math.shock_shape` and `split_normal`. Tests: decay = 1 is constant over the horizon and zero after; decay 0.5 halves; zero outside; `split_normal` at z = −Z90, 0, Z90 is low, base, high; that it is monotone in z, that low = base = high is constant.
- **Step 2.** `dcf` split into the row index and an array-ready valuation; `Shock` schema and validation; driver paths with shocks (`apply_shocks`). Tests: every existing dcf and reproduce test still passes unchanged; a zero-magnitude shock reproduces the baseline to the cent; a revenue growth shock is a lasting level shift; a year takes the mean of its quarters; risk premium moves only the discount rate; invalid shocks refused.
- **Step 3.** `montecarlo.simulate`, migration 0008, storage, `reproduce-sim`, the CLI and report. Tests: same seed gives identical outputs; sampled p10/p50/p90 of a single shock's magnitude match low/base/high within 2% of (high − low) at N = 10,000; an invalid sample stops the run; the migration applies to an existing database; reproduce-sim checks to the cent; the CLI end to end on Test Corp.
- **Step 4.** The third case by its rule, `shocks.csv` (transcribed guidance with quotes and sources), the conversion rule (tests: quotes parse; MSFT's shocks by hand; a full-year guide lands on unreported quarters only; > 4 quarters refused), `guard_shock_dates`, the `with_shocks` variant and report row. Tests on Test Corp: a shock dated after the case date fails the case; with_shocks rows carry p10/p50/p90 and seed; no shocks, no rows.
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

- **Analyst** (6 blockers on Step 4, all accepted; Steps 1–3 sound): CAT guides EPS only and AAPL gives no figure, so the third case comes from a stated rule; Walmart guides rates, so rates become amounts first; full-year guides go to the unreported quarters only; operating income guidance counted the revenue cut twice; a level change must be scaled by (1 + g) to become a growth shock, and units are pinned by a test; transcription needs a quote and a parse test. Ideas taken: impossible-driver samples stop the run; empty ranges named; MSFT's actual outside its revised range noted. Ideas to backlog: mean/p50 flag for skewed value ranges, a spread floor under the old rule, a separate line for permanent revenue effects.
- **Explainer** (5 gaps, all answered above): what decay = 1 means beyond the horizon (Permanent), how Y3–Y5 take a growth shock (Years), the risk premium's rates and weights, the terminal order (decided), and the guidance denominator and basis. Ideas taken: `computed` source, the exact generator call, the hash format, the invalid-sample case, tolerances, which run with_shocks uses, the EPS fallback, who enters the numbers, sign convention.
- **Professor** (1 blocker, accepted): value per share as a range must not be reported before the terminal rule is decided (Build Plan M2.1 B). The owner decided it (oct.30.2026); Step 5 lands before the Monte Carlo report shows a value range. Suggestions taken: the corrected reason for rejecting Wallis's two-piece normal, the edition and chapter of Koller et al., guidance ends as an assumption, the band labelled shock-size only, percentiles don't add. Ideas left to the report: a worked growth-shock example.

## Where the work stopped

(Updated at the end of each run.)
