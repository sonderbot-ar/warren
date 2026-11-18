# Backlog #455: the rounding note's lesson says the long-term debt also has leases

Issue: https://github.com/sonderbot-ar/warren/issues/455 (front-end request, from the gatekeeper on PR #454) · Branch `backlog-455-rounding-lesson-leases` · Version v0.10.6 (planned).

## Problem

The English lesson of the run note `debt_current_within_rounding` (`domains/analysis/text.py`, `WARNING_LESSONS`) says Warren read the precise figure with leases because it "matches how the company states its long-term debt". It does not say *how* the long-term debt is stated. The brief's Spanish (PR #454) now says it: "se presenta igual que la deuda de largo plazo de la empresa, también con arrendamientos". The front-end's Spanish may say no more than the English (gatekeeper rule on the brief), so the English must say it too.

The clause is true by construction: `facts.current_on_noncurrent_basis` (`domains/fundamentals/facts.py`) takes a lease-inclusive current figure below a rounded plain one only when `lease_inclusive(noncurrent)`, that is, when the long-term debt's own tag includes finance (capital) leases.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).
- **Step 1. One clause in the lesson.** "…which fits inside that range and matches how the company states its long-term debt (also with leases)." The lesson stays two sentences, keeps its params (none), group, reference and Warren-rule line.
  - Tests (`tests/analysis/test_warning_lessons.py`):
    - the lesson holds the clause word for word;
    - the clause is what the engine does: with a plain current figure of 6,200M ("$6.2 billion") and a lease-inclusive 6,180M, `current_on_noncurrent_basis` reads 6,180M beside a lease-inclusive long-term debt tag and 6,200M beside a plain one;
    - the existing one-or-two-sentence, no-code-names test still passes.
  - Exit: full suite (2,597 passed, 10 skipped), `ruff check .` and `ruff format --check .` clean.

## Alternatives considered

- **Name the tag ("finance leases").** "Leases" is the word the lesson's first sentence already uses ("the lease payments due in that year"), and the brief's Spanish says "arrendamientos". Rejected: a second word for one thing.
- **A separate sentence.** Breaks the one-or-two-sentence rule. Rejected.

## Files to change

`domains/analysis/text.py`, `tests/analysis/test_warning_lessons.py`, this doc; after merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

- **Serves:** brief Q3, Q4, Q5 and Q8 (the "Los datos de partida" notes and the side panel of `debt`, `cost_of_debt`, `nwc_pct`).
- **Changed:** the English `why` of `debt_current_within_rounding`; no code, param, group, reference, value, run or note changes; nothing renamed or removed.
- **For the front-end:** none needed; the brief's Spanish already says it (PR #454). The English and Spanish now agree.
- **Breaks:** nothing. No stored output holds a lesson's text.

## Review notes

Design review, nov.18.2026:

- **Explainer.** Restated the change correctly. Listed eight places where the lesson as a whole makes a student guess (what "debt due within a year" is, why a lower figure points to rounding, "last digit" vs "rounding unit", trailing zeros, "by little" unquantified, internal rule names in the source line). **Rejected for this item:** all but one are about wording that predates #455 and that the brief's Spanish already settles for students (PR #454); widening the lesson would break its two-sentence rule and is a separate request. On the clause itself (it doesn't name the tag): "leases" is the word the lesson already uses, and a tag name is a code name the lesson rules forbid (`test_lessons_are_one_or_two_plain_sentences_with_their_params`). The design-doc gap (the condition) is answered under *Problem*, second paragraph.
- **Analyst: GO.** Only `facts.current_on_noncurrent_basis` sets `rounded_plain` (`domains/fundamentals/facts.py`, inside the `lease_inclusive(noncurrent)` branch), and the note is emitted only from it (`math_engine.py` around 1165–1185); the total-in-place and inside-short-term paths clear the current portion before the note. Suggestion: on a carried-forward balance the current portion's date can be earlier than the long-term debt the run uses, so "states" is true at the note's own `period_end`, not necessarily at the run's balance date. **Accepted as is:** the note carries that `period_end` and the app shows it beside the lesson; no filing in Warren's data trips the margin today (`reading_rules.md`). Recorded on #451 with the other rounding-note follow-ups.
