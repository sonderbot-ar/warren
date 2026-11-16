# Backlog #412: commercial paper left out beside short-term bank loans

Issue: https://github.com/sonderbot-ar/warren/issues/412 (from the #408 design review) · Branch `backlog-412-pg-commercial-paper` · Version v0.9.79 (to be recorded on merge).


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

- **Step 1. Judge from the filing's own total, as #408 does (companies as data, Decision 11).** Commit `82aa98c`.
  - `math_engine.paper_beside(short_term, paper, on, inside)`: at the short-term figure's date, with commercial paper dated the same day and above zero, the filing's `DebtCurrent` total (map item `debt_current_total`, added by #408, never counted) is (a) strictly nearer short-term borrowings + the current portion + commercial paper than the same without commercial paper (a tie is not beside), and (b) within half the commercial paper of the sum with it (a total that fits neither sum is a broken or differently built figure, not evidence). The current portion is the one dated that day, zero when there is none or when #408 found it inside short-term borrowings. No tolerance to tune. On real data it holds at 15 of Exxon's 17 year ends (2010 to 2023 and 2025: 0M off the sum with paper at ten of them, 2M to 762M at the others, always nearer than without it; 2009's total, 2,476M, fits neither sum, 1,591M or 1,391M, so (b) keeps today's reading; 2024 has no paper) and at P&G's two (90M and 173M off, against 7,761M and 11,705M without). It never holds for Microsoft, Coca-Cola or Walmart (no total).
  - When it holds, `debt_parts` counts commercial paper beside short-term borrowings (row `balance:commercial_paper`, debt row method says why); `_operating_nwc` takes it out of current liabilities too (history row method says why); the cost of debt reads `debt_parts` at each year end, so it follows. Without the total, nothing changes: commercial paper counts only in place of short-term borrowings.
  - A quarter-end run carries the year-end parts forward (Exxon tags only the total at quarter ends), and the year-end judgement goes with them, as #408's does.
  - Run note `commercial_paper_beside_short_term` (group `data`; params `period_end` (ISO, the date judged), `commercial_paper`, `short_term_borrowings`, `debt_current` (the current portion counted that day, 0 if none), `debt_current_total` (unscaled, in `currency`), `currency`, `accession_no` (the commercial paper's filing), `assumptions` (`["debt", "cost_of_debt", "nwc_pct"]`)) and its lesson in `text.WARNING_LESSONS`. The reported view (`reported._net_debt`) reads debt through `debt_parts`, so it agrees, and carries the same code with the same params but `assumptions`; its formula text names the rule.
  - `READING_RULES_VERSION` 6 → 7, with its row in `domains/analysis/reading_rules.md`. A rebuild through a map made before `debt_current_total` existed doesn't read the total, so stored runs rebuild as before.
  - Tests (`tests/analysis/test_paper_beside.py`, 16): beside bank loans (debt 280, not 210; row, method, note params); a short-term line of zero beside paper (P&G 2017); paper inside short-term borrowings is not added (Microsoft's case); no total, no change; paper alone still counts in place of borrowings; history working capital takes the paper out; a year-end judgement carried to a quarter; P&G 2018 and Exxon 2019 figures; four edge cases (no paper, a tie, paper dated apart, a total far above both sums); code and lesson catalogued; the reported view agrees; a map without the check item reads as before.
  - Exit: full suite and ruff clean.

- **Step 2. Real data.** On the restored snapshot (`warren-20261116T053654Z`, which already holds every `DebtCurrent` fact from #408's ingest): `reproduce --all --rebuild`: every stored run reproduces to the cent and rebuilds as before through its own map. Build every stored run date of P&G and Exxon fresh (same pinned market data and choices) with and without the check, none stored, and list what moves. The other five companies tag no `DebtCurrent` (#408's ingest), so they cannot move. Exit: only Exxon and P&G move, each moved debt carries the note.

## Alternatives considered

- **Always count commercial paper beside short-term borrowings.** Double counts Microsoft, Coca-Cola and Walmart, whose paper is inside the short-term line.
- **Count it beside when paper is larger than short-term borrowings.** Paper larger than the line that would hold it can't be inside it, but Microsoft's two lines differ only by rounding (25,100 vs 25,065 at 2016-12-31), so a size test needs a tolerance and still guesses.
- **Use `DebtCurrent` itself as the whole current debt.** It would also fix Exxon's quarter ends, where only the total is tagged (follow-up below), but it would replace three traced lines with one, and the parts are what a student reads; most companies don't tag it.
- **A company-scoped concept map row** (#341's `companies` column) mapping Exxon's bank loans elsewhere. Hard-wires two companies, while the check reads each filing.
- **One joint check for #408 and #412** (pick whichever of four presentations the total fits best). Cleaner on paper; today no company has both a current portion inside its short-term line and separate paper, so the two checks never meet. Kept separate so #408's verdicts stay byte-identical; a company with both would be judged correctly on paper by this rule only if #408 is right first (named in the limits below).

**Limits.** Exxon tags only the total at quarter ends, so a quarter-end run still carries the year-end parts (e.g. at 2020-06-30 the parts counted add to 20.5bn against a filed total of 23.0bn). That is a separate rule (using a quarter's own total), filed as a follow-up.

## Design review

To be filled in after the explainer, analyst, professor and product lead.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/reported.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `.md`; `tests/analysis/test_paper_beside.py`; `docs/build-plan.md` (D3 wording and risk row); on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves the estimate questions of `docs/product/brief.md` (Q3, Q5, Q8, value per share) and Q4 (where each part of the WACC comes from: Exxon's and P&G's cost of debt and debt weight move): fresh Exxon and P&G runs count commercial paper they listed apart. Stored runs keep their rows.

- **Added:** run-note code `commercial_paper_beside_short_term`, group `data` ("Los datos de partida"), params `period_end` (ISO), `commercial_paper`, `short_term_borrowings`, `debt_current`, `debt_current_total` (unscaled amounts in `currency`, shown in millones de US$), `currency`, `accession_no` (the commercial paper's filing, for a link) and `assumptions` (`["debt", "cost_of_debt", "nwc_pct"]`), and its lesson (no params).
- **Reported view:** the `net_debt` ratio carries the same code with the same params except `assumptions`; group 2 of the reported-figure notes; its `formula` text changes (now names commercial paper beside short-term borrowings).
- **Changed on a run that carries the note:** a `balance:commercial_paper` row beside `balance:short_term_borrowings`; the `debt` row's method names the check; the `history:nwc` rows of years whose year end has paper beside name it too.
- **Two runs of the same date.** Runs now record reading rules v7. Every stored Exxon and P&G run has no recorded version, so beside a fresh one it is the brief's "Either version NULL" case.
- Nothing renamed or removed. For the front-end team: the code and lesson in the Spanish catalogue (#344's list); the brief's "Hoy" line on the current rules version moves from 6 to 7.

## Results (Step 2)

To be filled in.
