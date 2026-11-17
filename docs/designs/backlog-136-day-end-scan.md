# Backlog #136: the day-end import scan, with its gaps closed

Status: Done (nov.17.2026, v0.9.84 on merge) · Elephant: agent team · Branch `backlog-136-day-end-scan`

## Problem

v0.9.2 (#133, PR #135) added a scan that fails if any module takes the "has this day ended in New York" rule (`known_by`, `CASE_TZ`) from anywhere but `shared_kernel.calendar`. The gatekeeper on #135 found three gaps (none used in the code today):

1. Any name `calendar` was trusted: `from domains.news import gdelt as calendar` then `calendar.known_by` passed.
2. `getattr(module, "known_by")` was not caught, and the scan read only `main.py`, `domains/` and `shared_kernel/` (the web app, `webapp/`, has arrived since).
3. The scan proved files were read, not that a real use of the kernel was seen.

## Plan

- **Step 0.** This doc.
- **Step 1.** In `tests/shared_kernel/test_calendar.py`: a name may reach the rule by attribute only if this module bound it to the kernel (`from shared_kernel import calendar [as x]`, `import shared_kernel.calendar as x`, or the full dotted `shared_kernel.calendar`); `getattr(x, "known_by")` with the rule's name as a string is flagged unless `x` is the kernel; `webapp/` is scanned; at least one `from shared_kernel.calendar import known_by|CASE_TZ` must be seen. Tests: six borrowed forms are flagged (alias, `import … as calendar`, adapter attribute, adapter import, `getattr` by string, the standard library's `calendar`), seven kernel forms pass; a mutation (the alias form added to a real module) fails the scan. Exit: the suite green, the mutation caught.

Limits, stated: a `getattr` whose name is built at run time can't be read by a static scan; it is not flagged (flagging every dynamic `getattr` flagged 14 unrelated uses). Kernel names are gathered per file, so a name bound to the kernel and later rebound elsewhere still passes; a star import (`from domains.news.gdelt import *`) is not caught; a relative `from .calendar import known_by` inside the kernel would be flagged by mistake (none exists). All three are backlog #438.

## PR review (nov.17.2026)

Gatekeeper GO on PR #437: its own mutations on real modules (alias in `domains/orchestration/report.py`, `getattr` by string in `webapp/app.py`, adapter import) were caught and a kernel alias passed. Notes taken: the borrowed-form count (six, not seven) fixed here; the star import, per-file rebinding and relative-import edges filed as #438.

## Alternatives considered

- Flag every `getattr` with a non-constant name: 14 false hits (e.g. `domains/analysis/montecarlo.py:199`), so a rule nobody could keep.
- Check at import time by monkeypatching: catches run-time paths only where tests reach them; the static scan sees every file.

## Files to change

`tests/shared_kernel/test_calendar.py`, this doc, at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

None: tests only; no output, rule or number changes. Brief questions served: none directly.
