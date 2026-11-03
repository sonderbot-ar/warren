# Backlog #119: one import path for the day-end rule

Issue: https://github.com/sonderbot-ar/warren/issues/119 · Branch `backlog-119-known-by` · Version v0.9.1 when merged.

## Problem

From the gatekeeper's review of #118 (backlog #112):

1. Backlog #112 moved `known_by` and `CASE_TZ` into `shared_kernel/calendar.py` but kept a re-export in `domains/news/gdelt.py` so no caller had to change. The orchestration report, the shock proposer, the event clusterer, the pipeline nodes, the evaluation harness, the news report and the news store still reach the day-end rule through the news adapter. That keeps a needless dependency on the news adapter (Decision 11, guardrail 1: a source's adapter is its own) and hides where the rule lives.
2. In `domains/orchestration/nodes.py` (`load_market`), `fetched < known_by(as_of)` can no longer be true: `market.store.require_coverage` raises first for such a download (backlog #112), and that path is already handled as stale. Only the `--refresh` part still does anything.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. Import from the kernel, drop the dead check.** Every caller imports `known_by` and `CASE_TZ` from `shared_kernel.calendar`; `gdelt.py` imports them only for its own use (the `# noqa: F401 (re-exported)` goes, `gdelt.known_by` still resolves because `window_bounds` uses it, so the existing identity test keeps passing unchanged). `load_market` keeps `stale = refresh and fetched < started_at`, with a comment saying why the day-end comparison is gone. `docs/designs/m7-orchestration.md` names `shared_kernel.calendar.known_by`. Tests: unchanged and green (the pipeline's day-end boundary tests from #112 still pass through `require_coverage`). Exit: ruff and the full suite green; no stored number changes, since no rule changed.

## Alternatives considered

- *Remove `known_by` from `gdelt`'s namespace entirely.* Not possible without inlining it, since `window_bounds` uses it; and the issue says tests stay as they are.
- *Keep the redundant check as a belt-and-braces guard.* Rejected: a condition that can't be true reads as if it could, which misleads the next reader; `require_coverage` is the one rule and it is tested at the boundary.

## Files to change

`domains/news/gdelt.py`, `domains/news/{cluster,report,store}.py`, `domains/llm/propose.py`, `domains/evaluation/harness.py`, `domains/orchestration/{nodes,report}.py`, `docs/designs/m7-orchestration.md`; at merge `docs/versions.md`.
