# Warren versions

One row per merged version, newest first. A version is a milestone (minor number) or a backlog item (patch number). To restore a version, revert the merges after its commit with a revert PR; never rewrite `main`.

| Version | Date | What it is | Merge commit | PRs |
|---|---|---|---|---|
| v0.2 | oct.30.2026 | DCF engine (M2) and its hardening (M2.1): a baseline DCF for every Phase 1 company on any date, reproducible to the cent and rebuildable from the data it used | `2c9e6b3` | #5, #6, #7 |
| v0.1 | oct.26.2026 | Point-in-time fundamentals from SEC EDGAR (M1) and their hardening (M1.1) | `35cfdc0` | #3, #4 |
| v0.0 | oct.14.2026 | Foundations and documentation (M0) | `824efd0` | #1, #2 |
