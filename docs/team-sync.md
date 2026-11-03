# Team sync: engine and front-end

How Warren's two building teams keep each other informed (owner's ask, nov.03.2026; Structure Guide Decision 13). The engine team builds the analysis (milestones M<n> and backlog items); the front-end team owns the product brief and the student web app (F<n>). They work side by side: neither edits the other's code, and neither learns about the other's changes by surprise.

## How the teams talk

1. **This file is the shared channel.** Every merged version from either team adds an entry under "Log" in the same follow-up commit that adds it to `docs/versions.md`. Every run of either team reads the entries added since its last run before it picks work.
2. **Each design doc names its effect on the other team.** An engine design doc has a section *Product impact*: which brief questions (`docs/product/brief.md`, once it exists) it serves, changes or breaks, and any output, name or field it adds, renames or removes. A front-end design doc has a section *Engine needs*: what it needs from the engine, each as a linked issue.
3. **The other team reviews the design doc.** The front-end `product-lead` reads every engine design doc's *Product impact* at the design review; an engine `track-lead` reads every front-end design doc's *Engine needs*. Objections cite the brief question or the file and line, as any Goldfish objection does, and are written in the design doc's review notes or as an issue.
4. **Requests are issues.** What the front-end needs from the engine is an issue labelled `backlog` and `front-end`. An engine Elephant picks these like any backlog issue and links the PR. A question about the other team's work that blocks a step is also an issue labelled `front-end`, titled "Question for engine: …" or "Question for front-end: …"; the team it is for answers it in its next run.
5. **Roadmaps stay current here.** Each team keeps its next three items in "Roadmaps" below, updated when it starts or finishes an item, with any reason the order changed.

## Roadmaps

**Engine team** (from `docs/build-plan.md`):
1. M10 — More test dates, including after the models' training cutoff (Planned).
2. Open `front-end` requests from F1, weighed with the other backlog issues.
3. Backlog in order of what it unblocks.

**Front-end team:**
1. F1 — Product brief: student questions, literal vs hypothetical rule, language and audience (In progress since nov.03.2026; draft in `docs/product/brief.md` on `f1-product-brief`, waiting on the owner's sign-off).
2. Engine needs from F1, filed as `front-end` issues (R1–R6 in the brief, §5). Most useful first: R1 (reported figures) and #128 (default to today), which F2's first screen needs.
3. F2 — Web app, run locally (after M10).

## Log

Newest first. One entry per merged version: the version and team, what changed in a sentence, its effect on the other team (questions served or broken, outputs added, renamed or removed; "none" is fine), and any roadmap change.

- **nov.03.2026 · Decision 13 (process, no version) · both teams.** The front-end team exists. Effect on the engine team: design docs get a *Product impact* section and are read by the `product-lead`; requests arrive as `front-end` issues. Roadmap: F1 starts now, F2 after M10.
