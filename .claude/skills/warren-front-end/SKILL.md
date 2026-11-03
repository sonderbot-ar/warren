---
name: "warren-front-end"
description: "Run Warren's front-end team: write the product brief (the student questions, literal vs hypothetical, language), turn its needs into engine issues, and later build the student web app in sonderbot-ar/warren."
---

# Warren front-end team

The front-end team builds Warren's student web app and owns the product decisions that shape the engine (Structure Guide Decision 13). Every UX and UI choice goes through this team. It works with the engine team; it never takes over engine code.

## Members

- **Product lead** (`product-lead`, Elephant): runs one front-end track from design doc to merge.
- **Student reviewer** (`student-reviewer`, Goldfish): reads the brief or a screen as a finance student in Latin America would.
- **Design critic** (`design-critic`, Goldfish): judges every mockup and screen for clarity, polish, consistency and accessibility, with screenshots, before the owner sees it.
- The existing Goldfish: `explainer`, `analyst` (would a practitioner answer the question this way), `professor` (is it teachable and defensible), `gatekeeper` (final GO or NO-GO on a PR).

## Working with the owner

The owner wants Warren's look and feel to be pristine and intuitive, and asked (nov.03.2026) for close coordination and reporting on this team's work. So, unlike the engine team, the front-end team gets the owner's sign-off on what students will see. Everything else (engine needs, reviews, internal docs) runs on its own as in `CLAUDE.md`.

**Sign-off points** (each is one decision card with a recommendation and a link; options are at least "Approve" and "Changes needed"):

1. **The brief** (F1): the student questions and what each returns, before it merges.
2. **Design principles** (F1): `docs/product/design-principles.md`, one page: who the student is, the tone, what "intuitive" means for Warren (for example "one question per screen", "every number one click from its filing"), and the bar a screen must clear. Before it merges.
3. **Visual direction** (F2, once): two or three distinct mockups of the same screen (type, colour, layout, density), shown side by side. The owner picks one or mixes them.
4. **Each screen, twice:** the mockup before it is built, and the built screen (screenshots at laptop and phone widths) before its PR merges.

Before any sign-off, the `design-critic` must say READY FOR OWNER and the `student-reviewer` must have no blockers. The owner sees only work that already clears the bar.

While a card waits, keep working on what it doesn't block (the next mockup, engine needs). A changes-needed answer goes back one step, not to the start.

**The owner's taste is the team's memory.** Every comment the owner makes on look, feel, wording or flow goes into `docs/product/owner-notes.md`, dated, in the owner's words where possible, with what changed because of it. Read it before every design step; never make the owner say the same thing twice.

**Reporting:**

- **The studio page.** One Artifact, "Warren studio", that the owner opens to see the front-end work: the current brief, the design principles, the latest mockups and screenshots, what changed since last time, and the decisions waiting. Create it at the first mockup or brief draft; then update it (same URL, recorded in `docs/product/owner-notes.md`) at every run that changes something visible.
- **Each run** that has something for the owner posts a short summary in the project with the studio link: what's new to look at, what's waiting on the owner, and what was asked of the engine team. Runs with nothing to show stay quiet.
- **Email** per `CLAUDE.md`: each sign-off card is a "Warren: need you: …" email with the studio link.
- **Desk and digest:** each merged F item gets a desk entry and lesson like any version; the weekly digest has a front-end line.

## Each run

A scheduled run starts every 12 hours (owner's ask, nov.03.2026). Each run:

1. Reads `docs/team-sync.md` entries since the last run, the open `front-end` issues and the engine's open design docs and PRs.
2. Reads `docs/product/owner-notes.md` and any owner answers since the last run, and records new owner comments there.
3. Reviews the *Product impact* section of any new engine design doc against the brief, and answers issues titled "Question for front-end:".
4. Advances the current front-end item one step (below), on its branch.
5. Adds a `docs/team-sync.md` entry for anything it merged and updates the front-end roadmap there.
6. Updates the studio page if anything visible changed, and ends with a short summary: what changed, what it asked the engine team for, anything waiting on the owner (see Reporting).

Skip step 4 when nothing is ready and say why. Never work on a branch with a commit pushed in the last 3 hours unless a cloud run made it (its commit messages end with a `Claude-Session:` line).

## What to work on, and when

1. **Now: the product brief (F1).** Cheap now, expensive to retrofit.
   - 10–15 real questions a finance student would ask, in Spanish with an English gloss. Mix the kinds: a company's actual numbers, a forecast for periods not yet reported (backlog #128), "what if this input changes", "what did a past event do", "what happens if this event happens".
   - For each: literal or hypothetical, what Warren returns, which engine inputs, outputs or cases it needs, and whether the engine answers it today.
   - The sorting rule (backlog #130). **Literal**: names a model input and gives it a value ("WACC if the Fed adds 25 bps"). Deterministic code recomputes; any pass-through assumption (the Fed funds rate to the 10-year yield) is stated and can be changed. **Hypothetical**: names an event, not an input ("if the Democrats win the midterms"). Answered by a curated query of the case library: analogous past events, what followed in sales and margins, and the metrics to watch. No invented numbers. Proposed: an LLM sorts the question and its reading is shown to the user before anything is computed (a new LLM step, so it goes to the owner; see Rules).
   - Language and audience: Spanish first, finance students in Latin America, terms as their courses use them.
   - The design principles (`docs/product/design-principles.md`, see Sign-off points).
2. **Always: engine needs.** Each gap between a brief question and today's engine becomes a GitHub issue labelled `backlog` and `front-end`: what to expose (a named input, an output, a stored field), the brief questions it serves, and why. An engine Elephant builds it through the normal loop. Check new engine design docs against the brief and comment on the issue, not the code, when one misses a question it should serve.
3. **Later: the web app (F2).** Start only after M10 merges, so screens are not redone while the engine's outputs change. The owner chose (nov.03.2026) a web app that runs locally first: it runs on the owner's Mac and opens in the browser, nothing hosted, no cost. Compare free stacks in the design doc that can be hosted later without a rewrite, and send the owner one decision card with a recommendation. Then show the owner two or three visual directions, and build screens one at a time, each from a brief question, through the sign-off points above.

## The loop

Same as `CLAUDE.md`: design doc in `docs/designs/f<n>-<short-name>.md` (the brief itself lives in `docs/product/brief.md`; the doc has an *Engine needs* section, see `docs/team-sync.md`), Goldfish review, build, PR, gatekeeper, merge with a merge commit, record. Front-end items are F<n> in `docs/build-plan.md`, branches `f<n>-<short-name>`; versions follow `docs/versions.md` (a merged F item gets a patch version, as a backlog item does; see `docs/versions.md`). Reporters write the desk entry and lesson as for any version, and the version gets its `docs/team-sync.md` entry.

- **Design review:** `explainer`, `student-reviewer` and `professor` in parallel, and a `track-lead` on the *Engine needs* section; add the `analyst` when the brief says how a number should be computed or compared.
- **Mockup review:** `design-critic` and `student-reviewer`, then the owner's sign-off.
- **PR review:** CI green, then the `gatekeeper`; add the `student-reviewer` for any reader-facing text, and the `design-critic` for any screen; then the owner's sign-off on a screen before merge.

## Rules

- Never edit `domains/`, `shared_kernel/`, or `main.py`. The app calls the engine as a library (Decision 11, guardrail 4). App code lives in its own top-level folder, chosen with the stack.
- Every number on screen comes from the engine and shows its source (filing, tag, period, as-of date). No LLM produces a financial number. An LLM that sorts a question and maps it to inputs is a new LLM step under Decision 9: propose it to the owner with the sorting rule, and build it only once Decision 9 records it.
- Every query behind an answer is point-in-time.
- Reader-facing text stays apart from logic, ready for Spanish and Portuguese (Decision 11, guardrail 5).
- Free tools only. A library or stack needs a licence that allows a paid product (the rule of Decision 12) and must run on the owner's 16 GB Apple Silicon MacBook.
- Ideas that are not the current item become issues labelled `backlog` and `front-end`.

## Escalate to the owner (one decision card, with a recommendation)

- The sign-off points above.

- The app's stack.
- Hosting the app, or adding logins and multiple users.
- Each new Accepted decision the team proposes, including the literal and hypothetical rule.
- Anything that costs money, any change to Phase 1's goal or scope, anything irreversible.
