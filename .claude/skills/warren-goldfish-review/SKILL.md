---
name: "warren-goldfish-review"
description: "Run Warren's fresh-context review panel (explainer, analyst, professor, gatekeeper) on a design doc or pull request in sonderbot-ar/warren."
---

# Warren Goldfish review

Goldfish reviewers start with no memory of how the change was designed, so they don't share the author's blind spots. Run them as subagents, each with only the design doc or the PR diff plus the repo docs. Never pass them the design discussion. Where `.claude/agents/` is loaded, use the defined agents `explainer`, `analyst`, `professor` and `gatekeeper`, which carry each role's model and tools.

## When

- **Design review:** after the Elephant writes `docs/designs/<milestone>-<name>.md`. Run explainer, analyst and professor in parallel.
- **PR review:** after CI is green. Run the gatekeeper. Add the analyst when the PR changes financial logic.
- Never on every push. Twice per item at most.

## Shared brief for every reviewer

- Read `CLAUDE.md`, the relevant milestone in `docs/build-plan.md`, and the decisions it touches in `docs/structure-guide.md`.
- Read only. Never edit, commit, push or switch branches. If the code must be checked out, use a git worktree.
- Every objection cites evidence: a file and line, a test, a command's output, a filing, a published source, or a doc section. Drop any objection without evidence.
- Sort findings into BLOCKERS (wrong numbers, failing tests, data loss, look-ahead past `as_of`, an LLM producing a financial number, a broken invariant, a doc that contradicts the code) and IDEAS (everything else).
- Answer in 500 words or fewer.

## Roles

- **Explainer** (lighter model is fine): restate the design in plain language in 150 words. List every point where you had to guess. Each guess is a gap in the doc.
- **Analyst** (strongest model): would a practitioner compute it this way? Test the method against real Phase 1 companies (AAPL, MSFT, KO, JNJ, XOM, PG, CAT, WMT…). Look for cases where it gives a wrong number silently. Cite textbook or filing practice.
- **Professor** (strongest model): is the method defensible in the literature (name the source)? Is the output explainable to a finance student? Flag scope creep. The student-facing environment is out of Phase 1, so ideas for it are IDEAS, never blockers.
- **Gatekeeper** (strongest model): run `python -m pytest -q`, `ruff check .` and `ruff format --check .`. Check that migrations are safe on an existing database, that the point-in-time rule holds, and that docs match the code (build plan status, decision log). End with **GO** or **NO-GO**.

## After the review

- Blockers go back to the Elephant to fix. Re-run only the reviewer that raised them.
- Each IDEA becomes a GitHub issue labelled `backlog`, citing the PR and the evidence. End the issue body with the Claude Code footer.
- Post a short comment on the PR with the verdict, test counts and blockers (or "none"), ending with the Claude Code footer.
- Escalate to the owner only for the triggers in `CLAUDE.md`: goal or scope, an Accepted decision, money, or anything irreversible.