# Backlog #513: refusal filings, a quarterly test and the CIK passed in

Issue: https://github.com/sonderbot-ar/warren/issues/513 (from the #512 gatekeeper) · Branch `backlog-513-refusal-filings-tidy` · Version v0.10.24 when merged.

Status: In progress (nov.21.2026; PR open).

## Problem

v0.10.23 (#509) gave six refusal codes a `filings` param. The gatekeeper's GO left two non-blocking gaps:

1. `math_engine.period_accessions` has three branches (a balance date, a fiscal year, a quarter). Tests reach the first two through `build_inputs`; the quarter branch (a `flow_item_not_reported` for one quarter) is covered only by reading.
2. `math_engine.refusal_filings` looks the company's CIK up again by ticker and indexes `.fetchone()["cik"]`, which would raise a bare `TypeError` if the row were missing. It can't be missing today (accessions imply an ingested company), but `_build_inputs` already holds the CIK when it refuses.

## Plan

**Step 0. This doc.**

**Step 1. The quarterly test and the CIK passed in.**

- `EngineError` gains an internal attribute `cik` (None by default), set by `_build_inputs`' existing `except EngineError` around the steps (the same place a missing line's accessions are filled), from the company row it read. Like `accessions`, it never enters `params`.
- `refusal_filings(conn, cik, accessions)` takes the CIK instead of the ticker; `build_inputs` passes `e.cik`. Every one of the six codes is raised inside that `try` (checked: `resolve`, `_balance`, `_securities`, `_shares`, `_nonzero`, all reached from the steps), so `e.cik` is set whenever there are accessions; a refusal with accessions and no CIK is a programming error and fails an assertion, never a silent empty list.
- New test (`tests/analysis/test_refusal_codes.py`): the test company with operating income and interest expense dropped for the quarter ending 2019-03-31 (in the FY2019 Q1 10-Q and as the comparative in the FY2020 Q1 10-Q) refuses `flow_item_not_reported` for FY2019 Q1 and names the newest 10-Q that reported that quarter's flows, the FY2020 Q1 10-Q `0000000123-20-000016` filed 2020-04-30, not the original 2019 one.
- New test: the refusal carries the run's CIK on `e.cik` and not in `params`; `refusal_filings` asserts when given accessions without a CIK.
- Exit: full suite, `ruff check`, `ruff format --check` green. No number, param, note, text or stored row changes.

## Alternatives considered

- **Keep the ticker lookup and return an empty list when the row is missing.** It would hide a broken invariant behind a missing link; the CIK is already at hand.
- **Put the CIK in `params`.** The app doesn't need it (the URL already carries it), and params are a public shape.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/reading_rules.md` (a same-version row: the fingerprint covers `math_engine.py`), `tests/analysis/test_refusal_codes.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. No output, param, code or wording is added, renamed or removed; brief questions unchanged.

## Review notes

Explainer, analyst and professor not run: tests and an internal argument only, no method, number or source rule changes (as for other test-only items, e.g. v0.10.9). The gatekeeper reviews the PR.
