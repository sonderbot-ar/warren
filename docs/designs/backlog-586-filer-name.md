# Backlog #586: say who filed a filing when it is the successor's, so *Fuente* can name ExxonMobil Holdings

Issue: https://github.com/sonderbot-ar/warren/issues/586 (front-end request, from the v0.10.44 brief update) · Branch `backlog-586-filer-name` · Version v0.10.45 when merged.

Status: In progress (nov.25.2026).

## Problem

Since v0.10.44 (#573), Exxon's 10-Q and 10-K filed from 2026-08-03 are read from its successor, ExxonMobil Holdings Corp (CIK 0002115436), into the old CIK's history (0000034088). Every filing the engine returns has the #140 shape `{accession_no, form, filed_at, url}`, with the link built under CIK 34088 (EDGAR serves both new accessions there). A student who opens the link for an FY2026 Q2 or Q3 figure sees a filing by "ExxonMobil Holdings Corp" while the source panel says nothing, and may think Warren linked the wrong company. Clarity, not correctness.

## Plan

**Step 0. This doc.**

**Step 1. A `filer` on every filing.**
- `Filing` (`domains/analysis/reported.py`) gains `filer: dict | None = None`. `_Filings.get`, the one place every #140 filing is built (a part's filing and inputs in `reported_period` and `inputs_behind`, a run source's `filing` and `input_filings`, a refusal's `filings`, the single-value notes' `effective_rate_filing` and `evidence_filings`), sets it with a new `successor_filer(cik, filed_at)`.
- `successor_filer` returns `{"cik": successor_cik, "name": successor_name, "successor": True}` when the company's universe row is `successor_linked` and the filing was filed on or after its `history_ends`; else None. The filing date alone is exact: since #573 `merge_company_facts` keeps, from `history_ends` on, only the successor's 10-Q and 10-K facts (the predecessor's own are dropped and counted, none today), and `extract_facts` stores only those forms. An accession Warren never read has no date and no filer.
- The key is always present, null for a company's own filings, so the app can test one field. Links are unchanged.
- Tests, `tests/analysis/test_filer.py`: Exxon on and after 2026-08-03 names the successor, before it and other companies name none, an unknown accession names none; with the link turned off (`unlinked_xom`) none; on Test Corp with a made-up linked row (cut 2020-01-01), `_Filings` gives the successor only for filings from the cut, the shape has exactly five keys and the link stays under the company's CIK; a refusal's filings carry it and survive JSON; `reported_period` on three periods marks every filing (latest, first reported, and a derived figure's inputs) by its date, sees both kinds, and is otherwise identical with and without the link. `tests/analysis/test_refusal_codes.py`'s expected filing gains `"filer": None` (Test Corp's filings are its own).

Exit: full suite, `ruff check`, `ruff format --check` green.

**Step 2. Results on real data.** Restore the snapshot; check Exxon's FY2026 Q2 and Q3 filings carry the successor and older ones don't; Apple's filings carry none; `reproduce --all` to the cent (no number changes).

## Alternatives considered

- **Store the registrant per fact at ingest** (a `filer_cik` column, a migration and a re-ingest). Exact for any future joint or mixed case, but a schema change and a snapshot rebuild for a fact the date already gives exactly today. Worth it only if a second company is linked with filings that overlap in time; noted under Risks.
- **Only a flag `successor: true`** (the issue's second option). The app would then need the name from elsewhere; giving the name and CIK costs nothing.
- **A filer on every filing, own filings included** (`{"cik": "0000034088", "name": "Exxon Mobil Corp", ...}`). Adds the company's own name to thousands of filings for no gain; null says "the company itself" plainly.
- **Build the successor's link under its own CIK.** Both work today; changing working links is out of scope.

## Files to change

`domains/analysis/reported.py`, `tests/analysis/test_filer.py` (new), `tests/analysis/test_refusal_codes.py`, this doc; on merge `docs/versions.md`, `docs/build-plan.md` (no milestone status changes), `docs/team-sync.md`.

## Product impact

- Serves Q1 and Q2 (a reported figure's source) and Q3 and Q5 (an estimate's inputs) on Exxon dates from 2026-08-03: each filing in those answers now says when it was filed by ExxonMobil Holdings Corp, so *Fuente* can add the brief's line ("Presentado por ExxonMobil Holdings Corp, la nueva entidad legal de Exxon desde agosto de 2026").
- Adds one field, `filer`, to the #140 filing shape everywhere it appears; nothing is renamed or removed. For the seven other companies, and for Exxon's filings before 2026-08-03, it is null.
- Note for the front-end: the FY2026 Q2 10-Q (0000034088-26-000093) was filed jointly by both registrants, under the old CIK's accession prefix; "presentado por ExxonMobil Holdings Corp" is still true of it. Some Exxon FY2025 lines also show the successor, because their newest version is a comparative restated in a 2026 10-Q (same figures, #573 checked all 56).

## Risks

- The rule reads the universe file at answer time. If a linked row's `history_ends` were later moved, old filings would be re-labelled; the same is true of the #573 merge, which uses the same date, so the two stay consistent.

## Review notes

*(to fill)*

## Results on real data (Step 2)

*(to fill)*
