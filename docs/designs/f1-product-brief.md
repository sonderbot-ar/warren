# F1 design: the product brief

Status: In progress (nov.03.2026) · Elephant: front-end team (`product-lead`) · Branch `f1-product-brief`
Implements F1 of the front-end track (Build Plan §4, Structure Guide Decision 13).

## Problem

The engine answers questions an analyst asks from the command line. Nobody has written down the questions a student will ask the app, so engine milestones cannot check whether they serve them, and F2's screens would be designed without knowing what they must hold. The literal and hypothetical rule (backlog #130) is also undecided.

## Plan

**Step 0. Owner notes and studio.** `docs/product/owner-notes.md` with every owner comment so far on what students see (from the project threads, oct.14 to nov.03.2026) and a sign-off table; the "Warren studio" page, its URL recorded there. Test: every note has a date and what changed. Exit: notes merged in this PR; studio published.

**Step 1. The brief.** `docs/product/brief.md`: audience and language; the sorting rule (dato, pronóstico, supuesto, hipotético) with its edge case; 15 questions in Spanish with an English gloss, each with its kind, what Warren returns, what the engine needs and whether it answers today; out-of-scope questions and Warren's answer to each. Test: every question's "Today" claim cites a command, a file or an issue; a reviewer can check each. Exit: student-reviewer, professor and analyst raise no blocker.

**Step 2. Design principles.** `docs/product/design-principles.md`, one page: the student, the tone, what "intuitive" means, the bar. Test: each principle traces to an owner note or a standing rule. Exit: design critic says READY FOR OWNER.

**Step 3. Engine needs.** Each gap becomes an issue labelled `backlog` and `front-end` (R1–R6 below), and the brief's table links them. Exit: every "Partly" or "No" question links to an issue.

**Step 4. Owner sign-off.** Three decision cards with a recommendation and the studio link: the brief, the design principles, the sorting rule (#130, a new decision: AI reader or menus only). A "Warren: need you" email per CLAUDE.md. The transmission list's first entry (R2c) is a new method, so the engine team sends its own card when it builds it. Exit: both sign-offs given; the rule decided.

**Step 5. Merge and record.** CI green, gatekeeper GO, sign-offs given. Merge with a merge commit; v0.9.x in `docs/versions.md`; `docs/team-sync.md` entry and roadmap; Build Plan F1 Done; if the owner accepts the AI reader, Decision 9 and the decision log are updated in the same PR or a follow-up; desk entry and lesson.

## Alternatives considered

- **Questions by the engine team, from the engine's outputs.** Faster, but it would list what Warren can already do, not what a student asks; the gaps would never show.
- **A two-way rule (literal or hypothetical) only.** The #130 wording. Splitting literal into dato, pronóstico and supuesto costs nothing and tells the engine which of three different outputs a question needs.
- **An AI that answers event questions with an estimated impact.** Ruled out by the standing rule (LLMs never produce financial numbers) and the owner's #130 text.
- **Menus only, no AI reader.** Works today and needs no Decision 9 change; kept as the fallback in the brief and as an option on the card.

## Engine needs

Each is an issue labelled `backlog` and `front-end`; numbers in `docs/product/brief.md` §5. Revised after the engine lead's review (below).

- **R1 (#140) Reported figures and ratios** (questions 1, 2): a library call and command that return line items and named ratios (operating, gross and net margin; revenue growth year on year; capex and D&A as a share of revenue; effective tax rate; net debt) for a company and fiscal period, with filing, tag, period end and filing date, first reported and latest, a revision flag (not a reason), derived quarters marked, and the quality report's "newest filing disagrees" rows. Point in time. Takes over #128 item 2, so one issue owns it.
- **R2a (#141) What-if revaluation** (7, 8): revalue a stored run with named model inputs changed (`DRIVERS` and `SINGLE_VALUES` in `domains/analysis/dcf.py`, except `equity_market_value` and `roll_years`), plus two teaching overrides: WACC set directly and the terminal method (value-driver or Gordon), deterministic (reusing `shocks.apply` for driver paths where it fits, not the Monte Carlo path), stored as a child run linked to its parent with its changes as rows, so it reproduces to the cent. When `risk_free` changes, whether terminal growth follows it is decided by the run's `terminal_growth_method` row and recorded in the child's rows, unless the student overrides growth.
- **R2b (#142) Sensitivity grid** (9): a two-input grid on R2a (first use: the WACC override × terminal growth, under each terminal method); cells where growth reaches WACC carry the existing gap reason (v0.5.4).
- **R2c (#143) List of transmissions** (7): a checked-in list of transmissions from an event to a model input. First entry proposed: an unexpected policy-rate move → the 10-year yield, as a sourced range for surprises only (Kuttner 2001; Gürkaynak, Sack & Swanson 2005), point in time. A new method under Decision 4, so the engine team sends it to the owner as a card before building.
- **R3 (#144) Error ranges on every run** (5): M9's baseline p10–p90 from the misses public on the as-of date for any run, with the pooled and the company's own coverage; a run with shocks or an R2 child says which range it shows.
- **R4 (#145) Track record per company** (6): per company and quarter, the forecast, the first-reported actual, the error, range hit and the seasonal random-walk benchmark, from stored batches; per-company miscalibration shown, not hidden.
- **R5 (#146) Past-event query** (10–15): cases chosen by a stated rule (event type plus tags), with company and mechanism closeness, the forecast before and actuals after by quarter, the company's usual miss on quarters without an event, n and a numeric thin-evidence threshold, the `scope_change` warning; `grid` and `control` rows excluded; a checked-in "metrics to watch" table per event type, each row sourced to a filing or textbook and reviewed.
- **R6 (#147) Analogue cases** (11, 13, 14, 15): currency, inflation, commodity supply and elections or policy cases in a separate file that is never scored, so the evaluation library and its SHA-256 stay as they are; themes as tags on the existing event types (`domains/llm/event_types.csv`), not new types; depends on #108.
- Also #128 items 1 and 3 (default to the latest ended day) and #130 (the rule; owner decision).

## Engine design docs reviewed this run

- **M10 (`docs/designs/m10-more-dates.md`, PR #129).** Written before *Product impact* sections existed, so it has none. Read against the brief: it breaks no question. Its grid cases (event type `grid`, no event) are not analogues for hypothetical questions and must not appear in R5's results; its post-cutoff scores feed question 6 (R4). Comment left on the PR.

## Review notes

Design review, nov.03.2026, round 1 (explainer, student-reviewer, professor, analyst, design-critic, engine track-lead). All six raised blockers; all were accepted and fixed in the brief and principles:

- **Terminal value effect (professor B1, analyst B1, student B2).** The draft said a higher risk-free rate raises terminal growth and the two "partly offset". Under Warren's method, TV = NOPAT × (1 + g) / WACC (`financial_math.value_driver_terminal_value`), so growth barely matters. Q7 and Q9 now say so and name the run's method; Q9's lesson is the near-flat growth axis, with Gordon beside it.
- **Expected vs surprise rate moves (professor B2).** The transmission is for unexpected moves only, as a sourced range; the reading says an expected move is already priced.
- **Open-ended pass-through and missing inputs (explainer B1, professor B3, analyst B2).** The rule now names every model input from `dcf.py` and a closed, checked-in list of transmissions with one proposed entry; currency and inflation are events because nothing is listed for them.
- **Menu-only version undefined (explainer B2).** Both ways of sorting are described, with the same reading card.
- **Weak analogues (student B3, analyst I7, professor I1, I2, I5).** Every event answer shows closeness, n, a thin-evidence flag and the company's usual miss; cases are chosen by rule. Q11 drops the Coca-Cola guidance case; Q13 says there is no close case; Q14 marks "dirección opuesta".
- **"Sin valor" (student B1).** Now "no definido: el crecimiento terminal alcanza el WACC".
- **Ranges vs value per share (design-critic B1).** Principle 4 and brief §2 say which uncertainty each output has; value per share shows the ERP ± 1 SE values.
- **¿Y si…? on every number (design-critic B2), no visual rules (B3).** Principle 2 limits it to model inputs; a "How Warren looks" section adds tokens, number formats, separators, states and focus.
- **Missing links (explainer B3, design-critic B4).** Issues filed and linked; studio URL recorded.
- **Engine asks (track-lead B1–B3).** R6 goes in a separate unscored file with tags, not new types; R2c is a new method and goes to the owner; R1 names its ratios and takes over #128 item 2. R2 split into R2a–c.
- **Smaller points taken:** Q3 cites the free `dcf` command and the day-end rule; Q1 drops "why" and marks Apple's derived fourth quarter; Q2 adds period ends and "as reported"; Q4 notes book debt; Q5 shows the company's own coverage; Q10 carries the scope-change warning; *estimación* replaces *pronóstico*, *cambio de supuesto* replaces *supuesto*, *transmisión/traslado* replaces *traspaso*; a lay summary box opens the brief; "¿está cara o barata?" is in §4.
- **Not taken:** more questions (net debt, which assumption weighs most, two-company value comparison): concepts go to the side panel, and the other two wait for F2's screens rather than growing the brief past fifteen.

Design review, round 2 (design-critic, student-reviewer, and one reviewer for professor, analyst and track-lead): round-1 fixes confirmed against the code. New blockers, all fixed:

- **Dato vs estimación had two tests** (blocker-check B1). The rule now uses one: what the question names; a past event is an *evento*.
- **WACC is not an input** (blocker-check B2). WACC set directly and the terminal method are named teaching overrides in the rule and in R2a/R2b (#141, #142 updated).
- **The AI reader could return numbers** (blocker-check B3). Values are only copied word for word from the question and checked by code; otherwise blank.
- **ERP ± 1 SE read as a range** (student B1) and **WACC with no stated uncertainty** (design-critic B1). Brief §2 and principle 4 label a sensitivity as a sensitivity and point values as estimates.
- **"No definido" under Warren's formula** (student B2) and **Warren's choices read as rules** (student B3). Q9 explains the shared perpetuity; Q7 names both choices as Warren's.
- **Smaller points taken:** region setting apart from language (separators, `SUMA` syntax), *tú* stated as a choice, *elecciones intermedias*, the 65–95% band explained, the "Hoy: No" reasons for stored cases, Q12's 2020 case marked close rather than same mechanism, the cost of debt not moving in Q7, inputs that are never edited (the price), principle 7 retitled, "every figure" scoped, number rules for beta, multiples and pb, narrow-screen tables, and the owner box says what is not being approved.
