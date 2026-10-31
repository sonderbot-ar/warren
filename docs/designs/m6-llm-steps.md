# M6 design: LLM steps (event extraction and shock proposal)

Status: In progress (oct.31.2026) · Elephant: agent team · Branch `m6-llm-steps`
Implements Structure Guide Decisions 1 (keys and model map), 6 (event extraction and shock proposal) and 9 (LLM usage), and Build Plan M6.

## Problem

M5 gives each case window a list of news events: a group of headlines that name the company, with first and last sighting, source count and themes. M4 can simulate shocks, but only shocks a person typed in. M6 joins the two: an LLM reads each event's headlines and says what kind of event it is and how material; a second LLM step proposes zero or more shocks for it; a review step approves, edits or rejects them; and everything is stored so M8 can score "with shocks" against "without".

Two rules shape every step:

- **LLMs never produce financial numbers** (CLAUDE.md). The LLM chooses from fixed categories (event type, materiality, driver, direction, size class, duration class, start quarter). Code turns those choices into the numbers a shock needs (low, base, high, horizon, decay), from the company's own history as of the date and from a checked-in table. The LLM's output schema has no field that holds a magnitude, so it cannot write one.
- **Point-in-time.** The LLM sees only the event's headlines known by the as-of date, the company's baseline drivers and history as of that date, and the as-of date itself. The model's own memory is the one leak code can't close; see "Look-ahead through the model's memory".

## Keys and models (Decision 1)

- `shared_kernel/config.py` gains `anthropic_api_key()`, read once from the environment (or `.env` for local runs), raising `ConfigError` with setup steps when missing, never printing the value.
- One node-to-model map in the same file:

  | Node | Model | Why |
  |---|---|---|
  | `extract_events` | `claude-haiku-5-5` | classification over short text; many calls |
  | `check_headlines` | `claude-haiku-5-5` | same job as extraction's about-the-company part |
  | `propose_shocks` | `claude-sonnet-5-5` | reasoning over the event plus the company's drivers; few calls |

  The map is data in one place: changing a model is a one-line change, and the model id is stored on every call.
- Every call runs at temperature 0 and stores its model, so a later model can be compared with the stored outputs, never silently mixed with them.

## The LLM adapter (Decision 11, guardrail 1)

- `domains/llm/client.py` defines `LLMClient`, one method: `call(node, system, user, schema) -> Reply(raw_json, input_tokens, output_tokens, model, latency_ms)`. `AnthropicClient` implements it with the `anthropic` SDK's tool use: the schema is the Pydantic model's JSON schema, the tool is forced, so the answer is one JSON object.
- `FakeClient` replays answers from a list or a function, for tests. CI never needs a key.
- `structured_call(conn, client, node, prompt, inputs, model_cls, ref)` is the only path to an LLM. It renders the prompt, calls, validates the answer with the Pydantic model, and on a validation error calls again with the error appended, at most 3 attempts. Every attempt is one row in `llm_calls`. After 3 invalid answers it raises `LLMRejected`; the caller stores the event as `failed`, never a guess.
- **Budget.** Each command takes `--max-tokens-total` (default 2,000,000 input plus output). The running total is read from `llm_calls` for the command's batch id; the next call is refused once it is reached, and the command stops cleanly with a count of what is left. `--dry-run` renders every prompt, counts characters / 4 as a token estimate, prints calls and tokens per node, and calls nothing.

## Prompts

Prompts are files: `domains/llm/prompts/<node>.v<N>.md`, a system part and a user template with named slots. A change to a prompt is a new file (v2), never an edit; the old file stays. Each call stores the prompt's name, version and SHA-256. Prompt text is reader-facing text apart from logic (guardrail 5).

## Step A: event extraction (LLM 1)

**Which events.** For each eval case: the stored event run as of the case date with the headline rule (M5, Step 6). All its events with `source_count ≥ 2`, the 15 largest by source count (ties by `first_seen`); single-source events are usually one outlet's angle on a bigger story. Every case's skipped events are counted in the report. A case with no qualifying events gets the record `no_events`, so "nothing happened" is visible, not missing.

**Input.** The company's name and ticker, the as-of date, and the event's headlines (up to 25, earliest first, each with its `article_id`, source domain and sighting time). No article text: M5 stores titles only (Build Plan M5, Article text).

**Output** (`EventClassification`, validated):

```text
event_type     : one of the fixed taxonomy (domains/llm/event_types.csv)
materiality    : low | medium | high
reasons        : 1–3 short sentences on why that materiality
summary        : one factual sentence, ≤ 40 words
evidence       : article_ids it relied on, each one from the input
headlines      : for every input headline: article_id, about (true | false)
```

Validation refuses: a type outside the taxonomy; an `article_id` not in the input; a `headlines` list that misses or repeats an input headline.

**The taxonomy** is data (`event_types.csv`, one row per type with a one-line definition that also goes in the prompt): `guidance`, `earnings`, `m_and_a`, `litigation`, `regulation`, `product`, `management`, `supply_chain`, `restructuring`, `capital_return`, `macro`, `other`, and `not_about_company`. It covers every `event_type` in `domains/evaluation/cases.csv` except `control`, which is a case kind, not an event type.

**About the company (carried from M5).** Each headline is marked `about: true` when the company is the subject, and `false` when it only names it (a market wrap, a list of stocks, another company's story). What the event does with the answer:

- Headlines marked `false` are left out of the event's evidence and of shock proposal.
- An event where no headline is about the company is stored as type `not_about_company` (whatever type the model chose), and gets no shock proposal.
- The M5 event itself is not changed: clustering stays reproducible from stored sightings, and the about-answer is a separate row that points at it.

## Scoring the about-check

`python -m domains.llm check-headlines` runs the same about-the-company question on every row of the two labelled draws in `domains/news/match_sample.csv`, in batches of 20 headlines per company, and stores each answer in `headline_checks`. The report gives, per company and pooled, with Wilson intervals as in M5:

- **precision**: of the headlines the model kept, the share labelled `about`, on draw 2's `org_exact` rows (the rows the headline rule already passed), set next to the rule's own 0.72 pooled on the same rows;
- **recall**: of the `about` rows, the share the model kept;
- **dropped rows**: on draw 2's `org_exact_dropped` rows, how many the model calls `about` (stories the word rule loses);
- agreement with each labeller separately (both labels are reported, as in M5).

The labels are inputs, so the model is never shown them. The score is measured, not assumed; if the model does not beat the rule, the report says so and the about-answer stays advisory.

## Step B: shock proposal (LLM 2)

**Which events.** Every classified event except `not_about_company` and `failed`. An event of materiality `low` is still sent: "no shock" is the expected answer and is recorded as such.

**Input.** The classification (type, materiality, summary, the `about` headlines), the as-of date, and from the baseline run as of the case date: the first 8 forecast quarters of revenue growth, operating margin and capex intensity, and the last 8 reported quarters of the same three ratios (as first reported, point-in-time).

**Output** (`ShockProposalSet`, validated): zero to three proposals, each

```text
driver        : revenue_growth | operating_margin | capex_intensity | risk_premium
direction     : up | down
size          : small | medium | large
duration      : one_quarter | fading | lasting | permanent
start_quarter : 1–4 (first affected forecast quarter)
rationale     : 1–2 sentences tied to the evidence
evidence      : article_ids, each one from the input
```

plus `no_material_impact: true` with a reason when the list is empty. Validation refuses a repeated driver, an empty list without the flag, and any extra field (`extra="forbid"`), so a number the model adds is an invalid answer, retried, not stored.

**Code turns the classes into a shock** (`domains/llm/scales.py`, pure functions, property-tested):

- **Scale σ for a driver** = the standard deviation of the driver's year-over-year change over the last 12 reported quarters, as first reported, as of the case date (the same series the baseline is built on). It is the company's own normal quarter-to-quarter variation: a "large" cut for Microsoft's margin and for Walmart's is a different number of points, as a practitioner would expect. When fewer than 8 quarters exist, the size table's fallback σ is used, and the row is flagged.
- **Size → multiple of σ** (`scales.csv`, checked in): small 0.5, medium 1.0, large 2.0. base = sign × multiple × σ; low and high are base × 0.5 and base × 1.5, sorted, so the range keeps the sign and is asymmetric toward bigger moves (the M4 split normal takes them as p10 and p90).
- **Risk premium** has no reported history, so `scales.csv` gives fixed basis points: small 25, medium 50, large 100. This is an assumption, stated in the report and in each shock's rationale.
- **Duration → (horizon, decay)**: one_quarter (1, 1.0); fading (8, 0.7); lasting (8, 1.0); permanent (21 − start, 1.0), which reaches quarter 20, so it is in force in Y5 and carried into the terminal value (M4, Permanent).
- The result is an M4 `Shock` with `source='llm_proposed'`, `event_id` set, and `rationale` = the model's rationale, the evidence URLs, and the class choices in words ("medium cut, fading, from Q1"). The M4 validator then checks it like any other shock.

These multiples are a starting point, not a calibration. Calibrating them against outcomes is M8's job (backlog #33 asks the same for guided ranges); the report says so.

## Human review

- `python -m domains.llm review --case CASE_ID` shows each proposal with its event, evidence and computed numbers, and asks approve, edit or reject. An edit takes new low, base, high, start, horizon or decay; the edited shock is stored with `source='user'` and the proposal keeps the model's original. A rejection stores the reason.
- **Eval cases are not reviewed by a person.** A person reviewing a 2020 event today knows what happened next, which is the look-ahead the harness exists to prevent. So `--auto` records every proposal as `auto_approved` with reviewer `none`, and M8 scores those. The manual path is for live use (a date with no future yet), and its tests run it with scripted answers.
- Approved shocks (auto or manual) are written to M4's `shocks` table against the case's baseline run, so `with_shocks` in the harness can read them in M8.

## Look-ahead through the model's memory

- **Masked variant.** Every event is classified and proposed twice: `named`, and `masked`, where every company alias (M5's `aliases.csv`) and the ticker in a headline become "the Company", and the company name and ticker are left out of the input. Both are stored (`variant` column) and kept apart all the way to M8, which reports both (Build Plan M6 and M8).
- **Cutoff.** The node-to-model map stores each model's published training cutoff. Each case is tagged pre- or post-cutoff by its date. Today all 26 cases fall before the models' cutoffs, so the masked variant is the mitigation that counts; the report says this plainly.
- The prompt tells the model the as-of date and to use only the headlines given. That is an instruction, not a guarantee, and is described as such.

## Storage (migration `0012_llm.sql`)

```text
llm_calls(call_id, batch_id, node, model, prompt_name, prompt_version, prompt_sha256,
          ref, attempt, input_json, output_json, status ok|invalid|error, error,
          input_tokens, output_tokens, latency_ms, created_at)
event_classifications(classification_id, event_id, variant named|masked, call_id,
          status ok|failed|no_events, event_type, materiality, reasons, summary,
          evidence_json, about_json, created_at)   UNIQUE(event_id, variant, prompt_sha256, model)
headline_checks(article_id, cik, draw, variant, call_id, about, model, prompt_sha256)
shock_proposals(proposal_id, classification_id, call_id, driver, direction, size,
          duration, start_quarter, rationale, evidence_json, sigma, sigma_source,
          low, base, high, horizon, decay, status proposed|auto_approved|approved|edited|rejected,
          reviewer, review_note, shock_id, created_at)
```

No money columns (shocks are in points and basis points), so guardrail 3 adds nothing here. A rerun with the same event, variant, prompt and model returns the stored classification instead of paying again. `events.event_type` and `events.summary` (left empty in M5 for M6) stay empty: the answers live in `event_classifications`, because one event has two variants and may be classified by more than one model.

## Commands

- `python -m domains.llm classify --case CASE_ID | --all-cases [--variant named|masked|both] [--dry-run]`
- `python -m domains.llm propose --case CASE_ID | --all-cases [...]`
- `python -m domains.llm review --case CASE_ID [--auto]`
- `python -m domains.llm check-headlines [--dry-run]`
- `python -m domains.llm report` (per case: events classified, skipped, failed; types; proposals and their status; tokens per node; the about-check score; named vs masked agreement), written to `data/reports/llm/`.

## Steps

- **Step 0.** This design doc; M6 "In progress" in the build plan.
- **Step 1.** Keys and the model map in `shared_kernel/config.py`; `anthropic` pinned in `requirements.txt`. Tests: a missing key raises `ConfigError` naming the setup steps and never the value; every node has a model; the key is read once.
- **Step 2.** Migration 0012, `LLMClient`, `FakeClient`, `AnthropicClient`, `structured_call` with retry and the budget, prompt loading. Tests: a valid answer is stored once; an invalid one is retried with the error and stored per attempt; three invalid answers raise `LLMRejected`; the budget refuses the next call; a prompt's SHA and version are stored; the migration applies to a v11 database.
- **Step 3.** Taxonomy, `EventClassification`, `extract_event.v1`, event selection, masking, `classify`. Tests: an out-of-taxonomy type, an unknown or missing `article_id` are refused; all `about: false` becomes `not_about_company`; masking removes every alias and the ticker; an event seen after the as-of date is never an input; a rerun pays nothing; `no_events` is recorded.
- **Step 4.** `check-headlines` and its score. Tests: precision and recall by hand on six rows; labels are never in a prompt; both labellers reported.
- **Step 5.** `ShockProposalSet`, `scales.py`, `scales.csv`, `propose_shocks.v1`, `propose`. Tests: an extra numeric field is refused; σ by hand for Test Corp; size and duration map to the table; every computed shock passes M4's validator (property test over all class combinations and σ > 0); permanent reaches quarter 20; the fallback σ is flagged; the history read is as first reported and as of the date.
- **Step 6.** `review` (manual with scripted answers, and `--auto`), writing to `shocks`. Tests: an edit stores `source='user'` and keeps the original; a rejection writes no shock; `--auto` records reviewer `none`; approved shocks simulate with M4 on Test Corp and reproduce to the cent.
- **Step 7.** CLI, `--dry-run`, the report with tokens per node. Tests: dry run calls nothing and counts calls; the CLI end to end on Test Corp with `FakeClient`.
- **Step 8.** Real run (needs `ANTHROPIC_API_KEY`, and the M5 news data rebuilt locally): the stability check (ten fixed events classified three times at temperature 0; event type agrees in at least 9 of 10, stated in the report, not a CI test since CI has no key), the about-check score, then every eval case classified and proposed in both variants and auto-reviewed. Results here and in the build plan; M6 Done on merge.

Steps 1–7 make no LLM call outside tests and merge as one engine-only PR, as M3 and M4 did. Step 8 is a second PR.

**Cost estimate for Step 8.** About 26 cases × up to 15 events × 2 variants = up to 780 extraction calls of roughly 1,500 input tokens, plus up to 780 proposal calls of roughly 2,500, plus about 70 headline-check calls. That is under 4 million tokens, a few US dollars at list prices. The default budget stops each command at 2 million.

## Exit criterion (Build Plan)

For every eval case, events are classified and shocks proposed, reviewed and stored. Read here as: every eval case has a stored classification (or `no_events`) for each selected event in both variants, every classified event has a stored proposal set (possibly "no material impact"), and every proposal has a review status.

## Alternatives considered

- **The LLM writes low/base/high directly** (the M4 schema as its output). Rejected: that is an LLM producing a financial number. It chooses classes; code computes.
- **Size classes as fixed points for every company** (say, small = 1 point of growth). Rejected: one point of margin is noise for one company and a crisis for another; scaling by the company's own σ is the standardised-surprise idea from the earnings literature (Latané and Jones 1977; Foster, Olsen and Shevlin 1984).
- **Human review of eval cases.** Rejected for the backtest: the reviewer knows the outcome. Kept for live use.
- **One LLM call for both steps.** Rejected: Decision 9 names them as two tasks, and splitting them lets a cheap model classify many events while a stronger model reasons about the few that matter. Each step's output is then checked on its own.
- **Free-text JSON parsing instead of forced tool use.** Rejected: tool use with a schema is how the SDK returns a structured object, and validation still runs on it.
- **LangGraph now.** Deferred to M7 (Build Plan); M6 functions are plain calls that M7's nodes will wrap.
- **A local open model** (scout issue #71). Deferred: compare after M6 on the same stored inputs.

## Files

New: `domains/llm/{client,calls,prompts_io,taxonomy,extract,headlines,scales,propose,review,report,__main__}.py`, `domains/llm/event_types.csv`, `domains/llm/scales.csv`, `domains/llm/prompts/*.md`, `shared_kernel/migrations/0012_llm.sql`, `tests/llm/*`.
Changed: `shared_kernel/config.py`, `requirements.txt`, `docs/build-plan.md`, `docs/structure-guide.md` (Decision 1 row: implemented), `.env.example` if present.

## Review log

(Filled in after the design review.)
