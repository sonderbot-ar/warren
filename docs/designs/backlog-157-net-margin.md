# Backlog #157: net margin on net income to the parent (front-end R1)

Issue #157 (front-end, follow-up to #140, `docs/designs/backlog-140-reported-figures.md`, "Net margin is left out"). Branch `backlog-157-net-margin`.

Status: In progress (nov.05.2026).

## Problem

The reported-figures call (v0.9.6, `domains/analysis/reported.py`) gives a student gross margin, operating margin, growth, capex and D&A shares, the tax rate and net debt, but no net margin, the ratio most students ask about first. The only net income the concept map holds is `us-gaap:ProfitLoss` (`net_income_including_nci`, `concept_map.csv`), which includes the minority interests' share and is tagged by few of the eight companies. The textbook net margin is net income attributable to the parent's shareholders over revenue (CFA Level I, *Financial Analysis Techniques*; Penman, *Financial Statement Analysis and Security Valuation*, ch. 8), which every US filer tags as `us-gaap:NetIncomeLoss`.

A second trap: net income includes discontinued operations. Johnson & Johnson's 2023 net income holds about $21bn from the Kenvue exit (#140 analyst), so its net margin is about 41% against about 16% from continuing operations. A student must be told, not left to find it.

## The catch: the concept map's fingerprint

Every run stores the SHA-256 of `concept_map.csv` (`runs.concept_map_sha256`). `runs.rebuild` refuses a run whose map differs ("concept_map.csv changed since the run, it can't be rebuilt", `domains/analysis/runs.py`), the pipeline reuses a run only when the map is the same (`domains/orchestration/nodes.py`), and a run warns `concept_map_changed` when the last ingest used another map (`math_engine.build_inputs`). The fingerprint is of the whole file, so adding one row to it would make all of the 911+ stored runs impossible to rebuild and stop the pipeline from reusing any of them, although the valuation never reads the new items (it asks `get_facts` for its own `ITEMS` only; `math_engine.py`).

So the new items go in a **second file, `domains/fundamentals/concept_map_reported.csv`**: same columns and rules, for items that only the reported-figures query reads. `load_concept_map()` reads both and validates them as one map (a tag still maps to one name across both files; a name lives in one file), so ingest and the `concepts` table see every item. `concept_map_sha256()` stays the fingerprint of `concept_map.csv` alone, the file that can change a valuation, so every stored hash still matches. A test fails if any name in the reported-only file appears in the valuation's `ITEMS`, the evaluation's or the AI step's item lists, so an item can't move into a valuation without moving files and changing the fingerprint.

## What changes

**New items** (`concept_map_reported.csv`, both `gate` optional so a company without them never fails the M1 quality gate):

| Item | Tags, by priority | Meaning |
|---|---|---|
| `net_income` | `us-gaap:NetIncomeLoss` | Net income attributable to the parent's shareholders (after minority interests; includes discontinued operations) |
| `discontinued_operations` | `us-gaap:IncomeLossFromDiscontinuedOperationsNetOfTax`, then `us-gaap:IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity` | Income (loss) from discontinued operations, net of tax |

**New ratio** in `reported.py`: `net_margin`, `formula_id` `net_income_to_parent_over_revenue`, formula "net income attributable to the parent ÷ revenue", through `financial_math.ratio` like the others. It can be negative (a loss). When `net_income` is not reported: `missing` `not_reported`. When the period reports discontinued operations that are not zero, a coded note `includes_discontinued_operations` with `amount` and `share_of_net_income`, and the `uses` list names the line, so the app can show both. The share is computed by `financial_math.ratio` too; when net income is zero or negative the share is left out (no meaningful share of a loss).

**No ProfitLoss fallback.** A net margin that silently mixed in minority interests for some companies and not others would break a cross-company comparison (brief Q2); a gap is honest.

## Steps

- **Step 0.** This design doc; the issue's ask restated with the fingerprint catch.
- **Step 1.** The second file and its loader: `concepts.CONCEPT_MAP_REPORTED_PATH`, `load_concept_map(path=None)` reading both (a `path` argument still reads one file, for tests), cross-file validation, `concept_map_sha256()` unchanged. Tests (`tests/fundamentals/test_concepts.py`): the shipped maps load together and hold `net_income`; a tag in both files is rejected; a name split across both files is rejected; the fingerprint equals the SHA-256 of `concept_map.csv`'s bytes (so an edit of the reported file leaves it alone); no reported-only name is in the valuation, evaluation or AI item lists. Exit: every stored run's fingerprint still matches.
- **Step 2.** `net_margin` in `reported.py`, with the note. Test Corp gains `NetIncomeLoss` (75% of pretax) in `tests/analysis/conftest.py`. Tests (`tests/analysis/test_reported.py`): net margin on a year and a derived Q4 equals net income ÷ revenue by construction; a fixture without `NetIncomeLoss` gives the coded gap; a fixture with discontinued operations gives the note with amount and share, and its line in `uses`; a loss gives a negative margin and a note without a share; existing Test Corp runs reproduce to the cent (the fixture change touches no valuation item).
- **Step 3.** Real data: re-ingest the eight companies from the cached filings (`fundamentals ingest --all`, no new download needed for old filings), then: the M1 quality report still passes its gate; `analysis reproduce --all` reproduces every stored run; `reproduce --rebuild` on a sample of runs still rebuilds (the fingerprint holds); net margins for each company's last three fiscal years, checked against the 10-K's income statement for at least Walmart (minority interests), Johnson & Johnson 2023 (Kenvue) and Apple; results below.

**Exit criterion:** all tests pass; on real data every stored run reproduces, a rebuild sample still rebuilds, and the net margins match the filings; `docs/team-sync.md` names the new ratio, items and note.

## Alternatives considered

- **Add the rows to `concept_map.csv`** (the issue's ask as written). Rejected: it changes the fingerprint every run stores, so no stored run could be rebuilt again and the pipeline would rebuild everything (above).
- **Fingerprint only the valuation's items inside one file.** Works, but the rule would live in code and a reader of the CSV couldn't see which rows count; old fingerprints are of the whole file's bytes, so matching them would need the new rows to sit last and be cut out by text. Two files say it plainly.
- **Net margin on `ProfitLoss`, labelled "including minority interests".** Rejected in #140 and again here: few of the eight tag it and it is not the textbook ratio.
- **Net margin from continuing operations** (`IncomeLossFromContinuingOperations`). It mostly includes minority interests, and companies tag it unevenly. The note with the discontinued amount lets the app show both numbers without a second definition.
- **Exxon's tax-rate note** (analyst idea in #157). Different item and needs equity-method income; left for a follow-up issue.

## Product impact

Serves brief Q2 (margins by fiscal year) with the ratio students ask about most, and moves no other question. Adds to `ReportedPeriod.to_dict()`: a ratio named `net_margin` (`formula_id` `net_income_to_parent_over_revenue`), the lines `net_income` and `discontinued_operations` when reported, and the note code `includes_discontinued_operations` (`amount` in the line's currency, `share_of_net_income` as a fraction or absent). Nothing is renamed or removed; existing ratios keep their values. The app must translate the new note code.

## Files to change

New: `domains/fundamentals/concept_map_reported.csv`, `docs/designs/backlog-157-net-margin.md`. Changed: `domains/fundamentals/concepts.py`, `domains/analysis/reported.py`, `tests/fundamentals/test_concepts.py`, `tests/analysis/conftest.py`, `tests/analysis/test_reported.py`; at merge `docs/versions.md`, `docs/team-sync.md`.
