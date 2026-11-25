# Backlog #573: read Exxon's filings on its new CIK into the same history

Issue: https://github.com/sonderbot-ar/warren/issues/573 (from the #571 analyst) · Branch `backlog-573-xom-successor-link` · Version v0.10.44 when merged.

Status: In review (nov.25.2026; Steps 0–3 built).

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

**Step 1. The link is data.** `universe.csv` gains a column `successor_linked`, the last one (after `note`, so every existing row only gains a trailing comma): empty, or `yes` when Warren reads the successor's filings into this history. Validation: `yes` needs `successor_cik`; any other non-empty value is refused. XOM gets `yes`, and its note drops "Linking predecessor and successor is a later task" for a sentence saying the successor's 10-Q and 10-K filings are read into the same history (the note's date backstop, #256, still passes). `UniverseCompany` gains `successor_linked: bool = False` and a property `coverage_ends`: `None` when linked, else `history_ends`. `coverage_gap` (the `beyond_history` warning) uses `coverage_ends`, so a linked company never warns; `reported_period`'s `history_ends` field uses it too (null for Exxon from now on; its code comment now says "where the filings read stop"). The past-events call (`past_events.coverage_notes`) asks with `scored=True`: the evaluation grid still cuts at `history_ends`, so the typical errors it quotes still stop there, and the note stays (product lead, analyst). For a linked company its words change: `beyond_history` says Warren reads the later filings from the successor's CIK but the scored track record has not been re-run past that date; `history_cut` says the typical errors stop there and a quarter not in the data is "not filed by the question's date"; the `thin_evidence` sentence drops "filings are missing". Each carries `successor_linked: true` (absent for an unlinked company, whose words and params are byte for byte as before). `history_ends`, `reason` and the successor columns keep their meaning (where the predecessor's own filings stop, and why), so `coverage_fields`, which fills stored notes, is unchanged. Tests (`tests/fundamentals/test_universe.py`): XOM is linked and its `coverage_ends` is None; `coverage_gap` is None past the cut for a linked row and unchanged for an unlinked one (a tmp universe); a bad value and `yes` without a successor are refused; the seven-column file before this change is refused (a new test; the old four-column test stays). Tests that check the warning's mechanism on Exxon now run on an unlinked Exxon (a `unlinked_xom` fixture in `tests/conftest.py`), with the same assertions; new tests check the linked Exxon never warns and the past-events wording (`tests/evaluation/test_past_events.py`). Exit: suite and ruff green.

**Step 2. Ingest reads both.** `ingest_company` takes `successor_cik`; the CLI passes it for a linked row. When given (with `successor_since`, the row's `history_ends`; a linked row always has one, since `successor_cik` needs `history_ends`), it fetches the successor's companyfacts (same client; cached at `data/raw/edgar/companyfacts/CIK<successor>.json`; `--refresh` refreshes both) and `merge_company_facts` in `ingest.py` returns one document: for each taxonomy, tag and unit, the predecessor's facts filed before `history_ends`, plus the successor's 10-Q and 10-K facts filed on or after it. From the cut on only the successor speaks: the predecessor is still registered (its notes; a 424B2 on 2026-09-25, analyst) and may file again under Rule 12g-3, so its own 10-Q or 10-K facts filed from the cut are left out and counted as `skipped["predecessor_after_cut"]` (professor, analyst; none today). A joint filing is one accession, kept once by `extract_facts`'s key (concept, unit, start, end, accession). A successor comparative of an earlier period is a later version of it, as any 10-Q comparative is (analyst: all of them equal the predecessor's figures). The merged document is extracted once under the predecessor CIK, so the filing calendar, fiscal labels and every reader see one history. `ingest_runs` records the merged document's hash and the older of the two download times. The past-events freshness check (`fundamentals_freshness`) now reads the newest dated ingest instead of the newest time over all ingests, so an earlier predecessor-only ingest can't hide an old successor copy (analyst). The company row (name, aliases) stays the predecessor's: aliases feed news matching (M5), and a new alias would change stored clusters. Tests (`tests/fundamentals/test_ingest.py`, a fake client with two documents): a successor quarter lands under the predecessor CIK with its own accession and date and the right fiscal label; a successor fact filed before `history_ends` is left out; a predecessor 10-Q filed after the cut is left out and counted; the successor's comparative is the period's newest version; the run records the older download; a successor without its cut is refused; an unlinked ingest never asks for a second document; `get_facts` before the successor's filing date does not see it (point-in-time). Exit: suite and ruff green.

**Step 3. Results on real data.** Pass: every check below as stated. Restore the snapshot; `ingest --ticker XOM`; check FY2026 Q2 and Q3 revenue appear with their accessions and dates; `reported --ticker XOM --period latest-quarter --as-of 2026-11-24 --json` gives FY2026Q3 with no warning; the quality report for XOM; `reproduce --all` (stored runs reproduce to the cent); `runs.rebuild` on 11 baselines drawn with seed 573 plus the stored XOM runs dated from 2026-08-03, compared row by row with the pre-ingest copy of the database, where a stored XOM run dated after 2026-08-03 is expected to differ (it now sees two more quarters) and every other to match; the successor's comparatives equal the predecessor's figures (professor); the EDGAR archive link for both new accessions under the predecessor CIK answers HTTP 200. Save a snapshot.

## Not in this item (follow-up #582)

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
- New Exxon runs and `reported` answers no longer carry `beyond_history`. Stored runs keep theirs, and they still read back filled (#196). The past-events answer (Q10, Q14) keeps its Exxon notes, since the scored track record still stops at 2026-08-03 (#582), with `successor_linked: true` and words that no longer say the filings are missing; the app shows none of these codes today (product lead: no `webapp/` reader). The brief's Q10 and Q14 "Hoy" lines (`docs/product/brief.md`) are the front-end team's to update. No code is added or renamed; one param, `successor_linked`, is added to three notes for a linked company.
- `reported_period`'s `history_ends` is null for Exxon from now on (it says where the company's filings stop, and they no longer stop).
- Links: a successor filing's EDGAR link is built with the predecessor CIK; EDGAR serves both new accessions under it (checked: HTTP 200 for both). A `filer` field per filing (product lead's idea, so *Fuente* can name ExxonMobil Holdings) is not in this item.
- `universe.csv` gains a column; the question reader reads only `ticker`, so it is unaffected.

## Design review

Explainer, analyst, professor and the front-end product lead, in parallel, on the Step 0 doc (nov.25.2026). All blockers fixed above.

- **Analyst.** GO with changes. EDGAR: the successor holds exactly the two 10-Qs; 271 of their facts cover periods the predecessor reported, and none differ; every tag of the Q1 2026 10-Q is in the Q3 one; the reorganisation's new equity tags are not mapped. Blockers taken: the past-events notes stay (the grid still cuts) with true words; freshness reads the newest dated ingest; predecessor facts filed from the cut are left out. Ideas: the exact-duplicate rule was already `extract_facts`'s key (said so, dropped from the merge); links with the successor's CIK (not taken: EDGAR serves both); a grid re-run issue (filed, #582).
- **Professor.** GO with one blocker, taken: from the cut only the successor speaks (Rule 12g-3). Defensible as a permanent company id (CRSP PERMNO; WRDS linking suite); the parent carries the old book values under common control (ASC 805-50). Suggestions taken: check the comparatives equal the predecessor's (Step 3); the share exchange was one for one (cover shares 4.11 billion at 2026-06-30, in line with before; Step 3).
- **Product lead.** Nothing breaks the app: `webapp/` reads none of `beyond_history`, `history_cut` or `history_ends`, and the reader reads only `ticker`. Blocker taken as option (a): keep the past-events notes while the grid cut stays. Missing items added: the brief's Q10/Q14 lines, the follow-up number. Ideas filed in the doc: a `filer` per filing; a test that Exxon's `reported` has no warning (Step 3, on real data).
- **Explainer.** Gaps fixed: the column's place, the merge's home and cut, the cache, the download time, the rebuild sample and pass criteria, the past-events path, the `history_ends` field's meaning.

## Results on real data

nov.25.2026, snapshot `warren-20261123T052122Z` (schema 23), Exxon ingested again from the cached predecessor copy and a fresh successor copy.

- Ingest: 3,567 facts kept, 110 new (all from the two successor 10-Qs), 70 filing periods, none renumbered, `predecessor_after_cut` 0.
- FY2026 Q3 revenue 113,164M, accession 0002115436-26-000020, filed 2026-11-02, labelled FY2026 Q3, as EDGAR gives it.
- `reported --ticker XOM --period latest-quarter`: as of 2026-11-24, FY2026Q3, `history_ends` null, no warnings; as of 2026-10-30, FY2026Q2 (the Q3 10-Q was not filed yet: point-in-time holds).
- The 56 successor facts that restate an earlier period equal the predecessor's latest figure (0 differ). Cover shares 4,111,911,960 (Q2) and 4,079,222,444 (Q3), labelled Q2 and Q3.
- Quality report: XOM 0 unexplained gaps.
- `reproduce --all`: 909 of 909 runs reproduced to the cent.
- `rebuild`, 11 baselines with seed 573 plus `XOM_2026-10-30_1` and `_2`, against the pre-ingest database: the 11 give the same result on both (9 match; `XOM_2019-06-01_1` and `XOM_2023-04-01_1` differ by 24 rows on both, made under older reading rules); the two late Exxon runs matched before and now differ (44 and 47 rows: balance sheet and the two new quarters), as expected.
- EDGAR archive under CIK 34088: HTTP 200 for 000003408826000093 and 000211543626000020.
