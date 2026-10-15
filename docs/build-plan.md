---
title: "PROJECT WARREN — Phase 1 Build Plan"
version: "1.0 (proposal)"
updated: "oct.14.2026"
companion: "structure-guide.md (design decisions; wins on any conflict about decisions)"
status: "Proposed. Awaiting owner approval. No code is written until the owner commands each step."
---

# PROJECT WARREN — Phase 1 Build Plan

**Version 1.0 (proposal) · oct.2026**\
Collaborators: Andrés Rodarte — sonderbot-ar

> **How to use this document (humans and LLMs).** This plan turns the decisions in `structure-guide.md` into an ordered sequence of milestones. Each milestone lists its goal, the decisions it implements, the tasks, what gets tested, and an exit criterion that must be met before the next milestone starts. Work happens one milestone at a time and only on the owner's command. When a milestone finishes, its status in Section 2 is updated and any decision that changed is recorded in the Structure Guide's decision log.

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
| M1 | Fundamentals data layer (EDGAR, point-in-time) | 2 | oct.26 – nov.08 | M0 | In progress (started oct.14.2026) |
| M2 | Deterministic forecast and DCF engine | 2 | nov.09 – nov.22 | M1 | Not started |
| M3 | Evaluation harness v1 (baseline only) | 1.5 | nov.23 – dec.03 | M2 | Not started |
| M4 | Shock model and Monte Carlo (manual shocks) | 1.5 | dec.04 – dec.13 | M2 | Not started |
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
| 4 Deterministic math engine | M2, M4 |
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

- **`financial_math.py` (pure functions, no I/O):** project revenue and operating income from drivers; unlevered free cash flow = EBIT × (1 − tax) + D&A − capex − ΔNWC; discount factors for a time-varying discount rate; Gordon-growth terminal value; enterprise value to equity value (minus net debt) to value per diluted share; CAPM cost of equity; WACC.
- **Cost of capital:** beta estimated from Yahoo Finance returns of the stock against a broad index over a documented window; risk-free rate from a Treasury yield series; equity risk premium is a `user` assumption (never defaulted silently); cost of debt from interest expense over average debt; weights from market value of equity and book debt. Price data is cached in a `prices` table and used for nothing else.
- **Existing work on the `finance` branch (decided oct.14.2026):** the branch stays unmerged. Its pure ratio library `financial_math.py` moves into `domains/analysis/` with tests here in M2. Its EAV-based `math_engine.py` is discarded and rewritten against `financial_facts`.
- **`math_engine.py`:** pulls point-in-time facts (M1) and prices, pivots them into DataFrames, computes baseline drivers and calls `financial_math.py`.
- **Sanity checks (raise errors):** terminal growth ≥ discount rate; non-positive diluted shares; missing required inputs. **Warnings:** terminal value above a set share of enterprise value; margins outside the company's historical range by a wide margin.

**Tests:** every formula against hand-computed examples (a spreadsheet you build yourself is a great fixture); property tests (higher discount rate never raises value; zero growth and zero reinvestment reduce to a perpetuity); sanity checks fire when they should.

**Exit criterion:** a baseline DCF for every Phase 1 company as of any date, reproducible to the cent from the stored assumptions.

**Learning notes:** a DCF is usually dominated by the terminal value, which is why the warning exists and why small changes to terminal growth or WACC move the result so much. Seeing that in your own numbers is one of the best lessons the engine will give you.

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

**Exit criterion:** `python -m warren run --ticker XXX --as-of YYYY-MM-DD` produces a report and a complete trace.

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
