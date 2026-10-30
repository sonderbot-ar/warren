---
name: "warren-run-track"
description: "Act as Warren's Elephant developer: pick the next milestone or backlog item in sonderbot-ar/warren and take it from design doc to merged version."
---

# Run a Warren track (Elephant)

The owner has delegated building and merging to the agent team (Structure Guide Decision 10). Follow the loop in `CLAUDE.md`. The repo docs are the team's memory, so read them first and keep them current.

## 1. Pick

- Read `CLAUDE.md`, `docs/build-plan.md` (Section 2 has the status) and `docs/versions.md`.
- List the open PRs and the open issues labelled `backlog`. Finish an open track before starting a new one.
- Take the next milestone whose dependencies are Done. If none is ready, take the backlog issue that unblocks the most. Independent milestones may run in parallel threads, but only one thread per track.

## 2. Design

- Create the branch: `m<n>-<short-name>` for a milestone, `backlog-<issue>-<short-name>` for a backlog item.
- Write `docs/designs/<milestone>-<name>.md` with: the problem; the plan as Step 0, Step 1 and so on, each with its tests and exit criterion; the alternatives considered; and the files to change. Mark the milestone "In progress" in the build plan.
- Run the `warren-goldfish-review` skill (design review). Fix gaps, or reject an objection with a reason.
- If a trigger in `CLAUDE.md` is hit, send the owner one decision card with a recommendation. Keep working on the parts the card doesn't affect.

## 3. Build

- One focused commit per step, with tests in every step. Run `python -m pytest -q`, `ruff check .` and `ruff format --check .` before each push.
- Never skip, disable or weaken a test to get green. LLMs never produce financial numbers. Every query is point-in-time.
- Open the PR to `main`, subscribe to its activity, and fix CI failures.

## 4. Review and merge

- When CI is green, run the gatekeeper with `warren-goldfish-review`. A NO-GO goes back to step 3.
- On GO: merge with a merge commit. Add the version to `docs/versions.md`, mark the build plan status Done and record any decision changes, all in a small follow-up commit or the next PR.
- Run `warren-desk-report` for the desk entry and the lesson.

## 5. Next

Go back to step 1 while usage lasts. When usage runs out, stop cleanly: push the work in progress, and leave a note in the design doc saying where the work stopped. The next scheduled run continues from there.