# Backlog #465: tie the debt-note tags to the concept map with a test

Issue: https://github.com/sonderbot-ar/warren/issues/465 (from the gatekeeper on PR #464) · Branch `backlog-465-note-tags-map` · Version v0.10.9 (a backlog patch). Test only: no reading module changes, so the reading rules and their fingerprint stay as they are (v11).

## Problem

v0.10.8 (#451 item 3) added `facts.NOTE_TAGS` (`domains/fundamentals/facts.py`, beside `SMALLEST_ROUNDING_UNIT`): the `debt_current` tags read from the debt note rather than the balance sheet, so the rounding margin never treats a note figure as a rounded twin of a lease-inclusive balance-sheet figure. It names `us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` by hand. The concept map reads the same tag into `debt_current` (priority 2, CAT only, `concept_map.csv` line 24). Nothing ties the two: if the map's tag were renamed or replaced, or a second note tag were added to `debt_current`, the guard would silently stop matching and the 6,195M case (`test_a_note_figure_is_never_a_rounded_twin`) would still pass, since it builds its facts with the tag by hand. A guard that stops matching lets the rounding margin (`facts.current_on_noncurrent_basis`) compare CAT's note figure with a lease-inclusive balance-sheet figure again, the case #451 item 3 closed; CAT files no lease-inclusive current tag today, so nothing would move until it did.

## Plan

- **Step 0.** This design doc.
- **Step 1. One test** (`tests/analysis/test_current_lease_debt.py`, `test_note_tags_are_the_maps_debt_note_tags`), on today's shipped concept map (`load_concept_map()` with no arguments: `concept_map.csv` and `concept_map_reported.csv` on disk, not an archived map in force for a stored run). Company-scoped rows count like global ones (line 24 is CAT only):
  - `NOTE_TAGS` is not empty, and every entry is a `debt_current` tag in the map;
  - every `debt_current` tag is either the balance-sheet line (`us-gaap:LongTermDebtCurrent`, named in the test as `BALANCE_SHEET_CURRENT`) or in `NOTE_TAGS`, and no tag is both. A new `debt_current` tag therefore fails the test until someone places it on one side on purpose: a balance-sheet tag goes into `BALANCE_SHEET_CURRENT` in the test, a note tag into `NOTE_TAGS` in `facts.py`. Adding a map row changes the map's hash, and adding a tag to `NOTE_TAGS` changes `facts.py` and so the reading-rules fingerprint, as any map or guard change already does; this test changes neither.
  - Exit: the test passes on `main`'s code; it fails when the tag in `NOTE_TAGS` is misspelt, and when the map's line 24 names another tag (both checked by hand, below); full suite, `ruff check .` and `ruff format --check .` clean.

## Alternatives considered

- **Derive `NOTE_TAGS` from the map** (a column or a note marker). Changes the map's schema and its hash, and so every stored run's map fingerprint, for one row. Rejected; the issue asks for a test.
- **Only the first direction** (every `NOTE_TAGS` entry is in the map). Catches a rename, but not a new note tag added to `debt_current` without the guard. Rejected; the issue asks for both.
- **Check the archived maps too.** Maps before #341 have no note tag, and `NOTE_TAGS` acts on facts by their tag, so an older map can only read fewer note facts, never mislabel one. Not needed.

## Files to change

`tests/analysis/test_current_lease_debt.py`, this doc; after merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

None. No value, run, note, param, lesson or output changes; nothing added, renamed or removed. Brief questions served or broken: none.

## Results

- The test passes on `main`'s code (86 passed in the file).
- Misspelling the tag in `NOTE_TAGS` (`…NextTwelveMonth`): the test fails. Replacing the map's line 24 tag with `us-gaap:LongTermDebtCurrentMaturities`: the test fails. Both files restored after; each run was `python -m pytest -q tests/analysis/test_current_lease_debt.py -k note_tags`.
- Full suite: 2,620 passed, 10 skipped.

## Review notes

Design review, nov.18.2026: test-only, one assertion set on a constant and a CSV, no method or number for the analyst or professor to judge, and no product impact for the product lead; the explainer and the gatekeeper review it.

- **Explainer.** Restated the change correctly. Gaps taken into the doc: which map is loaded (the shipped files, not an archived one), that company-scoped rows count, how a second balance-sheet tag is added, what a new row does to the fingerprints, and what a guard that stops matching would do. Left as is: the archived-map claim (an older map reads fewer tags, and `NOTE_TAGS` acts on a fact's own tag, so it cannot mislabel one) and the hand checks (the commands are the two edits named under Results, run with `pytest -k note_tags`).
