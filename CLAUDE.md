# CLAUDE.md

Guidance for Claude Code and any other coding assistant working in this repository.

## Read first

1. `docs/structure-guide.md`: what Warren is, and every design decision with its status (Accepted, Under review, Superseded, Out of scope). Source of truth for decisions.
2. `docs/build-plan.md`: the Phase 1 milestones, their order, tasks and exit criteria. Source of truth for sequencing and status.

If the two disagree, the Structure Guide wins on decisions and the Build Plan wins on sequencing.

## Standing rules

- **No code changes without the owner's explicit command.** Proposing a change is fine; writing or editing code is not, until asked.
- **The owner is the human in the loop (HITL) for every merge.** Warren is a learning project and a personal research tool, so the owner reviews all code before it reaches `main`. Assistants commit only to the milestone branch. When a milestone is done, they may push that branch and open a PR to `main`. They never approve or merge a PR, and never commit or push to `main`. The owner reviews and merges every PR.
- Work one milestone at a time, in the order of the Build Plan, and only start a milestone when told to.
- Warren analyses fundamentals. It never predicts stock prices.
- LLMs never produce financial numbers. They propose structured assumptions; deterministic, tested code (`financial_math.py`) computes every number.
- Every data query that feeds an analysis is point-in-time (`as_of`), so nothing uses information that was not public yet.

## Milestone workflow

Unless the owner overrides it, every milestone follows these steps:

1. **Plan.** Read the milestone in `docs/build-plan.md` and check the repo's actual state. Then propose a plan made of named, numbered steps (Step 0, Step 1, …) with the tests and exit criterion for each. Flag any mismatch between the docs and the repo.
2. **Ask.** List the open decisions that are the owner's to make, each with a recommendation.
3. **Wait for the trigger.** Write no code and make no repo changes until the owner says **"go M<n>"** (e.g. "go M1"). Answering the open decisions is not the trigger.
4. **Execute.** Work through the steps in order on a branch named `m<n>-<short-name>`, making one focused commit per step. Update the milestone's status in the build plan when it starts ("In progress") and when it meets its exit criterion ("Exit criterion met, PR open"). A milestone is **Done** only once its PR is merged; the owner, or the next milestone's Step 0, records that.
5. **Report.** Show the test results, what changed and any deviations from the plan. Push the milestone branch and open a PR to `main`, or hand over a draft PR description if a PR can't be opened. Then stop. The owner reviews and merges the PR, and the next milestone's plan is proposed only when the owner asks for it.

## Keeping the docs current

- The Markdown files in `docs/` are the only editable copies. PDFs are exports and are never edited.
- When a design decision is made, changed or dropped, update `docs/structure-guide.md`: edit the decision's section and add or update its row in the decision log with a date and status. Superseded decisions stay listed.
- When a milestone starts, meets its exit criterion, or is merged, update its status in `docs/build-plan.md` (Section 2). Done means merged.
- Commit doc changes with the code change they describe, or on their own, never silently.
