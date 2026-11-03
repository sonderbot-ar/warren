# Warren design principles

Status: Draft for review (F1, nov.03.2026; revised after design review) · Owner sign-off: waiting

One page. Every mockup and screen is judged against it by the `design-critic` and the `student-reviewer`, then by the owner. The owner's own words behind it are in `docs/product/owner-notes.md`.

## Who it is for

A finance student in Latin America who has built a DCF in a spreadsheet and wants to know *why* each number is what it is, and the professor who teaches them. They read Spanish first. They are smart and busy; they are not yet analysts.

## Tone

Like a good teaching assistant: plain, exact, calm. Short sentences in natural Latin American Spanish, *tú*, the terms the course uses (`docs/product/brief.md`, §1). It says what it does not know ("hay pocos casos parecidos") and never sells. No hype, no jargon without a one-line gloss, no exclamation marks.

## What "intuitive" means here

1. **One question per screen.** Each screen answers one of the brief's questions and says which in its title.
2. **Every number is a door.** Any number opens a side panel, a separate layer over the screen, with five tabs (owner, oct.30.2026): *Fuente* (filing, tag, period, filing date), *Fórmula* (the steps, and the spreadsheet formula a student would write), *Concepto* (what it means, for example net debt), *¿Y si…?* and *Para leer* (headlines from before the *fecha de corte*, related companies). *¿Y si…?* edits only model inputs (brief §2); on a reported figure or an output it says "Este número sale de X" and links to the inputs that move it. Labels and column headings open *Concepto* only; buttons open nothing.
3. **Nothing from the future.** Every screen shows its *fecha de corte*. Nothing on it was public after that date. Looking back is an explicit choice, and then what really happened is shown beside the estimate.
4. **Uncertainty, honestly labelled.** Each output shows the uncertainty the engine measures for it, as the brief lists (§2, "Which uncertainty each answer shows"), with a plain sentence on what it means. Never a range the engine did not compute, and never a lone number made to look certain.
5. **The spreadsheet becomes the explanation.** Warren does the arithmetic; the formula a student would type is shown beside it, in the spreadsheet language of the chosen toggle (Spanish: `=SUMA(A1;B1)`; English: `=SUM(A1,B1)`) (owner, oct.30.2026).
6. **The reading comes first.** Before computing, Warren shows how it read the question (kind, company, date, inputs and values) on one editable card, whether the reading came from menus or from the AI reader.
7. **Events are never numbers.** An event shows past cases, how close each is, how many there are, and what to watch. Never an AI's estimate of an impact.
8. **Change shows its ripple.** When an input changes, everything it moves is marked with before and after, a one-line reason, and a mark that does not rely on colour alone (an arrow and the signed change).

## How Warren looks

The exact type, colours and layout are chosen once, at the visual direction (F2), and then hold everywhere. Fixed now:

- **Tokens.** One type scale and one spacing scale, defined as tokens; no screen sets its own sizes or colours.
- **Numbers.** Right-aligned, tabular figures, units in the column header (*millones de US$*, %, pb). One decimal for percentages, none for millions, two for per-share values. Negatives with a minus sign; in financial statements, in parentheses as the filings show them. The decimal and thousands separators follow the chosen language (Spanish: 1.234,5; English: 1,234.5); dates as *15 nov 2026*.
- **States.** Every screen has a designed loading, empty, error and thin-evidence state; none is a blank or a spinner alone.
- **Focus.** Every control has a visible keyboard focus.

## The bar a screen must clear

- **Five seconds.** The `student-reviewer`, shown only a screenshot, can say which question the screen answers. The source of any number is one click away.
- One clear focus; nothing on the screen (outside the side panel) that does not serve its question.
- Consistent with the tokens and the number rules above, across screens.
- Natural Spanish, reviewed by the `student-reviewer`; English through the toggle; no text hard-coded in logic.
- WCAG AA contrast, full keyboard use, readable at laptop (1440 px) and phone (390 px) widths, light and dark.
- Nothing broken, clipped or overlapping at either width.
- No number the engine did not produce; no price target anywhere.
