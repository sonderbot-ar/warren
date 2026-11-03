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
1. M10 — More test dates, including after the models' training cutoff (In progress: AI run done; the scored batch waits for actuals as of 2026-11-16).
2. Open `front-end` requests from F1 (#140 done in v0.9.6; next #128 and #144), weighed with the other backlog issues.
3. Backlog in order of what it unblocks.

**Front-end team:**
1. Engine needs from F1 (#140–#147), followed on each run. Most useful first: #140 (reported figures) and #128 (default to the latest ended day), which F2's first screen needs.
2. F2 — Web app, run locally (after M10): the stack card (including the question reader's model, free tools only), then two or three visual directions for the owner.
3. F2's first screen: one company and date, the forecast with its range, every number traced to its source, the question reader in front.

## Log

Newest first. One entry per merged version: the version and team, what changed in a sentence, its effect on the other team (questions served or broken, outputs added, renamed or removed; "none" is fine), and any roadmap change.

- **nov.03.2026 · v0.9.6 reported figures and named ratios (backlog #140, front-end R1) · engine team.** New call `domains.analysis.reported.reported_period(conn, ticker, period, as_of)` and command `python -m domains.analysis reported --ticker T --period FY2025Q4|FY2025|latest-quarter|latest-year --as-of D [--json]`: a period's lines with filing provenance (form, accession, date, EDGAR link), first-reported and latest values with `changed`, derived quarters with their inputs, disagreement rows, and ratios (`gross_margin`, `operating_margin`, `revenue_growth_yoy`, `capex_share`, `da_share`, `effective_tax_rate`, `net_debt`). Ratios are fractions, values raw in their unit; every gap, note and warning is `{code, params, text}` with English text as fallback, so the app owns the Spanish words. Field list and codes: `docs/designs/backlog-140-reported-figures.md`, Product impact. Effect on the front-end team: brief Q1 and Q2 are now answered (Sí); net margin is not in yet (#157); for Q2's five years, ask five periods. Nothing existing renamed or removed. Roadmap: #140 done; M10 resumes after 2026-11-16.
- **nov.03.2026 · v0.9.5 snapshots in parts (backlog #153) · engine team.** Saved data is now written in pieces under 400 MB, because the shared folder silently dropped anything over 512 MiB. Effect on the front-end team: none (no outputs, names or fields change). Roadmap: unchanged.
- **nov.03.2026 · v0.9.4 snapshot safety (backlog #150) · engine team.** Restoring saved data now skips a half-saved copy and uses the newest good one, and the clean-up can no longer delete the last good copy. Effect on the front-end team: none (no outputs, names or fields change). Roadmap: unchanged; M10's AI run continues.
- **nov.03.2026 · v0.9.3 F1 product brief · front-end team.** The student brief, the design principles and the sorting rule are merged and signed off by the owner (`docs/product/`). Effect on the engine team: engine design docs now check their *Product impact* against the 15 questions in `docs/product/brief.md`; eight requests are open as `front-end` issues (#140–#147; #143 needs an owner card before it is built, #147 keeps analogue cases out of the scored library); #128 item 2 moved to #140; Decision 9 now lists the app's question reader (labels only, never a number). The engine's outputs and names are unchanged. Roadmap: F1 Done; F2 after M10.
- **nov.03.2026 · Decision 13 (process, no version) · both teams.** The front-end team exists. Effect on the engine team: design docs get a *Product impact* section and are read by the `product-lead`; requests arrive as `front-end` issues. Roadmap: F1 starts now, F2 after M10.
