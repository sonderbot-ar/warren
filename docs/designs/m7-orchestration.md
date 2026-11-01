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
| `load_fundamentals` | `fundamentals.ingest.ingest_company` when the company has no stored ingest, its latest ingest was fetched before the as-of date (filings public on the date could be missing), or `--refresh` is given; otherwise nothing | `cik`, company name, the latest `ingest_runs` id |
| `load_market` | `market.prices.load_prices` for the ticker and the market index, `market.yields.load_yields` for DGS10, each only when `market.store.require_coverage` refuses it (no download, or one made before the as-of date), or `--refresh` is given | the `market_fetches` ids used |
| `build_baseline` | a stored baseline for (ticker, as-of) only when it was built from exactly what a new one would read (below), else `analysis.runs.run_baseline` | `run_id`, value per share (and whether it was reused) |
| `fetch_news` | `news.store.ingest_window` for the 7 New York days ending on the as-of date (M5's case window); files already read under the current alias set are not downloaded again | files by status (ok, missing, fetch_error, …), articles kept |
| `cluster_events` | `news.cluster.run_events` with the headline rule (M5) | `event_run_id`, events in the window |
| `extract_events` | `llm.extract.classify_case`, case id `<TICKER>_<as-of>` | classifications per variant: total, failed, not about the company |
| `propose_shocks` | `llm.propose.propose_case` per variant, on the pipeline's event run and baseline run | `set_id` per variant, proposals in classes (driver, direction, size, duration) |
| `review_shocks` | `llm.review.review_set`, auto or with a person (below) | counts by review status per variant |
| `simulate` | `analysis.montecarlo.save_simulation` per variant with that variant's stored shocks (`llm.review.approved_shocks`: proposals `approved`, `auto_approved` or `edited`; a rejected proposal stores no shock), on the run the set was sized on, which is the pipeline's run | `sim_id` per variant (or none when there is no shock), value per share p10/p50/p90 |
| `write_report` | `orchestration.report.write_report` | report path |

**Data freshness, one rule.** A stored download is used when it was made on or after the as-of date, which is the rule M2 already enforces for prices (`market.store.require_coverage`); anything older is downloaded again (online) or refused (`--offline`). Because the rule looks at when the data was fetched, not at the last date in the series, a weekend, a holiday or a series published a day late (DGS10) does not trigger a download on every run (analyst review). The as-of date must have ended: a date whose New York midnight (`news.gdelt.known_by`, M5's cut-off) is still in the future is refused, so news and prices never cover part of a day.

**Baseline reuse.** A stored baseline for (ticker, as-of) is reused only when its ingest run is the company's latest, its concept-map hash is today's, its three market fetch hashes are the ones `selected_fetch` gives now, and its stored owner choices (`analysis.runs.stored_choices`) equal today's `user_assumptions.csv`. Otherwise a new run is built. `--refresh` downloads again and so builds a new run. The code version is not part of the match: a run made by older code is still checked to the cent by `reproduce` (analyst review).

**Case id.** M6 keys its stored answers by case id `<TICKER>_<YYYY-MM-DD>`, which is how every eval case id is built (`domains/evaluation/cases.csv`). The pipeline uses the same id for any ticker and date, so running the pipeline on an eval case reuses M6's stored answers (no new LLM call), and a new date gets new rows under its own id. Reuse is not by case id alone: a classification is keyed by event id, which carries the event run's hash (`cluster.run_events`), and a proposal set by the classifications it read.

**Two fixes to M6's reuse (analyst review, both blockers).** M6 had one news ingest and one baseline per case, so two gaps never showed; a pipeline that runs again can hit both:

- *One story counted twice.* `propose.case_events` read the classifications of every event run stored for the case id. A second ingest of the window (a fetch error read again, a new alias set) makes a second event run, and the proposal would see the same story under two event ids. It now reads one event run: the pipeline's, or for the M6 command the case's most recent (`case_llm_status`, by row order).
- *Shocks sized on one baseline, simulated on another.* A proposal set's σ and low, base and high are computed from its baseline run, but the run was not in the set's key, so a set sized on run `_1` was reused for run `_3`. Migration 0015 rebuilds `proposal_sets` with `run_id` and `scales_sha256` (the SHA-256 of `scales.csv`) in its key; stored sets keep their run and get today's scales hash, which is right because `scales.csv` has not changed since it was added (oct.31.2026), before any stored set. `simulate` checks that the set's run is the pipeline's run, and `reproduce` checks it again.

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

- **auto** records every proposal `auto_approved` with reviewer `none` (M6). It is the default for any as-of date more than 7 days before today, because a person reviewing a past event today knows what happened next (M6, Human review; Fischhoff 1975, "Hindsight ≠ foresight"). That covers every eval case, and any old date, in the library or not (professor and analyst review).
- **manual** is the default for a date in the last 7 days (live use). Asked for on an older date, it runs, but the command warns first and the report marks each shock a person reviewed after its as-of date: `reviewed_at` (new on `shock_proposals`) against `as_of`, with the reviewer, as model-risk guidance asks of every override (Federal Reserve SR 11-7, 2011). `review_shocks` lists the variant's proposals and calls LangGraph's `interrupt()` with them (driver, classes, the code-computed low, base and high, rationale, evidence). The command line shows each one, asks approve, edit or reject (the M6 prompts), and resumes the graph with the answers. `review_set` then stores them, so an edited shock keeps `source='user'` and the proposal keeps the model's original (M6).
- **later** stops at the interrupt and exits with code 4 and the command to continue: `resume --pipeline-id ID`, which asks the questions then. The run's state waits in the checkpoint, so the person can come back days later.

Nothing is written before the interrupt; the answers are applied after it, so the node re-running on resume does not double anything. The answers come back together, so they are checked together before `review_set` writes anything: one answer per open proposal, no unknown proposal id, a known action, and an edit that changes at least one editable field. One bad answer refuses the whole batch and the graph asks again (professor review: `review_set` commits one proposal at a time).

One interrupt for every variant at once (a resume replays a node's interrupts in order, so one pause per node keeps the replay simple), with the answers sent back as JSON text. A variant with no open proposals (no events, "no material impact", or every proposal already reviewed) skips it. **Earlier verdicts are inherited:** review is idempotent (M6), so a proposal reviewed by an earlier pipeline or by M6's `--auto` keeps that status and is not asked again; the report lists each shock's status, reviewer and review time, so an inherited verdict is visible (analyst review).

## Simulation and the report

`simulate` runs one Monte Carlo per variant that has at least one approved shock, on the baseline run, with the pipeline's seed and `--n` samples (default 10,000, M4). A variant with no shocks gets no simulation, and the report says the shocked value equals the baseline.

`write_report` writes `data/reports/pipeline/<pipeline_id>.md`. Sections 1–5 are rendered only from stored rows, so they render to the same text every time; section 6, the trace, comes after a fixed marker line and reads the telemetry file (explainer and professor review). Report text sits in one place, `domains/orchestration/text.py`, apart from the code that fills it (guardrail 5).

1. **Headline.** Company, as-of date, value per share: baseline, and per variant the shocked p10, p50 and p90 (Build Plan M7), with one line saying that p10–p90 is the spread of values the shocks allow, not a forecast of the share price, and one line on what the named and masked variants are. Both variants use the pipeline's one seed, so their ranges differ only by their shocks. Any warning the simulation stored (M4 rate checks, backlog #90) is listed here. When a variant has no shock, the report says why: no events in the window, the model found no material impact, the proposal failed, or every proposal was rejected; its value is the baseline's, and its paths show the baseline only.
2. **Paths.** Per period (Q1–Q8, Y3–Y5): revenue, operating income (EBIT) and free cash flow, baseline and shocked p10/p50/p90, from `simulation_outputs`. (A percentile of margin is not EBIT's percentile over revenue's, so the stored lines are shown, not a ratio of them.)
3. **Shocks with their evidence.** Each approved shock: driver, low/base/high, start, horizon, decay, source and review status, the model's classes and σ (the M6 rationale line), and the headlines of the events it cites, with their dates.
4. **News used.** Files read and missing in the window, events in the window, events classified, failed and not about the company.
5. **Assumptions with sources.** The baseline run's assumption table, from the M2 report (`analysis.report.render`), included as is.
6. **Trace.** The pipeline id, the code version, each node's status, and where the checkpoint and the telemetry file are. Durations and tokens are read from the telemetry file, so they are listed apart from the numbers and are the one part that is not a function of the database.

`reproduce` compares the report's bytes up to the trace marker, never the trace.

## Telemetry (Decision 5)

A decoupled emitter (`domains/orchestration/telemetry.py`) wraps each node: before it runs and after, it appends one JSON line to `data/telemetry/<pipeline_id>.jsonl`. A line is a `TelemetryEvent` (`shared_kernel/schemas.py`), extended:

```text
pipeline_id, node, status started|ok|error|interrupted, started_at, ended_at, duration_ms,
error (type and message, no traceback), and for LLM nodes per model:
calls, reused (answers taken from the database), input_tokens, output_tokens
```

The LLM numbers are not estimated: each LLM node runs with batch id `<pipeline_id>:<node>`, and the emitter sums `llm_calls` for that batch after the node (M6 records every attempt with its tokens). The sum covers every attempt of that node in the pipeline so far, so after a resume the last end line holds the node's whole cost. The M6 budget is per batch, so per node per pipeline; when it is spent the node fails with exit 3, and `resume --max-tokens-total N` continues with a larger one.

**The telemetry file is kept.** `shared_kernel/snapshot.py` adds `data/telemetry/` to the archive, so a restored machine has the trace the report points to. Reports are not added: `python main.py report --pipeline-id` renders one again from the database (explainer review). Keys never appear: the emitter writes no inputs, prompts or environment. LangSmith tracing, which LangGraph can send to an outside service, stays off: `deps` refuses to start when `LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2` is set true, because Decision 5 keeps telemetry local.

Decision 5's open details are settled as the Build Plan's M7 lists them (model, input and output tokens, status, errors, timing). Cost in dollars is left out: prices change, and tokens per model are enough to price a run on any day. The decision log gets a row.

## Storage (migration 0015)

```text
proposal_sets: rebuilt with run_id and scales_sha256 in its UNIQUE key (above)
shock_proposals: + reviewed_at
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
python main.py report --pipeline-id ID
```

(`python -m domains.orchestration …` is the same command; `main.py` only calls it.)

- `--variant` defaults to `named` for a new date and `both` for an eval case, as M8 scores both.
- `resume` continues a `failed` or `waiting_review` pipeline from its last checkpoint; on a `done` one it does nothing. `reproduce` needs a `done` pipeline.
- `--offline` downloads nothing: a node whose data is missing fails with what is missing, instead of fetching.
- `--max-tokens-total` is M6's budget, per LLM node.
- `reproduce` checks the pipeline's baseline run (`analysis.runs.reproduce`) and each simulation (`montecarlo.reproduce_simulation`) to the cent, and that the report renders to the same text; exits 1 on any difference.
- Exit codes: 0 done, 1 a node failed, 2 bad arguments or setup (a missing key), 3 the LLM budget was spent (M6), 4 waiting for review.

## Steps

- **Step 0.** This design doc; M7 "In progress" in the build plan.
- **Step 1.** `langgraph` and `langgraph-checkpoint-sqlite` pinned (MIT; the scout's licence check, issue #87); `PipelineState` (replacing `SimulationState`); the extended `TelemetryEvent` and the emitter; migration 0015 (`pipeline_runs`, `reviewed_at`, the `proposal_sets` key); the two M6 reuse fixes; telemetry in the snapshot. Tests: state refuses an unknown field; a telemetry line is valid JSON that validates as `TelemetryEvent`, one `started` and one end line per node run; an error line has the message and no traceback; LLM token sums by batch id; LangSmith tracing set true is refused; the migration applies to a v14 database holding a proposal set and keeps it; a proposal set is not reused for another baseline run; a second event run of the same case is not read with the first; the snapshot keeps the telemetry folder.
- **Step 2.** The nodes as plain functions over `deps`. Tests on Test Corp (fundamentals, market, news through fake downloaders, a `FakeClient`): each node writes what the table says; `load_fundamentals` and `load_market` download nothing when the data is stored and `--offline` fails clearly when it is not; filings dated after the as-of date leave the baseline unchanged; every node run twice adds no row, on a Sunday as-of date too; a stored baseline built from an older ingest or other owner choices is not reused; an as-of date not yet closed in New York is refused.
- **Step 3.** The graph, the checkpointer and the review interrupt. Tests: the graph runs end to end on Test Corp with LLM calls stubbed and gives the same value per share as the M6 commands run by hand; a node that fails once is resumed and the nodes before it don't run again; `later` stops with the state saved and `resume` with answers finishes it; manual edit and reject answers reach `review_set`; an answer naming an unknown proposal, or a batch missing one, is refused before any write; the checkpoint history has one entry per node.
- **Step 4.** The report. Tests: every section is there; rendering twice gives the same text; a variant with no shocks says the shocked value equals the baseline; each shock lists its evidence headlines.
- **Step 5.** The command line and `main.py`. Tests: `run` end to end on Test Corp with a fake client (exit 0, report and telemetry written); `later` exits 4 and `resume` finishes; `reproduce` exits 0, and 1 after a stored output is changed; a missing key exits 2 before any call.
- **Step 6.** Real run (needs the data snapshot, the key and SEC_USER_AGENT; news from GDELT's free 15-minute files as in M5, about 670 files and some minutes for a new week; BigQuery, listed in the Build Plan for M7, is not needed, so nothing is paid for it): one eval case (expected: M6's answers reused, zero LLM tokens, the same shocks as stored) and one new date not in the case library (all steps live, auto review, so the run can finish unattended). Results here and in the build plan; M7 Done on merge.

Steps 1–5 were planned as one engine PR and Step 6 as a second; the real run needed one small change (syndicated headlines shown once in the evidence), so all six steps went in one PR.

**Cost of Step 6.** The eval case costs nothing (stored answers). The new date is up to 15 extraction calls and one proposal call per variant: at M6's prices, a few cents.

## Exit criterion (Build Plan)

A single command, given a ticker and an as-of date, produces a report and a complete trace. Read here as: `python main.py run` on a new date finishes with exit 0, a report with every section above, a telemetry line per node, and a checkpoint per node; and `reproduce` on it exits 0.

## Alternatives considered

- **No LangGraph; a plain Python function calling the steps in order.** Simpler, and it would work today. Rejected: Decision 2 names LangGraph's checkpointer as the audit trail, and resuming after a human review or a failure is exactly what it gives for free. It is also the orchestration a finance student will meet elsewhere.
- **A separate checkpoint file.** Keeps LangGraph's tables out of `warren.db`. Rejected: Decision 2 makes one database the system of record, and the snapshot would need a second file.
- **Pass the database connection in state.** Rejected: state is checkpointed and must be plain data; the connection goes in `deps`.
- **Telemetry in a database table.** Rejected for now: Decision 5 chose a local log file so a broken database can't hide why a run broke.
- **An LLM narrative in the report.** Deferred: optional in the Build Plan, and a narrative about numbers is the one place an LLM could restate a figure wrongly.
- **BigQuery for news** (Build Plan Section 6). Not needed for M7: the M5 file adapter fetches one week in minutes for free. It stays an option behind the same adapter when many new dates are run.
- **Checkpoints as a tamper-evident record.** They are not: LangGraph's serialized rows can be edited by anyone with the file. They are a resumable, step-by-step record (Decision 2's audit trail in that sense); tamper evidence would need hashing each checkpoint into a chain, which no Phase 1 goal needs (professor review).
- **Parallel nodes (news while the baseline builds).** Deferred: the pipeline is minutes, dominated by the GDELT download, and a straight line is easier to read and to resume.

## Files

New: `domains/orchestration/{state,telemetry,nodes,graph,report,text,__main__}.py`, `shared_kernel/migrations/0015_pipeline_runs.sql`, `tests/orchestration/*`.
Changed: `domains/llm/propose.py` and `review.py` (the two reuse fixes, `reviewed_at`), `shared_kernel/snapshot.py` (telemetry), `main.py`, `shared_kernel/schemas.py` (`TelemetryEvent`, `SimulationState` removed), `requirements.txt`, `docs/build-plan.md`, `docs/structure-guide.md` (Decision 5 details and the log row, Section 4 layout).

## Review log

- **Professor** (2 blockers, both accepted): manual review on any past date brings hindsight (now auto by default for any date over 7 days old, with `reviewed_at` and a marked report; Fischhoff 1975, SR 11-7); the doc contradicted itself on what `reproduce` compares (now the report up to the trace marker). Taken from the suggestions: review answers checked as a batch before any write; checkpoints called a resumable record, not a tamper-evident one; report text in `text.py`; the free news path stated against the Build Plan's BigQuery line; lines on p10–p90 and on the variants. Student ideas (fork from a checkpoint, `show` as a lab notebook, a glossary) are for after Phase 1.
- **Explainer** (8 blockers): the report and `reproduce` (fixed, as above); "one line per node" now "per node run"; the telemetry file was not in the snapshot (now it is); "approved shocks" named by status; stale fundamentals (now the fetched-on-or-after rule); baseline reuse (now by inputs); BigQuery (not used, free path). Answered: eval reuse is not by case id alone, as event ids carry the event run's hash, but see the analyst's blocker 2. Ideas taken: one interrupt per variant; simulation warnings in the report; the no-shock report; the budget and `resume`; the name check on LangGraph's tables is a test; `resume` and `reproduce` by status. Already in place: a 10-second lock wait on every connection (`get_db_connection`); keys never in telemetry (a test in Step 1).
- **Analyst** (NO-GO, 5 blockers, all accepted): shocks sized on one baseline could be simulated on another (now `run_id` and the scales hash in the set's key, checked in `simulate` and `reproduce`); one story could be counted twice across event runs (now one event run per proposal); the market rule re-downloaded on every weekend date (now the fetched-on-or-after rule); the baseline was reused too broadly (now by inputs and choices); hindsight through manual review, and inherited verdicts (now auto for old dates, review times in the report). Ideas taken: the report names why there is no shock; a date not yet closed is refused; `reproduce` checks the set belongs to the run; one seed for both variants is said. To backlog: give non-eval dates their own case-id namespace, so a date added to the case library later can't bring in answers made for it before.

## Step 6 results (nov.01.2026, real data: the snapshot of nov.01.2026, the key and SEC_USER_AGENT)

- **An eval case, MSFT_2022-06-02** (`python main.py run --ticker MSFT --as-of 2022-06-02 --offline`): done, exit 0. Every source was stored and fresh, so nothing was downloaded; both variants (an eval case); review auto. The baseline M6 used (`MSFT_2022-06-02_1`) was reused, as it was built from the same ingest, fetches, concept map and choices, so M6's classifications and both proposal sets were reused: **zero LLM calls**. Value per share: baseline 156.77; named p10 / p50 / p90 156.38 / 156.59 / 156.80; masked 156.10 / 156.45 / 156.81. `reproduce`: baseline (101 outputs), both simulations (36 outputs each) and the report, all OK.
- **A new date, WMT_2025-08-21** (Walmart's Q2 FY2026 results day; not in the case library): done, exit 0, every step live, review auto (the date is over 7 days old). Filings, prices and the rate were stored and fresh (fetched oct.31.2026); the news week was downloaded: 672 of 672 files, 5.5 minutes. 15 events chosen, 15 classified (1 not about the company), 15 Haiku calls (37,412 input and 13,361 output tokens) and 1 Sonnet call (12,457 and 362): about 4 cents. One shock: revenue level up, small, lasting, from the raised sales outlook; the model judged the tariff cost on margin and a shrimp recall immaterial. Value per share: baseline 26.81; named p10 / p50 / p90 26.69 / 26.80 / 26.91. The value barely moves because under the M4 terminal rule growth past year 5 adds no value, and the shock lasts 8 quarters; revenue's p50 is 1.4% above the baseline in each shocked quarter. `reproduce`: all OK.
- **Not M7's to fix, said straight.** Walmart's baseline value, 26.81 a share, is far below where the stock traded that day: the M2 baseline is conservative for a company whose value is mostly growth. The pipeline reports the baseline as it is; whether shocks make forecasts better is M8's question.
- **Changed by the run:** syndicated stories repeated one headline four times in a shock's evidence; the report now shows each headline once (the title before " – " or " - ", case ignored).

## Where the work stopped

Steps 0–6 done; PR open for review.
