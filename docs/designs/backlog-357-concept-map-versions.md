# Backlog #357: rebuild each stored run with the concept map it was made with

Issue: https://github.com/sonderbot-ar/warren/issues/357 · Branch `backlog-357-concept-map-versions` · Status: In progress (nov.13.2026)

## Problem

The concept map (`domains/fundamentals/concept_map.csv`) says which XBRL tags stand for each item Warren reads, in priority order. Every stored run records the map's SHA-256 (`runs.concept_map_sha256`), and `rebuild` (`domains/analysis/runs.py`) refuses a run whose map differs from today's file: "concept_map.csv changed since the run, it can't be rebuilt". The refusal is right, because a different map can pick a different tag for an old date and so a different number. But it means one edit to the map stops all 903 stored runs, and the M10 grid runs, from rebuilding. Three things go through `rebuild`:

- `python -m domains.analysis reproduce --all --rebuild`, the check that a run's assumptions come out of the data it used;
- the sources backfill for runs made before v0.9.11 (`domains/analysis/sources.py`);
- the notes backfill for older runs (`domains/analysis/runs.py`, `backfill_notes`).

So known data faults that need a map edit are parked: Caterpillar's current debt read as zero in every run (#341), P&G's FY2012–FY2014 revenue read from a segment (#322). The nov.12 findings on #341 name a versioned map as the way out.

What is not affected: `reproduce` without `--rebuild` recomputes outputs to the cent from stored assumptions and never reads the map. That invariant holds before and after this change.

## Why an old map still sees the same facts

Two existing rules make it safe to query old dates through an old map:

1. **Facts are only added.** Ingest appends every filing's version of every mapped tag (`domains/fundamentals/ingest.py`); nothing is overwritten. The point-in-time query only sees facts filed on or before the as-of date.
2. **A tag with stored facts can't leave the map.** `sync_concepts` (`domains/fundamentals/concepts.py`) fails loudly if a removed tag still has facts.

So every tag an old map named still has all its facts in the database. A newer map can add tags (whose facts the old map must not see) or reorder priorities (which the old map must not follow). Querying through the old map's own rows gives back exactly what the run saw, as long as the facts it used are still there, which rule 1 guarantees.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. Keep every valuation map, named by its fingerprint.** New folder `domains/fundamentals/concept_maps/`, holding `<sha256>.csv`, a byte-for-byte copy of each `concept_map.csv` a run may have been made with. Today that is one file: the map has not changed since oct.26.2026 (`git log -- domains/fundamentals/concept_map.csv`, last commit `1e81c37`), so every stored run carries the same fingerprint (checked on the snapshot in Step 3). New in `concepts.py`:
  - `CONCEPT_MAPS_DIR` and `archived_concept_map(sha256) -> list[ConceptRow]`: reads `<sha256>.csv`, checks its content hashes to its name, validates it with `load_concept_map`, and adds today's reported-only file (`concept_map_reported.csv`, which is outside the fingerprint by design, backlog #157). Raises `ConceptMapError` naming the fingerprint when there is no copy or the copy doesn't match.
  - `concept_map_sha256()` reads `CONCEPT_MAP_PATH` when called (today the path is bound when the module loads, so a test can't point it elsewhere). Same value.
  - Tests (`tests/fundamentals/test_concepts.py`): today's map has a copy in the folder, identical byte for byte (so whoever edits the map must add the new copy in the same commit, and the test says so); every file in the folder is named by its own SHA-256 and validates; an unknown fingerprint and a copy whose content doesn't match its name are both refused with the fingerprint in the message.
  - Exit: tests pass.
- **Step 2. `rebuild` queries through the run's own map.** New context manager `concept_map_in_force(conn, sha256)` in `concepts.py`:
  - When `sha256` is today's map: does nothing. Runs on today's map take exactly the path they take now.
  - Otherwise: creates a temporary table `temp.concepts` with the same columns, filled from `archived_concept_map(sha256)`, and drops it on exit, also when the body raises. SQLite looks up an unqualified table name in `temp` before `main`, so every query that joins `concepts` (`facts.py`'s `QUERY` and `_ranks`, `past_events.py`) reads the old map for the length of the rebuild, with no change to those queries. A temporary table lives only on that connection and is never written to the database file. If `temp.concepts` already exists, it refuses (no nesting).
  - `rebuild` replaces its refusal with `with concept_map_in_force(conn, run["concept_map_sha256"]):` around `build_inputs`. A run whose map has no copy is still refused, now with "no copy of concept map <sha>… in domains/fundamentals/concept_maps/, it can't be rebuilt".
  - Unchanged on purpose: `_same_inputs` in `domains/orchestration/nodes.py` still treats a run on another map as not reusable (the pipeline builds a new run on today's map); the `concept_map_changed` run note still compares today's file with the last ingest's (it is about whether ingest is fresh, not about which map a query uses); a new run always uses today's map.
  - Tests (`tests/analysis/test_runs.py`, on Test Corp from `tests/analysis/conftest.py`), the #341 case in miniature: Test Corp files its current debt only under a tag the map doesn't read (`LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths`), so run A counts `debt_current` as zero. Then the map is edited in a temporary folder to read that tag at priority 3, synced, and Test Corp ingested again. A fresh run B now has `debt_current` 20 and a different value per share (the edit matters); `rebuild` of A is `ok` (under its own map, from the copy) and `rebuild` of B is `ok` (today's map). Without Step 2, A's rebuild shows a mismatch on `debt_current` (checked by hand, not committed). Also: the temporary table is gone after a rebuild and after a rebuild that raises; a run on today's map creates no temporary table; the old refusal test becomes "a run whose map has no copy is refused" (same refusal, new message, so the test is kept, not weakened).
  - Exit: tests pass; full suite green.
- **Step 3. Real data, before merge.** On the restored snapshot (`20261110T202538Z`): count the distinct `concept_map_sha256` values in `runs` (expected: one, today's); `reproduce --all --rebuild` gives the same result as on `main` for every stored run. Then a trial on a copy of the database, not committed: edit the map to read CAT's current debt under `LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` at priority 3 (the tag the #341 findings name), sync, ingest CAT from SEC EDGAR again, and rebuild every stored CAT run (expected: all `ok` under their own map) and make one fresh CAT run (expected: `debt_current` no longer zero). Exit: the counts below, under "Step 3 results".

## Alternatives considered

- **Pass the map through every query** (a `concepts` argument on `facts.py`'s functions). Rejected: about a dozen functions and three modules would carry an argument for one caller, and a missed one would silently use today's map. The temporary table reaches every query at once.
- **Copy the database, or a view per map.** Rejected: a database copy is 1 GB per map; a view still needs the old rows from somewhere, and the copy in the repo is the source either way.
- **Read old maps from git history.** Rejected: a cloud machine may have a shallow clone (this one did), and a run should not depend on git being present. A copy in the repo is a few kilobytes.
- **Relax the invariant** (let runs on an old map go unchecked). Rejected: the owner's call (CLAUDE.md), and not needed.
- **A CAT-only rule** (companies as data). Still open for #341 itself: this change makes either fix possible without losing the rebuild check; it doesn't choose between them.

## Known limits

- A map that removes a tag needs its facts deleted first (`sync_concepts`). After that, an old run that used those facts can't be rebuilt; the rebuild shows the mismatch, as it should. No such removal is planned.
- The copy holds the valuation map only. The reported-only file is read from today's version, as now.
- The temporary table is per connection. Two rebuilds at once on two connections each get their own; nesting on one connection is refused.

**Point in time.** Unchanged: the old map changes which tags a query reads, not which filings are public on the as-of date. **LLMs.** None. **Decision 11.** No source, company or currency change; the change keeps companies-as-data fixes possible. **Numbers.** No value, assumption, output or note changes on any stored run.

## Files to change

`domains/fundamentals/concepts.py`, new `domains/fundamentals/concept_maps/<sha256>.csv`, `domains/analysis/runs.py`, `tests/fundamentals/test_concepts.py`, `tests/analysis/test_runs.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief questions served, changed or broken: none. No output, run note, code or lesson is added, renamed or removed. What students see doesn't change. Indirectly: data fixes the brief's answers depend on (Caterpillar's net debt in #341, P&G's revenue in #322) can now ship without breaking the rebuild of stored runs, so the app can keep showing old runs beside new ones.
