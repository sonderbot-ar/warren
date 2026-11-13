# Backlog #343: a share count filed in the wrong unit is named, and never used

Issue: https://github.com/sonderbot-ar/warren/issues/343 · Branch `backlog-343-share-scale` · Version v0.9.66 (PR open)

## Problem

Coca-Cola's 10-Q filed in 2019 (accession 0000021344-19-000028) tags its weighted diluted shares (`us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding`) as 4,306. The figure is in millions, but the filing gives it no scale: the cover page of the same filing says 4,266,115,111 shares. Warren takes the value as filed.

What that does today (`domains/analysis/math_engine.py`, `_shares`):

1. **Value per share is right.** Warren divides by the cover-page count; the diluted count is only a check and a fallback.
2. **The check says the wrong thing.** Cover and diluted differ by more than 10%, so the run carries `shares_cover_differs`, whose lesson tells a student to look for "a buyback, a share issue or a figure filed in the wrong unit". A gap of a factor of a million is never a buyback; the note should say which it is.
3. **The fallback would be wrong by a million.** A run with no cover-page count falls back to the newest diluted count. If that is a mis-scaled figure, the market value, and every per-share figure, would be off by a factor of 1,000 or 1,000,000, with nothing to stop it.

## Plan

- **Step 0.** This design doc. No build plan change (backlog item).
- **Step 1. A scale test, and its own note.** In `math_engine.py`:
  - `share_scale(a, b)` returns 1,000 or 1,000,000 when the ratio of two share counts (either way round) is within `SHARES_TOLERANCE` (10%) of that power of a thousand, else `None`. A thousand is the step between units in filings (thousands, millions); no split or buyback comes near it (the largest split in the universe is Apple's 7-for-1). Counts are compared after the split adjustment `_shares` already makes.
  - In `_shares`, when `share_scale` finds a factor between the cover and the newest diluted count, the run notes `shares_scale_mismatch` instead of `shares_cover_differs`: params `cover_shares_adjusted`, `tolerance`, `diluted_shares_adjusted`, `scale` (1000 or 1000000), and `diluted_accession_no` and `diluted_period_end` so the app can link the filing. English: "Cover-page shares (4,266,115,111) and diluted shares (4,306) are about 1,000,000 times apart, so one was filed in the wrong unit; the cover-page count is used". The text does not say which count is wrong: beside the cover page it cannot tell (see Known limits). Value per share is unchanged (the cover count was already used).
  - The code joins `RUN_NOTE_CODES` (`domains/analysis/coded.py`) and gets a lesson in `text.WARNING_LESSONS` (group `data`, param `tolerance`, reference the SEC Office of Structured Disclosure notice *Scaling Errors Between Entity Common Stock Shares Outstanding and Common Stock Shares Outstanding* (Nov 19, 2020; professor, design review: KO's 2019 10-Q is plain XBRL, so an Inline XBRL `scale` citation would name a mechanism it does not use), Warren rule `math_engine.share_scale`).
  - `shares_cover_differs`'s lesson keeps "or a figure filed in the wrong unit" (product lead, design review): stored runs keep their old notes, including KO 2019's, whose cause is exactly that, and a unit error that is not a power of a thousand (a typo, a wrong decimal) still lands there.
  - Tests (`tests/analysis/test_build_warning_codes.py`, `tests/analysis/test_share_scale.py`): a diluted count at 1/1,000 and 1/1,000,000 of the cover gives `shares_scale_mismatch` and no `shares_cover_differs`; a count 1,000× too large does too; a 50% gap still gives `shares_cover_differs`; a ratio of 700 or 1,300 (outside 10% of 1,000) gives `shares_cover_differs`; `share_scale` property test (Hypothesis): symmetric, `None` for any ratio within 10% of 1, and found for every count scaled by 1,000 or 1,000,000 times a factor within 10%. The lesson test's `THRESHOLDS` gains the code.
  - Exit: tests pass; ruff clean.
- **Step 2. The fallback never uses a mis-scaled count.** When there is no cover count, `_shares` takes the newest diluted count whose unit agrees with the history's middle diluted count (split-adjusted; the lower middle one when the count is even, so it is a filed count and always agrees with itself, and the fallback always finds one). A newer count that `share_scale` puts 1,000 or 1,000,000 away from the middle is skipped, with `shares_scale_mismatch` (params `median_diluted_adjusted`, `tolerance`, `diluted_shares_adjusted`, `scale`, `diluted_accession_no`, `diluted_period_end`; text "Diluted shares for 2020-03-31 (0) look filed in the wrong unit: the history's middle count (100) is about 1,000,000 times larger; that count is not used"). With one diluted count there is nothing to compare, and it is used as before.
  - Tests: Test Corp without the cover tag and with its newest diluted count divided by 1,000,000: the run uses the previous quarter's count and notes the skip; with every diluted count consistent, nothing changes (existing fallback test). Divided by 1,000 also skipped.
  - Exit: tests pass.
- **Step 3. Real data.** On the snapshot (nov.10): list every `diluted_shares` and `shares_outstanding` fact whose value is a power of 1,000 away from the same company's neighbouring facts (a one-off SQL check, results here, not committed code); rebuild every stored run and count the notes that move from `shares_cover_differs` to `shares_scale_mismatch`; check that no stored run's values change (`reproduce --all`, `rebuild` values). Exit: the counts written here, every stored run reproducing.

## Real data (Step 3, nov.13.2026)

Snapshot of nov.10.2026 (903 stored baseline runs), restored on this run.

- **Scan.** Of 3,904 share-count facts (diluted and cover page) for the eight companies, the only ones a power of a thousand away from their neighbours are Coca-Cola's: its 10-Qs 0000021344-18-000023 (Q1 2017 comparatives), 0000021344-18-000042 (Q3 2017 and 2018) and 0000021344-19-000028 (Q1 2018 and 2019) file weighted shares in millions with no scale, and the 10-Q 0000021344-19-000034 files Q2 2018 in units while its neighbours are those millions. No cover-page count is off by a power of a thousand, so the case in Known limits (a wrong cover count) does not occur in the data.
- **Notes.** Every stored run rebuilt in memory on this branch: the 5 stored `shares_cover_differs` notes (KO 2019-05-01, 05-15, 06-01, 07-01, 07-23) become `shares_scale_mismatch` (4,266,115,111 against 4,306, scale 1,000,000); no other run gains or loses a share note. Stored notes are not rewritten (product lead): those five runs keep their old note, whose lesson still names a wrong unit.
- **Values.** The runs whose rebuilt rows differ in value are the same 82 on `main` and on this branch, with the same rows (the runs v0.9.41, #264, already rebuilds differently; none on `shares` or market value); `reproduce --all`: 903 of 903 OK. No stored run used the fallback on a mis-scaled count.

## Alternatives considered

- **Fix the scale in the stored fact** (multiply 4,306 by 1,000,000 at ingest). Rejected: facts are stored as filed (Decision 2), and an earlier change of that kind (the flipped sign, #280; a part tagged as the whole, #322) was an amendment to Decision 2 approved by the owner. Here the engine never needs the corrected number: it already uses the cover count, and the fallback can use a consistent earlier count. So the fix stays in the engine and needs no decision.
- **Rescale the mis-scaled count in the fallback** instead of skipping it. Rejected: guessing the unit is a step further than refusing a figure; the previous quarter's count is a filed number and is at most three months older.
- **Leave `shares_cover_differs` and add a `scale` param.** Rejected: the two cases teach different things (a real difference between two counts against a filing error), and the app shows one lesson per code.

## Known limits

- Dual-class companies: a count of one class against an as-converted count of another can sit near a power of a thousand (Berkshire's B shares against its A-equivalent count, about 1,500×). No dual-class company of that kind is in the Phase 1 universe; a company added later would need a look (professor, design review).
- The SEC's own check (the OSD notice above) flags counts more than a hundredfold apart; a 100× error is not caught here and still shows as `shares_cover_differs`, whose lesson still names a wrong unit.

- A figure off by a factor that is not a power of a thousand (a typo, a wrong decimal) still shows as `shares_cover_differs`; that is the right note for it.
- The fallback's middle count needs at least two diluted counts in the history; with one, there is nothing to compare and it is used as before. If most of the history were filed in the wrong unit, the middle count would be too; a filer that consistent is not one we have seen.
- Beside a cover count, Warren cannot tell which of the two is in the wrong unit, so the note does not say. If the cover count itself were the wrong one, value per share would be off by the factor; Step 3 checks whether any cover count in the data is. Choosing between them by the diluted history is left for later unless Step 3 finds a case.

**Point in time.** Nothing new is read: the check uses the counts the run already loads as of its date. **LLMs.** None. **Decision 11.** No source, company or currency change. **Stored runs.** Notes are stored with each run and not changed; values never change, so `reproduce` and `rebuild` hold (rebuild compares values and method text; notes are rebuilt but not compared).

## Files to change

`domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `tests/analysis/test_build_warning_codes.py`, `tests/analysis/test_warning_lessons.py`, a new `tests/analysis/test_share_scale.py`, this doc; at merge `docs/versions.md` and `docs/team-sync.md`.

## Product impact

Brief: the run warnings the app shows (the "Datos" group, v0.9.60), and every question that shows a value per share (Q1–Q5), which do not change. Added: run-note code `shares_scale_mismatch` (group `data`; params `cover_shares_adjusted` beside a cover count, or `median_diluted_adjusted` in the fallback, plus `tolerance`, `diluted_shares_adjusted`, `scale`, `diluted_accession_no`, `diluted_period_end`) and its lesson (param `tolerance`). The note names the count left out; the count used and its filing are in the `shares` assumption's source (*Fuente*), not in the note. In the fallback, a run can carry more than one `shares_scale_mismatch` (one per newer count skipped), so a screen should group them. Unchanged: `shares_cover_differs`, its params and its lesson. Nothing renamed or removed. Stored runs keep their notes: the runs whose `shares_cover_differs` was a unit error are listed under Step 3's results, so the app can tell them apart if it wants. Effect on the front-end team: add the new code and its lesson to the Spanish catalogue (#344).

## Design review (nov.13.2026)

Built with its tests before review (Steps 1–2), as on #322. Professor and product lead in parallel; the analyst on the real data at Step 3.

- **Professor: NO-GO, one blocker, taken.** The lesson cited Inline XBRL's `scale` attribute, but KO's 2019 10-Q is plain XBRL (a separate instance file), so that names a mechanism the motivating filing does not use: the reference is now the SEC Office of Structured Disclosure notice on scaling errors in share counts (Nov 19, 2020). Suggestions **taken**: "no buyback does (splits are already adjusted for)", since a 1-for-1,000 reverse split exists at microcaps and splits are adjusted before the test; dual-class companies and the SEC's hundredfold test in Known limits. Method judged defensible; skipping rather than rescaling judged right (Decision 2). DQC_0095 could not be opened from the session (xbrl.us blocked), so it is not cited.
- **Product lead: NO-GO, one blocker, taken.** Dropping "or a figure filed in the wrong unit" from `shares_cover_differs`'s lesson would make stored runs (KO 2019 among them) show a lesson that rules out their own cause: the clause stays. Asked Product impact to say the count used is in the `shares` assumption's source and that the fallback can give more than one note: **taken**. Nothing in `webapp/` reads run notes yet; the Spanish text goes to #344.
