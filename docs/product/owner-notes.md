# Owner notes: look, feel, wording and flow

The owner's comments on what students see, kept so the owner never says the same thing twice (Structure Guide Decision 13; `warren-front-end` skill). Newest first. Each note: the date, the owner's words where possible, and what changed because of it. Comments only, never personal data. Read this file before every design step.

**Studio page** (the front-end team's work for the owner): https://claude.ai/artifact/Wh9PzrYHFHxexMdKFRm7BR

## Sign-offs

| Item | Sent | Answer | Date |
|---|---|---|---|
| The reader's model after the free local models failed the bar: test Claude Haiku (about $0.06), a second free round, or menus (`docs/designs/f2-web-app.md`, Step 3 results, part 2) | nov.05.2026 | Waiting | |
| Product brief (`docs/product/brief.md`) | nov.03.2026 | Approved (card) | nov.03.2026 |
| Design principles (`docs/product/design-principles.md`) | nov.03.2026 | Approved (card), including the side-panel narrowing and the Mexico number format | nov.03.2026 |
| The app's stack and the reader's model (`docs/designs/f2-web-app.md`) | nov.04.2026 | FastAPI + htmx, local open model (card, the recommended option) | nov.04.2026 |
| Start F2's stack comparison before M10 merges (no screens until it does) | nov.04.2026 | Approved (card) | nov.04.2026 |
| Literal and hypothetical sorting rule (backlog #130): AI reader or menus only | nov.03.2026 | AI reader (card), then "no menus first": the reader is built from the start, menus only as a fallback | nov.03.2026 |

## Notes

- **nov.04.2026 · Compare stacks now.** On the card "Start comparing app stacks now, while M10 waits until 16 Nov?", chose "Start the stack comparison now". *Changed:* F2 starts with its stack card (`docs/designs/f2-web-app.md`); mockups and screens still wait for M10.
- **nov.03.2026 · No tagging by students.** On the sorting card: "I am not too fond of users having to tag their type of question — maybe we get a decision model in this part of the process?" Then chose the AI reader and added: "I agree, no menus first." *Changed:* Decision 9 records the question reader, built with the first screens; menus are only a fallback when the reader is unsure or unavailable; the student only confirms the reading. Students should not have to classify their own question.
- **nov.03.2026 · Pristine and intuitive.** "I want the aesthetics and functionality of Warren to be pristine and intuitive." "This front-end team will need a lot of coordination and reporting with me." *Changed:* the owner signs off the brief, the design principles, the visual direction and each screen (mockup and built); a design critic passes everything first; this file and the studio page exist.
- **nov.03.2026 · A web app, run locally first.** Asked whether a desktop app was overkill, and chose a web app that runs on the owner's Mac first and is hosted later. *Changed:* Decision 13; F2 compares free stacks that can be hosted without a rewrite.
- **nov.03.2026 · Side by side with the engine team.** "The front-end team should work side to side with the back-end team … establish a mean of effective communication to understand the implications of each update." *Changed:* `docs/team-sync.md`; every front-end design doc has an *Engine needs* section.
- **nov.03.2026 · Literal vs hypothetical (backlog #130).** The impact of an event on a company is never an LLM's output; it comes from a curated query of past cases plus suggested metrics. A literal question (names an input and a value) is recomputed by code, with any pass-through assumption stated and changeable. An LLM may sort the question; its reading is shown before anything is computed. *Changed:* the brief's sorting rule (`docs/product/brief.md`, section 2), sent to the owner as a decision card.
- **nov.02.2026 · Today by default (backlog #128).** A normal run should forecast only what is not reported yet; a completed period returns the reported numbers, as first reported and as restated; past-date forecasts stay as an explicit option. *Changed:* brief questions 1–5 assume this default.
- **oct.30.2026 · Every number opens a side panel (prototype "Warren Classroom", v2).** "Every cell (or button) is interactive and pops up a side panel with information … number traceability, formula and steps followed, theoretical explanation of concept (e.g., what is Net Debt), and the option to edit the current number to understand the implications on other linked numbers … Finally, the sidebar suggests some headlines from that company's industry that should be worthwhile reading, as well as other tickers that may be related." *Changed:* design principle 2 (every number is a door) and the five-part panel in the principles.
- **oct.30.2026 · Excel becomes the explanation, not the tool.** "The idea is for Excel to become an alternative tool for explanation. Just like paper became an alternative to calculators." *Changed:* design principle 5 (show the formula a spreadsheet would use, beside the answer).
- **oct.30.2026 · Both student and professor; a language toggle; Apple as the demo company.** Hero: "both can be". Language: "a toggle". Company: "one of the eight companies — maybe AAPL". *Changed:* the brief names both audiences; Spanish first with an English toggle; Apple leads the brief's examples.
- **oct.14.2026 · Fundamentals, never prices; when and why.** "I DO NOT want to try to predict price changes." Warren should help students understand "when and why a company's change in beta, capital structure, or book value might have an impact on other indicators". *Changed:* price questions are out of scope in the brief (section 4); what-if questions show the ripple and the reason.
