# M6 design: LLM steps (event extraction and shock proposal)

Status: In progress (oct.31.2026; Steps 1–7 in the engine PR #72, Step 8 waits on the key reaching cloud runs as `WARREN_ANTHROPIC_API_KEY`, backlog #95) · Elephant: agent team · Branch `m6-llm-steps`
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
- Every call stores its model, so a later model can be compared with the stored outputs, never silently mixed with them. (Planned at temperature 0; the current models and SDK take no temperature, so calls run at the model's default sampling, with effort set per node. See Step 8.)

## The LLM adapter (Decision 11, guardrail 1)

- `domains/llm/client.py` defines `LLMClient`, one method: `call(node, system, user, schema) -> Reply(raw_json, input_tokens, output_tokens, model, latency_ms)`. `AnthropicClient` implements it with the `anthropic` SDK's tool use: the schema is the Pydantic model's JSON schema, the tool is forced, so the answer is one JSON object.
- `FakeClient` replays answers from a list or a function, for tests. CI never needs a key.
- `structured_call(conn, client, node, prompt, inputs, model_cls, ref)` is the only path to an LLM. It renders the prompt, calls, validates the answer with the Pydantic model, and on a validation error calls again with the error appended, at most 3 attempts. Every attempt is one row in `llm_calls`. After 3 invalid answers it raises `LLMRejected`; the caller stores the event as `failed`, never a guess.
- **Budget.** Each command takes `--max-tokens-total` (default 2,000,000 input plus output). The running total is read from `llm_calls` for the command's batch id; the next call is refused once it is reached, and the command stops cleanly with a count of what is left. `--dry-run` renders every prompt, counts characters / 4 as a token estimate, prints calls and tokens per node, and calls nothing.

## Prompts

Prompts are files: `domains/llm/prompts/<node>.v<N>.md`, a system part and a user template with named slots. A change to a prompt is a new file (v2), never an edit; the old file stays. Each call stores the prompt's name, version and SHA-256. Prompt text is reader-facing text apart from logic (guardrail 5).

## Step A: event extraction (LLM 1)

**Which events.** For each eval case: the stored event run as of the case date with the headline rule (M5, Step 6). All its events with `source_count ≥ 2`, the 15 largest by source count (ties by `first_seen`); single-source events are usually one outlet's angle on a bigger story. Every case's skipped events are counted in the report. A case with no qualifying events gets the record `no_events`, so "nothing happened" is visible, not missing.

**Input.** The company's name and ticker, the as-of date, and the event's headlines, each with its `article_id`, source domain and sighting time. When an event has more than 25 headlines, the 25 are chosen as one per source domain first, earliest first, then the earliest of the rest. No article text: M5 stores titles only (Build Plan M5, Article text), so the Build Plan's "available text" is titles in Phase 1.

**Output** (`EventClassification`, validated):

```text
event_type     : one of the fixed taxonomy (domains/llm/event_types.csv)
materiality    : low | medium | high
reasons        : 1–3 short sentences on why that materiality
summary        : one factual sentence, ≤ 40 words
evidence       : article_ids it relied on, each one from the input
headlines      : for every input headline: article_id, about (true | false)
```

Validation refuses (and so asks again, Step 2): a type outside the taxonomy; an `article_id` not in the input; a `headlines` list that misses or repeats an input headline; evidence citing a headline marked `about: false`; and the type `not_about_company` while some headline is marked `about: true`.

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

**One proposal set per case, not per event** (analyst review). M5's clustering can split one story into several events when outlets word it differently on different days, so per-event proposals could stack three revenue cuts for one Apple warning. LLM 2 therefore sees all of a case's classified events at once (one call per case and variant), and proposes **at most one shock per driver for the case**, citing the events and headlines it rests on. Events classified `not_about_company` or `failed` are left out; events of materiality `low` stay in, and "no shock" is the expected answer and is recorded as such.

**Input.** For each event: id, type, materiality, summary and its `about` headlines; the as-of date; and from the baseline run as of the case date: the first 8 forecast quarters of revenue growth, operating margin and capex intensity, and the last 8 reported quarters of the same three ratios (as first reported, point-in-time). Quarters are labelled Q1…Q8 (forecast) and Q−8…Q−1 (reported) in both variants; only the named variant has the company and the as-of date.

**Output** (`ShockProposalSet`, validated): zero to four proposals (one per driver at most), each

```text
driver        : revenue_growth | operating_margin | capex_intensity | risk_premium
direction     : up | down
size          : small | medium | large
duration      : one_quarter | fading | lasting | permanent
start_quarter : 1–4 (first affected forecast quarter)
rationale     : 1–2 sentences tied to the evidence
evidence      : event ids and article_ids, each one from the input
```

plus `no_material_impact: true` with a reason when the list is empty. Validation refuses a repeated driver, an empty list without the flag, `risk_premium` with duration `permanent` unless one cited event has materiality `high` (a permanent premium reaches the terminal value; 100 bp on a large company's cost of equity is a double-digit share of its value), and any extra field (`extra="forbid"`), so a number the model adds is an invalid answer, retried, not stored.

**Code turns the classes into a shock** (`domains/llm/scales.py`, pure functions, property-tested; the table is `scales.csv`, checked in):

- **The series.** For each driver, x_q is the reported quarter's value as first reported, point-in-time on the case date: revenue growth = revenue over the same quarter a year earlier, minus 1; operating margin = operating income over revenue; capex intensity = capex over revenue (the same items and fallbacks the baseline run uses).
- **The scale σ** is the robust spread of the driver's four-quarter change d_q = x_q − x_{q−4} over the last 12 reported quarters before the case date: σ = 1.4826 × median(|d_q − median(d)|), the median absolute deviation scaled to match a standard deviation for normal data. The shock is a change in the driver, so σ measures how much the driver usually changes in a year; for revenue growth that is the change in the growth rate, which needs 20 quarters of revenue. The median keeps one or two odd quarters from setting σ: a large impairment (P&G's Gillette charge, Exxon's 2020 write-down), a 14-week quarter (Apple's Q1 FY2017), or a quarter after a change in what the company owns (Coca-Cola's bottler refranchising). Taking those quarters out by name waits for backlog #23 (14-week quarters) and the `scope_change` column of the case file; until then the median is the guard, and each case's 12 changes are in the report so a reader can see them.
- **Fallback and bounds.** With fewer than 12 changes, σ is the driver's fallback value in `scales.csv` (revenue growth 2.0 points, margin 1.0, capex intensity 0.5), flagged `fallback`. σ is then held between the table's floor and cap per driver (growth 0.5–10 points, margin 0.2–5, capex 0.1–3), flagged `floored` or `capped`. These values are judgments, stated as such in the table and the report.
- **Size and range.** base = sign × m × σ, with m = 0.5, 1.0, 2.0 for small, medium, large; low and high = base ∓ c × σ with c = 0.75 for every size (analyst review). The range has the same width for every size, as the uncertainty about an event's effect does not shrink because the effect is small, and a small shock's range crosses zero: the model may be wrong about the direction.
- **Duration → (horizon, decay):** one_quarter (1, 1.0); fading (8, 0.7: the effect halves in about 2 quarters, said in the rationale text); lasting (8, 1.0); permanent (21 − start, 1.0), which reaches quarter 20, so it is in force in Y5 and carried into the terminal value (M4, Permanent).
- **Revenue is a level** (analyst review, twice). M4's revenue growth is against the same quarter a year earlier, so a one-quarter growth cut leaves every later quarter lower: a lasting level loss that reaches the terminal value (M4, Drivers). A cut followed by a reversal four quarters later doesn't fix it: (1 − s)(1 + s) = 1 − s² leaves part of the loss, and as two M4 shocks the cut and the reversal would take separate draws in the simulation (`montecarlo.py`, one draw per shock), so samples would carry level noise. So for revenue the size class describes the revenue *level*, and M4 gains a `basis` on a shock: `growth` (the default, every existing shock) or `level` (allowed for `revenue_growth` only). A level shock multiplies revenue in each period by 1 + magnitude × the period's share of the shape (`shock_shape`, Y3–Y5 the mean of their quarters, as for every shock); `shocks.apply` turns that target into the growth path exactly, period by period, from the run's own seed: quarter g′ₕ = L′ₕ / L′ₕ₋₄ − 1, and each year g′ = L′ / L′ of the year before − 1. It is one shock with one draw per sample, and once its shape ends the level is the baseline's again. Old simulations are untouched: a `growth` shock hashes as before (`shocks_sha256` leaves the default out), and the `shocks` table gains a `basis` column defaulting to `growth`. Tests: on samples, not only the base, a level shock that ends before Y5 leaves Y5 revenue equal to the baseline to the cent, and revenue in each shocked period equals baseline × (1 + magnitude × share); a permanent one keeps the level lower in Y5; a level shock's `low` at or below −100% is refused, and a simulation stops when any sample's revenue would reach zero or below (`_check_samples`, a growth of −100% or less; gatekeeper review).
- **Risk premium** has no reported history, so `scales.csv` gives fixed basis points as base (small 25, medium 50, large 100) and the same range rule with σ = 25 bp. This is an assumption, stated in the report and in each shock's rationale.
- **Bounds on the shocked path.** M4 stops a simulation when a sample makes a driver impossible. So code checks each shock against the baseline path out to the 1st and 99th percentiles of its split normal (base ∓ 1.815 × the distance to low or high; the tail the shock points to meets every bound, the other tail only the hard ones, capex at zero and the revenue level band): capex intensity must stay ≥ 0, operating margin must stay within the company's lowest and highest margin of the last 12 quarters widened by 2σ, and the four-quarter revenue level within ±50%. When a shock would cross, low, base and high are scaled down together until it fits, and the shock is flagged `clipped`; the report counts clipped shocks. This is the automatic sanity check that stands where a person would in live use.
- The result is an M4 `Shock` (basis `level` for revenue) with `source='llm_proposed'`, `event_id` = the first cited event, and `rationale` = the model's rationale, the class choices and σ in words, and the cited event ids (the headlines are one join away, in `event_classifications`) ("medium cut in revenue level, fading, from Q1; σ 1.8 points"). The M4 validator then checks it like any other shock.

These multiples, the range width and the bounds are a starting point, not a calibration. Calibrating them on the 26 eval cases would tune the method on its own test set, so calibration needs held-out cases and is a backlog item, not part of M6 or M8 (professor review).

## Human review

- `python -m domains.llm review --case CASE_ID` shows each proposal with its event, evidence and computed numbers, and asks approve, edit or reject. An edit takes new low, base, high, start, horizon or decay; the edited shock is stored with `source='user'` and the proposal keeps the model's original. A rejection stores the reason.
- **Eval cases are not reviewed by a person.** A person reviewing a 2020 event today knows what happened next, which is the look-ahead the harness exists to prevent. So `--auto` records every proposal as `auto_approved` with reviewer `none`, and M8 scores those. The manual path is for live use (a date with no future yet), and its tests run it with scripted answers.
- Approved shocks (auto or manual) are written to M4's `shocks` table against the case's baseline run, so `with_shocks` in the harness can read them in M8. Review is idempotent: a proposal that already has a review status is skipped, so running `review` twice writes no second shock.

## Look-ahead through the model's memory

An LLM trained on later text may know what happened after a 2020 event, which would make the backtest look better than it is. Code can't close this leak; the design reduces it and reports it.

- **Masked variant.** Every event is classified, and every case proposed, twice: `named`, and `masked`. In the masked input, every company alias (M5's `aliases.csv`) and the ticker become "the Company" in headlines; source domains are dropped; absolute dates become relative ones (day 0 is the as-of date, sightings are "day −2, 14:00"; history quarters are "Q−8 … Q−1" and forecast quarters "Q1 … Q8"); and the company name, ticker and as-of date are left out. Both variants are stored (`variant` column) and kept apart all the way to M8, which reports both (Build Plan M6 and M8). Relative dates follow Kim, Muhn and Nikolaev (2024), who anonymised statements the same way.
- **What masking does not do.** Look-ahead bias in pretrained models is real and measurable (Sarkar and Vafa 2024). Models can recover a masked company and date from small clues, such as a product, an executive or the shape of the numbers, and instructions to ignore later knowledge do not stop the recall (Lopez-Lira, Tang and Zhu 2025, "The Memorization Problem"). Glasserman and Lin (2023) show that the gap between named and masked results mixes memory of what happened next with a "distraction effect" of the name itself. So masking reduces the leak, it does not remove it, and M8 must not read the named-vs-masked gap as a measure of look-ahead on its own. The report says this next to the masked results.
- **Cutoff.** The node-to-model map has a field for each model's published training cutoff, empty until Step 8 fills it from the model cards (no date is guessed). Each case is then tagged pre- or post-cutoff by its date; with the case library ending in 2025, the expected count of post-cutoff cases is zero, and the report puts that count next to the masked results.
- The prompt tells the model the as-of date (named variant only) and to use only the information given. That is an instruction, not a guarantee, and is described as such.

**Related work.** Classifying news with an LLM follows Lopez-Lira and Tang (2023), who score headlines for stock returns; Warren classifies the *type* and *materiality* of an event instead of good or bad news, which fits Decision 6 (sentiment is not impact).

## Storage (migration `0012_llm.sql`)

```text
llm_calls(call_id, batch_id, node, model, prompt_name, prompt_version, prompt_sha256,
          ref, attempt, input_json, output_json, status ok|invalid|error, error,
          input_tokens, output_tokens, latency_ms, created_at)
event_classifications(classification_id, event_id, variant named|masked, model, prompt_sha256,
          call_id, status ok|failed, event_type, model_event_type, materiality, reasons,
          summary, evidence_json, about_json, created_at)
          UNIQUE(event_id, variant, model, prompt_sha256)
case_llm_status(case_id, event_run_id, variant, events_total, events_chosen)
headline_checks(article_id, cik, variant, model, prompt_sha256, call_id, about)
proposal_sets(set_id, case_id, event_run_id, variant, model, prompt_sha256, call_id, run_id,
          status ok|failed, no_impact, reason, created_at)
          UNIQUE(case_id, event_run_id, variant, model, prompt_sha256)
shock_proposals(proposal_id, set_id, driver, direction, size, duration, start_quarter,
          rationale, evidence_json, sigma, sigma_flag, low, base, high, horizon, decay,
          clipped, status proposed|auto_approved|approved|edited|rejected,
          reviewer, review_note, created_at)
proposal_shocks(proposal_id, shock_id)       -- the M4 shock a reviewed proposal became
```

- `batch_id` is one command's id (`<command>_<UTC time>`), used for its token budget; `ref` is what a call is about (an event id, a case id and variant, or a headline batch).
- **Reruns.** A rerun with the same event (or case), variant, prompt and model returns the stored `ok` answer instead of paying again; a `failed` one is tried again and its row replaced. `case_llm_status` records how many events a case had and how many were chosen, so a case with none (`events_chosen = 0`) is visible, not missing.
- No money columns (shocks are in points and basis points), so guardrail 3 adds nothing here. `events.event_type` and `events.summary` (left empty in M5 for M6) stay empty: the answers live in `event_classifications`, because one event has two variants and may be classified by more than one model.

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
- **Step 5.** `ShockProposalSet`, `scales.py`, `scales.csv`, `propose_shocks.v1`, `propose`. Tests: an extra numeric field is refused; a repeated driver is refused; a permanent risk premium without a high-materiality event is refused; σ (median absolute deviation) by hand for Test Corp, and one outlier quarter barely moves it; fallback, floor and cap are flagged; size and duration map to the table; every computed shock passes M4's validator (property test over all class combinations and σ in its bounds); permanent reaches quarter 20; a level shock that ends before Y5 leaves Y5 revenue equal to the baseline to the cent on every sample, and a permanent one doesn't; a capex cut that would go below zero is clipped and flagged; the history read is as first reported and as of the date; one proposal set per case, so two events about one story give one shock per driver.
- **Step 6.** `review` (manual with scripted answers, and `--auto`), writing to `shocks`. Tests: an edit stores `source='user'` and keeps the original; a rejection writes no shock; `--auto` records reviewer `none`; reviewing twice writes no second shock; approved shocks simulate with M4 on Test Corp and reproduce to the cent.
- **Step 7.** CLI, `--dry-run` (it runs on a throwaway copy of the database, made with SQLite's backup so the WAL is included, with a client that answers nothing; a `propose` dry run therefore counts only cases already classified for real), the report with tokens per node, macro events per case, clipped shocks and σ flags. Tests: dry run calls nothing and counts calls; the CLI end to end on Test Corp with `FakeClient`.
- **Step 8.** Real run (needs the key as `WARREN_ANTHROPIC_API_KEY`, or `ANTHROPIC_API_KEY` in a local `.env`, and the M5 news data rebuilt locally): fill the models' training cutoffs from their model cards; the stability check (the largest event of each of the first ten cases by case id that have one, classified three times at temperature 0; the type is the same in all three runs for at least 9 of the 10, stated in the report); the about-check score; then every eval case classified and proposed in both variants and auto-reviewed. Results here and in the build plan; M6 Done on merge. The Build Plan's M6 test "stable classifications at low temperature" moves here from CI, because CI has no key; CI tests the same code with recorded answers.

Steps 1–7 make no LLM call outside tests and merge as one engine-only PR, as M3 and M4 did. Step 8 is a second PR.

**Cost estimate for Step 8.** About 26 cases × up to 15 events × 2 variants = up to 780 extraction calls of roughly 1,500 input tokens, plus 52 proposal calls (one per case and variant) of roughly 6,000, plus about 70 headline-check calls of roughly 1,500, plus 30 stability calls. That is about 1.6 million tokens over four commands (classify, propose, check-headlines, stability), each under the 2 million default budget. `--dry-run` gives the real count before any money is spent; the dollar figure follows from Anthropic's published per-token prices on the day and goes in the report.

## Exit criterion (Build Plan)

For every eval case, events are classified and shocks proposed, reviewed and stored. Read here as: every eval case has a stored classification (or `no_events`) for each selected event in both variants, every classified event has a stored proposal set (possibly "no material impact"), and every proposal has a review status.

## Alternatives considered

- **The LLM writes low/base/high directly** (the M4 schema as its output). Rejected: that is an LLM producing a financial number. It chooses classes; code computes.
- **One proposal per event.** Rejected (analyst review): one story split into several events would stack shocks on one driver.
- **A revenue cut plus its reversal as two growth shocks.** Rejected (analyst re-review): it leaves a loss of about s², and the two take separate draws.
- **σ as a plain standard deviation.** Rejected (analyst review): one impairment or 14-week quarter in 12 sets it; the median absolute deviation ignores one or two.
- **low/high as base × 0.5 and × 1.5.** Rejected (analyst review): a small shock's range would be narrow and never cross zero, overconfident against Decision 7's 80% coverage target.
- **Size classes as fixed points for every company** (say, small = 1 point of growth). Rejected: one point of margin is noise for one company and a crisis for another; scaling by the company's own σ borrows the standardised-surprise idea from the earnings literature (Latané and Jones 1977; Foster, Olsen and Shevlin 1984), which scales a surprise by the spread of past forecast errors. That literature measures surprises after the fact; it does not support the particular multiples, which are judgments.
- **Human review of eval cases.** Rejected for the backtest: the reviewer knows the outcome. Kept for live use.
- **One LLM call for both steps.** Rejected: Decision 9 names them as two tasks, and splitting them lets a cheap model classify many events while a stronger model reasons about the few that matter. Each step's output is then checked on its own.
- **Free-text JSON parsing instead of forced tool use.** Rejected: tool use with a schema is how the SDK returns a structured object, and validation still runs on it.
- **LangGraph now.** Deferred to M7 (Build Plan); M6 functions are plain calls that M7's nodes will wrap.
- **A local open model** (scout issue #71). Deferred: compare after M6 on the same stored inputs.

## Files

New: `domains/llm/{client,calls,prompts_io,taxonomy,extract,headlines,scales,propose,review,report,__main__}.py`, `domains/llm/event_types.csv`, `domains/llm/scales.csv`, `domains/llm/prompts/*.md`, `shared_kernel/migrations/0012_llm.sql`, `tests/llm/*`.
Changed: `domains/analysis/{shocks,montecarlo}.py` (the `level` basis), `shared_kernel/config.py`, `requirements.txt`, `docs/build-plan.md`, `docs/structure-guide.md` (Decision 1 row, on M6 Done), `.env.example` if present.

## Review log

- **Analyst** (NO-GO, 3 blockers, all accepted): one story split across events stacked shocks (now one proposal set per case, one shock per driver); a temporary revenue-growth shock was a lasting level loss (now a cut and its reversal four quarters later; Y5 test); σ was loose, not robust and unbounded (now the median absolute deviation of the four-quarter change over 12 quarters, with fallback, floor, cap and bounds on the shocked path, all flagged). Ideas taken: equal-width ranges crossing zero; a permanent risk premium only for a high-materiality event; the fading half-life in the rationale; clips as the automatic check for auto-approved shocks. To report in Step 7: how many selected events are macro. **Re-review:** blockers 1 and 3 fixed; blocker 2 not: a cut and a reversal leave 1 − s² of the level and take separate draws. Accepted: revenue shocks now have a `level` basis in M4, computed exactly from the seed with one draw (Step B, Revenue is a level); the PR review checks it with the analyst.
- **Professor** (changes requested, 2 blockers, both accepted; re-review GO, with the Sarkar and Vafa citation narrowed to what it shows): masking left absolute dates and domains in and the doc overstated it (now relative dates, domains dropped, and a section on what masking does not do, with Glasserman and Lin 2023, Sarkar and Vafa 2024, Lopez-Lira, Tang and Zhu 2025, Kim, Muhn and Nikolaev 2024); calibration was handed to M8 (now a backlog item on held-out cases). Ideas taken: cite Lopez-Lira and Tang 2023; define σ exactly; label the basis points as an assumption; a worked σ example in the lesson.
- **Explainer** (4 blockers, all answered): σ defined; `no_events` lives in `case_llm_status`; reruns defined (stored answers reused, failed ones retried, review idempotent); domains are dropped in the masked variant. Gaps answered: cutoffs are filled from model cards in Step 8; which headlines when more than 25; the `not_about_company` and evidence rules; an API error counts as an attempt (`calls.py`); `batch_id` and `ref`; commands vs the budget; the stability set and its agreement rule; titles only and stability outside CI are recorded against the Build Plan. Proposals use each variant's own classifications; `check-headlines` runs named only, as it scores the rule M5 measured on named headlines.
- **PR review** (gatekeeper and analyst, NO-GO, 1 blocker, fixed): a level sample at or below −100% gave negative or NaN revenue without an error; `_check_samples` now stops on a revenue growth of −100% or less or a non-finite one (tests). Taken from the ideas: the margin band is checked only on the tail the shock points to, so a shock is no longer zeroed when the baseline already sits outside the band on the other side, while the other tail still keeps capex at zero or above (gatekeeper re-check: GO); the stale migration comment and doc lines fixed. Confirmed by fuzzing: the level arithmetic is exact (max relative error 1e-13 over 300 seeds × 500 draws), and an existing database with a stored simulation upgrades to 0012 and still reproduces. To backlog: a CI test upgrading a pre-0012 database that holds a simulation; a lesson sentence on Y3–Y5 taking the year's mean share.

- **PR #101 review, the real run** (nov.01.2026):
  - **Gatekeeper GO** (553 tests, then 556). Notes went to backlog #104: check manifest names in snapshots, state Python 3.11.4 as the minimum, and swap before deleting on `--force`.
  - **Analyst NO-GO, 1 blocker, fixed.** Cases read other weeks' news (8g). The design doc's token figure was corrected.
  - **Re-review GO from both.** Every case reads its own window, and no shock cites an event from outside it. Each design-doc count was recomputed from the database. The analyst judged 8 of 10 held-out stability acceptable: neither flip changes a shock.
  - **Ideas to backlog.** Sizing went to #102: M&A from the target's revenue share, and a σ fallback for commodity producers. Extraction went to #103: the earnings/guidance line, taxonomy gaps, masked name leaks, a thin-coverage flag, the stability set, and shocks that argue with the baseline.

## Step 8: changes found on the real run (oct.31.2026)

- **The client as merged could not call the current models.** Anthropic's SDK 2.3.0 has no `temperature` argument, and Claude Haiku 5.5 and Claude Sonnet 5.5 answer 400 to a forced tool choice. `AnthropicClient` now offers the `answer` tool with `tool_choice: auto`, adds one line to the system prompt telling the model to answer only through the tool, and sets effort per node (`low` for the two Haiku nodes, `medium` for the Sonnet proposal). An answer without the tool comes back empty and `structured_call` retries it as invalid, as before. Checked with one live call per model before any batch.
- **Stability at default sampling.** With no temperature setting, the three stability runs use the model's default sampling, which is a harder test than temperature 0. Command: `python -m domains.llm stability`; answers are logged as calls (`ref` = `event:stability:k`), never stored as classifications.
- **Training cutoffs.** Anthropic's models overview (read oct.31.2026) gives "Jun 2026" as the training data cutoff for both models, month only; the first of the month is stored. Every case is dated 2025 or earlier, so all 26 are pre-cutoff: masking reduces recall of what happened next, and the cutoff does not.
- **Cost.** The classify dry run for AAPL_2020-02-17 counted 30 calls and about 27,000 input tokens. At Anthropic's published prices on the day (Haiku 5.5 $0.10 / $0.50 per million input / output tokens, Sonnet 5.5 $2 / $10), the whole step is a few dollars at most.

- **Made-up event types (8c, 8d).** On the first pass (prompt v1) Haiku answered with a type outside the taxonomy in 351 of 662 calls (53%: `regulatory_action`, `acquisition`, `product_launch`, …), and 51 of 362 events failed after three tries. `structured_call` now takes `choices`, which put the taxonomy into the answer schema as an enum, and prompt v2 says names must be copied exactly: 10 of 786 calls invalid (1.3%). The answer tool is then made strict, so the API holds the answer to the schema. Strict mode refuses `maxItems`, integer `minimum`/`maximum` and length limits (400 on the real run), so the schema sent drops only those, and the full Pydantic model still validates every answer. What is still rejected breaks a rule a schema can't hold (evidence citing a headline marked not about the company).
- **Stability failed, then two ties were broken (8e).** At v2 the check gave 7 of 10 (bar 9): JNJ's FDA actions (the 2021 vaccine pause) flipped between `regulation` and `product`. The taxonomy's definitions overlap there. v3 adds that a regulator's action on a product is `regulation`; then CAT's results-with-forecast flipped between `earnings` and `guidance` (8 of 10). v4 adds that results with a forecast in the same release are `earnings`: 10 of 10. The rules were written from the stability set, so the check was run again on the next ten cases by case id: 9 of 10 (a P&G CEO interview flips between `product` and `management`). The overlaps are definitional, not tuned to cases; the type list itself is unchanged (Decision 6).
- **A headline batch with no valid answer stopped the command (8b).** It is now skipped, counted and asked again on the next run, as a failed classification is.
- **Proposals saw each event once per prompt version (8f).** `case_events` read every stored classification, so after v2 and v4 the proposal prompt listed most events two or three times (the dry run's estimate: about 631,000 input tokens for 52 calls, against 272,000 once fixed; the API billed 990,458 for those 52 calls and 457,312 for the next 52). It now reads the current extraction prompt's rows only. Those 52 sets stay in the database with `''` and are left out of the report and review. The report's calls table is split by prompt version.

- **Cases read other weeks' news (8g, analyst NO-GO on the first full run).** `choose_events` took the 15 largest events from all of a company's stored news, which holds every case window of that company, from 2019 on. In 6 of 26 cases none of the 15 was from the case's own week: WMT_2022-07-25 lost its profit warning (37 sources) to 2019 stories, and AAPL_2022-11-06 shocked revenue on the Feb 2020 virus warning. An event must now still be running in the case window, the 7 New York days ending on the case date, as M5 ingests (`extract.WINDOW_DAYS`). Because the choice of events can change under a stored set, migration 0014 keys a proposal set by `inputs_sha256`, the SHA-256 of the extraction prompt's hash and the sorted classification ids the set read; `propose.case_events` applies the current choice, and report and review use `propose.current_set`. The 52 sets of the first full run keep their old key, prefixed `extract-prompt:`, and are never reused.

### Step 8 results (nov.01.2026: extraction prompt v4, proposal prompt v1, events from the case window)

- **Every case classified, proposed, reviewed and stored** (the exit criterion): 26 cases × 2 variants. 654 events classified (327 per variant), all valid, none failed. Every case has events in its window; 8 have fewer than 15 (KO_2019-07-23 2; CAT_2020-08-19, JNJ_2022-05-23, KO_2022-08-20 6; PG_2019-04-23 7; PG_2019-07-30, PG_2024-02-19 8; XOM_2019-08-19 14).
- **Proposals:** 52 sets, all valid: 36 propose shocks (56 shocks, all auto-approved), 16 say no material impact. Operating margin down 21, revenue growth down 16, revenue growth up 9, capex up 4, capex down 3, one each of margin up, risk premium up and down. Spot checks the analyst asked for now read the case's own news: WMT_2022-07-25 margin down (the profit warning), AAPL_2022-11-06 revenue down (China lockdowns cut iPhone 14 output), MSFT_2022-06-02 revenue and margin down small (the currency cut to guidance).
- **Stability:** 9 of 10 on the stated set (pass; KO_2019-07-23's two-story event flips between `not_about_company` and `other`). On the next ten cases, 8 of 10: WMT_2022-07-25's warning flips between `guidance` and `earnings`, and a PG event between `not_about_company` and `other`. The earnings/guidance line is the weak spot (backlog).
- **Named and masked:** of 327 events classified in both, 259 (79%) get the same type.
- **About-the-company check** (first labeller, pooled, `org_exact` rows of the rule draw): the model's precision is 0.90 (0.86–0.93, n=273) against the headline rule's 0.72 (0.68–0.77, n=373), keeping 0.91 of the stories labelled about. Second labeller: 0.92 against 0.81. KO is the exception (0.36 against 0.52, n=14): KO's headlines are mostly "Coca-Cola" the drink.
- **Cost:** about $5.81 in all, every pass included: Haiku $1.78 (2,915 calls), Sonnet $4.03 (157 calls). The report is `data/reports/llm/llm_report.md`; the data, with every answer, is in the snapshot of nov.01.2026.
- **For M8:** these are proposals, not yet results. Whether they make the forecasts better is M8's question.

## Where the work stopped

- Done. Merged in #101 (`5784262`, v0.6, M6 Done) after green CI and GO from the gatekeeper and analyst (556 tests). Review ideas: backlog #102, #103, #104. Data: the snapshot `warren-20261101T035819Z` in the project's shared files.
