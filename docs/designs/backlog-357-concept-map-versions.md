# Backlog #357: rebuild each stored run with the concept map it was made with

Issue: https://github.com/sonderbot-ar/warren/issues/357 · Branch `backlog-357-concept-map-versions` · Version v0.9.64, merged nov.13.2026 (PR #358, merge `3973726`)

## Problem

The concept map (`domains/fundamentals/concept_map.csv`) says which XBRL tags stand for each item Warren reads, in priority order. Every stored run records the map's SHA-256 (`runs.concept_map_sha256`), and `rebuild` (`domains/analysis/runs.py`) refuses a run whose map differs from today's file: "concept_map.csv changed since the run, it can't be rebuilt". The refusal is right, because a different map can pick a different tag for an old date and so a different number. But it means one edit to the map stops all 903 stored runs, and the M10 grid runs, from rebuilding. Three things go through `rebuild`:

- `python -m domains.analysis reproduce --all --rebuild`, the check that a run's assumptions come out of the data it used;
- the sources backfill for runs made before v0.9.11 (`domains/analysis/sources.py`);
- the notes backfill for older runs (`domains/analysis/runs.py`, `backfill_notes`).

So known data faults that need a map edit are parked: Caterpillar's current debt read as zero in every run (#341), P&G's FY2012–FY2014 revenue read from a segment (#322). The nov.12 findings on #341 name a versioned map as the way out.

What is not affected: `reproduce` without `--rebuild` recomputes outputs to the cent from stored assumptions and never reads the map. That invariant holds before and after this change.

## Why an old map still sees the same facts

Two existing rules make it safe to query old dates through an old map:

1. **Fact values are only added.** Ingest appends every filing's version of every mapped tag (`domains/fundamentals/ingest.py`); no value is overwritten. The point-in-time query only sees facts filed on or before the as-of date. Labels are the exception (analyst): a re-ingest can rewrite a fact's `fiscal_year` and `fiscal_period` (`ingest.py`, `UPSERT_FACT ... DO UPDATE`) and rebuilds `filing_labels`, and those labels key the history (`math_engine.py`, `History`). That is a change in the data, not in the map, and the rebuild check shows it today with or without this change; Step 3 compares against `main` so a label change can't be mistaken for a map effect.
2. **A tag with stored facts can't leave the map.** `sync_concepts` (`domains/fundamentals/concepts.py`) fails loudly if a removed tag still has facts.

So every tag an old map named still has all its facts in the database. A newer map can add tags (whose facts the old map must not see) or reorder priorities (which the old map must not follow). Querying through the old map's own rows gives back exactly what the run saw, as long as the facts it used are still there, which rule 1 guarantees.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Keep every valuation map, named by its fingerprint.** New folder `domains/fundamentals/concept_maps/`, holding `<sha256>.csv`, a byte-for-byte copy of each `concept_map.csv` a run may have been made with. Today that is one file: the map has not changed since oct.26.2026 (`git log -- domains/fundamentals/concept_map.csv`, last commit `1e81c37`), so every stored run carries the same fingerprint (checked on the snapshot in Step 3). New in `concepts.py`:
  - `CONCEPT_MAPS_DIR` and `archived_concept_map(sha256) -> list[ConceptRow]`: reads `<sha256>.csv`, checks its content hashes to its name, validates it with `load_concept_map`, and adds today's reported-only file (`concept_map_reported.csv`, which is outside the fingerprint by design, backlog #157). Raises `ConceptMapError` naming the fingerprint when there is no copy or the copy doesn't match.
  - `concept_map_sha256(path=None)` reads `CONCEPT_MAP_PATH` when called (today the default is bound when the module loads, so a test can't point it elsewhere). Same value. Tests point `concepts.CONCEPT_MAP_PATH` and `concepts.CONCEPT_MAPS_DIR` at temporary files with `monkeypatch`.
  - `concept_maps/CHANGES.md`: one line per fingerprint, with its date, its commit or issue, and what changed and why (professor: a hash alone tells a reader nothing). The procedure for whoever edits the map: copy the new `concept_map.csv` to `concept_maps/<its sha256>.csv` and add its line, in the same commit; the test below fails until both are there.
  - Tests (`tests/fundamentals/test_concepts.py`): today's map has a copy in the folder, identical byte for byte (so whoever edits the map must add the new copy in the same commit, and the test says so); every file in the folder is named by its own SHA-256, validates together with today's reported-only file (a tag or item in both is refused by `load_concept_map`, as today), and has its line in `CHANGES.md`; an unknown fingerprint and a copy whose content doesn't match its name are both refused with the fingerprint in the message.
  - Exit: tests pass.
- **Step 2. `rebuild` queries through the run's own map.** New context manager `concept_map_in_force(conn, sha256)` in `concepts.py`:
  - When `sha256` is today's map: does nothing. Runs on today's map take exactly the path they take now.
  - Otherwise: creates a temporary table `temp.concepts` with the main table's six columns (`canonical_name`, `xbrl_concept`, `priority`, `unit`, `period_type`, `definition`; the CSV's `gate` and `note` are not stored in either table), filled from `archived_concept_map(sha256)`, and drops it on exit, also when the body raises. SQLite looks up an unqualified table name in `temp` before `main`, so every query that joins `concepts` (`facts.py`'s `QUERY` and `_ranks`, `past_events.py`) reads the old map for the length of the rebuild, with no change to those queries. A temporary table lives only on that connection and is never written to the database file. If `temp.concepts` already exists, it raises `ConceptMapError("A concept map is already in force on this connection")` and leaves the outer one in place (no nesting).
  - `rebuild` checks the copy first, then replaces its refusal with `with concept_map_in_force(conn, run["concept_map_sha256"]):` around `build_inputs`. A run whose map has no copy is still refused, as a `ValueError` like today (so `reproduce --rebuild`, the sources backfill and the notes backfill count it as failed, as they do now), with "No copy of concept map <first 12 of the sha> in concept_maps/, it can't be rebuilt". `Rebuild` gains `archived_map` (true when the run was read through an older map), and `reproduce --rebuild` adds "under the run's own concept map" to such a run's line (professor).
  - Unchanged on purpose: `_same_inputs` in `domains/orchestration/nodes.py` still treats a run on another map as not reusable (the pipeline builds a new run on today's map); the `concept_map_changed` run note still compares today's file with the last ingest's (it is about whether ingest is fresh, not about which map a query uses); a new run always uses today's map.
  - Tests (`tests/analysis/test_runs.py`, on Test Corp from `tests/analysis/conftest.py`), the #341 case in miniature: Test Corp files its current debt only under a tag the map doesn't read (`LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths`), so run A counts `debt_current` as zero. Then the map is edited in a temporary folder to read that tag at priority 3, synced, and Test Corp ingested again. A fresh run B now has `debt_current` 20 and a different value per share (the edit matters); `rebuild` of A is `ok` (under its own map, from the copy) and `rebuild` of B is `ok` (today's map). Without Step 2, A's rebuild shows a mismatch on `debt_current` (checked by hand, not committed). Also: the temporary table is gone after a rebuild and after a rebuild that raises; a run on today's map creates no temporary table; the old refusal test becomes "a run whose map has no copy is refused" (same refusal, new message, so the test is kept, not weakened).
  - Exit: tests pass; full suite green.
- **Step 3. Real data, before merge.** On the restored snapshot (`20261110T202538Z`): count the distinct `concept_map_sha256` values in `runs` (expected: one, today's); `reproduce --all --rebuild` gives the same result as on `main` for every stored run. Then a trial on a copy of the database, not committed: edit the map to read CAT's current debt under `LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` at priority 3 (the tag the #341 findings name), sync, ingest CAT from SEC EDGAR again, and rebuild every stored CAT run (expected: every run read through its own map, and exactly the same runs `ok` as on `main`, since 15 of 113 CAT runs already differ there from later code, analyst) and make one fresh CAT run (expected: `debt_current` no longer zero at a year-end balance). Exit: the counts below, under "Step 3 results".

## Step 3 results (nov.13.2026, snapshot `20261110T202538Z`)

- **One fingerprint.** All 903 stored runs and all 27 ingest runs carry `2a263604a945…`, today's map; its copy is `concept_maps/2a2636….csv`. The `concepts` table (54 rows) equals both today's file and the copy (analyst).
- **Nothing changes today.** `reproduce --all --rebuild` on this branch prints the same lines as on `main` for every run, apart from the code version: 903 of 903 reproduce to the cent, 821 of 903 rebuild to identical rows on both. The 82 that differ do so on `main` too, from code since the runs were made (v0.9.4x quarter-tag rules, recorded in `docs/versions.md`). The analyst also rebuilt the first and last run of each company twice, once forced through the temporary table: identical results, notes and mismatches.
- **The #341 trial** (a copy of the database, not committed): the map edited to read CAT's current debt under `LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` at priority 3 (fingerprint `f8c44a1b…`), CAT ingested again from SEC EDGAR (16 new facts, all December year ends), then every stored CAT baseline rebuilt: all 113 read through their own map, 98 of 113 rebuild to identical rows, the same 98 as on `main`. Without this change all 113 would have been refused. A fresh CAT run as of 2026-10-30 reads current debt of $7.12bn at 2025-12-31 (the same date as its non-current debt, since CAT tags consolidated debt only at year ends): debt goes from $36.21bn to $43.33bn and value per share from $218.45 to $205.62 (−5.9%). That is the size of the #341 fault; fixing it is #341's own track (with #233's finance-arm question), not this one.

## Alternatives considered

- **Pass the map through every query** (a `concepts` argument on `facts.py`'s functions). Rejected: about a dozen functions and three modules would carry an argument for one caller, and a missed one would silently use today's map. The temporary table reaches every query at once.
- **Copy the database, or a view per map.** Rejected: a database copy is 1 GB per map; a view still needs the old rows from somewhere, and the copy in the repo is the source either way.
- **Read old maps from git history.** Rejected: a cloud machine may have a shallow clone (this one did), and a run should not depend on git being present. A copy in the repo is a few kilobytes.
- **Relax the invariant** (let runs on an old map go unchecked). Rejected: the owner's call (CLAUDE.md), and not needed.
- **A CAT-only rule** (companies as data). Still open for #341 itself: this change makes either fix possible without losing the rebuild check; it doesn't choose between them.

## Known limits

- An older map may lack an item that newer code reads. The facts query then fails with "Not in the concept map" (`facts.py`, `_rows_by_period`), and the rebuild counts as failed. That is right: the code reads something the run never read, so the rows can't match. Code changes already show up as rebuild differences today (Step 3: 82 of 903 runs differ on `main`, all from later code, not the map).
- **Only added tags and reordered priorities within existing items are covered** (analyst). Changing a tag's unit or period type leaks facts ingested under the new rule into the old map, because the query joins on the tag alone (`facts.py`, `QUERY`); the rebuild then shows a mismatch, loudly.
- **Re-ingest every company after a map edit** (analyst). The first ingest after an edit syncs the table for everyone (`ingest.py`, `sync_concepts`), but another company's facts for a new tag arrive only at its own re-ingest. A run made in between carries the new fingerprint without those facts, and its later rebuild differs, loudly. `concept_maps/CHANGES.md` states the rule.
- The today's-map path trusts that the `concepts` table was synced from today's file, as every query does now; only ingest syncs it (analyst).
- `runs.concept_map_sha256` is set on every stored run (903 of 903 on the snapshot); a run with none would be refused as having no copy.

- A map that removes a tag needs its facts deleted first (`sync_concepts`). After that, an old run that used those facts can't be rebuilt; the rebuild shows the mismatch, as it should. No such removal is planned.
- The copy holds the valuation map only. The reported-only file is read from today's version, as now.
- The temporary table is per connection. Two rebuilds at once on two connections each get their own; nesting on one connection is refused.

**Point in time.** Unchanged: the old map changes which tags a query reads, not which filings are public on the as-of date. **LLMs.** None. **Decision 11.** No source, company or currency change; the change keeps companies-as-data fixes possible. **Numbers.** No value, assumption, output or note changes on any stored run.

## Files to change

`domains/fundamentals/concepts.py`, new `domains/fundamentals/concept_maps/<sha256>.csv`, `domains/analysis/runs.py`, `tests/fundamentals/test_concepts.py`, `tests/analysis/test_runs.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief questions served, changed or broken: none. No output, run note, code or lesson is added, renamed or removed. What students see doesn't change. Indirectly: data fixes the brief's answers depend on (Caterpillar's net debt in #341, P&G's revenue in #322) can now ship without breaking the rebuild of stored runs, so the app can keep showing old runs beside new ones.

## Design review (nov.13.2026)

Explainer, analyst and professor in parallel. The product lead was not asked: the *Product impact* is none (no output, note, code or lesson changes).

- **Explainer** GO on clarity, 13 gaps. Taken: how `concept_map_sha256` stops binding at import and what the tests patch; the six columns the temporary table takes (no `gate`, no `note`); a new item an old map lacks fails loudly (Known limits); the nesting error; the reported-only file validated with the copy; the no-copy refusal stays a `ValueError`, so both backfills count it as failed; the git evidence (the clone was shallow; unshallowed, `git log` shows `1e81c37` as the last map commit); a NULL fingerprint; the results section; how the trial edits the map; the procedure for a map edit (`CHANGES.md`).
- **Analyst** NO-GO on the first draft, two blockers, both taken, then GO: (1) Step 3's CAT exit is now "the same runs as on `main`", because 15 of 113 CAT runs already differ there; (2) "facts are only added" now says labels are rewritten on re-ingest. Ideas taken into Known limits: re-ingest every company after an edit (also in `CHANGES.md`), unit or period changes, new items, the synced-table assumption; the tag covers year ends only (Step 3).
- **Professor** GO: content addressing (Chacon and Straub, *Pro Git*, ch. 10), Sandve et al. 2013 rules 1 and 4, and append-only point-in-time storage (Snodgrass 1999). Ideas taken: `CHANGES.md` beside the copies; `reproduce --rebuild` says when a run was read through its own older map; the lesson names "facts known then" vs "rules in force then" and that the reported-only file is not versioned.
