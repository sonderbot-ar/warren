# Backlog #133: tests that pin the day-end rule to its one home

Issue: https://github.com/sonderbot-ar/warren/issues/133 · Branch `backlog-133-day-end-tests` · Version v0.9.2 when merged.

## Problem

From the gatekeeper's review of #131 (backlog #119, GO):

1. `tests/shared_kernel/test_calendar.py` checked `gdelt.known_by is calendar.known_by`, and two tests in `tests/news/test_gdelt.py` called `gdelt.known_by`. After #119 removed the re-export, these pass only because the news adapter imports the rule for its own use. Nothing stops a module from borrowing the rule through another module again.
2. Since #119, `load_market` in `domains/orchestration/nodes.py` has no day-end check of its own and relies on `market.store.require_coverage`. A comment says so; no node-level test pins it.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1. The tests, and the one leak they found.** In `tests/shared_kernel/test_calendar.py`: an AST scan over `main.py`, `domains/` and `shared_kernel/` that fails on any `from X import known_by/CASE_TZ` where X is not `shared_kernel.calendar`, and on any attribute access `<module>.known_by` / `<module>.CASE_TZ` other than `calendar.`; a check that the scan sees the kernel and its users (so an empty scan can't pass); and a check that a news window ends at `calendar.known_by(as_of)` in summer and winter, replacing the identity check. `tests/news/test_gdelt.py` calls `calendar.known_by` directly. The scan found one leak #119 missed: `domains/llm/extract.py` took `CASE_TZ` as `cluster.CASE_TZ` (three default arguments); it now imports it from the kernel. In `tests/orchestration/test_nodes.py`: a spy on `require_coverage` shows that every fetch id `load_market` returns was handed back by `require_coverage` for the run's as-of date, one per market series. Checked by mutation: with the leak put back the scan fails; with `load_market` reading `selected_fetch` instead of `require_coverage`, the new node test (and the two boundary tests) fail. Exit: ruff and the full suite green; no number changes.

## Alternatives considered

- *Grep instead of an AST scan.* Rejected: it would match comments and docstrings, and miss an aliased import.
- *Make `gdelt` hide the names (`del` after use, or `__all__`).* Rejected: `__all__` doesn't stop `gdelt.known_by`, and hiding names makes the adapter harder to read for no gain the scan doesn't give.

## Files to change

`tests/shared_kernel/test_calendar.py`, `tests/news/test_gdelt.py`, `tests/orchestration/test_nodes.py`, `domains/llm/extract.py`; at merge `docs/versions.md`.
