# Backlog #412: commercial paper left out beside short-term bank loans

Issue: https://github.com/sonderbot-ar/warren/issues/412 (from the #408 design review) · Branch `backlog-412-pg-commercial-paper` · Version v0.9.79, merged nov.16.2026 (PR #416, merge `8252533`, after CI green and a gatekeeper GO).


## Problem

`math_engine.debt_parts` counts commercial paper only when no short-term borrowings are tagged (D3, `docs/build-plan.md`: "commercial paper only when short-term borrowings are absent"). The rule guards a real risk: many companies fold commercial paper into the short-term borrowings line (risk register, build plan line 512). But when a company tags a small short-term line *and* a separate commercial paper line, the paper is dropped.

The issue found it at P&G's 2018-06-30 year end (short-term bank loans 800M, commercial paper 7,761M). Looking at every company and date where both lines are tagged showed it is much larger at Exxon. Figures in millions, first filed value, from the restored snapshot (company facts):

| Company, date | Short-term line (tag) | Commercial paper | Current portion | DebtCurrent (filed total) | Short + current | + commercial paper |
|---|---|---|---|---|---|---|
| P&G 2017-06-30 | 0 (bank loans) | 11,705 | 1,676 | 13,554 | 1,676 | 13,381 |
| P&G 2018-06-30 | 800 (bank loans) | 7,761 | 1,772 | 10,423 | 2,572 | 10,333 |
| Exxon 2018-12-31 | 325 (bank loans) | 12,863 | 4,070 | 17,258 | 4,395 | 17,258 |
| Exxon 2019-12-31 | 316 (bank loans) | 18,561 | 1,617 | 20,578 | 1,933 | 20,494 |
| Exxon 2020-12-31 | 222 (bank loans) | 17,306 | 2,930 | 20,458 | 3,152 | 20,458 |
| Exxon 2021-12-31 | 276 (bank loans) | 1,608 | 2,392 | 4,276 | 2,668 | 4,276 |
| Exxon 2025-12-31 | 3 (bank loans) | 3,059 | 6,200 | 9,296 | 6,203 | 9,262 |
| Microsoft 2016-12-31 | 25,065 (`ShortTermBorrowings`) | 25,100 | 599 | not tagged | | |
| Coca-Cola 2019-12-31 | 10,994 (`ShortTermBorrowings`) | 10,007 | 4,253 | not tagged | | |
| Walmart 2009-10-31 | 5,239 (`ShortTermBorrowings`) | 5,239 | 4,169 | not tagged | | |

Exxon tags `us-gaap:ShortTermBankLoansAndNotesPayable` (mapped to `short_term_borrowings`, priority 2) at every year end 2009 to 2025 beside `us-gaap:CommercialPaper`, and its filed total equals the three parts added (to the million at most year ends). Its balance sheet line "Notes and loans payable" is that total. P&G's "Debt due within one year" is the same kind of total. So Warren counted Exxon's short-term debt without its commercial paper on every run, up to $18.6bn short, and P&G's $7.8bn short on runs reading 2018-06-30 (and its cost of debt read 2017-06-30 without $11.7bn).

Microsoft, Coca-Cola and Walmart are the other case: their commercial paper is a part of short-term borrowings (Microsoft's two lines are the same amount; Coca-Cola's paper is smaller than its loans and notes payable), so adding it would count it twice. None of them tags `DebtCurrent`.

## Plan

- **Step 0.** This design doc. No build plan change except the D3 wording (a backlog item).

- **Step 1. Judge from the filing's own total, as #408 does (companies as data, Decision 11).** Commits `82aa98c`, and `f0195c0` for the review fix (an older short-term figure).
  - `math_engine.paper_beside(short_term, paper, on, inside)`: at the commercial paper's date (`on(item, day)` is `History.on`, a fact dated exactly that day and filed by the run's as-of date), with commercial paper above zero and a short-term figure no newer than it, the filing's `DebtCurrent` total (map item `debt_current_total`, added by #408, never counted) is (a) strictly nearer short-term borrowings + the current portion + commercial paper than short-term borrowings + the current portion (a tie is not beside), and (b) strictly less than half the commercial paper away from the sum with it (a total that fits neither sum is a broken or differently built figure, not evidence). The current portion is the one dated that day, zero when there is none or when #408 found it inside short-term borrowings. **A short-term figure older than the paper** (carried forward because the company stopped tagging it) counts as zero at the paper's date, and when the check holds it is left out of debt and of the carried-forward list, the paper counted in its place (analyst, design review: P&G tags bank loans only at its 2017 and 2018 year ends, so at 2019-06-30 the 2018 figure of 800M, 365 days old, pushed out 6,183M of that year's paper; the 2019 total, 9,697M, is 126M off paper + current portion). No tolerance to tune. On real data it holds at 15 of Exxon's 17 year ends (2010 to 2023 and 2025: 0M off the sum with paper at ten of them, 2M to 762M at the others, always nearer than without it; 2009's total, 2,476M, fits neither sum, 1,591M or 1,391M, so (b) keeps today's reading; 2024 has no paper) and at P&G's two (90M and 173M off, against 7,761M and 11,705M without). It never holds for Microsoft, Coca-Cola or Walmart (no total).
  - When it holds, `debt_parts` counts commercial paper beside short-term borrowings (row `balance:commercial_paper`, debt row method says why); `_operating_nwc` takes it out of current liabilities too, beside short-term borrowings and the current portion it already takes out (history row method says why); the cost of debt reads `debt_parts` at each year end, so it follows. Without the total, nothing changes: commercial paper counts only in place of short-term borrowings.
  - A quarter-end run carries the year-end parts forward (Exxon tags only the total at quarter ends), and the year-end judgement goes with them, as #408's does.
  - Run note `commercial_paper_beside_short_term` (group `data`; params `period_end` (ISO, the date judged), `commercial_paper`, `short_term_borrowings`, `debt_current` (the current portion counted that day, 0 if none), `debt_current_total` (unscaled, in `currency`), `currency`, `accession_no` (the commercial paper's filing), `short_term_left_out` and `short_term_left_out_period_end` (an older short-term figure left out, else null; `short_term_borrowings` is then 0), `assumptions` (`["debt", "cost_of_debt", "nwc_pct"]`)) and its lesson in `text.WARNING_LESSONS`. The reported view (`reported._net_debt`) reads debt through `debt_parts`, so it agrees, and carries the same code with the same params but `assumptions`; its formula text names the rule.
  - `READING_RULES_VERSION` 6 → 7, with its row in `domains/analysis/reading_rules.md`. A rebuild through a map made before `debt_current_total` existed doesn't read the total, so stored runs rebuild as before.
  - Tests (`tests/analysis/test_paper_beside.py`, 19 with the parametrised cases counted one each): beside bank loans (debt 280, not 210; row, method, note params); a short-term line of zero beside paper (P&G 2017); paper inside short-term borrowings is not added (Microsoft's case); no total, no change; paper alone still counts in place of borrowings; history working capital takes the paper out; a year-end judgement carried to a quarter; P&G 2018 and Exxon 2019 figures; P&G 2019's carried bank loans (unit and run level), and an older figure kept when the total doesn't fit; four edge cases (no paper, a tie, paper dated apart, a total far above both sums); code and lesson catalogued; the reported view agrees; a map without the check item reads as before.
  - Exit: full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot (`warren-20261116T053654Z`, which already holds every `DebtCurrent` fact from #408's ingest): `reproduce --all --rebuild`: every stored run reproduces to the cent and rebuilds as before through its own map. Build every stored run date of all eight companies fresh (same pinned market data and choices) with and without the check (the measuring script swaps `paper_beside` for a function returning None; nothing in the code base has a switch), none stored, and list what moves. The other five companies tag no `DebtCurrent` (#408's ingest), so they cannot move. Exit: only Exxon and P&G move, each moved debt carries the note.

## Alternatives considered

- **Always count commercial paper beside short-term borrowings.** Double counts Microsoft, Coca-Cola and Walmart, whose paper is inside the short-term line.
- **Count it beside when paper is larger than short-term borrowings.** Paper larger than the line that would hold it can't be inside it, but Microsoft's two lines differ only by rounding (25,100 vs 25,065 at 2016-12-31), so a size test needs a tolerance and still guesses.
- **Use `DebtCurrent` itself as the whole current debt.** It would also fix Exxon's quarter ends, where only the total is tagged (follow-up below), but it would replace three traced lines with one, and the parts are what a student reads; most companies don't tag it.
- **A company-scoped concept map row** (#341's `companies` column) mapping Exxon's bank loans elsewhere. Hard-wires two companies, while the check reads each filing.
- **One joint check for #408 and #412** (pick whichever of four presentations the total fits best). Cleaner on paper; today no company has both a current portion inside its short-term line and separate paper, so the two checks never meet. Kept separate so #408's verdicts stay byte-identical; a company with both would be judged correctly on paper by this rule only if #408 is right first (named in the limits below).

**Limits.** Exxon tags only the total at quarter ends, so a quarter-end run still carries the year-end parts beside a quarter-end non-current figure, mixing two dates (e.g. at 2020-06-30 the parts counted add to 20.5bn against a filed total of 23.0bn); and before February 2011 Exxon's parts were not yet filed, only its total. Both need a separate rule (a total when the parts are older or missing), filed as a follow-up. A company whose current portion sits inside its short-term line *and* whose paper is a separate line could still be counted twice when the current portion is under half the paper (#408 then says "not inside"); no Phase 1 company does both (JNJ never tags paper on the same date as its short-term line), so it goes to the follow-up with a property test.

## Design review (nov.16.2026)

- **Analyst, NO-GO, one blocker, taken.** P&G at 2019-06-30: the 2018 bank loans carried forward pushed out that year's 6,183M of paper with no note (stored runs `PG_2019-09-01_1`, `PG_2019-10-01_1`). Fixed as proposed: the check is made at the paper's date with an older short-term figure counted as zero, and that figure is left out when it holds (Step 1, tests). Confirmed no double count for the other six companies (none tags `DebtCurrent` beside a short-term line), and that #408 can't misfire when the paper is above zero. Ideas filed (follow-up issue): Exxon's quarter ends mix two dates; Exxon before Feb 2011 has only the total; the #408 + #412 double count on paper (property test); a note when paper is dropped because a short-term line exists (Microsoft, Coca-Cola, Walmart).
- **Professor, GO, no blockers.** Defensible (Koller, Goedhart and Wessels count every claim and keep short-term debt out of operating working capital; Penman classes commercial paper as a financial obligation; the taxonomy's `ShortTermBorrowings` doesn't say whether paper is inside, so a data test is needed). Taken: the lesson says the cost-of-debt effect comes from Warren's interest-over-average-debt method; it cites the "Reorganizing the Financial Statements" chapter; it says Warren *assumes* paper is part of the loans when there is no total. Filed: the XBRL calculation linkbase as direct evidence; showing the parts adding up to the total in the app.
- **Explainer.** Gaps taken: how "with and without" was measured, which date `on` is called with, that stored runs are not re-judged (they rebuild through their own maps), what working capital takes out, the strict inequality in (b), that "without" includes the current portion, the test list. Not taken: glosses of other items and of text kept in code (the catalogue reads it there); the branch and file names differ by design (the branch was named before the scope widened to Exxon).
- **Product lead, no blockers.** Taken: Q1 and Q2 served through the reported view; the note's place in group 2 after #408's; Spanish needs (a label for `balance:commercial_paper`, a variant for a zero part); the "Hoy" line (the brief still says 5); the size of the change in the team-sync entry; the quarter-end limit is not explained with the app's own numbers.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/reported.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `.md`; `tests/analysis/test_paper_beside.py`; `docs/build-plan.md` (D3 wording and risk row); on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8, value per share), Q1 and Q2 through the reported view's `net_debt`, and Q4 (where each part of the WACC comes from: Exxon's and P&G's cost of debt and debt weight move): fresh Exxon and P&G runs count commercial paper they listed apart. Stored runs keep their rows.

- **Added:** run-note code `commercial_paper_beside_short_term`, group `data` ("Los datos de partida"), params `period_end` (ISO), `commercial_paper`, `short_term_borrowings`, `debt_current`, `debt_current_total` (unscaled amounts in `currency`, shown in millones de US$), `currency`, `accession_no` (the commercial paper's filing, for a link) and `assumptions` (`["debt", "cost_of_debt", "nwc_pct"]`), and its lesson (no params).
- **Reported view:** the `net_debt` ratio carries the same code with the same params except `assumptions`; group 2 of the reported-figure notes, after `debt_current_inside_short_term`; its `formula` text changes (now names commercial paper beside short-term borrowings).
- **Changed on a run that carries the note:** a `balance:commercial_paper` row beside `balance:short_term_borrowings`; the `debt` row's method names the check; the `history:nwc` rows of years whose year end has paper beside name it too.
- **Two runs of the same date.** Runs now record reading rules v7. Every stored Exxon and P&G run has no recorded version, so beside a fresh one it is the brief's "Either version NULL" case.
- **On a quarter-end Exxon run** the year-end parts are carried, and they won't add up to that quarter's own total (e.g. 20.5bn against 23.0bn at 2020-06-30); the app should not try to explain that gap with its own numbers (brief, the reading-rules section).
- Nothing renamed or removed. For the front-end team: the code and lesson in the Spanish catalogue (#344's list), a line label for `balance:commercial_paper` ("Papel comercial", also in `balance_carried_forward`'s items), and a sentence variant when `short_term_borrowings` or `debt_current` is 0 (P&G 2017 and 2019); the brief's "Hoy" line on the current rules version moves to 7 (it still says 5; v0.9.78 moved it to 6).

## Results (Step 2, nov.16.2026)

On the restored snapshot (`warren-20261116T053654Z`; no ingest needed, #408's ingest already holds every `DebtCurrent` fact):

- **Stored runs.** `reproduce --all --rebuild`: 903 of 903 reproduced to the cent; 692 of 903 rebuilt to identical rows, the same count as on `main` (#408); the other 211 were made by older code and differ from today's rebuild as before. No stored run moves, by design: each rebuilds through its own map, which never read `DebtCurrent`.
- **Fresh runs.** Every stored run date of all eight companies (899) built twice in memory, same pinned market data and choices, with and without the check; none stored. Every moved debt carries the note. Apple, Microsoft, Coca-Cola, Johnson & Johnson, Caterpillar and Walmart: nothing moves on any date.

| Runs dated | Runs | Debt moves | Commercial paper added | Cost of debt (year's last run) | Value per share |
|---|---|---|---|---|---|
| Exxon 2019 | 12 | 12 | 12.9bn | 2.90% → 1.94% | −1.2% to −0.1% |
| Exxon 2020 | 16 | 16 | 12.9bn to 18.6bn | 3.12% → 1.96% | −0.4% to +6.9% |
| Exxon 2021 | 14 | 14 | 17.3bn to 18.6bn | 2.95% → 2.02% | −38.7% to +4.1% |
| Exxon 2022 | 14 | 14 | 1.6bn to 17.3bn | 1.96% → 1.64% | −21.3% to −1.9% |
| Exxon 2023 | 15 | 15 | 0.1bn to 1.6bn | 1.83% → 1.80% | −2.1% to −1.1% |
| Exxon 2024 | 14 | 14 | 0.1bn | 2.06% → 2.05% | −1.2% to 0.0% |
| Exxon 2025 | 14 | 2 | 0.1bn | 2.39% → 2.39% | −0.1% to 0.0% |
| Exxon 2026 | 1 | 1 | 3.1bn | 1.47% → 1.42% | −0.3% |
| P&G 2019 | 13 | 10 | 5.4bn to 7.8bn | 1.91% → 1.66% | −1.4% to +0.2% |
| P&G 2020–2021 | 28 | 0 | | unchanged | −0.1% to +0.4% (working capital and cost of debt of history years only, on 23 runs) |
| P&G 2022–2026 | 73 | 0 | | unchanged | unchanged |

For example, Exxon as of 2020-04-01: debt $28.3bn → $46.8bn, cost of debt 3.12% → 1.96%, value per share $95.22 → $99.83; as of 2021-03-01: debt $50.3bn → $67.6bn, value per share $7.47 → $4.87; P&G as of 2019-04-01: debt $24.1bn → $31.8bn, $84.23 → $83.82; as of 2019-10-01 (the case the analyst found): $24.6bn → $30.0bn, value per share −1.4%.

Two effects pull against each other. More debt is subtracted from enterprise value, which lowers value per share; but the cost of debt is interest divided by average debt, and Exxon's interest already paid for the commercial paper, so with the paper counted the cost of debt falls by about a point, the WACC falls, and enterprise value rises. Where Exxon's equity value is small (2021, after its 2020 loss), $17bn more debt is a large share of it, hence −39%. In 2020 the lower WACC wins, hence up to +7%. Both are the arithmetic of counting debt the filing shows; neither is a forecast of the price. Revenue and EBIT forecasts don't read debt, so the forecast-error scores (M3, M8, M9, M10's batch) don't move.

## Gatekeeper (nov.16.2026)

First pass NO-GO, one blocker, fixed: the new reading-rules row said Exxon meets the check at every year end 2009 to 2025 and "at their shared date"; it now names 2010 to 2023 and 2025 and the paper's date (the row was not yet merged, so the append-only rule wasn't broken). Taken: working capital no longer lists a left-out older short-term figure in its sources or method. Checks: 2,386 passed, ruff clean, 903 of 903 reproduce and 692 rebuild identical, point-in-time reads only through `History.on` and the as-of query; an independent run of the check on every paper date agreed with Step 1. Follow-ups are in #415.

Re-check on `5319a14`: GO, no blockers: 2,387 passed, 10 skipped, ruff clean; the row's fingerprint `ec6caca2994f` matches v7; `PG_2019-10-01_1` reproduces to the cent and rebuilds identical.
