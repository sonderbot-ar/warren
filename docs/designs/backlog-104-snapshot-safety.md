# Backlog #104: safer data snapshots

Issue: https://github.com/sonderbot-ar/warren/issues/104 · Branch `backlog-104-snapshot-safety` · Version v0.6.1 when merged.

## Problem

The gatekeeper's notes on `shared_kernel/snapshot.py` from PR #101:

1. `restore` and the prune step in `save` build a path from the manifest's `archive` field without checking it, so a bad manifest could point `restore` at, or the prune step's delete at, a file outside the snapshot folder.
2. `extractall(filter="data")` needs Python 3.11.4 or later; `pyproject.toml` said 3.11.
3. `restore --force` deleted `raw/edgar` (and the database's WAL) before moving the new copy in, so a failed move lost the old files.
4. The SHA-256 proves integrity, not origin, and the module did not say so.

## Plan

**Step 0. This design doc.** Exit: doc on the branch.

**Step 1 (one commit).**
- `_archive_path(manifest_path, manifest)`: the archive must be exactly `warren-<stamp>.tar.gz`, with the same stamp as the manifest's own name, in the same folder; anything else raises `SnapshotError`. `restore` uses it before reading the archive. The prune step uses it too, and leaves an odd manifest and whatever it names alone (for a person to look at) instead of deleting.
- `_swap_in(new, targets, aside)`: moves the old files (the database with its `-wal` and `-shm`, or `raw/edgar`) aside inside the unpack folder, moves the new copy in, and only then lets the old ones go with the unpack folder. If the move fails, a half-moved new copy is removed and the old files go back. The unpack folder sits in `data/`, so the aside moves are renames on one disk.
- `requires-python = ">=3.11.4"` in `pyproject.toml` and the README; the module docstring states it and that the hash proves integrity, not origin (fine for the project's shared folder, which only Warren's runs write to).

Tests (`tests/shared_kernel/test_snapshot.py`): five odd archive names (parent path, absolute path, wrong extension, another stamp, a subfolder) are refused and nothing is unpacked; the prune step never deletes a file an odd manifest names; a failed raw move (after a half copy) keeps the old raw files, local-only file included; a failed database move keeps the old database with its newest row. All eight new tests fail on the old code. The real snapshot in the project folder passes the name check. Exit: `pytest`, `ruff check`, `ruff format --check` green.

## Alternatives considered

- *Sign the manifest.* Rejected: it needs a key to manage, and only Warren's own runs write to the shared folder; the docstring says not to restore from a folder others can write to.
- *Make the whole restore atomic (database and raw files together).* Not done: if the raw swap fails after the database swap, the new database sits beside the old raw files. The raw files are a download cache that the ingest re-fetches by need, and the error is raised, so the run stops before trusting anything.

No design decision changes. No number changes.

## Files

`shared_kernel/snapshot.py`, `tests/shared_kernel/test_snapshot.py`, `pyproject.toml`, `README.md`, `docs/versions.md`.

## Review log

Design review not run: this is a four-point fix list that the gatekeeper already wrote as the issue, with no financial logic. Gatekeeper at the PR stage.

## Where the work stopped

- Step 1 built and pushed; PR open.
