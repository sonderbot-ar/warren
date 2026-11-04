# F2 design: the web app, run locally

Status: In progress (Step 0 done nov.04.2026: the owner chose FastAPI, Jinja2 and htmx, and a local open model for the reader. Step 1 done nov.04.2026: the skeleton, see "Step 1 results"; next, Step 3, the reader's labelled set; no screens until M10 merges) · Elephant: front-end team (`product-lead`)
Implements F2 of the front-end track (Build Plan §4, Structure Guide Decisions 11 and 13).

## Problem

Warren's engine answers the brief's questions from the command line (`docs/product/brief.md`; six work today, five in part). Students need them in a browser, in Spanish, with every number one click from its source (design principles 2 and 3). Decision 13 fixes the shape: a web app that runs on the owner's Mac first, nothing hosted, no cost, and that can be hosted for a school later without a rewrite. It also needs a model for the question reader that Decision 9 records (owner, nov.03.2026: "no menus first"). Neither the stack nor the reader's model has been chosen; both go to the owner on one card.

## What the stack must do

Each line comes from a standing rule or a signed-off document; the comparison below scores every option on them.

1. **Call the engine as a library** (Decision 11, guardrail 4). The engine is Python (`domains/`, `shared_kernel/`); the app imports it and never edits it. So the server is Python.
2. **Free, with a licence that allows a paid product** (Decision 12's rule: no GPL, AGPL or non-commercial), and runs on the owner's 16 GB Apple Silicon MacBook.
3. **Hostable later without a rewrite** (Decision 13): one process and the SQLite database, deployable to any host or a school's own server.
4. **Pristine look under our full control** (owner, nov.03.2026; design principles, "How Warren looks"): our own tokens, type scale and number rules; no framework look we fight against.
5. **The interactions the principles name:** the reading card before anything is computed (6), the side panel with five tabs on every figure (2), the what-if with its ripple (8), wide tables that scroll in their own frame, phone width with the panel full screen.
6. **Accessible in both themes** (principles, "How Warren looks" and "The bar"): light and dark, WCAG AA contrast, full keyboard use (the panel's tabs by arrow keys, focus into and back out of the panel, Escape to close), screen readers told what changed after a partial update, touch targets of at least 24 × 24 px.
7. **Spanish first, English by a toggle, numbers by region** (brief §1; principles, "Numbers": Mexico by default, 1,234.5 or 1.234,5 by region). Text apart from logic (guardrail 5), and the engine's coded notes (#172, `reported.Coded`) translated in one place (the app's text catalogues, keyed by code).
8. **Point in time on every request.** Every page carries its *fecha de corte* in its address (`?corte=2026-11-03`); a request without one is redirected to the last day ended in New York (`shared_kernel.calendar.last_ended_day`, as the engine's commands do since v0.9.7), so every engine call has an explicit `as_of` (standing rule).
9. **Testable in CI**: ruff and pytest as today, plus one added CI step that runs Playwright (Apache-2.0) and its Chromium for keyboard runs and screenshots at 1440 px and 390 px for the `design-critic`.

## Options compared

Versions are today's releases, to be pinned in Step 1. Licences checked on PyPI and npm (nov.04.2026).

| | A. FastAPI + Jinja2 templates + htmx | B. FastAPI API + React (Vite) | C. A Python UI framework (Streamlit, NiceGUI, Reflex, Dash) |
|---|---|---|---|
| Licences | FastAPI MIT, Starlette and Uvicorn BSD-3, Jinja2 BSD-3, Babel BSD-3, htmx 0BSD (tests: Playwright Apache-2.0, as for B) | FastAPI MIT; React MIT, Vite MIT | Streamlit Apache-2.0, NiceGUI MIT, Reflex Apache-2.0, Dash MIT |
| 1. Engine as a library | Yes, same process | Yes, behind a JSON API | Yes, same process |
| 3. Hosted later | One Python process + SQLite; any host, a container or a school server | The same API, plus static files | Streamlit, NiceGUI and Reflex keep a live connection per student, which needs their own hosting patterns for a class; Dash runs over plain requests |
| 4. Look under our control | Full: our HTML and CSS, nothing to override | Full | Partial: NiceGUI and Dash can be restyled with our CSS, Streamlit hardly at all (it reruns the whole page on each input); in all four the widgets' behaviour and keyboard handling are theirs, not ours |
| 5. Interactions | Server returns page fragments: the reading card, the panel tabs, the what-if ripple are each one request; a little plain JavaScript for focus and the panel | Richest client-side state; every interaction is ours to build | Fast to prototype; side panels over the page and a ripple with before and after are hard to make pristine |
| 6. Accessibility | Ours to build: native `<dialog>` for the panel, WAI-ARIA tabs, `aria-live` regions for what htmx swaps in, one tab stop per table with arrow keys inside | Ours to build, with the same patterns in React | The widgets' own; hardest to make fully keyboard-accessible (Streamlit, Dash) |
| 7. Spanish and regions | Babel formats numbers and dates by region on the server (es_MX, es_AR, en_US) and holds the text catalogues; one place for every number's format | Either the API sends numbers already formatted by Babel, or the browser formats them (`Intl`, same CLDR data); both work, at the price of a second toolchain | Mixed; framework widgets format numbers their own way |
| 8. Point in time | Each route takes `as_of`; checked by pytest | The same, in the API | The same |
| 9. Tests | pytest and FastAPI's test client on every route; Playwright screenshots | pytest on the API, plus a JavaScript test stack and a Node toolchain in CI | pytest on logic; UI tests awkward |
| Languages to maintain | Python, HTML, CSS, a little JavaScript | Python and TypeScript, two build tools | Python |
| Cost | Free | Free | Free |

**Recommendation: A.** It is the only option that meets every line without a second language or a framework look. Its edge over B is one language and one toolchain to maintain and test, with every number formatted by one Python function by region, next to the engine that produced it. The interactions the principles ask for are each a server round trip that the engine has to make anyway (a what-if is computed and stored by `domains.analysis.whatif.revalue`), so client-side state buys little. If a later screen needs heavy client interaction (a live chart the student drags), a single component can be added on that screen without changing the rest; B stays the fallback. C is ruled out on lines 4 and 6: the owner asked for pristine, and these frameworks' widgets, their behaviour and their keyboard handling are not ours to change.

Charts are chosen at the visual direction, among free options that render on the server or with one small script (inline SVG from Python, or Observable Plot, ISC).

## The question reader's model

Decision 9 records the reader: it returns only labels (the kind, the company, the date, the inputs it names, values copied word for word), code checks every field, and the student confirms the reading. It is measured on a labelled set of student questions before students use it. The model behind it:

| | 1. A local open model (about 8B parameters, 4-bit) | 2. Claude Haiku through Warren's existing key | 3. No model (menus only) |
|---|---|---|---|
| Cost | Free | Paid per question (small, but a cost; and per student once hosted) | Free |
| Runs on the Mac | Yes, through Ollama (MIT) or llama.cpp (MIT) with Metal; about 5 GB of memory | Needs the network | Yes |
| Licence | An Apache-2.0 model such as Qwen3-8B, picked by Decision 12's rules (safetensors or GGUF, no remote code) | Anthropic's terms | n/a |
| Answers as fields | Output held to a JSON schema by the runtime's grammar | Tool use with a schema | n/a |
| Hosted later | Needs a server with about 8 GB of memory, a cost decided at hosting | Cost per call | n/a |
| Owner's earlier answer | Fits "free tools only" | A cost: owner's call | Rejected as the primary path ("no menus first"); kept as the fallback |

**Recommendation: 1**, behind one interface (`read_question(text, locale) -> Reading`, where `Reading` holds the kind, company, date, the inputs named with any value copied from the question, and an unsure flag; a field that fails the code check is dropped and the reading is marked unsure, so the reading card asks the student) so the model can be swapped without touching the screens, as data sources sit behind adapters (guardrail 1). The front-end team picks the exact model in Step 3 by Decision 12's rules and the score on the labelled set. If the local model fails the bar, the team comes back with a card for option 2 and its measured cost.

## Plan

**Step 0. Stack card (this step).** This doc; review by the `explainer`, the `design-critic` (can the stack deliver the principles) and an engine `track-lead` (the engine side, *Engine needs*); then one decision card to the owner with the recommendation and the studio link, and a "Warren: need you" email. The `student-reviewer` and `professor` review the screens and the reader's labelled set, not this step, since nothing here is read by a student. Exit: the owner has chosen a stack and a reader model; Decision 13 records the stack and Decision 9 the reader's model, each with a row in the decision log.

**Step 1. The skeleton (may start before M10; no screens).** A top-level `webapp/` folder, run with `python -m webapp` on the Mac; pinned dependencies with their licences in `requirements.txt`; tokens as CSS variables with no values chosen yet; text catalogues for `es` and `en` with a test that no template holds a hard-coded string; `webapp/__init__.py` and `__main__.py`, tests under `tests/webapp/`; a number formatter by region with tests against the principles' table (one decimal for %, none for millions, two per share, whole bp, minus or parentheses), the spreadsheet formula's separators by region (`=SUMA(A1;B1)` or `=SUMA(A1,B1)`), parsing what a student types ("1.234,5") with Babel, and dates pinned in a test ("15 nov 2026"); the panel's keyboard behaviour (arrow keys between tabs, focus in and back, Escape, `aria-live` after a swap) tested by Playwright; the panel's state in the address (`hx-push-url`) so Back works; the database rules of *Engine needs*; a route test that a request without a *fecha de corte* is redirected to one; a Playwright script that saves screenshots at 1440 px and 390 px. Dependencies go in `requirements.txt`, the repo's source of pins, with `uv.lock` refreshed in the same commit. Exit: CI green with the new tests and the Playwright step; nothing under `domains/`, `shared_kernel/` or `main.py` changed.

**Step 2. Visual direction (after M10 merges).** Two or three mockups of the first screen, distinct in type, colour, layout and density, side by side on the studio page; `design-critic` READY FOR OWNER and `student-reviewer` no blockers; then the owner's card. Exit: a direction chosen and its measurable rules (hierarchy, density, white space) added to the principles.

**Step 3. The reader's labelled set (may start before M10).** At least 100 student questions in Spanish and English, each labelled with its kind, company, date and inputs by the brief's rule, reviewed by the `student-reviewer` and the `professor`; drawn from the brief's 15, their variants and questions the `student-reviewer` writes, about half in each language; a scoring script and the bar, with its numbers set before the model is run (proposed: the kind right on at least 95%, inputs exactly right on at least 90%, and never a wrong reading without the unsure flag on more than 2%); the chosen model run against it. Exit: the score is recorded; the reader passes the bar or the owner gets the card for option 2.

**Step 4. The first screen (after M10).** One company and date, the forecast with its range, every number traced to its source, the reader in front (Build Plan F2). Mockup and built screen each signed off by the owner.

### Step 1 results (nov.04.2026)

Built in `webapp/` with tests in `tests/webapp/` (82 tests: 75 without a browser, 7 in Chromium). Nothing under `domains/`, `shared_kernel/` or `main.py` changed.

- **Run it:** `python -m webapp` (127.0.0.1:8000 only). It checks the database first and refuses to start, naming the restore command, when a migration is missing or unknown (`webapp/database.py`); it never applies one. `/salud` reports the same check as JSON.
- **Point in time:** every page and fragment takes `?corte=`; none, or a day that has not ended in New York, is a 307 redirect to `last_ended_day(now)` that keeps the rest of the address; an unreadable date is the designed 400 page. Page views never open the database (tested).
- **Words and regions:** `webapp/text/es.json` and `en.json` hold every word; tests keep their keys and placeholders equal and fail on any word or readable attribute (`aria-label`, `title`, `alt`, `placeholder`) written into a template. The language toggle sets a cookie and returns to the same address (only paths on the site). `webapp/formatting.py` formats every figure by the principles' table (half up on the shown digits, a true minus sign or parentheses, never −0), parses what a student types strictly by region (Mexico's 1,234.5 is refused under Argentina's settings rather than guessed), pins dates (15 nov 2026; Nov 15, 2026; September follows each region, "sep" in Mexico and "sept" further south, as CLDR has it) and writes the spreadsheet formula with the region's separators and Spanish function names.
- **Tokens:** `webapp/static/tokens.css` names every token with provisional values for light and dark; a test refuses a raw colour or type size in `app.css` or a `style=` in a template, and keeps the two themes on the same colour tokens.
- **The side panel** on a component bench (`/componentes`, placeholder text, no figures): a modal `<dialog>` at the right, full screen at phone width; WAI-ARIA tabs with arrow keys, Home and End; Escape or the close button returns focus to the figure; the panel and its tab live in the address (opened with `hx-push-url`, tabs with `hx-replace-url`), so Back reopens it and a copied link opens the same tab; a polite live region says which tab is showing. Without JavaScript the links still load the page with the panel open. htmx 2.0.11 is vendored (0BSD, npm integrity checked, its hash pinned in a test).
- **CI:** Playwright 1.64.1 and its Chromium are installed in the `tests` job; with `WARREN_BROWSER_TESTS=1` a missing browser fails the run. `python -m webapp.screenshots --out DIR` saves each page at 1440 and 390 px, light and dark, and CI uploads them as the `webapp-screenshots` artifact for the `design-critic`.
- **Design critic on the skeleton** (NOT READY on the first build, two blockers, both fixed and tested): a slow tab's answer could land under a newer tab (tabs now share one `hx-sync` queue, and the announced tab is the one whose content loaded; a test holds a response back), and a failed tab kept the old content under the new name (it now shows the catalogue's error message with a retry link, and the live region says it). Polish taken: the close control is a link that works without JavaScript; a click on the dimmed page closes; Space and Enter select a tab; the tabs wrap on a phone instead of being cut off; no `role="alert"` on full error pages; "el enlace" instead of "la dirección" in Spanish. Carried to later steps: the *fecha de corte* explanation becomes visible text or a door to *Concepto* on the first screen (now only a tooltip); control borders reach 3:1 (WCAG 1.4.11) at the visual direction, since the provisional line colour is about 1.4:1; the panel's title names its figure once there are figures.
- **Changed from the plan:** no write lock in the app. Since v0.9.10 (#176) the engine numbers runs inside its own write lock, so the lock the engine lead asked for is no longer needed for correctness. `uv.lock` is unchanged: `pyproject.toml` lists no dependencies (`requirements.txt` is the source of pins), so the lock holds only the project itself.

## Alternatives considered

- **Wait for M10 before choosing a stack.** The Build Plan's first order. The owner chose (nov.04.2026) to compare stacks now, since the stack does not depend on the engine's outputs; screens still wait.
- **A desktop app.** Rejected in Decision 13 (installs and a copy of the data on every school machine).
- **Django instead of FastAPI.** Its login and admin tools help once there are users, which Phase 1 does not have, and logins are a separate owner decision. FastAPI is smaller; moving the templates later costs little, since they stay plain Jinja-style HTML.

## Engine needs

None for Step 0 or Step 1. The app imports the engine's existing calls: `domains.analysis.reported.reported_period` (reported figures with their filings), `domains.analysis.whatif.revalue` (what-ifs), `domains.analysis.runs.run_baseline` (a run on a date), `domains.evaluation.run_ranges` (a run's range and its track record, v0.9.8), `domains.evaluation.hindsight` (what was reported afterwards, v0.9.7) and `shared_kernel.calendar.last_ended_day` (today's *fecha de corte*). It reads and writes the database through `shared_kernel.database.get_db_connection` (existing; SQLite in WAL mode, so engine writes do not block the app's reads).

**Rules for sharing the database** (engine lead's review):
- Each route opens its own connection inside its body (`with get_db_connection() as conn:`), never through a dependency that can cross worker threads (the connection keeps SQLite's same-thread check).
- The app never applies migrations. At start it compares `current_schema_version` with `list_migrations` and refuses to start, with a message naming the command, if they differ.
- The app writes only when a student asks for something new (a what-if, a run on a date with none stored), never on a page view. (The first draft also put every write behind one lock in the app, because run ids were counted outside the write; v0.9.10, #176, moved that count inside the engine's own write lock, so the app needs none.)
- A write that waits past SQLite's 10 s timeout (during a long ingest) shows the designed error state and can be retried.

**Asks filed for the first screen:** a structured source for every forecast assumption (today a run's filings are only inside the free text of each assumption's `method`; principle 2 needs them as fields) (#175), and run ids allocated inside the transaction (#176, before hosting). Already open: #172 (warnings as codes, so they show in Spanish), #145 (the company's track record) and #142 (the sensitivity grid). Also noted: the "filings may be out of date" note lives only in the command line (`domains/analysis/__main__.py`), and `code_version()` reads git, so a hosted copy without `.git` would store runs as "unknown"; both go into the first screen's asks if it needs them.

## Design review

nov.04.2026, on the first draft. All points accepted; the doc above is the revised version.

- **Explainer** (11 gaps): where `as_of` comes from, the `Reading` fields and what happens when a field fails its check, who picks the model, the bar's numbers, the labelled set's source and languages, the engine calls by name, Playwright in CI. All answered in the sections above. The studio page and READY FOR OWNER are defined in the `warren-front-end` skill.
- **Design critic** (SOUND, no blockers): the requirement list left out light and dark, WCAG AA, keyboard use and touch targets, so the table never scored them (added as line 6 and a table row); "a little plain JavaScript" undersold the panel's keyboard work (named in Step 1, tested by Playwright); formula separators, parsing typed numbers and pinned dates belong in Step 1's tests (added); keep the panel in the address (added). Unfair wording fixed: B can send numbers formatted by Babel, so A's edge is one toolchain; Dash runs over plain requests; NiceGUI and Dash can be restyled, so C is ruled out on widget behaviour and accessibility, not on looks alone; Playwright listed.
- **Engine track-lead** (NO-GO on the first draft, on two blockers, both fixed): the engine calls were misplaced (ranges and hindsight live in `domains/evaluation`) and the first screen needs a structured source per forecast assumption, which does not exist (filed as #175); and the doc did not state how the app shares SQLite with engine commands (connections per route, no migrations by the app, one write lock because run ids are counted, the 10 s timeout). Notes taken: no runs on page views, `code_version()` without git, `requirements.txt` as the source with `uv.lock` refreshed, the Playwright CI step, `webapp/__init__.py` and `__main__.py`, tests in `tests/webapp/`.
