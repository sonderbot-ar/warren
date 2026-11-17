# Backlog #419: the debt-note lessons say why working capital moves with short-term debt

Issue: https://github.com/sonderbot-ar/warren/issues/419 (front-end request, from the student reviewer on PR #418) · Branch `backlog-419-debt-lesson-clause` · Version v0.10.3 (patch, backlog item).

## Problem

Three run-note lessons (`domains/analysis/text.py`) say that reading short-term debt differently moves working capital: `debt_current_inside_short_term` (#408: "Counted twice, it would overstate debt and working capital"), `commercial_paper_beside_short_term` (#412: "Left out, the paper would understate debt and working capital") and `debt_current_total_in_place` (#415: "old or missing pieces would misstate debt, working capital and the cost of debt"). A finance student has learnt that financial debt stays out of operating working capital, so they cannot see why debt would move it, and the lesson reads as a contradiction.

The reason is in Warren's own formula (`math_engine._operating_nwc`): operating working capital is (current assets − cash − marketable securities − other short-term investments) − (current liabilities − current portion of long-term debt − short-term borrowings or commercial paper). Short-term debt is taken *out* of current liabilities, so the more of it Warren counts, the smaller the operating liabilities and the higher working capital is. The front-end's Spanish may say no more than the English (gatekeeper rule on the brief), so the clause has to come from the engine first.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).
- **Step 1. One clause in each of the three lessons.** After "working capital", in parentheses: "(Warren's working capital holds only operating items, so it takes short-term debt, which finances the company, out of the current liabilities: the more debt Warren counts, the higher working capital is)". The issue names the first two; the third (#415) makes the same claim with the same gap, so it gets the same clause. Each lesson stays two sentences (the clause sits inside the second), keeps its params (none), group, reference and Warren-rule line.
  - Tests (`tests/analysis/test_warning_lessons.py`):
    - each of the three lessons holds the clause word for word;
    - the clause holds when #415's total stands in for older pieces: a total 20 higher gives working capital 20 higher (analyst);
    - the clause is what the engine does: on one balance sheet, `_operating_nwc` with commercial paper counted beside the bank loans (#412, a `DebtCurrent` total of 10 + 20 + 70) gives working capital 70 higher than with the paper read inside the loans (no total), and the existing one-or-two-sentence, no-code-names test still passes.
  - Exit: full suite, `ruff check .` and `ruff format --check .` clean.

## Alternatives considered

- **A separate sentence instead of a parenthesis.** Breaks the lessons' one-or-two-sentence rule (`test_lessons_are_one_or_two_plain_sentences_with_their_params`) for two of the three. Rejected.
- **Say it once in the `data` group's text.** Groups have names, not lessons (`WARNING_GROUPS`); a student opens one note's lesson, not the group's. Rejected.
- **Only the two lessons the issue names.** Leaves #415's lesson with the same puzzle on the dates where it replaces the other two. Rejected.

## Files to change

`domains/analysis/text.py`, `tests/analysis/test_warning_lessons.py`, this doc; after merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

- **Serves:** brief Q3, Q4, Q5 and Q8 (the notes under "Los datos de partida" and in the side panel of `debt`, `cost_of_debt`, `nwc_pct`), and Q1 and Q2 through `net_debt` (the reported view carries the same codes and shares the lessons; there no working capital is shown, so the clause explains a figure that is not on that screen, acceptable because the lesson is one per code).
- **Changed:** the English `why` of the three lessons above; no code, param, group, reference, value, run or note changes; nothing renamed or removed.
- **For the front-end:** the brief's three hand-written Spanish lessons (`docs/product/brief.md` lines 158 and 159, "When short-term debt is counted once, or beside the bank loans", and line 167, "When the report's own total stands in for the pieces") may now add the same clause, e.g. "(el capital de trabajo de Warren solo incluye partidas operativas, así que resta de los pasivos corrientes la deuda de corto plazo, que financia a la empresa: cuanta más deuda cuenta Warren, más alto sale el capital de trabajo)". That is a front-end edit.
- **Breaks:** nothing. No stored output holds a lesson's text.

## Review notes

Design review, nov.17.2026:

- **Explainer.** The first wording ("takes short-term debt out of the current liabilities") never said *operating* working capital nor why debt is left out, so a student who reads working capital as current assets minus current liabilities sees the direction backwards. **Accepted:** the clause now says Warren's working capital holds only operating items and that short-term debt finances the company.
- **Analyst: GO.** Checked every path of `_operating_nwc` (base, total in place, older short-term line left out, counted once, paper beside): the clause holds in each, and each lesson's overstate / understate / misstate agrees. Suggested a test on the total-in-place path: **accepted** (Step 1). Noted that the reported view shows these lessons without a working capital figure: **accepted as is** and written under *Product impact*; one lesson per code.
- **Product-lead: GO.** Asked for the brief's lessons by line and a Spanish sample with a clear subject: **accepted**, both above. Asked the *Serves* bullet to say Q1 and Q2 show no working capital: **accepted**.
- Gatekeeper at the PR.
