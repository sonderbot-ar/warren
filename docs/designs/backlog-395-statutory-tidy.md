# Backlog #395: the statutory tax rate's exact floor, a coded refusal, and the real date rule

Issue: https://github.com/sonderbot-ar/warren/issues/395 · Branch `backlog-395-statutory-tidy` · Version v0.9.74 (patch)

## Problem

The gatekeeper's review of PR #394 (v0.9.73, backlog #385) left three follow-ups. None changes a number in any Phase 1 run; they keep the rule honest as it grows.

1. **The "at the floor" test is not at the floor.** `test_at_the_floor_takes_the_statutory_rate` (`tests/analysis/test_statutory_tax.py`) builds a 0.99% three-year pretax margin. The rule is "at or below" `math_engine.PRETAX_MARGIN_FLOOR` (1%, `pretax_sum <= PRETAX_MARGIN_FLOOR * revenue` in `math_engine._drivers`), so turning `<=` into `<` leaves every test green.
2. **A missing law is a refusal without a code.** `statutory_tax.statutory_rate` raises `StatutoryRateError` (a `LookupError`) for an unknown jurisdiction or a date before every law. `math_engine._statutory_tax` lets it through, so a run would fail with a bare `LookupError`, outside the refusal codes the app reads (`coded.ENGINE_REFUSAL_CODES`, v0.9.69). Unreachable today (every company is US through `math_engine.TAX_JURISDICTION`, every date is after `SUPPORTED_FROM`, 2019-03-01), but a wider universe or the Phase 2 IFRS adapter (#314) would reach it.
3. **A looser-than-needed check.** `test_every_rate_is_a_dated_sourced_fraction` checks `applies_from <= enacted_on + 1 year`, which would accept a law applying decades before it was signed.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. The exact floor, both sides.** Two tests in `tests/analysis/test_statutory_tax.py`:
  - *At exactly the floor.* Test Corp with FY2017 and FY2018 pretax income set to 0 and FY2019 pretax set to `PRETAX_MARGIN_FLOOR × Σ revenue` (Σ revenue read from a plain build, in the engine's own order). Then Σ pretax is that product exactly (0 + 0 + x = x in floating point), and the test asserts it before checking that the run takes the statutory rate. Scaling every year by one factor (the old test) can't hit the product exactly, because the three rounded products need not add up to it.
  - *One step above.* The same company with FY2019 pretax set to `math.nextafter(x, inf)`: no `tax_rate_statutory` note. Together the two pin `<=`: changing it to `<` fails the first, and to anything looser fails the second.
  - The old 0.99% test is renamed `test_just_below_the_floor_takes_the_statutory_rate`; what it checks is unchanged.
  - The pretax rows edited are every annual (`fp` FY) row of the pretax tags whose period ends in 2017 or 2018 (set to 0) or on 2019-12-31 (set to x), in every filing that gives them, comparatives included; tax rows are left as filed. "The engine's own order" is `_sum` (plain `sum` over the fiscal years in order, `math_engine.py`), and the test asserts the stored Σ pretax equals x before anything else, so a value changed on its way into the database would fail it.
  - Exit: tests pass; changing `<=` to `<` in `math_engine._drivers` fails the exact-floor test (checked by hand, not committed).
- **Step 2. A coded refusal for a missing law.** In `math_engine._statutory_tax`, `StatutoryRateError` becomes `EngineError(..., code="no_statutory_rate", params={"jurisdiction": ..., "as_of": ...})`. In `coded.py`, `no_statutory_rate` joins `REFUSAL_GROUPS` in group `setup`: the missing piece is Warren's own table of laws (`statutory_tax.RATES`), never the student's or the company's doing. The `setup` group lesson (`text.REFUSAL_GROUP_LESSONS`) is reworded so it stays true for the new code: a missing law is not loaded but added to Warren's table (analyst, professor). Its `why` becomes "Warren's own data for this estimate isn't there yet: a company's filings, its market prices, the Treasury rate, or a country's tax rate in Warren's table of tax laws. This doesn't depend on the student or the company; whoever runs Warren has to load or add it." and its `warren_rule` names "its table of statutory tax rates" beside the two loads. The catch sits in `math_engine._statutory_tax`; the English is the lookup's own message plus "; the run's three-year pretax income is at or below 1% of revenue, so it needs the statutory rate". `as_of` is an ISO date string, like `enacted_on` and `applies_from` in `tax_rate_statutory`.
  - `statutory_rate` keeps raising `StatutoryRateError` (it is a table lookup, not a run); only the run turns it into a refusal.
  - Tests: the existing refusal scans (`tests/analysis/test_refusal_codes.py`) find the new raise and require its code in the catalogue and in a group. A new test in `test_refusal_codes.py` builds Test Corp with a zero pretax sum while `math_engine.TAX_JURISDICTION` is monkeypatched to a jurisdiction with no row (`"MX"`), and checks code, params and text. `test_refusal_lessons.py` already requires every code to get a lesson (here the group's).
  - Exit: tests pass; `no_statutory_rate` is the 26th engine refusal code. The code change moves the reading rules' fingerprint, so `domains/analysis/reading_rules.md` gets a row under version 3 (only a raised error changes).
- **Step 3. The real date rule.** Each law in the table applies to tax years beginning on a January 1, in its own words: Pub. L. 103-66 §13221(d), "taxable years beginning on or after January 1, 1993", signed August 10, 1993, so it reached back; Pub. L. 115-97 §13001(c)(1), "taxable years beginning after December 31, 2017", signed December 22, 2017. So the check (`applies_like_the_table` in `tests/analysis/test_statutory_tax.py`) becomes: `applies_from` is a January 1, and no more than one calendar year before or after `enacted_on` (the old upper bound kept, a lower bound added). Its docstring says the rule fits the rows in the table, not every US law: the Tax Reform Act of 1986 cut the rate for years beginning on or after July 1, 1987 (professor, analyst), so a row like it would widen the check on purpose. `statutory_tax.py` is not edited.
  - Tests: a parametrized test runs the check on 2018-01-01 and 2017-01-01 (fit) and on 2018-07-01, 1980-01-01 and 2020-01-01 (refused), against TCJA's enactment date; the existing table test uses it on every row.
  - Exit: tests pass.

## Alternatives considered

- **Require a jurisdiction per company in the universe data** (the issue's other option for item 2). Not now: it is the right shape for Phase 2 (companies as data, Decision 11), but with eight US companies it adds a column every row repeats, and it still needs a coded refusal for a date before every law. Recorded under Known limits for the IFRS adapter (#314).
- **Group `company_data` for the new code.** Rejected: the company's filings are fine; Warren lacks a law. `setup` is the group whose words say "this doesn't depend on you" (`docs/product/brief.md`, refusal groups).
- **Make `StatutoryRateError` itself carry a code.** Rejected: the refusal scan reads `EngineError` and `MarketDataError` raises on the way to a run; one more exception type would need its own scan, for one raise.

## Known limits

The jurisdiction is still one constant (`math_engine.TAX_JURISDICTION = "US"`), so while it stays, a non-US company added to the universe would be given the US statutory rate on a near-zero-profit run, not the new refusal; the refusal only fires once a jurisdiction other than one in the table is passed. Reading a jurisdiction per company belongs with the IFRS adapter (#314). A US fiscal-year company whose year straddles a rate change pays a blended rate (IRC §15); the table gives one rate per law (professor's idea, not Phase 1: every supported date is after 2018).

**Point in time.** Nothing new is read; the law lookup is unchanged. **LLMs.** None. **Decision 11.** No source or currency change; the refusal makes a missing country's law visible instead of a crash. **Stored runs.** No run note or number changes; no stored run reaches the new refusal.

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.md`, `tests/analysis/test_statutory_tax.py`, `tests/analysis/test_refusal_codes.py`, `docs/product/brief.md` (the `setup` row lists the new code; asked for by the product lead, no student-facing words change), this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the refusal screens (`docs/product/brief.md`, "refusal groups"). Added: refusal code `no_statutory_rate` (params `jurisdiction`, `as_of`) in group `setup`; the brief's `setup` row lists it. Changed: the `setup` group lesson's English (Step 2 has the exact words). Nothing renamed or removed; no student can reach the new code in Phase 1. For the front-end team: add the code to the `setup` row of the text catalogue (no params are shown, as for the other `setup` codes). The Spanish `setup` lesson repeats the screen's own words and lists nothing (brief, "The `setup` lesson"), so it needs no change.

## Design review (nov.15.2026)

Explainer, analyst and professor in parallel, and the product lead on *Product impact*. Analyst GO, professor GO, product lead OK.

- **Analyst.** Ran the new floor tests; the exact-floor case is sound in floating point and pinned on both sides. Lowest three-year margin across stored runs is about 3% (WMT, XOM; #385 design), so nothing in Phase 1 moves. Taken: the `setup` lesson and its rule reworded (a law is added, not loaded); the January 1 rule called the form of the table's laws, with TRA 1986 as the counterexample; `as_of` stated as an ISO string; each law quoted in its own words.
- **Professor.** Checked both effective dates against the Senate Finance print of OBRA 1993 and CRS R45092 (congress.gov was not reachable). Same three suggestions as the analyst, all taken. Idea (IRC §15 blended rates) recorded under Known limits.
- **Explainer.** Six "blockers", all doc gaps, fixed: the 26th code, not 25th; Known limits rewritten (a constant "US" means a non-US company gets the US rate, not the refusal); the lesson change stated once, with exact words; the check is in `_drivers`; `reading_rules.md` added to the files; Step 3 now has a committed parametrized test. The brief edit was asked for by the product lead and changes no student-facing words.
- **Product lead.** OK. Taken: the brief's `setup` row lists the code in this PR. Not needed: a change to the Spanish `setup` lesson (it lists nothing).

## PR review (nov.15.2026)

Gatekeeper: GO, no blockers. `tests/analysis` 777 passed, ruff clean; the `<=` to `<` mutation fails exactly the exact-floor test; the renamed floor test is unchanged; the reading-rules row matches the fingerprint. Taken before merge: the date check's upper bound was one day looser than the old one (366 days against one calendar year), so it now keeps the old bound, `enacted_on` plus one year, with a test case more than a year before.
