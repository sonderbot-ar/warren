# Warren versions

One row per merged version, newest first. A version is a milestone (minor number) or a backlog item (patch number). To restore a version, revert the merges after its commit with a revert PR; never rewrite `main`.

The owner's desk, with an entry and a lesson for each version: https://claude.ai/artifact/5BGLYAQEjkqQHugGWpzKut

| Version | Date | What it is | Merge commit | PRs |
|---|---|---|---|---|
| v0.5.2 | oct.31.2026 | Why a value is missing (backlog #9): when value per share at the ERP ± 1 standard error has no value, the run stores the real cause and the report and run notes name it, instead of always blaming "WACC ≤ growth"; the report now says the missing bound is the upper one; no number changes | `d6789b5` | #78 |
| v0.5.1 | oct.31.2026 | A rebuild uses the run's own choices (backlog #11): each run's owner choices are read back from its stored rows, so editing `user_assumptions.csv` later no longer breaks the rebuild of earlier runs; the loader refuses a choice whose stored text could not be read back | `740f735` | #75 |
| v0.5 | oct.30.2026 | News ingestion and events (M5): GDELT news for all 26 case windows, matched to the eight companies and grouped into events that rebuild exactly; a headline rule keeps only articles that name the company, lifting measured precision from 0.18 to 0.72 pooled (0.52–0.90 per company, accepted by the owner) | `cbec76b` | #41, #43, #48, #51, #65, #66, #67 |
| v0.4.1 | oct.30.2026 | News downloads (backlog #52): a file we failed to download is a fetch error, apart from a gap in GDELT, and is read again on the next run; polite retries with back-off on busy or failing servers; a sliding window of downloads so one slow file no longer idles the rest | `8fa9256` | #62 |
| v0.3.1 | oct.30.2026 | The company list is data (backlog #18): the Phase 1 companies live in a checked-in CSV with a validating loader, so adding a company needs no code change (Decision 11, guardrail 2) | `29dddd1` | #44 |
| v0.4 | oct.30.2026 | Shock model and Monte Carlo (M4): shocks with a time shape and a p10/p50/p90 size, a 10,000-sample simulation that reproduces to the cent, company guidance turned into shocks by code, and a terminal value where growth past year 5 adds no value; three cases run with shocks | `2241c83` | #30, #39 |
| v0.3 | oct.30.2026 | Evaluation harness v1 (M3): the baseline scored against first-reported actuals and a naive benchmark on 24 cases; median revenue error 5.6% (naive 7.5%), EBIT 3.17 margin points (naive 4.16) | `0b1008f` | #16 |
| v0.2 | oct.30.2026 | DCF engine (M2) and its hardening (M2.1): a baseline DCF for every Phase 1 company on any date, reproducible to the cent and rebuildable from the data it used | `2c9e6b3` | #5, #6, #7 |
| v0.1 | oct.26.2026 | Point-in-time fundamentals from SEC EDGAR (M1) and their hardening (M1.1) | `35cfdc0` | #3, #4 |
| v0.0 | oct.14.2026 | Foundations and documentation (M0) | `824efd0` | #1, #2 |
