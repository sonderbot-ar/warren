# CLAUDE.md

Guidance for Claude Code and any other coding assistant working in this repository.

## Read first

1. `docs/structure-guide.md`: what Warren is, and every design decision with its status (Accepted, Under review, Superseded, Out of scope). Source of truth for decisions.
2. `docs/build-plan.md`: the Phase 1 milestones, their order, tasks and exit criteria. Source of truth for sequencing and status.

If the two disagree, the Structure Guide wins on decisions and the Build Plan wins on sequencing.

## Standing rules

- **No code changes without the owner's explicit command.** Proposing a change is fine; writing or editing code is not, until asked.
- Work one milestone at a time, in the order of the Build Plan, and only start a milestone when told to.
- Warren analyses fundamentals. It never predicts stock prices.
- LLMs never produce financial numbers. They propose structured assumptions; deterministic, tested code (`financial_math.py`) computes every number.
- Every data query that feeds an analysis is point-in-time (`as_of`), so nothing uses information that was not public yet.

## Keeping the docs current

- The Markdown files in `docs/` are the only editable copies. PDFs are exports and are never edited.
- When a design decision is made, changed or dropped, update `docs/structure-guide.md`: edit the decision's section and add or update its row in the decision log with a date and status. Superseded decisions stay listed.
- When a milestone starts or meets its exit criterion, update its status in `docs/build-plan.md` (Section 2).
- Commit doc changes with the code change they describe, or on their own, never silently.
