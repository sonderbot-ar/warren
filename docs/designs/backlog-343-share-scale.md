# Backlog #343: a share count filed in the wrong unit is named, and never used

Issue: https://github.com/sonderbot-ar/warren/issues/343 · Branch `backlog-343-share-scale` · Version v0.9.66 (to merge)

## Problem

Coca-Cola's 10-Q filed in 2019 (accession 0000021344-19-000028) tags its weighted diluted shares (`us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding`) as 4,306. The figure is in millions, but the filing gives it no scale: the cover page of the same filing says 4,266,115,111 shares. Warren takes the value as filed.

What that does today (`domains/analysis/math_engine.py`, `_shares`):

1. **Value per share is right.** Warren divides by the cover-page count; the diluted count is only a check and a fallback.
2. **The check says the wrong thing.** Cover and diluted differ by more than 10%, so the run carries `shares_cover_differs`, whose lesson tells a student to look for "a buyback, a share issue or a figure filed in the wrong unit". A gap of a factor of a million is never a buyback; the note should say which it is.
3. **The fallback would be wrong by a million.** A run with no cover-page count falls back to the newest diluted count. If that is a mis-scaled figure, the market value, and every per-share figure, would be off by a factor of 1,000 or 1,000,000, with nothing to stop it.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A scale test, and its own note.** In `math_engine.py`:
  - `share_scale(larger_or_smaller, other)` returns 1,000 or 1,000,000 when the ratio of two share counts (either way round) is within `SHARES_TOLERANCE` (10%) of that power of a thousand, else `None`. A thousand is the step between units in filings (thousands, millions); no split or buyback comes near it (the largest split in the universe is Apple's 7-for-1). Counts are compared after the split adjustment `_shares` already makes.
  - In `_shares`, when cover and diluted differ by more than 10% and `share_scale` finds a factor, the run notes `shares_scale_mismatch` instead of `shares_cover_differs`: params `cover_shares_adjusted`, `diluted_shares_adjusted`, `scale` (1000 or 1000000), and `diluted_accession_no` and `diluted_period_end` so the app can link the filing. English: "Diluted shares (4,306) look filed in the wrong unit: the cover page (4,266,115,111) is about 1,000,000 times larger; the cover-page count is used". Value per share is unchanged (the cover count was already used).
  - The code joins `RUN_NOTE_CODES` (`domains/analysis/coded.py`) and gets a lesson in `text.WARNING_LESSONS` (group `data`, param `tolerance`, reference the Inline XBRL 1.1 specification (the `scale` attribute of `ix:nonFraction`, which turns a figure shown in millions into the stored value; the professor to confirm the citation), Warren rule `math_engine.share_scale`).
  - `shares_cover_differs`'s lesson drops "or a figure filed in the wrong unit" (that case has its own code now).
  - Tests (`tests/analysis/test_build_warning_codes.py`, `tests/analysis/test_share_scale.py`): a diluted count at 1/1,000 and 1/1,000,000 of the cover gives `shares_scale_mismatch` and no `shares_cover_differs`; a count 1,000× too large does too; a 50% gap still gives `shares_cover_differs`; a ratio of 700 or 1,300 (outside 10% of 1,000) gives `shares_cover_differs`; `share_scale` property test (Hypothesis): symmetric, `None` for any ratio within 10% of 1, and found for every count scaled by 1,000 or 1,000,000 times a factor within 10%. The lesson test's `THRESHOLDS` gains the code.
  - Exit: tests pass; ruff clean.
- **Step 2. The fallback never uses a mis-scaled count.** When there is no cover count, `_shares` takes the newest diluted count whose scale agrees with the median of the history's diluted counts (split-adjusted); a newer one that `share_scale` puts 1,000 or 1,000,000 away from that median is skipped, with `shares_scale_mismatch` (params as above, `cover_shares_adjusted` replaced by `median_diluted_adjusted`; the text says which count was used). If no diluted count agrees (fewer than one), the run stops with an `EngineError` naming the filings, as it does today when there is no count at all.
  - Tests: Test Corp without the cover tag and with its newest diluted count divided by 1,000,000: the run uses the previous quarter's count and notes the skip; with every diluted count consistent, nothing changes (existing fallback test). Divided by 1,000 also skipped.
  - Exit: tests pass.
- **Step 3. Real data.** On the snapshot (nov.10): list every `diluted_shares` and `shares_outstanding` fact whose value is a power of 1,000 away from the same company's neighbouring facts (a one-off SQL check, results here, not committed code); rebuild every stored run and count the notes that move from `shares_cover_differs` to `shares_scale_mismatch`; check that no stored run's values change (`reproduce --all`, `rebuild` values). Exit: the counts written here, every stored run reproducing.

## Alternatives considered

- **Fix the scale in the stored fact** (multiply 4,306 by 1,000,000 at ingest). Rejected: facts are stored as filed (Decision 2), and an earlier change of that kind (the flipped sign, #280; a part tagged as the whole, #322) was an amendment to Decision 2 approved by the owner. Here the engine never needs the corrected number: it already uses the cover count, and the fallback can use a consistent earlier count. So the fix stays in the engine and needs no decision.
- **Rescale the mis-scaled count in the fallback** instead of skipping it. Rejected: guessing the unit is a step further than refusing a figure; the previous quarter's count is a filed number and is at most three months older.
- **Leave `shares_cover_differs` and add a `scale` param.** Rejected: the two cases teach different things (a real difference between two counts against a filing error), and the app shows one lesson per code.

## Known limits

- A figure off by a factor that is not a power of a thousand (a typo, a wrong decimal) still shows as `shares_cover_differs`; that is the right note for it.
- The fallback's median needs at least two diluted counts in the history; with one, there is nothing to compare and it is used as before.

**Point in time.** Nothing new is read: the check uses the counts the run already loads as of its date. **LLMs.** None. **Decision 11.** No source, company or currency change. **Stored runs.** Notes are stored with each run and not changed; values never change, so `reproduce` and `rebuild` hold (rebuild compares values and method text; notes are rebuilt but not compared).

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `tests/analysis/test_build_warning_codes.py`, `tests/analysis/test_warning_lessons.py`, a new `tests/analysis/test_share_scale.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the run warnings the app shows (the "Datos" group, v0.9.60), and every question that shows a value per share (Q1–Q5), which do not change. Added: run-note code `shares_scale_mismatch` (group `data`; params `cover_shares_adjusted` or `median_diluted_adjusted`, `diluted_shares_adjusted`, `scale`, `diluted_accession_no`, `diluted_period_end`) and its lesson (param `tolerance`). Changed: `shares_cover_differs`'s English lesson loses its last clause ("or a figure filed in the wrong unit"); its params are unchanged. Nothing renamed or removed. Effect on the front-end team: add the new code and its lesson to the Spanish catalogue (#344), and drop the same clause from the Spanish `shares_cover_differs` lesson.
