# Reading rules versions

The reading rules are the code that turns filed and downloaded data into a run's assumption rows: `domains/fundamentals/facts.py`, `domains/analysis/math_engine.py` and every Warren module they import, directly or not, except the few `NOT_RULES` in `reading_rules.py` names (backlog #365). `python -m domains.analysis.reading_rules` prints the list. Each run stores `READING_RULES_VERSION` as `runs.reading_rules_version`; runs stored before v0.9.67 have none.

`tests/analysis/test_reading_rules.py` fails until today's fingerprint (`python -m domains.analysis.reading_rules`) has a row here under `READING_RULES_VERSION`. Comments, docstrings and layout don't change the fingerprint; code does. When it changes, in the same commit:

- **If the change can change what a run reads** (which figure, which quarter, which count, which row): add 1 to `READING_RULES_VERSION` and add a row with the new version.
- **If it cannot** (a rename, a refactor, a new function no run calls yet): add a row under the same version and say why. The rebuild check (`reproduce --all --rebuild`) is the backstop for a wrong call.

Rows are never edited or deleted. Versions start at 1 and go up by at most one per row.

| Fingerprint | Version | From | What changed and why |
|---|---|---|---|
| `e8cb250579da` | 1 | nov.13.2026 (v0.9.67, #365) | First recorded version: the rules as of v0.9.66 (part-as-whole skip #322, share scale #343, and everything before). Runs stored before this have no version. |
| `43a83f2eaa66` | 2 | nov.14.2026 (v0.9.68, #364) | A share count of zero or below is never used: a newer one gives way to the newest count above zero (with run note `shares_not_positive`), and a diluted count of zero no longer reaches the cover-against-diluted check, where it divided by zero. No stored run reads such a count (the only one, Coca-Cola's 2009 cover page, is older than every run's newest count). |
| `a561d2402283` | 2 | nov.14.2026 (v0.9.69, #376) | Refusals carry a code and params (`EngineError`, `MarketDataError`), `where_params` splits a refusal's period, and the ERP information lines skip a too-short window by its code (`MarketDataError` `erp_too_few_years`; before, a `ValueError` catch that could never match). Only raised errors change: no run reads a different figure, and every refusal keeps its English text, so the version stays 2. |
| `a47dfeb444ca` | 2 | nov.14.2026 (v0.9.70, #383) | A divisor of exactly zero on the way to a run is refused with code `zero_divisor` instead of crashing with a `ZeroDivisionError`: a quarter's or a year's revenue in the forecast ratios and the seed's check against its year, a prior year's revenue in the growth comparatives, and the three-year revenue or pretax sums. Every other divisor gives the same float as before (the arithmetic is unchanged; the check runs first), so no run reads a different figure and the version stays 2. |
