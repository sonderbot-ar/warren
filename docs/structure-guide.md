---
title: "PROJECT WARREN — Structure Guide"
version: "2.0"
updated: "oct.28.2026"
supersedes: "Structure Guide, sep.2026 (archived at docs/archive/structure-guide-sep2026.pdf)"
companion: "build-plan.md (Phase 1 timeline and implementation plan)"
---

# PROJECT WARREN — Structure Guide

**Version 2.0 · oct.2026** (supersedes the sep.2026 guide)\
Collaborators: Andrés Rodarte — sonderbot-ar

> **How to read this document (humans and LLMs).** This guide states *what* Warren is and *which* design decisions are in force. The companion document `build-plan.md` states *how* and *in what order* Phase 1 gets built. When the two disagree, this guide wins on decisions and the build plan wins on sequencing. Every decision has a status: **Accepted**, **Under review**, **Superseded** or **Out of scope (Phase 1)**. No code is written or changed without an explicit command from the project owner.

## 1. Project Scope and Vision

Project "Warren" is a custom-built, modular financial analysis engine that helps a user track and understand a company's finances **at the fundamental level**, and how news and market sentiment might affect them over time.

Warren merges **deterministic financial calculations** (Discounted Cash Flow models and the financial statements behind them) with **qualitative events** (news, geopolitical or academic developments). The user can apply or alter scenario parameters, representing real-world events or sentiment shocks, and see how a company's projected revenue, margins, cash flows and intrinsic value respond, **when** they respond, and for **how long**.

Warren is built from scratch with LangGraph for orchestration and plain, tested Python for all quantitative work. It avoids "black-box" third-party financial AI frameworks.

### 1.1 What Warren is not

- **Warren does not predict stock prices or market reactions.** That is explicitly out of scope; it belongs to traders and market makers. Price data is used only as an input to the cost of capital (e.g., beta) and for peer comparison.
- Warren does not let an LLM produce financial numbers by itself. LLMs read text and *propose* structured assumptions; deterministic code computes every number (see Decision 4).

### 1.2 Long-term vision (out of scope for Phase 1)

These goals shape the design so the Phase 1 build does not block them, but none of them is built in Phase 1:

- **When does sentiment matter?** Trace *when* sentiment from a given source (outlet, region, topic) has historically preceded a material change in fundamentals, as opposed to noise.
- **A learning environment for finance students.** An interactive tool that shows *when* and *why* a change in beta, capital structure or book value propagates to other lines of a company's financial statements and valuation, and that helps track and forecast performance as those inputs change.
- **Broader driver coverage.** Modelling every link between capital structure, risk and the three statements, beyond the Phase 1 driver set.

## 2. Guiding Principles

1. **Fundamentals, not prices.** Outputs are projected fundamentals and intrinsic value, never price targets.
2. **Time is a first-class dimension.** Every data point carries the period it describes *and* the date it became public. Every shock has a start, a horizon and a decay.
3. **Ranges, not point estimates.** Uncertain inputs are distributions; valuations are run as Monte Carlo simulations and reported as percentiles.
4. **Deterministic math, LLM judgment.** LLMs are used only where judgment over unstructured text is needed. Fetching, cleaning, pivoting and calculating are ordinary code.
5. **Everything is measured.** An evaluation harness checks Warren against what actually happened, using only data that was available at the time (no look-ahead).
6. **Traceability.** Every run records its inputs, assumptions (with their source), LLM calls and outputs, so any number can be traced back to where it came from.
7. **Single responsibility.** Each module and each graph node does one job. This applies at the module/node level, not as "one file per function".

## 3. Core Architecture — Decision Log

| # | Decision | Status | Date |
|---|---|---|---|
| 1 | Model allocation and API keys | Under review | sep.24.2026 |
| 2 | State management: SQLite, typed fact table, small data in graph state | **Accepted** (replaces EAV; version-selection rule revised and provenance added in M1.1) | oct.26.2026 |
| 3 | Data processing: SQLite only, no vector database | **Accepted** (replaces ChromaDB) | oct.14.2026 |
| 4 | Deterministic math engine with explicit, sourced assumptions | **Accepted** (strengthened; equity risk premium and terminal growth computed from market data, M2; terminal rule under review before M4, M2.1) | oct.28.2026 |
| 5 | Telemetry: local JSON log file | Accepted (details under review; timestamp bug fixed) | oct.14.2026 |
| 6 | Shock model: event taxonomy, time-shaped and probabilistic shocks | **Accepted** | oct.14.2026 |
| 7 | Evaluation harness on point-in-time data | **Accepted** | oct.14.2026 |
| 8 | Data sources: SEC EDGAR, Yahoo Finance, FRED, GDELT | **Accepted** (EDGAR coverage limits noted, M1; FRED added for the risk-free rate, M2) | oct.26.2026 |
| 9 | LLM usage limited to judgment-over-text steps | **Accepted** | oct.14.2026 |
| 10 | Development workflow: Claude agent teams plan, review, merge and report; owner sets goals | **Accepted** (replaces owner-approved plans and owner merges) | oct.30.2026 |
| — | Entity-Attribute-Value (EAV) metrics table | Superseded by 2 | sep.24.2026 |
| — | Passing only database IDs between graph nodes | Superseded by 2 | sep.24.2026 |
| — | ChromaDB vector store for documents | Superseded by 3 | sep.24.2026 |
| — | Point-in-time selection "newest filing first, then tag" | Superseded by 2 (M1.1) | oct.26.2026 |

### Decision 1 — Model Allocation and API Keys · *Under review*

- **Current decision (sep.2026):** API keys and model initialisations are declared locally within each domain's `tools.py`, rather than globally.
- **Goal it serves (kept):** different nodes can use different models (a fast, cheap model for extraction, a stronger model for reasoning), and token use and failures are attributable to a specific node.
- **Proposed revision (to be decided after the Phase 1 roadmap is settled):** load API keys once from `.env`; keep one configuration that maps each node to its model. This keeps per-node models and per-node token tracking while avoiding duplicated key handling across files.

### Decision 2 — State Management · *Accepted (replaces EAV and ID-only state)*

- **Decision:** A single SQLite database is the system of record. Reported financial data lives in a **typed, narrow `financial_facts` table keyed by US-GAAP XBRL concept**, with the reporting period and the date the fact was filed. All other entities (runs, assumptions, events, shocks, valuation results, evaluation cases) live in ordinary relational tables with real columns.
- **Controlled vocabulary:** a `concepts` table lists the XBRL concepts Warren uses (e.g., `us-gaap:Revenues`) and their canonical Warren names. Agents and code may only write concepts that exist in this table; they never invent metric names.
- **Point-in-time:** every fact stores `filed_at`. Queries take an `as_of` date and return only what was public on that date. Restated numbers never leak into a historical analysis.
- **Which version wins (revised oct.26.2026, M1.1):** for each period, the highest-priority tag that reports it, then that tag's newest filing public on `as_of`; "as first reported" is the earliest filing. Ranking the tag first separates a restatement from definition drift (a later filing repeating the period under a broader or narrower measure). Superseded: newest filing first, then tag (M1, oct.14.2026).
- **Provenance (oct.26.2026, M1.1):** every ingest records the content hash of the data it loaded, when that data was fetched, and the concept-map hash, because a different concept map can give different answers for the same date.
- **Graph state:** LangGraph state carries **small, typed data directly** (one company's financials are a few KB). Database IDs are used only for large objects (full filings, article bodies). `current_node` is removed from `SimulationState`; LangGraph already tracks it.
- **Audit trail:** LangGraph's SQLite checkpointer stores the full state after every step, which provides the permanent, step-by-step record the original design wanted.
- **Concurrency:** SQLite runs in **WAL (write-ahead logging) mode**, which lets readers keep reading while one writer writes, instead of locking the whole file.
- **Reasoning:** Financial statements already have a standard vocabulary (XBRL), so a generic EAV table only removed types, constraints and readable queries, and risked duplicate metric names. The typed fact table keeps EAV's flexibility (new concepts are new rows, not new columns) without those costs.
- **Superseded:** EAV model (sep.2026); passing only reference IDs between nodes (sep.2026).

### Decision 3 — Data Processing · *Accepted (replaces ChromaDB)*

- **Decision:** Quantitative and qualitative data stay separated, but both live in SQLite. Quantitative facts are pivoted into Pandas DataFrames for time-series alignment and vectorised math. News and documents are stored as rows with metadata (ticker, source, published timestamp) and searched with SQLite full-text search (FTS5).
- **Reasoning:** For news, the useful filters are company, date and source, which are SQL filters. A second database (ChromaDB) would have to be kept in sync for an unproven need.
- **Future option:** if semantic search becomes necessary, add the `sqlite-vec` extension to the same database file.

### Decision 4 — Deterministic Math Engine · *Accepted (strengthened)*

- **Decision:** Financial formulas are fully decoupled from data wrangling and from LLMs.
  - `financial_math.py` — a pure, deterministic calculation library (no I/O, no database, no LLM). Unit-tested in isolation.
  - `math_engine.py` — the data pipeline that fetches point-in-time facts, pivots them into DataFrames and builds the inputs for `financial_math.py`.
- **Additions (oct.2026):**
  - **Multi-year inputs.** A DCF needs several historical years of revenue, operating expenses, taxes, D&A, capex, working capital, cash, debt and diluted shares, not a single year of revenue and COGS. `BaselineFinancials` becomes a view built from facts.
  - **Assumptions are explicit and sourced.** Every assumption (WACC, terminal growth, margins, growth rates) is an input record with a `source` field: `computed`, `user` or `llm_proposed`. Nothing is silently defaulted. ("Must be computed or asked, never assumed" becomes a rule enforced in code, not a comment.)
  - **Sanity checks that fail loudly.** Examples: terminal growth must be below WACC; shares outstanding must be positive; a warning when terminal value dominates total value (since M2.1: when WACC − terminal growth is below 3 points). Warnings about a valuation read only the run's rows and outputs, so they also apply to shocked drivers (M2.1).
  - **Cost-of-capital inputs are computed (oct.26.2026, M2).** The equity risk premium is the realized geometric premium of the S&P 500 Total Return over a 10-year Treasury bond's total return (built from DGS10, the same rate CAPM uses), over full years from 1989 to the last year ended before the as-of date. Terminal growth equals the risk-free rate at the as-of date. The owner sets the methods, not the numbers; each run stores the computed values with their years, standard error and data hashes. Limits (noise, procyclicality, window dependence) are listed in the build plan's risks.
  - **Runs are reproducible from their rows (oct.26.2026, M2).** Every input of a DCF run, including the base values taken from filings and the reported history behind each driver, is an assumption row with its rule, tag and filing; the valuation is a pure function of those rows, and each run records the code version and the hashes of the data it was built from. Every market download is kept (M2.1, oct.28.2026), so a run's rows can also be rebuilt from the data it used: `reproduce --rebuild` pins the run's downloads by hash and compares every row. Driver, net-debt and share-count rules are in the build plan (M2, owner decisions and implementation notes).
  - **Terminal growth stays = R_f through M3 (oct.28.2026, M2.1).** M3's 1-4 quarter forecasts don't depend on it, so M3 can't test it; the terminal rule (cap on growth, floor on the WACC − growth spread, reinvestment tied to growth) is decided before M4.
  - **Checks are universal (oct.26.2026, M2).** Data-quality and sanity checks apply the same rules to every company; there is no per-company review list. Optional concept-map items are not part of the quality report; they are traced through the assumption rows of the runs that use them.
  - **Monte Carlo.** The DCF runs over sampled driver distributions with a fixed random seed for reproducibility, producing percentiles (p10/p50/p90) instead of a single value.

### Decision 5 — Telemetry: Local Log File · *Accepted (details under review)*

- **Decision:** The decoupled observer records system health and token usage by appending JSON lines to a local log file, rather than calling an external API.
- **Reasoning:** Writing to a local file avoids network-related bugs during the initial build. Once the orchestrator and database are stable, the emitter can be swapped for an API-based system.
- **Known issue (fixed oct.14.2026, M0):** `TelemetryEvent.timestamp` used `default_factory=datetime`, which raised an error. It now defaults to a timezone-aware UTC "now".
- **Proposed additions (under review):** record model name, input and output tokens separately, cost and latency per call.

### Decision 6 — Shock Model · *Accepted*

- **Principle:** sentiment is not impact. The *type* of event and its *materiality* drive impact, not how positive or negative the wording is.
- **Decision:** A news-driven shock is built in three steps:
  1. **Event extraction (LLM):** articles are deduplicated into a single event and classified into a fixed taxonomy (e.g., guidance change, earnings surprise, M&A, litigation, regulation, product launch or recall, management change, supply chain, macro).
  2. **Shock proposal (LLM, reviewable):** the event is mapped to changes in named model drivers, each with a range, a start date, a horizon and a decay. The LLM proposes; the user can override; code computes.
  3. **Simulation (deterministic):** shocks are applied to the driver paths and the DCF runs as Monte Carlo.
- **Shape of a shock:** *driver* (what it moves), *magnitude* as a distribution (low / base / high), *start* (when it begins), *horizon* (how long it lasts) and *decay factor* (how fast it fades; a decay of 1.0 means permanent).
- **Phase 1 driver set:** revenue growth, operating margin, capex intensity and a cost-of-capital (risk premium) adjustment. The model is designed so further drivers (beta, capital structure, book value) can be added later for the long-term vision.
- **Out of scope (Phase 1):** learning *when* sentiment from a particular source is impactful.

### Decision 7 — Evaluation Harness · *Accepted*

- **Decision:** Warren is evaluated against real outcomes from the start, not after the agents are built.
- **Method:** for a library of historical events, Warren runs *as of* the event date using only data public at that time, forecasts the affected fundamentals over the next quarters, and the forecast is compared with the figures the company later reported (as first reported).
- **Key question it answers:** does including the news-driven shock make the forecast better than the same forecast without it?
- **Metrics:** forecast error with and without shocks, direction accuracy, and calibration of the ranges (do roughly 80% of outcomes fall inside the p10–p90 band?).
- **Rule:** stock price movements are never an evaluation target (see 1.1).

### Decision 8 — Data Sources · *Accepted*

| Data | Source | Notes |
|---|---|---|
| Fundamentals | **SEC EDGAR** XBRL APIs (company facts / company concept) | Official and free; includes filing dates for point-in-time queries. Requires a descriptive User-Agent and respects SEC rate limits. Company facts include only standard-taxonomy, non-dimensional facts: lines a company reports under its own extension tag, or only by segment, are missing (found in M1; each gap is documented). |
| Prices | **Yahoo Finance** (via the `yfinance` library) | Used for beta / cost of capital (including the S&P 500 Total Return index behind the equity risk premium, M2) and peer comparison only. Unofficial interface, so it sits behind a small adapter and results are cached in SQLite. Closes come adjusted for later splits; stored split ratios put a price back on its own day's share basis (M2). A refresh adds a download and keeps the earlier ones (M2.1). |
| Risk-free rate | **FRED** (series DGS10, 10-year Treasury, from the Fed's H.15 release) | Added in M2 (owner decision oct.26.2026). Keyless CSV download, cached in SQLite. Published the next business day, so a query uses the latest observation dated before its as-of date. |
| News and events | **GDELT** (GDELT 2.0 Events and Global Knowledge Graph) | Free, global, timestamped, with themes, tone and organisations. Noisy by design: cleaning, company matching and deduplication are part of the work and part of the learning goal. GDELT provides article URLs and metadata, not full article text. |

### Decision 9 — LLM Usage · *Accepted*

- **Decision:** In Phase 1, LLMs are used for exactly two tasks: event extraction and classification, and shock proposal. A third, optional task is writing the final plain-language explanation of a run. Fetching data, cleaning, pivoting, calculating and evaluating are deterministic graph nodes without an LLM.
- **Reasoning:** fewer LLM steps make Warren cheaper, faster and testable. New LLM steps may be added as the project grows; each one will be recorded here.

### Decision 10 — Development Workflow: Agent Teams · *Accepted (oct.30.2026)*

- **Decision:** Warren is built by Claude agent teams. An *Elephant* thread per track writes a design doc, the code and the tests, and merges. *Goldfish* reviewers (explainer, analyst, professor, gatekeeper) start with fresh context and review the design and the PR. Reporters write a desk entry and a one-page lesson per merged version. The owner sets goals, answers decision cards and reads reports; the owner no longer approves plans or merges PRs. The full loop is in `CLAUDE.md`.
- **What still goes to the owner:** changes to the Phase 1 goal, universe or scope; changing, dropping or adding a design decision; anything that costs money; anything irreversible (rewriting or force-pushing `main`, deleting branches with unmerged work, making the repository public).
- **Safety net:** CI (ruff and pytest) on every PR, required before merge; invariants as tests (reproduce to the cent, point-in-time, property tests on `financial_math.py`); a version tag on every merge; bad merges undone by a revert PR.
- **Reasoning:** the owner had become the bottleneck for both building and learning. Independent fresh-context review, automated tests and cheap rollback replace line-by-line human review. Free tools only by default; Elephant-Goldfish is adopted as a method, not as a plugin.
- **Replaces:** the M0–M2.1 workflow (owner-approved plan, "go M<n>" trigger, owner reviews and merges every PR).

## 4. Project Structure

Target layout for Phase 1, created step by step through the build plan. So far `shared_kernel/` (config, database, migrations, schemas), `domains/fundamentals/` (M0–M1.1), `domains/market/` and `domains/analysis/` (M2) exist; the other domain packages are empty placeholders until their milestone:

```text
warren/
├── CLAUDE.md                 # short pointer for coding assistants: read docs/ first
├── README.md
├── pyproject.toml / requirements.txt
├── .env.example              # API keys, SEC User-Agent
├── docs/
│   ├── structure-guide.md    # this document (source of truth for decisions)
│   └── build-plan.md         # Phase 1 timeline and implementation plan
├── shared_kernel/
│   ├── config.py             # settings, node-to-model map (pending Decision 1)
│   ├── database.py           # connection, WAL mode, migrations
│   ├── schemas.py            # Pydantic models shared across domains
│   └── telemetry.py          # JSON-lines emitter
├── domains/
│   ├── fundamentals/         # EDGAR client, concept map, fact ingestion
│   ├── market/               # Yahoo Finance adapter, price cache
│   ├── news/                 # GDELT client, company matching, event clustering
│   ├── analysis/             # financial_math, math_engine, Monte Carlo
│   ├── llm/                  # event extraction, shock proposal, prompts
│   ├── orchestration/        # LangGraph graph, nodes, state
│   └── evaluation/           # case library, backtests, metrics
├── data/                     # git-ignored: warren.db, logs/, raw downloads
└── tests/                    # mirrors domains/
```

## 5. Glossary

- **XBRL / US-GAAP concept:** the standard machine-readable tags US companies use in SEC filings (e.g., `us-gaap:Revenues`).
- **Point-in-time (as-of) data:** data as it was publicly known on a given date, before any later restatement.
- **Look-ahead bias:** accidentally using information in a historical analysis that was not available at the time.
- **WAL mode:** SQLite's write-ahead logging; writes go to a separate log first so readers are not blocked.
- **Driver:** a model input that determines the forecast (e.g., revenue growth, operating margin).
- **Shock:** a change to a driver caused by an event, with magnitude, start, horizon and decay.
- **Decay factor:** how much of a shock remains each subsequent period; 1.0 is permanent, 0.5 halves each period.
- **Monte Carlo simulation:** running the model many times with inputs sampled from their distributions to get a distribution of outcomes.
- **p10 / p50 / p90:** the 10th, 50th and 90th percentiles of a simulated outcome.
