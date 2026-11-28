# Backlog #635: hindsight re-score tidy-ups (exit code, units, rows)

Issue: https://github.com/sonderbot-ar/warren/issues/635 · Branch `claude/project-thread-xgtprr` (the cloud run's assigned branch) · Version v0.10.62 when merged.

Status: Done (nov.28.2026). Merged as v0.10.62 in `b005c8f` (PR #638); gatekeeper GO; the stderr line's plural ("1 origins", the gatekeeper's nit) fixed in the record PR.

## Problem

The gatekeeper's GO on PR #634 (v0.10.61) left three notes. None changes a number.

1. `python -m domains.evaluation rescore` exits 0 when some origins fail to score, as long as one was re-scored, so a scheduled run would not notice a partial failure.
2. The report's "Not compared" list mixes counts of monthly origins and counts of quarter rows with no unit, so "282" could be read either way.
3. The comments on `Line.better`, `Line.worse` and `Line.moved_change` say "quarters"; they count rows (one quarter is forecast from several origins).

## Plan

**Step 0. This doc.**

**Step 1. The three fixes, one commit.**

- `Rescore.skipped` splits into `skipped_origins` and `skipped_rows`, filled by `skip_origin` and `skip_row`; the "origin: " prefix on reasons goes (the dict says it). The report's "Not compared" lists origins first, then rows, and every line ends with its unit ("2 origins", "1 quarter row"). The summary paragraph and the command's printed line say "quarter rows compared".
- `cmd_rescore` exits 1 when any origin failed to score, after writing the report, with an `error:` line on stderr giving the count and where to look. Exit 1 on all failed is kept (a subset of the new rule).
- The three comments say rows.
- Tests (`tests/evaluation/test_rescore.py`): the two skip tests assert the split dicts (same reasons, same counts); a new test that each "Not compared" line names its unit; a new test that one failed origin of two makes the command exit 1, say so on stderr and still write the report.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

No real-data step: nothing the command computes changes, and on the snapshot 0 of 728 origins fail (v0.10.61), so the exit code would be 0 there too.

## Alternatives considered

- **A warning line and exit 0** (the issue's other option). Rejected: a partial failure means the report's pooled numbers leave some origins out, and a scheduled caller only reads the exit code.
- **Keep one dict and add the unit to each reason's text.** Rejected: the unit would live in free text, and a test or caller could still sum origins with rows.

## Files to change

`domains/evaluation/rescore.py`, `domains/evaluation/__main__.py`, `tests/evaluation/test_rescore.py`, this doc; after merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. The re-score is an engine report, not read by the app (brief Q6 scores the runs of the time). No output, code, param or text the app reads is added, renamed or removed.

## Design review

Skipped as a panel: three tidy-ups the gatekeeper named on #634, no method or number change. The gatekeeper reviews the PR.
