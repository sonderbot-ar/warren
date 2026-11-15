# Backlog #395: the statutory tax rate's exact floor, a coded refusal, and the real date rule

Issue: https://github.com/sonderbot-ar/warren/issues/395 · Branch `backlog-395-statutory-tidy` · Version v0.9.74 (patch)

## Problem

The gatekeeper's review of PR #394 (v0.9.73, backlog #385) left three follow-ups. None changes a number in any Phase 1 run; they keep the rule honest as it grows.

1. **The "at the floor" test is not at the floor.** `test_at_the_floor_takes_the_statutory_rate` (`tests/analysis/test_statutory_tax.py`) builds a 0.99% three-year pretax margin. The rule is "at or below" `math_engine.PRETAX_MARGIN_FLOOR` (1%, `pretax_sum <= PRETAX_MARGIN_FLOOR * revenue` in `math_engine.build_inputs`), so turning `<=` into `<` leaves every test green.
2. **A missing law is a refusal without a code.** `statutory_tax.statutory_rate` raises `StatutoryRateError` (a `LookupError`) for an unknown jurisdiction or a date before every law. `math_engine._statutory_tax` lets it through, so a run would fail with a bare `LookupError`, outside the refusal codes the app reads (`coded.ENGINE_REFUSAL_CODES`, v0.9.69). Unreachable today (every company is US through `math_engine.TAX_JURISDICTION`, every date is after `SUPPORTED_FROM`, 2019-03-01), but a wider universe or the Phase 2 IFRS adapter (#314) would reach it.
3. **A looser-than-needed check.** `test_every_rate_is_a_dated_sourced_fraction` checks `applies_from <= enacted_on + 1 year`, which would accept a law applying decades before it was signed.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The exact floor, both sides.** Two tests in `tests/analysis/test_statutory_tax.py`:
  - *At exactly the floor.* Test Corp with FY2017 and FY2018 pretax income set to 0 and FY2019 pretax set to `PRETAX_MARGIN_FLOOR × Σ revenue` (Σ revenue read from a plain build, in the engine's own order). Then Σ pretax is that product exactly (0 + 0 + x = x in floating point), and the test asserts it before checking that the run takes the statutory rate. Scaling every year by one factor (the old test) can't hit the product exactly, because the three rounded products need not add up to it.
  - *One step above.* The same company with FY2019 pretax set to `math.nextafter(x, inf)`: no `tax_rate_statutory` note. Together the two pin `<=`: changing it to `<` fails the first, and to anything looser fails the second.
  - The old 0.99% test is renamed `test_just_below_the_floor_takes_the_statutory_rate`; what it checks is unchanged.
  - Exit: tests pass; changing `<=` to `<` in `math_engine.build_inputs` fails the exact-floor test (checked by hand, not committed).
- **Step 2. A coded refusal for a missing law.** In `math_engine._statutory_tax`, `StatutoryRateError` becomes `EngineError(..., code="no_statutory_rate", params={"jurisdiction": ..., "as_of": ...})`. In `coded.py`, `no_statutory_rate` joins `REFUSAL_GROUPS` in group `setup`: the missing piece is Warren's own table of laws (`statutory_tax.RATES`), never the student's or the company's doing. The `setup` group lesson (`text.REFUSAL_GROUP_LESSONS`) names "a country's tax law" beside the filings, prices and Treasury rate it already lists, so it stays true for the new code.
  - `statutory_rate` keeps raising `StatutoryRateError` (it is a table lookup, not a run); only the run turns it into a refusal.
  - Tests: the existing refusal scans (`tests/analysis/test_refusal_codes.py`) find the new raise and require its code in the catalogue and in a group. A new test in `test_refusal_codes.py` builds Test Corp with a zero pretax sum while `math_engine.TAX_JURISDICTION` is monkeypatched to a jurisdiction with no row (`"MX"`), and checks code, params and text. `test_refusal_lessons.py` already requires every code to get a lesson (here the group's).
  - Exit: tests pass; `no_statutory_rate` is the 25th engine refusal code.
- **Step 3. The real date rule.** Both laws in the table are written as "tax years beginning after December 31, year X" (Pub. L. 103-66 §13221(d): years beginning on or after January 1, 1993, signed August 10, 1993, so it reached back; Pub. L. 115-97 §13001(c): years beginning after December 31, 2017, signed December 22, 2017). So the check becomes: `applies_from` is a January 1, and within one year of `enacted_on` on either side. A short comment says it is the US form of an effective date; another country's rows would add their own rule.
  - Exit: tests pass; an `applies_from` of 1980-01-01 or 2018-07-01 on a copy of a row fails the check (checked by hand).

## Alternatives considered

- **Require a jurisdiction per company in the universe data** (the issue's other option for item 2). Not now: it is the right shape for Phase 2 (companies as data, Decision 11), but with eight US companies it adds a column every row repeats, and it still needs a coded refusal for a date before every law. Recorded under Known limits for the IFRS adapter (#314).
- **Group `company_data` for the new code.** Rejected: the company's filings are fine; Warren lacks a law. `setup` is the group whose words say "this doesn't depend on you" (`docs/product/brief.md`, refusal groups).
- **Make `StatutoryRateError` itself carry a code.** Rejected: the refusal scan reads `EngineError` and `MarketDataError` raises on the way to a run; one more exception type would need its own scan, for one raise.

## Known limits

The jurisdiction is still one constant (`math_engine.TAX_JURISDICTION = "US"`). A non-US company would hit the new refusal on any near-zero-profit run, and would silently use its own effective rate otherwise; reading a jurisdiction per company belongs with the IFRS adapter (#314).

**Point in time.** Nothing new is read; the law lookup is unchanged. **LLMs.** None. **Decision 11.** No source or currency change; the refusal makes a missing country's law visible instead of a crash. **Stored runs.** No run note or number changes; no stored run reaches the new refusal.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `tests/analysis/test_statutory_tax.py`, `tests/analysis/test_refusal_codes.py`, `docs/product/brief.md` (the `setup` row lists the new code), this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the refusal screens (`docs/product/brief.md`, "refusal groups"). Added: refusal code `no_statutory_rate` (params `jurisdiction`, `as_of`) in group `setup`; the brief's `setup` row lists it. Changed: the `setup` group lesson's English adds "a country's tax law" to what may be missing. Nothing renamed or removed; no student can reach the new code in Phase 1. For the front-end team: add the code to the `setup` row of the text catalogue (no params are shown, as for the other `setup` codes) and, if the Spanish `setup` lesson lists what may be missing, add "la ley de impuestos de un país".
