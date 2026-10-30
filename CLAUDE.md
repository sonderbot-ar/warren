# CLAUDE.md

Guidance for Claude Code and any other coding assistant working in this repository.

## Read first

1. `docs/structure-guide.md`: what Warren is, and every design decision with its status (Accepted, Under review, Superseded, Out of scope). Source of truth for decisions.
2. `docs/build-plan.md`: the Phase 1 milestones, their order, tasks and exit criteria. Source of truth for sequencing and status.

If the two disagree, the Structure Guide wins on decisions and the Build Plan wins on sequencing.

## How Warren is built (since oct.30.2026)

Warren is built by Claude agent teams that plan, review, merge and report on their own (Structure Guide Decision 10). The owner sets the goal, answers decision cards and reads reports. The owner no longer approves plans or merges PRs, and there is no "go M<n>" trigger.

**Teams**

- **Elephant (developers).** One long-running thread per track (a milestone, or a backlog item). It writes the design doc, the code and the tests, opens the PR, fixes failing checks and merges.
- **Goldfish (reviewers).** Subagents that start with no memory of the design discussion and see only the design doc or the PR. Roles: *explainer* (restates the design to prove it is clear), *analyst* (would a practitioner compute it this way, where does it break on real companies), *professor* (is the method defensible in the literature, can a student learn from it), *gatekeeper* (final go or no-go). Every objection cites a test, a file and line, a filing, a source or a doc section.
- **Reporters.** Write the desk entry and the lesson for each merged version, on a lighter model.

**The loop, for each item**

1. **Pick.** The next milestone in the Build Plan whose dependencies are Done, or the next backlog issue. Independent milestones (e.g. M3, M4, M5) may run as parallel tracks.
2. **Design doc.** On the track branch, in `docs/designs/<milestone>-<short-name>.md`: problem, plan as numbered steps (Step 0, Step 1, …) with tests and an exit criterion, alternatives considered, files to change.
3. **Design review.** Explainer, analyst and professor review in parallel. The Elephant accepts, rejects with a reason, or escalates.
4. **Escalate only on a trigger** (below). Otherwise continue without waiting.
5. **Build.** One focused commit per step, tests with every step. Open a PR to `main`.
6. **PR review.** CI must be green. The gatekeeper gives go or no-go; a no-go goes back to step 5. New ideas become GitHub issues labelled `backlog`, not additions to the PR.
7. **Merge, record, report.** Merge to `main` with a merge commit (so each step's commit stays visible), add the version to `docs/versions.md` (one minor version per milestone, patch versions for backlog items, each with its merge commit), update the Build Plan status, and post the desk entry and the lesson.

**What goes to the owner (decision card with a recommendation)**

- Any change to the Phase 1 goal, the company universe, or what is in or out of Phase 1.
- Changing or dropping an Accepted decision in the Structure Guide, or adding a new decision.
- Anything that costs money (paid API keys or services). Default is free tools only.
- Anything that cannot be undone: rewriting `main`'s history, force-pushing to `main`, deleting branches with unmerged work, making the repository public.

Work on other tracks continues while a card waits.

## Standing rules

- Warren analyses fundamentals. It never predicts stock prices.
- LLMs never produce financial numbers. They propose structured assumptions; deterministic, tested code (`financial_math.py`) computes every number.
- Every data query that feeds an analysis is point-in-time (`as_of`), so nothing uses information that was not public yet.
- Everything stays in this repository. Create as many branches as needed: `m<n>-<short-name>` for milestones, `backlog-<issue>-<short-name>` for backlog items.
- **Never merge with a failing check.** CI (`.github/workflows/tests.yml`: ruff and pytest) must pass. Never skip, disable or weaken a test to get green.
- A bad merge is undone with a revert PR, never by rewriting history.
- The invariants are tests: runs reproduce to the cent from stored assumptions, no data after `as_of`, property tests on `financial_math.py`. A change that needs to relax one is a decision for the owner.

## Reports for the owner

- **The desk:** one entry per merged version, newest first: what changed from the previous version and why it is better, the evidence (tests, reproduce check, from M3 on forecast error against the baseline), open arguments from the review, decisions waiting.
- **Lesson:** one page per version, teaching the version's concepts as they appear together in the code, with why they suit Warren or not.
- **Weekly digest:** versions shipped, what is next, anything waiting on the owner.

Plain language, short sentences. The owner reads reports, not code.

## Keeping the docs current

- The Markdown files in `docs/` are the only editable copies. PDFs are exports and are never edited.
- When a design decision is made, changed or dropped, update `docs/structure-guide.md`: edit the decision's section and add or update its row in the decision log with a date and status. Superseded decisions stay listed.
- Update a milestone's status in `docs/build-plan.md` (Section 2) when it starts ("In progress"), when its PR is open, and when it is merged ("Done").
- Commit doc changes with the code change they describe, or on their own, never silently.
