# Backlog #573: read Exxon's filings on its new CIK into the same history

Issue: https://github.com/sonderbot-ar/warren/issues/573 (from the #571 analyst) · Branch `backlog-573-xom-successor-link` · Version v0.10.44 when merged.

Status: In progress (nov.25.2026).

## Problem

ExxonMobil reorganised into a holding company on 2026-07-01. The new parent, ExxonMobil Holdings Corp, files under CIK 0002115436; Warren reads only the old registrant, Exxon Mobil Corp (CIK 0000034088, pinned in `domains/fundamentals/universe.csv`, `history_ends` 2026-08-03). The successor's companyfacts holds two 10-Qs today (checked on EDGAR, nov.25.2026):

| Accession | Form | Filed | Period |
|---|---|---|---|
| 0000034088-26-000093 | 10-Q | 2026-08-03 | FY2026 Q2 (filed jointly; absent from the predecessor's companyfacts) |
| 0002115436-26-000020 | 10-Q | 2026-11-02 | FY2026 Q3 |

So every Exxon answer dated after 2026-08-03 stops at Q1 2026 and carries the `beyond_history` warning, and from about February 2027 the cost-of-debt chart would keep reading FY2026 as `not_filed_yet` after the 10-K is out (the #571 analyst). The build plan's risk table (Section 6) already says: "link predecessor and successor before analysing later XOM dates".

## Plan

The idea is the permanent company identifier of the CRSP/Compustat databases (a PERMNO survives a CIK change): Warren keeps the predecessor CIK as Exxon's one history id and reads the successor's 10-Q and 10-K facts into it. Every query stays point-in-time, because each fact keeps its own accession and filing date.

**Step 0. This doc**, and a roadmap line in team sync on merge.

**Step 1. The link is data.** `universe.csv` gains a column `successor_linked`, after `successor_name`: empty, or `yes` when Warren reads the successor's filings into this history. Validation: `yes` needs `successor_cik`; any other non-empty value is refused. XOM gets `yes`, and its note drops "Linking predecessor and successor is a later task" for a sentence saying the successor's 10-Q and 10-K filings are read into the same history (the note's date backstop, #256, still passes). `UniverseCompany` gains `successor_linked: bool = False` and a property `coverage_ends`: `None` when linked, else `history_ends`. `coverage_gap` (the `beyond_history` warning, and the past-events coverage note built from it) uses `coverage_ends`, so a linked company never warns; `reported_period`'s `history_ends` field uses it too (null for Exxon from now on). `history_ends`, `reason` and the successor columns keep their meaning (where the predecessor's own filings stop, and why), so `coverage_fields`, which fills stored notes, is unchanged. Tests (`tests/fundamentals/test_universe.py`): XOM is linked and its `coverage_ends` is None; `coverage_gap` is None past the cut for a linked row and unchanged for an unlinked one (a tmp universe); a bad value and `yes` without a successor are refused; the old six-column file is refused (the existing old-columns test moves to the new set, on purpose). Exit: suite and ruff green.

**Step 2. Ingest reads both.** `ingest_company` takes `successor_cik`; the CLI passes it for a linked row. When given, it fetches the successor's companyfacts (same client, cache and refresh) and `merge_company_facts(predecessor, successor, since=history_ends)` returns one document: for each taxonomy, tag and unit, the predecessor's facts plus the successor's facts filed on or after `history_ends` from a 10-Q or 10-K, with an exact duplicate (same accession, start, end and value) kept once. The merged document is extracted once under the predecessor CIK, so the filing calendar, fiscal labels and every reader see one history. `ingest_runs` records the merged document's hash and the older of the two download times (so the stale-data warning cannot hide an old successor copy). The company row (name, aliases) stays the predecessor's: aliases feed news matching (M5), and a new alias would change stored clusters. Tests (`tests/fundamentals/test_ingest.py`, a fake client with two documents): a successor quarter lands under the predecessor CIK with its own accession and date and the right fiscal label; a successor fact filed before `history_ends` is left out; an exact duplicate is stored once; an unlinked ingest never asks for a second document; `get_facts` before the successor's filing date does not see it (point-in-time). Exit: suite and ruff green.

**Step 3. Results on real data.** Restore the snapshot; `ingest --ticker XOM`; check FY2026 Q2 and Q3 revenue appear with their accessions and dates; `reported --ticker XOM --period latest-quarter --as-of 2026-11-24 --json` gives FY2026Q3 with no warning; the quality report for XOM; `reproduce --all` (stored runs reproduce to the cent); `rebuild` on a seeded sample of baselines, where a stored XOM run dated after 2026-08-03 is expected to differ (it now sees two more quarters) and every other to match; check the EDGAR archive link for the successor-only accession under the predecessor CIK. Save a snapshot.

## Not in this item (follow-up issue)

The evaluation grid (`domains/evaluation/grid.py`, `_horizon`) and the harness's coverage guard (`harness.guard_coverage`) keep cutting Exxon at `history_ends`. The grid file is regenerated from a fixed rule and scored (M10); lifting the cut changes Exxon's horizons on dates from mid-2025 and so the scored track record. That is a deliberate re-run of the grid, its own item. Until then Exxon's scored cases stay as they are: conservative, never wrong.

## Alternatives considered

- **Store the successor's facts under its own CIK and query both.** Truer to EDGAR, but about twenty queries filter on one CIK (`facts.py`, `single_values.py`, `reported.py`, `harness.py`, …) and the filing calendar would be split in two. One history id does the same job with one change at ingest. Rejected for now.
- **Switch the pin to the successor CIK.** Its companyfacts carries only the comparatives of two 10-Qs, so ten years of history would vanish. Rejected.
- **Link automatically for every `holding_company_reorganisation`.** Hides a choice that changes data coverage; an explicit column keeps companies as data (Decision 11) and lets a future link be turned off. Rejected.
- **Add the successor's name to the aliases.** Changes news matching and stored clusters. Not done.

## Files to change

`domains/fundamentals/universe.csv`, `domains/fundamentals/universe.py`, `domains/fundamentals/ingest.py`, `domains/fundamentals/__main__.py`, `domains/analysis/reported.py`, `tests/fundamentals/test_universe.py`, `tests/fundamentals/test_ingest.py`, other tests that pin XOM's warning on a date past the cut, `docs/build-plan.md` (risk table row), this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

- Serves Q3, Q4, Q5 and Q14 of `docs/product/brief.md` on Exxon dates after 2026-08-03: answers now include FY2026 Q2 and Q3, and from early 2027 the 10-K, instead of stopping at Q1 2026.
- New Exxon answers no longer carry `beyond_history` (or the past-events `history_cut` built from it). Stored runs keep theirs, and they still read back filled (#196). No code, param or Spanish line is added, renamed or removed.
- `reported_period`'s `history_ends` is null for Exxon from now on (it says where the company's filings stop, and they no longer stop).
- Links: a successor filing's EDGAR link is built with the predecessor CIK; EDGAR serves both new accessions under it (checked: HTTP 200 for both).
- `universe.csv` gains a column; the question reader reads only `ticker`, so it is unaffected.
