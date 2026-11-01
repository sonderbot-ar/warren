# M7 design: one command runs the whole pipeline (LangGraph orchestration and telemetry)

Status: In progress (nov.01.2026) · Elephant: agent team · Branch `m7-orchestration`
Implements Structure Guide Decisions 2 (graph state, checkpointer) and 5 (telemetry), and Build Plan M7.

## Problem

Every piece of Warren works, but only as separate commands that a person runs in the right order: ingest filings, load prices, value the company, read a week of news, group it into events, classify the events, propose shocks, review them, simulate, write reports. Nothing ties one company and one date to one record of everything that was done for it. M7 makes that one command:

```text
python main.py run --ticker MSFT --as-of 2022-06-02
```

which produces one Markdown report and one complete trace: each step's state saved after it ran (the checkpoint), and one JSON line per step with its timing, status, errors and, for the two LLM steps, model and tokens.

M7 adds no new financial logic. Every number still comes from the M2–M6 code, called as a library (Decision 11, guardrail 4). The graph only decides the order, carries a small typed state, saves it after every step, and pauses for the human review.

## The graph

```text
load_fundamentals → load_market → build_baseline → fetch_news → cluster_events
    → extract_events (LLM) → propose_shocks (LLM) → review_shocks (human interrupt)
    → simulate (Monte Carlo) → write_report
```

The Build Plan's graph plus one node, `load_market`: prices and the risk-free rate are a second data source with their own adapter (Decision 8), so they get their own step (Principle 7). The Build Plan's optional LLM narrative in `write_report` is left out: the report is built from stored rows only, so it reproduces exactly and no LLM writes about numbers. A narrative can come later as a backlog item.

Each node is a plain function `node(state, deps) -> dict of state changes` in `domains/orchestration/nodes.py`, calling the existing domain functions. `deps` holds what can't go in state (the database connection, the LLM client, the EDGAR and GDELT downloaders, the clock, the report and telemetry folders); tests pass fakes. `graph.py` wraps each node with the telemetry emitter and wires them into a LangGraph `StateGraph`.

| Node | Calls | Writes to state |
|---|---|---|
| `load_fundamentals` | `fundamentals.ingest.ingest_company` when the company has no stored ingest or `--refresh` is given; otherwise nothing | `cik`, company name, the latest `ingest_runs` id and its fetch time |
| `load_market` | `market.prices.load_prices` for the ticker and the market index, `market.yields.load_yields` for DGS10, each only when the stored series ends before the as-of date or is missing | the `market_fetches` ids used |
| `build_baseline` | the latest stored baseline run for (ticker, as-of) with no seed, as `domains/llm/__main__._baseline_run` does, else `analysis.runs.run_baseline` | `run_id`, value per share (and whether it was reused) |
| `fetch_news` | `news.store.ingest_window` for the 7 New York days ending on the as-of date (M5's case window); files already read under the current alias set are not downloaded again | files by status (ok, missing, fetch_error, …), articles kept |
| `cluster_events` | `news.cluster.run_events` with the headline rule (M5) | `event_run_id`, events in the window |
| `extract_events` | `llm.extract.classify_case`, case id `<TICKER>_<as-of>` | classifications per variant: total, failed, not about the company |
| `propose_shocks` | `llm.propose.propose_case` per variant | `set_id` per variant, proposals in classes (driver, direction, size, duration) |
| `review_shocks` | `llm.review.review_set`, auto or with a person (below) | counts by review status per variant |
| `simulate` | `analysis.montecarlo.save_simulation` per variant with that variant's approved shocks | `sim_id` per variant (or none when there is no shock), value per share p10/p50/p90 |
| `write_report` | `orchestration.report.write_report` | report path |

**Case id.** M6 keys its stored answers by case id `<TICKER>_<YYYY-MM-DD>`, which is how every eval case id is built (`domains/evaluation/cases.csv`). The pipeline uses the same id for any ticker and date, so running the pipeline on an eval case reuses M6's stored answers (no new LLM call), and a new date gets new rows under its own id.

**Point-in-time.** No node adds a query. Each one calls a domain function that already takes the as-of date and reads only what was public by then (M1 facts by `filed_at`, M2 prices on or before the date, M5 sightings before the New York close of the as-of date, M6 inputs built from those). Downloading today's EDGAR file or today's price history is not a leak, because every read filters by date; a test runs the graph on Test Corp with filings dated after the as-of date in the data and checks the baseline is the same as without them.

## State (Decision 2)

`PipelineState`, a Pydantic model in `domains/orchestration/state.py` (`extra="forbid"`), replaces the `SimulationState` placeholder in `shared_kernel/schemas.py`, which said so. Small typed data only:

```text
pipeline_id, ticker, as_of, variants, review, seed, n_samples, budget      -- the request
cik, company, ingest_run_id, market_fetch_ids                               -- data used
run_id, baseline_value_per_share, baseline_reused                           -- baseline
news_files, articles_kept, event_run_id, events_in_window                   -- news
classified[variant], proposal_set[variant], proposals[variant]              -- LLM steps
reviewed[variant], sim[variant] (sim_id, p10, p50, p90)                     -- review, simulation
report_path
```

Database ids only for large things: article text and headlines stay in `article_sightings`, filings in `financial_facts`, assumptions in `run_assumptions`. A full state is a few KB. `current_node` is gone, as Decision 2 says: LangGraph records which node is next.

**The seed is chosen once, when the pipeline starts** (`--seed`, or a fresh one from `numpy.random.SeedSequence`, as M4), and stored in state and in `pipeline_runs`. So a `simulate` node that runs again after a failure or a resume uses the same seed, and finds its own stored simulation instead of adding a second one (below).

## Checkpointer (Decision 2, audit trail)

LangGraph's `SqliteSaver` (`langgraph-checkpoint-sqlite`, scout issue #87) saves the full state after every node. Thread id = `pipeline_id`. It writes to the same `data/warren.db`, the single system of record (Decision 2), on its own connection, as WAL mode allows one writer and many readers; its two tables (`checkpoints`, `writes`) are created by `SqliteSaver.setup()`, not by Warren's migrations, and migration 0015 checks no Warren table uses those names. Because it lives in `warren.db`, the data snapshot (`shared_kernel/snapshot.py`) carries it with no change. Durability is `sync`: the checkpoint is written before the next node starts.

- **Resume after a failure.** A node that raises stops the graph; its telemetry line says `error` with the message, and `pipeline_runs.status` is `failed`. `resume --pipeline-id` runs the graph again from the last checkpoint, which re-runs the failed node and never the ones before it.
- **Resume after review.** See below.
- **History.** `show --pipeline-id` prints every checkpoint in order: the node that ran and the state fields it changed.

### Nodes that run twice

LangGraph re-runs a node from the top when it resumes into it, and a crash between a node's commit and its checkpoint does the same. Every node is therefore safe to run twice:

- the domain functions are already idempotent (an ingest adds nothing new, `run_events` returns the stored run for the same input, M6 reuses stored `ok` answers, review skips proposals that have a status);
- `build_baseline` reuses the latest stored baseline for (ticker, as-of);
- `simulate` first looks for a stored simulation of the same run with the same seed, sample count and `shocks_sha256`, and returns it.

A test re-runs every node on its own output state and checks no table gained a row.

## Human review (the interrupt)

`--review auto | manual | later`:

- **auto** records every proposal `auto_approved` with reviewer `none` (M6). It is the default for an eval case, because a person reviewing a past event today knows what happened next (M6, Human review).
- **manual** is the default for any other date. `review_shocks` lists the variant's proposals and calls LangGraph's `interrupt()` with them (driver, classes, the code-computed low, base and high, rationale, evidence). The command line shows each one, asks approve, edit or reject (the M6 prompts), and resumes the graph with the answers. `review_set` then stores them, so an edited shock keeps `source='user'` and the proposal keeps the model's original (M6).
- **later** stops at the interrupt and exits with code 4 and the command to continue: `resume --pipeline-id ID`, which asks the questions then. The run's state waits in the checkpoint, so the person can come back days later.

Nothing is written before the interrupt; the answers are applied after it, so the node re-running on resume does not double anything. An answer that names a proposal not in the set, or an edit that changes nothing, is refused before any row is written (M6 `review_set` already refuses the second).

A variant with no proposals (no events, or "no material impact") skips the interrupt.

## Simulation and the report

`simulate` runs one Monte Carlo per variant that has at least one approved shock, on the baseline run, with the pipeline's seed and `--n` samples (default 10,000, M4). A variant with no shocks gets no simulation, and the report says the shocked value equals the baseline.

`write_report` writes `data/reports/pipeline/<pipeline_id>.md`, rendered only from stored rows, so the same pipeline renders the same text every time (a test renders twice and compares):

1. **Headline.** Company, as-of date, value per share: baseline, and per variant the shocked p10, p50 and p90 (Build Plan M7).
2. **Paths.** Per period (Q1–Q8, Y3–Y5): revenue, operating margin and free cash flow, baseline and shocked p10/p50/p90, from `simulation_outputs`.
3. **Shocks with their evidence.** Each approved shock: driver, low/base/high, start, horizon, decay, source and review status, the model's classes and σ (the M6 rationale line), and the headlines of the events it cites, with their dates.
4. **News used.** Files read and missing in the window, events in the window, events classified, failed and not about the company.
5. **Assumptions with sources.** The baseline run's assumption table, from the M2 report (`analysis.report.render`), included as is.
6. **Trace.** The pipeline id, the code version, each node's status, and where the checkpoint and the telemetry file are. Durations and tokens are read from the telemetry file, so they are listed apart from the numbers and are the one part that is not a function of the database.

Section 6 says what is not checked by `reproduce`: the telemetry lines.

## Telemetry (Decision 5)

A decoupled emitter (`domains/orchestration/telemetry.py`) wraps each node: before it runs and after, it appends one JSON line to `data/telemetry/<pipeline_id>.jsonl`. A line is a `TelemetryEvent` (`shared_kernel/schemas.py`), extended:

```text
pipeline_id, node, status started|ok|error|interrupted, started_at, ended_at, duration_ms,
error (type and message, no traceback), and for LLM nodes per model:
calls, reused (answers taken from the database), input_tokens, output_tokens
```

The LLM numbers are not estimated: each LLM node runs with batch id `<pipeline_id>:<node>`, and the emitter sums `llm_calls` for that batch after the node (M6 records every attempt with its tokens). Keys never appear: the emitter writes no inputs, prompts or environment. LangSmith tracing, which LangGraph can send to an outside service, stays off: `deps` refuses to start when `LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2` is set true, because Decision 5 keeps telemetry local.

Decision 5's open details are settled as the Build Plan's M7 lists them (model, input and output tokens, status, errors, timing). Cost in dollars is left out: prices change, and tokens per model are enough to price a run on any day. The decision log gets a row.

## Storage (migration 0015)

```text
pipeline_runs(pipeline_id PRIMARY KEY, ticker, as_of, variants, review, seed, n_samples,
              status running|waiting_review|done|failed, run_id, report_path,
              telemetry_path, code_version, started_at, finished_at)
```

`pipeline_id` is `<TICKER>_<as-of>_p<N>`, numbered per ticker and date like run ids. The table is the index of pipelines; their full state is in the checkpoints. No money columns (guardrail 3 adds nothing).

## Commands

```text
python main.py run --ticker T --as-of YYYY-MM-DD [--variant named|masked|both]
                   [--review auto|manual|later] [--seed N] [--n 10000] [--refresh] [--offline]
                   [--max-tokens-total N]
python main.py resume --pipeline-id ID
python main.py show --pipeline-id ID
python main.py reproduce --pipeline-id ID
```

(`python -m domains.orchestration …` is the same command; `main.py` only calls it.)

- `--variant` defaults to `named` for a new date and `both` for an eval case, as M8 scores both.
- `--offline` downloads nothing: a node whose data is missing fails with what is missing, instead of fetching.
- `--max-tokens-total` is M6's budget, per LLM node.
- `reproduce` checks the pipeline's baseline run (`analysis.runs.reproduce`) and each simulation (`montecarlo.reproduce_simulation`) to the cent, and that the report renders to the same text; exits 1 on any difference.
- Exit codes: 0 done, 1 a node failed, 2 bad arguments or setup (a missing key), 3 the LLM budget was spent (M6), 4 waiting for review.

## Steps

- **Step 0.** This design doc; M7 "In progress" in the build plan.
- **Step 1.** `langgraph` and `langgraph-checkpoint-sqlite` pinned (MIT; the scout's licence check, issue #87); `PipelineState` (replacing `SimulationState`); the extended `TelemetryEvent` and the emitter; migration 0015. Tests: state refuses an unknown field; a telemetry line is valid JSON that validates as `TelemetryEvent`, one `started` and one end line per node; an error line has the message and no traceback; LLM token sums by batch id; LangSmith tracing set true is refused; the migration applies to a v14 database.
- **Step 2.** The nodes as plain functions over `deps`. Tests on Test Corp (fundamentals, market, news through fake downloaders, a `FakeClient`): each node writes what the table says; `load_fundamentals` and `load_market` download nothing when the data is stored and `--offline` fails clearly when it is not; filings dated after the as-of date leave the baseline unchanged; every node run twice adds no row.
- **Step 3.** The graph, the checkpointer and the review interrupt. Tests: the graph runs end to end on Test Corp with LLM calls stubbed and gives the same value per share as the M6 commands run by hand; a node that fails once is resumed and the nodes before it don't run again; `later` stops with the state saved and `resume` with answers finishes it; manual edit and reject answers reach `review_set`; an answer naming an unknown proposal is refused before any write; the checkpoint history has one entry per node.
- **Step 4.** The report. Tests: every section is there; rendering twice gives the same text; a variant with no shocks says the shocked value equals the baseline; each shock lists its evidence headlines.
- **Step 5.** The command line and `main.py`. Tests: `run` end to end on Test Corp with a fake client (exit 0, report and telemetry written); `later` exits 4 and `resume` finishes; `reproduce` exits 0, and 1 after a stored output is changed; a missing key exits 2 before any call.
- **Step 6.** Real run (needs the data snapshot, the key and SEC_USER_AGENT): one eval case (expected: M6's answers reused, zero LLM tokens, the same shocks as stored) and one new date not in the case library (all steps live, auto review, so the run can finish unattended). Results here and in the build plan; M7 Done on merge.

Steps 1–5 merge as one engine PR, as M3, M4 and M6 did; Step 6 is a second PR.

**Cost of Step 6.** The eval case costs nothing (stored answers). The new date is up to 15 extraction calls and one proposal call per variant: at M6's prices, a few cents.

## Exit criterion (Build Plan)

A single command, given a ticker and an as-of date, produces a report and a complete trace. Read here as: `python main.py run` on a new date finishes with exit 0, a report with every section above, a telemetry line per node, and a checkpoint per node; and `reproduce` on it exits 0.

## Alternatives considered

- **No LangGraph; a plain Python function calling the steps in order.** Simpler, and it would work today. Rejected: Decision 2 names LangGraph's checkpointer as the audit trail, and resuming after a human review or a failure is exactly what it gives for free. It is also the orchestration a finance student will meet elsewhere.
- **A separate checkpoint file.** Keeps LangGraph's tables out of `warren.db`. Rejected: Decision 2 makes one database the system of record, and the snapshot would need a second file.
- **Pass the database connection in state.** Rejected: state is checkpointed and must be plain data; the connection goes in `deps`.
- **Telemetry in a database table.** Rejected for now: Decision 5 chose a local log file so a broken database can't hide why a run broke.
- **An LLM narrative in the report.** Deferred: optional in the Build Plan, and a narrative about numbers is the one place an LLM could restate a figure wrongly.
- **Parallel nodes (news while the baseline builds).** Deferred: the pipeline is minutes, dominated by the GDELT download, and a straight line is easier to read and to resume.

## Files

New: `domains/orchestration/{state,telemetry,nodes,graph,report,__main__}.py`, `shared_kernel/migrations/0015_pipeline_runs.sql`, `tests/orchestration/*`.
Changed: `main.py`, `shared_kernel/schemas.py` (`TelemetryEvent`, `SimulationState` removed), `requirements.txt`, `docs/build-plan.md`, `docs/structure-guide.md` (Decision 5 details and the log row, Section 4 layout).

## Review log

(design review pending)

## Where the work stopped

Step 0.
