---
title: "PROJECT WARREN — Phase 1 Build Plan"
version: "1.1"
updated: "oct.28.2026"
companion: "structure-guide.md (design decisions; wins on any conflict about decisions)"
status: "Approved and in progress. Since oct.30.2026 agent teams pick, build, review and merge milestones on their own (Structure Guide Decision 10)."
---

# PROJECT WARREN — Phase 1 Build Plan

**Version 1.1 · oct.2026**\
Collaborators: Andrés Rodarte — sonderbot-ar

> **How to use this document (humans and LLMs).** This plan turns the decisions in `structure-guide.md` into an ordered sequence of milestones. Each milestone lists its goal, the decisions it implements, the tasks, what gets tested, and an exit criterion that must be met before the next milestone starts. Agent teams take milestones in this order once their dependencies are Done, and may run independent milestones in parallel (Structure Guide Decision 10). When a milestone finishes, its status in Section 2 is updated and any decision that changed is recorded in the Structure Guide's decision log.

## 1. Phase 1 Goal

By the end of Phase 1, Warren can take one US company and a date, and:

1. Load the company's reported fundamentals **as they were known on that date** (SEC EDGAR).
2. Build a baseline multi-period forecast and a DCF valuation with explicit, sourced assumptions.
3. Find news events about the company around that date (GDELT), classify them, and propose time-shaped, probabilistic shocks to the model drivers.
4. Run the DCF as a Monte Carlo simulation with and without those shocks.
5. Report how the shocks change projected revenue, margins, cash flow and intrinsic value, over which periods, with p10/p50/p90 ranges and a full trace of where every number came from.
6. Prove, on a library of historical events, whether adding the shocks makes the forecast of reported fundamentals more accurate than the baseline.

**Phase 1 universe:** 5–10 large US non-financial companies with clean XBRL filings. Banks and insurers are excluded because their valuation does not follow a standard free-cash-flow DCF.

**Explicitly not in Phase 1:** stock price prediction (never in scope), learning *when* a sentiment source is impactful, the interactive environment for finance students, additional drivers such as beta, capital structure or book value, any user interface beyond a command-line run and a written report.

## 2. Timeline

Durations are indicative, assuming part-time work (roughly 8–12 hours a week). Adjust freely; the **order and exit criteria** are what matter. Start: week of oct.19.2026.

| Milestone | Focus | Weeks | Indicative dates | Depends on | Status |
|---|---|---|---|---|---|
| M0 | Foundations and documentation | 1 | oct.19 – oct.25 | — | **Done** (oct.14.2026) |
| M1 | Fundamentals data layer (EDGAR, point-in-time) | 2 | oct.26 – nov.08 | M0 | **Done** (oct.14.2026) |
| M1.1 | Fundamentals hardening (review of M1) | 0.5 | oct.26 – oct.29 | M1 | **Done** (oct.26.2026) |
| M2 | Deterministic forecast and DCF engine | 2 | nov.09 – nov.22 | M1.1 | **Done** (oct.26.2026; PRs #5 and #6) |
| M2.1 | DCF hardening (review of M2) | 0.5 | oct.28 – oct.30 | M2 | **Done** (oct.30.2026; PR #7, merged by the agent team after a gatekeeper GO; recorded as v0.2 in `docs/versions.md`) |
| M3 | Evaluation harness v1 (baseline only) | 1.5 | nov.23 – dec.03 | M2.1 | In progress (oct.30.2026; design in `docs/designs/m3-evaluation-harness.md`) |
| M4 | Shock model and Monte Carlo (manual shocks) | 1.5 | dec.04 – dec.13 | M2.1 | Not started |
| M5 | News ingestion (GDELT) and event clustering | 2.5 | dec.14 – jan.03 | M1 | Not started |
| M6 | LLM steps: event extraction and shock proposal | 2 | jan.04 – jan.17 | M4, M5 | Not started |
| M7 | LangGraph orchestration and telemetry | 1.5 | jan.18 – jan.27 | M6 | Not started |
| M8 | Full backtest and Phase 1 review | 1.5 | jan.28 – feb.07.2027 | M3, M7 | Not started |

**Why this order.** The numbers come first (M1–M2), then the ruler that measures them (M3), so every later step is judged against a known baseline. Shocks are built and tested by hand (M4) before any LLM produces them (M6), so a bad result can be traced to either the math or the LLM, never both at once. News ingestion (M5) only depends on M1 and can run in parallel with M2–M4 if time allows.

```text
M0 ─ M1 ─┬─ M2 ─┬─ M3 ─────────────────┐
         │      └─ M4 ─┐               ├─ M8
         └─ M5 ────────┴─ M6 ─ M7 ─────┘
```

## 3. Decision-to-Milestone Map

| Structure Guide decision | Implemented in |
|---|---|
| 1 Model allocation and API keys (under review) | Decided before M6; implemented in M6 |
| 2 State management: typed facts, point-in-time, WAL, small state | M0 (WAL, migrations), M1 (facts), M7 (graph state, checkpointer) |
| 3 SQLite only, FTS5 for text | M5 |
| 4 Deterministic math engine | M2, M2.1, M4 |
| 5 Telemetry | M0 (bug fix), M7 (full emitter) |
| 6 Shock model | M4 (deterministic), M6 (LLM proposal) |
| 7 Evaluation harness | M3 (baseline), M8 (with shocks) |
| 8 Data sources | M1 (EDGAR), M2 (Yahoo Finance), M5 (GDELT) |
| 9 LLM usage limited to text judgment | M6 |

## 4. Milestones in Detail

### M0 — Foundations and Documentation

**Goal:** a clean, testable skeleton and documentation that any person or LLM can pick up.

**Tasks**

- *(Done oct.14.2026)* Add `docs/structure-guide.md` and `docs/build-plan.md` (these documents) to the repo, plus a short `CLAUDE.md` at the root that tells coding assistants: read `docs/` first, follow the decision log, never write or change code without the owner's command, and update the docs when a decision changes.
- Create the folder layout from Structure Guide §4 (empty packages only).
- Fill in `requirements.txt` (or `pyproject.toml`) with pinned versions; set up `pytest` and a formatter/linter.
- `shared_kernel/database.py`: open connections with WAL mode and foreign keys on; add a minimal migration mechanism (numbered `.sql` files plus a `schema_version` table) so the schema can evolve without hand edits.
- `shared_kernel/schemas.py`: fix the `TelemetryEvent.timestamp` default (timezone-aware "now"); remove `current_node` from `SimulationState`; mark `BaselineFinancials` and `SentimentShock` as placeholders to be replaced in M2 and M4.
- Remove unused imports in `database.py`.

**Tests:** database opens in WAL mode; migrations apply cleanly to an empty database; `TelemetryEvent()` can be created without a timestamp.

**Exit criterion:** `pytest` passes on a fresh clone; the docs are in the repo.

**Learning notes:** WAL mode: SQLite normally locks the whole file while writing. In WAL mode, writes go to a separate `-wal` file first, so readers keep reading the last committed version while a writer works. It is one `PRAGMA journal_mode=WAL;` statement and persists in the database file.

### M1 — Fundamentals Data Layer (SEC EDGAR, point-in-time)

**Goal:** load a company's reported financials from EDGAR and query them as of any date.

**Implements:** Decisions 2 and 8.

**Data model**

```sql
companies(
  cik TEXT PRIMARY KEY, ticker TEXT UNIQUE, name TEXT,
  sic TEXT, fiscal_year_end TEXT, aliases_json TEXT        -- aliases used later by news matching
)

concepts(
  canonical_name TEXT,          -- Warren's name, e.g. 'revenue'
  xbrl_concept TEXT,            -- e.g. 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
  priority INTEGER,             -- which tag to prefer when a company reports several
  unit TEXT,                    -- USD, shares, USD/shares
  PRIMARY KEY (canonical_name, xbrl_concept)
)

financial_facts(
  cik TEXT REFERENCES companies,
  xbrl_concept TEXT,
  period_start DATE, period_end DATE,       -- period_start NULL for balance-sheet (instant) items
  fiscal_year INTEGER, fiscal_period TEXT,  -- FY, Q1, Q2, Q3
  value REAL, unit TEXT,
  form TEXT, accession_no TEXT,             -- 10-K / 10-Q and filing id
  filed_at DATE,                            -- when it became public
  PRIMARY KEY (cik, xbrl_concept, period_start, period_end, accession_no)
)
```

**Tasks**

- EDGAR client: ticker-to-CIK lookup (SEC's company tickers file), then the XBRL company-facts endpoint for each company. Send a descriptive `User-Agent` (name and email, as SEC requires) and stay under SEC's request-rate limit. Cache raw JSON under `data/raw/edgar/` so re-runs do not re-download.
- Ingestion: flatten the JSON into `financial_facts`, keeping every filing's version of a fact (the same period appears again in later filings as a comparative, sometimes restated).
- Concept map: seed `concepts` with the Phase 1 canonical items and their XBRL tags in priority order: revenue, cost of revenue, operating expenses, operating income, income tax expense, pre-tax income, D&A, capex, cash, total debt, diluted shares, current assets and liabilities (for working capital), interest expense.
- Point-in-time query: `get_facts(cik, canonical_names, as_of)` returns, for each period, the value from the latest filing with `filed_at <= as_of`. An `as_first_reported` mode returns the earliest filing instead (used by the evaluation harness as "truth").
- Quarterly normalisation: derive Q4 for flow items as fiscal-year value minus Q1–Q3, and derive standalone quarters where filings report year-to-date figures.
- Data-quality report per company: which canonical items were found, which tag was used, gaps by period.

**Tests:** fixtures with a small saved company-facts JSON; point-in-time query returns the original value before a restatement's filing date and the restated value after it; Q4 derivation; concept priority resolution.

**Exit criterion:** for every Phase 1 company, ten years of quarterly and annual canonical items load with a data-quality report showing no unexplained gaps.

**Learning notes:** the same economic item can use different XBRL tags across companies and years (for example, revenue tags changed after the 2018 revenue-recognition standard). That is why the concept map has priorities. Restatements are why `filed_at` matters: without it a backtest silently uses numbers nobody had at the time.

**Implementation notes (M1, oct.14.2026).** Decisions made while building, beyond the tasks above:

- **Schema.** `financial_facts` has a surrogate `fact_id` and a unique index on `(cik, xbrl_concept, unit, COALESCE(period_start,''), period_end, accession_no)`, because SQLite treats NULLs as distinct and a plain key would let duplicate balance-sheet facts in. `concepts.xbrl_concept` is unique and referenced by `financial_facts`, so unmapped tags can't be stored.
- **Fiscal labels** come from each filing's own period (the end date most of its facts share), not from the JSON's `fy`/`fp`, which describe the filing: a comparative in the FY2024 10-K carries `fy=2024`. Earlier periods are placed whole years back, with a few days' tolerance for 52/53-week years. Labels: Q1–Q4 and FY, plus H1 and M9 for year-to-date durations.
- **Point-in-time selection.** *(Revised in M1.1, see below.)* As built in M1: take the newest filing public on `as_of` (the earliest in `first_reported` mode), then the highest-priority tag within that filing.
- **Derived quarters** (Q2 = H1 − Q1, Q3 = M9 − H1, Q4 = FY − M9) are computed at query time from the inputs selected for that date, never stored. A derived value's `filed_at` is its latest input's, it lists its input filings, and it is flagged when it mixes restated and first-reported inputs. Only USD flows are derived: weighted-average shares are not additive.
- **API.** `get_facts(conn, cik, names, as_of, mode="latest"|"first_reported", frequency="reported"|"quarterly"|"annual")`.
- **Concept map** (`domains/fundamentals/concept_map.csv`): one precise definition per canonical item; only tags with the same meaning share a name. Owner decisions: restricted-cash-inclusive cash and basic shares are priority-2 fallbacks; `operating_expenses` stays strict. Debt is stored as components (non-current, current portion, short-term borrowings, commercial paper) for M2 to sum.
- **Universe** (`domains/fundamentals/universe.py`): AAPL, MSFT, WMT, KO, PG, JNJ, CAT, XOM. XOM is pinned to CIK 0000034088 (Exxon Mobil Corp), the registrant before the 2026-07-01 holding-company reorganisation; the ticker now maps to ExxonMobil Holdings Corp, whose filings start in 2026.
- **Gaps** are documented in `domains/fundamentals/known_gaps.csv` with a basis: `[annual only]`, `[not presented]`, `[extension tag]`, `[different line]`, `[bundled]` or `[inferred]`. The `[inferred]` ones (mostly debt balances absent for some periods) were not verified filing by filing.
- **Result.** 8 companies, 24,770 facts, 0 unexplained gaps for FY2016–FY2025. Spot check on MSFT FY2017 Q1 revenue (restated for ASC 606 on 2017-10-26): as of 2016-10-19 no value; as of 2017-10-25 20,453M; as of 2017-10-26 21,928M (restated); `first_reported` 20,453M.

### M1.1 — Fundamentals Hardening (review of M1)

**Goal:** fix what a review of M1 against the docs and the M1 lesson notes found, before M2 depends on it.

**Changes (oct.26.2026)**

- **Selection rule: best tag first, then its newest filing** (owner decision). Picking the newest filing first let later filings that repeat an old period under a broader or narrower tag replace the preferred value: definition drift treated as a restatement (90 cases, mostly cash including restricted cash from cash-flow statements, plus WMT revenue and XOM debt). Restatements filed under a higher-ranked tag still win (the ASC 606 revenue and cost-of-revenue restatements of MSFT, KO, PG, JNJ and CAT are unchanged). Concept-map rule: a renamed tag ranks above its old name (`InterestExpenseNonoperating` above `InterestExpense`). `first_reported` is unchanged; `restated` means "differs from first-reported", which also covers a period first reported only under a fallback tag (4 cases, 1 inside FY2016–FY2025: CAT FY2020 cash, 14M).
- **Ingestion guards.** Facts whose period ends after their filing date are rejected (one WMT EDGAR error) and refused by a database trigger (migration `0003`). Facts that can't be placed in a fiscal period are counted separately.
- **Quarters vs full year.** The quality report lists flows whose Q1–Q4 differ from the fiscal year by more than 0.5% (13 item-years), with which periods are restated: mixed restatement vintages (e.g. JNJ FY2022 after the Kenvue separation). Informational; M2 decides the basis for growth rates (owner decision).
- **Provenance.** `ingest_runs` records, per ingest, the company-facts content hash, when it was fetched (a `.meta.json` sidecar next to each cached download; `NULL` for files cached before M1.1), the concept-map hash and fact counts. The quality report names its data snapshot, warns when `concept_map.csv` changed since the last ingest, and links each `[inferred]` gap to the EDGAR filing to check.
- **New canonical items** (owner decision): `operating_lease_liabilities`, `finance_lease_liabilities` (totals, from ASC 842 adoption), `minority_interest`, and `shares_outstanding` (cover-page `dei:EntityCommonStockSharesOutstanding`, labelled with its filing's own fiscal period because its date falls after the period end). Quarterly and annual views keep one value per period when two dates share a label. Marketable securities are not mapped (owner decision).
- **XOM guard** (owner decision): `get_facts` raises a `CoverageWarning` for XOM as of 2026-11-01 or later, when its new filings move to the holding company's CIK (moved to 2026-08-03 in M2.1).

**Result.** 26,340 facts; 0 unexplained gaps for all 8 companies with the new items; tag-change audit shows only genuine restatements or moves to the preferred definition; 106 tests.

### M2 — Deterministic Forecast and DCF Engine

**Goal:** a pure, tested calculation library and the pipeline that feeds it.

**Implements:** Decisions 4 and 8 (Yahoo Finance).

**Design**

- **Period grid:** forecasts run quarterly for the first 8 quarters (where news effects mostly land and where evaluation happens), then annually to year 5, then a terminal value.
- **Drivers** (one value per forecast period): revenue growth, operating margin, tax rate, D&A as % of revenue, capex as % of revenue, net working capital as % of revenue, plus the discount rate.
- **Baseline drivers** are computed from history with a documented rule (e.g., trailing 3-year averages, growth fading linearly toward the terminal rate). Each is stored as an assumption with `source='computed'` and the rule that produced it.
- **Assumptions table:**

```sql
runs(run_id TEXT PRIMARY KEY, cik TEXT, as_of DATE, created_at TIMESTAMP,
     seed INTEGER, code_version TEXT, notes TEXT)

assumptions(run_id TEXT REFERENCES runs, name TEXT, period TEXT, value REAL,
            source TEXT CHECK (source IN ('computed','user','llm_proposed')),
            method TEXT, PRIMARY KEY (run_id, name, period))
```

- **`financial_math.py` (pure functions, no I/O):** project revenue and operating income from drivers; unlevered free cash flow = EBIT × (1 − tax) + D&A − capex − ΔNWC; discount factors for a time-varying discount rate; Gordon-growth terminal value; enterprise value to equity value (minus net debt) to value per share (shares per D4); CAPM cost of equity; WACC.
- **Cost of capital:** beta estimated from Yahoo Finance returns of the stock against a broad index over a documented window; risk-free rate from a Treasury yield series; equity risk premium computed from market data by an owner-set method (D7, revised; never defaulted silently); cost of debt from interest expense over average debt; weights from market value of equity and book debt. Price data is cached in a `prices` table and used for nothing else.
- **Existing work on the `finance` branch (decided oct.14.2026, narrowed oct.26.2026):** the branch stays unmerged. Only the formulas the DCF needs move into `domains/analysis/financial_math.py`, rewritten to raise errors instead of returning NaN; the other ratio functions stay on `finance` until a milestone uses them (owner decision D9). Its EAV-based `math_engine.py` is discarded and rewritten against `financial_facts`.
- **`math_engine.py`:** pulls point-in-time facts (M1) and prices, pivots them into DataFrames, computes baseline drivers and calls `financial_math.py`.
- **Sanity checks (raise errors):** terminal growth ≥ discount rate; non-positive shares; missing required inputs. **Warnings:** terminal value above a set share of enterprise value; margins outside the company's historical range by a wide margin.

**Tests:** every formula against hand-computed examples (a spreadsheet you build yourself is a great fixture); property tests (higher discount rate never raises value; zero growth and zero reinvestment reduce to a perpetuity); sanity checks fire when they should.

**Exit criterion:** a baseline DCF for every Phase 1 company as of any date from 2019-03-01 (three fiscal years of the FY2016+ history behind it), reproducible to the cent from the stored assumptions.

**Owner decisions (oct.26.2026)**, settled before any M2 code, from the M2 plan and the review of M1.1:

- **D1 Securities.** Map marketable securities (current, non-current) and other short-term investments. Reverses the M1.1 choice: without them both net debt and operating working capital are wrong for AAPL and MSFT.
- **D2 Growth basis and seasonality.** Annual growth from each 10-K's own current-vs-prior-year comparatives (one restatement basis per pair), 3-year average, fading linearly to terminal growth by year 5. Quarters grow from the same quarter a year earlier; a fiscal year listed under "Quarters vs full year" falls back to the full year × average seasonal share.
- **D3 Net debt.** Debt components plus finance leases (skipped where the selected debt tag already includes them, KO 2024+), commercial paper only when short-term borrowings are absent, minus cash, marketable securities and other short-term investments. Operating leases excluded (GAAP EBIT already deducts lease cost). Minority interest subtracted after EV. A missing component counts as zero, with a warning.
- **D4 Shares.** Value per share uses the latest cover-page shares outstanding, split-adjusted to the as-of date; weighted-average diluted shares are the fallback.
- **D5 Risk-free rate.** FRED DGS10, the latest observation before the as-of date. Prices: the last close on or before the as-of date.
- **D6 Beta.** 2 years of weekly total returns against the S&P 500 Total Return index (`^SP500TR`, revised from `^GSPC` so both sides are total returns; betas unchanged within 0.001), Blume-adjusted.
- **D7 Equity risk premium and terminal growth: computed, not assumed** (revised oct.26.2026; replaces owner-set values). ERP = E[R_m] − R_f, measured as the realized geometric premium of the S&P 500 Total Return over the total return of a 10-year Treasury bond built from DGS10 (the same rate CAPM uses as R_f), over full calendar years from 1989 (the first year Yahoo's `^SP500TR` covers fully) to the last year ended before the as-of date (an expanding window). Terminal growth g = R_f at the as-of date (DGS10), so g stays below WACC by construction and moves with the discount rate. The owner sets the *methods* (`erp_method=historical_geometric`, `erp_first_year=1989`, `terminal_growth_method=risk_free`), signed and dated in a tracked file; each run stores the computed values, years, standard error and fetch hashes. The DCF report shows the ERP's standard error, value per share at ERP ± 1 standard error, and the ERP over two alternative windows (for information only, never used).
- **D8 Coverage fallbacks.** EBIT = pretax + interest expense (JNJ, XOM); D&A = depreciation + intangibles amortization (MSFT); pretax = domestic + foreign, else net income including NCI + tax (PG); cost of debt from cash interest paid (CAT). Each is a documented `computed` method.
- **D9** Port only the formulas the DCF needs (see above).
- **D10** Two PRs: A (inputs: data refresh, concept map, `financial_math.py`, market data) and B (engine, runs, CLI, real run). M2 is Done when B is merged.
- **D11 Universal checks, no per-company review** (oct.26.2026). The quality report checks required items only; optional items (fallbacks, holdings) are not part of it. They stay traceable where they are used: every DCF input is stored as an assumption row naming the item, XBRL tag, period and accession, including which fallback was used. If an item and its fallback are both missing, the run fails naming both. Per-company spot checks are replaced by run invariants (securities ≤ current assets, cash + current securities ≤ current assets, no negative debt or cash component, cover-page shares within ±10% of diluted shares) and a fallback back-test over the whole universe, comparing each fallback with its primary wherever both exist.

**Implementation notes, PR A (oct.26.2026)**

- **Data refresh.** `ingest --all --refresh` once before any M2 number: two new 10-Qs (PG, JNJ), 78 new facts, no previously selected value changed; every `ingest_runs` row now has a fetch time.
- **Concept map.** New items `marketable_securities_current` (4 tags), `marketable_securities_noncurrent` (2), `other_short_term_investments` (KO), and fallbacks `depreciation`, `amortization_intangibles`, `pretax_income_domestic`, `pretax_income_foreign`, `net_income_including_nci` (`ProfitLoss`; PG FY2020–21 tag neither pretax nor its split) and `interest_paid`. A `gate` column marks them `optional`: the quality report checks required items only (D11), so no known-gap rows were added.
- **Tag-change audit, now standing.** The quality report's "Newest filing disagrees with the selected value" section lists periods the newest filing reports only under a lower-ranked tag with a different value. On the refreshed data: 70 periods, all cash including restricted cash (cash-flow statement) and one XOM debt figure including leases; no restatement missed.
- **`financial_math.py`.** Plain arithmetic (works on floats or numpy arrays), end-of-period discounting with a rate per period, terminal value from an annual cash flow, errors instead of NaN.
- **Market data (migration `0004`).** `prices` (split-adjusted close, total-return close, split ratio), `yields`, and `market_fetches` (download time and content hash; a refresh replaced a symbol's rows until M2.1, which keeps every download). Queries refuse as-of dates after the download, and a row dated on the download day is dropped because it may be mid-session. Splits seen: AAPL 2014 (7:1) and 2020 (4:1), KO 2012 (2:1), WMT 2024 (3:1).
- **Equity risk premium (D7).** `^SP500TR` loaded from 1988; `domains/market/erp.py` computes the premium from year-end values (each year must have an observation in its last week; a year counts from 7 days after it ends). Live values, geometric (arithmetic, standard error): as of 2019-06-30 3.80% (4.91%, 3.83); 2020-12-31 4.33% (5.46%, 3.75); 2022-06-30 5.26% (6.35%, 3.61); 2024-03-31 5.52% (6.62%, 3.44); 2026-09-30 6.19% (7.25%, 3.30). Terminal growth (= R_f) on the same dates: 2.00%, 0.93%, 3.10%, 4.20%, 5.26%.

**Implementation notes, PR B (oct.26.2026)**

- **Runs are pure functions of their rows.** `math_engine.build_inputs` turns point-in-time facts and market data into assumption rows; `dcf.value` values a run from those rows alone (no database). Besides the drivers, the rows hold the base values (revenue seed, debt, cash and investments, minority interest, shares, price, cost-of-capital inputs) and the reported history behind every driver (`history:<item>` per fiscal year or quarter, `balance:<item>`), each with its tag, period and accession. `info:` rows (arithmetic ERP, ERP from 1999 and 2009) are shown, never used. Migration `0005` adds `runs` (with code version, ingest run, concept-map, price, index and yield hashes), `assumptions` and `run_outputs`.
- **Period grid and timing.** 8 quarters, then three 12-month years (Y3-Y5), then a Gordon terminal value on Y5. Cash flows are discounted from the end of the last actual quarter; the enterprise value is carried to the as-of date at WACC. WACC is constant across periods.
- **Driver rules (D2).** Growth: average of the latest three 10-Ks' same-filing growth, fading linearly to terminal growth by year 5; quarters grow from the same quarter a year earlier (seed: the last 4 actual quarters; a quarter in a fiscal year whose quarters differ from the year by more than 0.5% is replaced by year × its share). Operating margin: average of the same fiscal quarter over the last 12 quarters (at least 2 per quarter), and Σ EBIT / Σ revenue over the last 3 fiscal years for Y3-Y5. Tax, D&A, capex: 3-year Σ ratios (tax clipped to 0-50% with a warning). Working capital: average year-end operating working capital / revenue; its level is that share of trailing-12-month revenue, so it changes only with growth.
- **Balance sheet (D3, D4).** From the latest balance sheet on or before the as-of date; a component dated within a year before it is carried forward (warning), an older or missing optional component counts as zero (warning), a missing required one (current assets, current liabilities, cash) fails the run. Cost of debt: interest over average debt in the newest of the last three fiscal years that reports both. Shares: cover page, adjusted for splits after its date; diluted shares (fallback) are adjusted only for splits after their filing, which already restates them.
- **Reproduce.** `python -m domains.analysis reproduce` values each stored run again from its rows: money outputs to the cent, rates to 1e-9. Value per share at ERP ± 1 standard error is stored too; where WACC falls to terminal growth it has no value and the run notes say so.
- **Real run.** 8 companies × 5 as-of dates (2019-06-30, 2020-12-31, 2022-06-30, 2024-03-31, 2026-09-30): 40 of 40 runs complete and reproduce to the cent (80 of 80 including the runs made before the share-split fix). AAPL as of 2024-03-31 net debt checked line by line against the 2023-12-30 balance sheet: debt 109,064M (term debt 10,954 + 95,088, commercial paper 1,998, finance leases 1,024), cash and investments 172,575M (cash 40,760, securities 32,340 + 99,475).
- **Fallback back-test** (`python -m domains.analysis fallbacks`, FY2016-FY2025, all companies): D&A fallback median gap 0.3%; both pretax fallbacks 0.0%; EBIT = pretax + interest median +5.5% above operating income (flagged; used for JNJ and XOM); interest paid vs interest expense median 15% (flagged; used for CAT's cost of debt).
- **Values are not tuned.** The baseline values span 0.35× (KO 2020) to 4.7× (XOM 2024) the share price. The spread between WACC and terminal growth dominates: with g = R_f it is about β × ERP, so low-beta companies (JNJ, PG, KO, XOM in 2026) get 1.5-3 points, terminal values of 85-92% of enterprise value and values well above the price, while 2026's high rates and ERP give AAPL, MSFT and CAT values well below it. Growth extrapolated from three years carries cycles forward (XOM as of 2024-03-31: +28.5% from the 2021-2023 oil prices). These are consequences of D2 and D7 and are left for the owner and M3 to judge.

**Learning notes:** a DCF is usually dominated by the terminal value, which is why the warning exists and why small changes to terminal growth or WACC move the result so much. Seeing that in your own numbers is one of the best lessons the engine will give you.

### M2.1 — DCF Hardening (review of M2)

**Goal:** fix what the review of M2 found before M3 depends on the engine: runs that can be rebuilt from data, checks that run where M4's shocked drivers will flow, and warnings that fire on a minority of runs.

**Implements:** Decision 4.

**Owner decisions (oct.28.2026)**, from the review of M2 and the M2.1 plan:

- **A.** A separate hardening milestone (as M1.1), so the M3 PR stays small.
- **B. Terminal growth = R_f stays for M3.** M3 compares revenue and operating income over 1-4 quarters; forecast year 1 grows at the 3-year average, so those errors don't depend on terminal growth, the ERP or WACC, and M3 cannot test the rule. The terminal rule (a cap on g, a floor on the spread, reinvestment tied to growth) is decided before M4, where value per share is first reported as a distribution.
- **C. Terminal warning on the spread.** Warn when WACC − terminal growth is below 3 points, instead of when terminal value is above 75% of enterprise value (that fired on 38 of the 40 M2 runs).
- **D. Keep every market download.** A refresh adds a fetch instead of replacing the symbol's rows, so a run can be rebuilt from the exact data it used.

**Steps**

- Step 0: docs (M2 Done, this section, stale ERP line, exit-criterion wording).
- Step 1: XOM coverage boundary to 2026-08-03, the filing date of its Q2 2026 10-Q on the new holding company's CIK.
- Step 2: rebuildable runs: prices and yields keyed by fetch (migration `0006`), queries pinned to a run's fetches, `reproduce --rebuild`.
- Step 3: the margin-range check reads a run's rows (so shocked rows pass through it); the spread warning replaces the terminal-share warning.
- Step 4: the report says in words when ERP − 1 SE has no value.
- Step 5: re-run the 40-run grid; rebuild, reproduce and count warnings.

**Exit criterion:** every stored run rebuilds from data to identical rows and reproduces to the cent; the margin check runs on any row set; each warning fires on a stated minority of the 40 runs; the docs are current.

**Implementation notes (oct.28.2026)**

- **Market history (migration `0006`).** `prices` and `yields` are keyed by `(symbol, fetch_id, date)`; a refresh adds a fetch. Queries read the latest fetch unless `pin_fetches()` pins one (`domains/market/store.py`); `fetch_with_hash()` finds a run's own download by its stored content hash.
- **Rebuild.** `runs.rebuild()` builds a run's rows again with its downloads pinned and compares name, period, value, source and method of every row. Facts need no pin (point-in-time queries, ingests only add facts); a changed concept map is refused. The owner's choices come from today's `user_assumptions.csv`, so editing it shows up as a difference. A run made by older code may differ in method text only; `reproduce --rebuild` lists that apart from value differences.
- **Checks.** `post_checks(rows, outputs)` reads only the run: the margin-range check (forecast margins against the mean ± 2 SD of the reported quarterly margins in the `history:` rows) and the spread warning (WACC − terminal growth < 3 points). A data warning raised by each facts query (XOM coverage) is noted once per run.
- **Report.** When ERP − 1 SE gives no value, the summary says the value has no useful precision.

**Result.** 195 tests. The 40-run grid (8 companies × 2019-06-30, 2020-12-31, 2022-06-30, 2024-03-31, 2026-09-30) gives the same values as M2, to the cent. All 160 stored runs reproduce to the cent; 120 rebuild to identical rows; the 40 made before the M2 share-split fix rebuild to identical values with older method text. Warnings on the 40 new runs: spread below 3 points 11 (WMT, KO, PG 2019; WMT, PG, JNJ 2020; JNJ 2024; KO, PG, JNJ, XOM 2026); margin range 0 (baseline margins are averages of the history, so it is for shocked rows); stale fundamentals 2 (KO, XOM 2026); XOM coverage 1 (2026-09-30). ERP − 1 SE has no value for 6 runs (AAPL, CAT, JNJ, KO, MSFT, PG 2019), whose reports now say so.

**Carried to the M3 plan** (review of M2): same EBIT definition for forecast and actual (JNJ, XOM); case library from 2019-03-01 and no 2026 KO or XOM cases until their data catch up; XOM coverage as a hard error in eval runs; `restated` never counted as "the company restated"; log the growth basis per case to measure cycles carried forward. **Before M4:** the terminal rule (B), including reinvestment tied to growth.

### M3 — Evaluation Harness v1 (baseline only)

**Goal:** a reproducible way to measure forecast quality, before any news enters the system.

**Implements:** Decision 7.

**Design**

```sql
eval_cases(case_id TEXT PRIMARY KEY, cik TEXT, event_date DATE,
           event_type TEXT, description TEXT, horizon_quarters INTEGER,
           selected_because TEXT)

eval_results(case_id TEXT, run_id TEXT, variant TEXT,      -- 'baseline' or 'with_shocks'
             metric TEXT, period TEXT, forecast REAL, actual REAL, value REAL,
             PRIMARY KEY (case_id, run_id, variant, metric, period))
```

- **Case library:** start with 15–25 historical events across the Phase 1 companies, covering several event types (guidance changes, recalls, litigation, regulation, M&A, supply-chain disruptions, macro). Record *why* each case was chosen so the library is not unconsciously cherry-picked; include "quiet" dates with no notable news as controls.
- **Procedure per case:** run Warren as of the event date (point-in-time data only), forecast revenue and operating income for the next 1–4 quarters, then compare with the **first-reported** actuals from later filings.
- **Metrics:** absolute percentage error per quarter; direction of change versus the prior year; later (M8) skill score = 1 − (error with shocks ÷ error of baseline) and coverage of the p10–p90 band.
- **Output:** a per-case table and a summary report saved under `data/reports/`, with the code version and seeds used, so any result can be reproduced exactly.

**Tests:** the harness refuses to run if any input fact has `filed_at` after the case date (an automatic look-ahead guard).

**Exit criterion:** baseline error for every case is computed and saved. This is the number every later milestone must beat.

### M4 — Shock Model and Monte Carlo (manual shocks)

**Goal:** time-shaped, probabilistic shocks applied to drivers, entered by hand first.

**Implements:** Decisions 4 and 6.

**Shock schema**

```text
Shock
  shock_id, run_id, event_id (nullable for manual shocks)
  driver        : revenue_growth | operating_margin | capex_intensity | risk_premium
  low, base, high : magnitude, read as p10 / p50 / p90
                    (percentage points for growth, margin and capex; basis points for risk premium)
  start_period  : first affected period
  horizon       : number of periods the shock can last
  decay         : 0 < decay ≤ 1, share of the effect remaining each period (1.0 = permanent within horizon)
  source        : user | llm_proposed
  rationale     : text, with evidence references
```

- **Time shape:** effect in period *k* after start = magnitude × decay^k, for *k* < horizon, else 0. Effects from several shocks on the same driver add up. Duplicates are prevented upstream by event clustering (M5), not by the math.
- **Distribution:** each shock's magnitude is sampled from a two-piece normal with median = base, so that low and high are the 10th and 90th percentiles. This handles asymmetric ranges (for example, a downside risk larger than the upside).
- **Monte Carlo runner:** N samples (default 10,000) with a stored seed; each sample perturbs the driver paths and runs `financial_math.py`; outputs p10/p50/p90 for value per share and for revenue, operating income and free cash flow per period. Shocks are treated as independent in Phase 1 (a documented simplification).
- **Comparison output:** baseline vs shocked, period by period, so the report shows *when* the effect appears and *how fast it fades*.

**Tests:** zero-magnitude shock reproduces the baseline exactly; decay = 1 holds constant over the horizon; same seed gives identical results; sampled percentiles match low/base/high within tolerance.

**Exit criterion:** for three eval cases, hand-entered shocks run end to end and appear in the harness as a `with_shocks` variant.

### M5 — News Ingestion (GDELT) and Event Clustering

**Goal:** a clean, deduplicated, timestamped set of company events from GDELT.

**Implements:** Decisions 3 and 8.

**Design**

- **Source:** GDELT 2.0 Global Knowledge Graph (GKG), which provides for each article its URL, timestamp, source, organisations mentioned, themes and tone. Access options: the raw 15-minute files, Google BigQuery for historical slices, or the DOC API for recent windows. Recommendation: BigQuery for building the historical case library (filter by organisation and date before downloading), raw files or the DOC API for recent data. Check current access terms and quotas before starting.
- **Tables:**

```sql
articles(article_id TEXT PRIMARY KEY, url TEXT, source TEXT, published_at TIMESTAMP,
         title TEXT, tone REAL, themes_json TEXT, orgs_json TEXT, text TEXT NULL)
article_companies(article_id TEXT, cik TEXT, match_method TEXT, confidence REAL)
events(event_id TEXT PRIMARY KEY, cik TEXT, first_seen TIMESTAMP, last_seen TIMESTAMP,
       article_count INTEGER, source_count INTEGER, event_type TEXT NULL, summary TEXT NULL)
event_articles(event_id TEXT, article_id TEXT)
-- plus an FTS5 virtual table over articles(title, text) for keyword search
```

- **Company matching:** match GKG organisation names against each company's aliases (from `companies.aliases_json`), with an exclusion list for ambiguous names. Store the match method and confidence; review a sample by hand for each company.
- **Clustering:** group a company's articles into one event when they fall within a time window and share themes or key terms. An event records when it was first seen and how many independent sources covered it (a useful materiality signal later).
- **Article text:** GDELT gives URLs, not text. Fetch titles and, where allowed and available, article text; many links will be paywalled or dead, so the pipeline must work on metadata and titles alone.

**Tests:** matching precision on a hand-labelled sample; the same story from ten outlets becomes one event; re-running ingestion is idempotent.

**Exit criterion:** for every eval case date, the events around it are ingested, matched and clustered, with a hand-checked sample showing acceptable precision.

**Learning notes:** GDELT is noisy by design: machine-coded, global and fast. Expect duplicates, wrong organisation matches and tone that does not track importance. Measuring and fixing that noise is the point of this milestone.

### M6 — LLM Steps: Event Extraction and Shock Proposal

**Goal:** turn clustered events into classified events and proposed shocks, with every output validated and traceable.

**Implements:** Decisions 1, 6 and 9.

**Before starting:** settle Decision 1 (how models and keys are configured).

**Design**

- **Event extraction (LLM 1):** input = one clustered event (titles, sources, timestamps, available text). Output = a validated structured object: event type from the fixed taxonomy, short factual summary, materiality (low / medium / high) with reasons, and the evidence it relied on. Invalid output is rejected and retried, never silently accepted.
- **Shock proposal (LLM 2):** input = the classified event plus the company's baseline drivers and recent history. Output = zero or more shocks in the M4 schema (driver, low/base/high, start, horizon, decay) with a rationale tied to evidence. "No material impact" is a valid and expected answer.
- **Human review:** proposed shocks pause for approval or edit before simulation (a LangGraph interrupt in M7; a command-line prompt before then). Edited values are stored with `source='user'`.
- **Traceability:** every LLM call stores model, prompt version (prompts live in versioned files), input, output, tokens and latency.
- **Look-ahead through the model's memory:** an LLM may already know what happened after a historical event, which would make the backtest look better than it really is. Mitigations: prefer evaluation events after the model's training cutoff where possible, test a variant with the company name masked, and report both.

**Tests:** schema validation rejects malformed output; a fixed set of example events produces stable classifications at low temperature; prompts and outputs are logged.

**Exit criterion:** for every eval case, events are classified and shocks proposed, reviewed and stored.

### M7 — LangGraph Orchestration and Telemetry

**Goal:** one command runs the full pipeline for a company and date.

**Implements:** Decisions 2 (graph state, checkpointer) and 5.

**Graph**

```text
load_fundamentals → build_baseline → fetch_news → cluster_events
    → extract_events (LLM) → propose_shocks (LLM) → review_shocks (human interrupt)
    → simulate (Monte Carlo) → write_report (optional LLM narrative)
```

- **State:** small typed data in state (company, as-of date, baseline drivers, event summaries, shocks, result percentiles); database IDs only for large items (article text, raw filings).
- **Checkpointer:** LangGraph's SQLite checkpointer stores state after each node, giving the full audit trail and the ability to resume after a failure or human review.
- **Telemetry:** a JSON-lines emitter records, per node, start and end time, status, errors and, for LLM nodes, model and input/output tokens.
- **Report:** a Markdown report per run: baseline vs shocked value per share (p10/p50/p90), per-period revenue, margin and free-cash-flow paths, each shock with its evidence, and the list of assumptions with sources.

**Tests:** the graph runs end to end on a fixture company with LLM calls stubbed; a run can be resumed from its checkpoint; telemetry lines are valid JSON.

**Exit criterion:** a single CLI run command (entry point chosen in M7), given a ticker and an as-of date, produces a report and a complete trace.

### M8 — Full Backtest and Phase 1 Review

**Goal:** an honest answer to "does news make Warren's fundamental forecasts better?"

**Tasks**

- Run every eval case in both variants (baseline, with shocks), and the name-masked variant from M6.
- Report skill score, direction accuracy and p10–p90 coverage, overall and by event type.
- Write a short review: what worked, what failed, which event types help and which add noise, and what Phase 2 should tackle.
- Update the Structure Guide decision log with anything learned.

**Exit criterion:** the review exists and the results are reproducible from stored seeds and code version. A negative result (shocks do not help yet) is a valid outcome; the harness exists to tell the truth.

## 5. Documentation Practice

- `docs/structure-guide.md` is the source of truth for decisions; `docs/build-plan.md` for sequencing and status. Markdown is the working format because coding assistants (Claude Code in VS Code included) read it directly; PDFs are exported copies for reading and sharing. PDFs are never edited and are not committed (except the archived sep.2026 guide); regenerate one when needed, for example with `pandoc docs/structure-guide.md -o structure-guide.pdf` or by asking Claude.
- `CLAUDE.md` at the repo root stays short and points to `docs/`. It states the standing rule: no code changes without the owner's explicit command.
- Every change to a decision adds or updates a row in the decision log with a date and status; superseded decisions stay listed so the history is visible.
- Each milestone's status in Section 2 is updated when it starts and when its exit criterion is met.

## 6. Risks and Open Questions

| Risk or question | Mitigation |
|---|---|
| XBRL tags inconsistent across companies and years | Concept map with priorities; data-quality report per company (M1) |
| GDELT noise and wrong company matches | Alias and exclusion lists, hand-labelled samples, source counts (M5) |
| Article text unavailable (paywalls, dead links) | Pipeline works on metadata and titles alone (M5) |
| LLM knows the outcome of historical events | Post-cutoff cases, name masking, report both (M6) |
| Too few eval cases to draw conclusions | Grow the library over time; report uncertainty, not just averages (M8) |
| Yahoo Finance interface changes or breaks | Small adapter plus local cache; only used for beta and comparison (M2) |
| Decision 1 (models and keys) still open | Decide before M6 |
| Telemetry details still open | Decide during M7 |
| SEC companyfacts omits company-specific (extension) and dimensional tags: no cash-flow D&A for MSFT, no interest expense for CAT, no quarterly pretax income for PG (M1) | Documented as known gaps; M2 decides whether to parse full XBRL filings or use fallbacks |
| JNJ and XOM present no operating income line (M1) | M2 derives EBIT from other lines, as a documented `computed` assumption |
| Debt components absent for some periods (M1) | M2 treats a missing component as zero, with a warning |
| XOM history sits on the predecessor CIK; filings from Q3 2026 are on the new holding company (M1) | `CoverageWarning` from 2026-08-03 (M1.1, moved in M2.1); link predecessor and successor before analysing later XOM dates |
| Marketable securities: mapped in M2 (D1); balance-sheet tagging varies (KO uses `MarketableSecurities` plus a separate short-term investments line) | Optional items in the concept map; run invariants (securities ≤ current assets) catch a tag that picks up the wrong measure, for any company (D11) |
| Historical ERP is noisy: standard error 3.3–3.8 points with 30–37 years (D7) | Report shows the standard error and value per share at ERP ± 1 SE; M4 samples the ERP from it; a longer history (Shiller, from 1871) is a candidate for a later milestone |
| Historical ERP is procyclical: it rose from 3.8% to 6.2% (2019 to 2026) with a long bull market and moving bond returns | Only a forward-looking (implied) ERP fixes it; candidate for a later milestone, from Shiller's earnings and dividends, first as a cross-check |
| Historical ERP depends on the first year (from 2006 instead: 8.2% for 2025) | Fixed expanding window from 1989, owner-signed, never tuned per run; alternative windows shown in the report for information |
| Terminal growth = R_f moves with rates (0.93% at end-2020, 5.26% in Sept 2026) | Intended: g and the discount rate move together; the report shows g and the terminal value's share of EV |
| WACC − terminal growth is small for low-beta companies under g = R_f (1.5-3 points), so terminal values reach 85-92% of enterprise value (M2 run) | Reported per run, with ERP ± 1 SE values; warned when the spread is below 3 points (M2.1); the terminal rule (a cap on g, a floor on the spread, or sampling g and the ERP) is decided before M4 |
| Baseline growth extrapolates the last three 10-Ks, cycles included (XOM 2024: +28.5%) | Fades to terminal growth by year 5; M3 measures the error; a longer or cycle-adjusted base is a candidate rule |
| EBIT fallback (pretax + interest) runs a median 5.5% above operating income where both exist; it includes other non-operating income (JNJ, XOM) | Back-test in every M2 PR; a fallback adding back other income is a candidate |
| Interest paid differs from interest expense by a median 15% (CAT's cost of debt) | Flagged by the back-test; CAT's cost of debt is approximate |
| CAT's current portion of long-term debt is not in companyfacts (dimensional); counted as zero, so CAT's debt is understated | Warned in each run; CAT already carries the captive-finance caveat |
| KO's and XOM's Q2 2026 10-Qs (filed 2026-07-29 and 2026-08-03) are not in SEC companyfacts as fetched 2026-10-26; XOM's was filed jointly with the new holding company (CIK 0002115436) | Runs warn when the last quarter is over 135 days old; XOM's `history_ends` moved to 2026-08-03 (M2.1); both need a data-layer follow-up |
| KO's 2019 diluted shares are tagged in millions (4,306 under a shares unit) | Caught by the shares invariant (warning); cover-page shares are used |
| Known gaps are listed row by row per company (review point 11) | Under the universal-checks principle (D11), pattern rules are the next step; deferred until the universe grows |
| CAT's consolidated debt includes its captive finance arm (Cat Financial), which a free-cash-flow DCF does not model | Phase 1 accepts it and the DCF report says so; companyfacts has no non-dimensional split |
| `ShortTermBorrowings` may already include commercial paper | M2 counts commercial paper only when short-term borrowings are absent (D3) |
| MSFT D&A fallback (depreciation + intangibles amortization) excludes the 'other' in its cash-flow line | Slightly understates D&A; documented `computed` method |
| Quarterly series can mix restatement vintages (13 item-years, M1.1 report) | M2 chooses the basis for growth rates (e.g. latest 10-K comparatives) |
| Finance leases may also sit inside lease-inclusive debt tags (KO 2024+) | M2 must not count them twice in net debt |
| `DepreciationAmortizationAndAccretionNet` differs from `DepreciationDepletionAndAmortization` for AAPL FY2015 (11.3B vs 9.2B) | Outside FY2016–FY2025 today; watch if the range extends |
| CAT FY2020–21 and PG FY2020 operating leases are tagged only as current + non-current parts | Small next to debt; add component items if M2 needs them |
