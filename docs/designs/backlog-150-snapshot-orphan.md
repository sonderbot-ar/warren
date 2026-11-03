# Backlog #150: a snapshot whose archive never landed

## Problem

On nov.03.2026 the M10 grid run saved a snapshot whose manifest reached the project's shared folder but whose 934 MB archive did not. The next run's `restore` stopped at that manifest with "missing or does not match its SHA-256" instead of using the good snapshot just before it, although its docstring promised "the newest good snapshot" (`shared_kernel/snapshot.py`, `restore`). Worse, `save` keeps the newest two manifests, so the orphan would have counted as one of them and the next save would have deleted the last good archive.

## Plan

- **Step 0.** This design doc.
- **Step 1.** `restore` tries manifests newest first and uses the first whose archive exists and matches its SHA-256; each one it passes over is listed in the result's `skipped` and printed by the command. With no good one it fails and names every manifest it tried. `save` counts toward the two it keeps only manifests whose archive sits beside them at the stated size; an orphan is left alone for a person to look at, as an odd manifest already is. Tests: restore skips an orphan and restores the older snapshot; only orphans → refused, named; good, orphan, good → both good archives stay; a fourth save prunes the oldest good one. Exit: the three tests pass with the existing 16.

## Alternatives considered

- **Delete orphans on save.** Rejected: an orphan may be an upload still in flight from another machine; leaving it costs 1.5 KB.
- **Re-read the archive after writing and refuse to write the manifest if it differs.** Already done in effect (`_sha256(archive)` reads the file in the folder); it cannot catch a shared folder that drops the file after the machine goes away, which is what happened.
- **Smaller snapshots** (leave rebuildable event rows out). Worth doing separately; it changes what a restore holds, so it needs its own design.

## Files

`shared_kernel/snapshot.py`, `tests/shared_kernel/test_snapshot.py`.

## Product impact

None. No engine output, name or field changes; no brief question is affected.
