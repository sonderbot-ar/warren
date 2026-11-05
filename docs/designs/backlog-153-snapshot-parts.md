# Backlog #153: snapshots the shared folder actually keeps

## Problem

On nov.03.2026 four snapshot archives (759 MB to 1.12 GB) never reached the project's shared folder; their small manifests did. The folder is an rclone mount with a write-back cache (`vfs_cache_mode: full`, `vfs_cache_max_size: 1G`). A 759 MB archive stayed "dirty" (not uploaded) for over an hour on a running machine, while a 361 MB file written to the same mount uploaded within minutes, and the 521 MB archive of 00:12 had landed. Every file that landed was under 512 MiB; every one above it was lost. As the database grows (the M10 grid nearly doubled it), every future snapshot would be lost.

## Plan

- **Step 0.** This design doc.
- **Step 1.** `save` builds the archive on local disk, then copies it into the folder as parts `warren-<stamp>.tar.gz.part000`, `.part001`, … of at most `PART_BYTES` (400 MB) each, each written as `.partial` and renamed. The manifest keeps the whole archive's SHA-256 and size and adds `parts`, each with its name, size and SHA-256; it is written last. `restore` checks every part's hash and unpacks the parts as one stream (no second copy on disk). A part's name must be `<archive>.partNNN` in order, beside the manifest, as the archive's name already must (#104). A manifest without `parts` (v0.9.4 and earlier) is read as before. Prune deletes every part; a manifest counts toward the two kept only when all its parts are there at their stated sizes (#150).
  Tests: a multi-part save restores exactly and no part exceeds `PART_BYTES`; a missing middle part makes the snapshot an orphan (skipped on restore, not counted by prune); a part with another name is refused; an older single-file snapshot still restores and is pruned. Real data: a 761 MB snapshot saved as 400 MB + 361 MB and restored in 26 s with all rows.
  Exit: tests pass; the 361 MB part uploaded through the shared folder (checked on nov.03).

## Alternatives considered

- **Leave rebuildable rows out** (events from `news rebuild-events`). Smaller, but a restore would then need a rebuild step and the snapshot would hold less than the database; it changes what a restore means. Parts fix the limit without that.
- **Wait for the upload before returning.** Doesn't help: an archive over the limit never uploads.

Disk: `save` needs about twice the archive size free on local disk (the database copy plus the archive, both in the system temp folder) before copying parts out.

## Files

`shared_kernel/snapshot.py`, `tests/shared_kernel/test_snapshot.py`.

## Product impact

None. No engine output, name or field changes.
