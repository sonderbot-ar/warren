# Backlog #157: net margin on net income to the parent (front-end R1)

Issue #157 (front-end, follow-up to #140, `docs/designs/backlog-140-reported-figures.md`, "Net margin is left out"). Branch `backlog-157-net-margin`.

Status: Done (nov.05.2026; v0.9.19, PR #209, merge `9c3910d`; gatekeeper GO, follow-ups in #210).

## Problem

The reported-figures call (v0.9.6, `domains/analysis/reported.py`) gives a student gross margin, operating margin, growth, capex and D&A shares, the tax rate and net debt, but no net margin, the ratio most students ask about first. The only net income the concept map holds is `us-gaap:ProfitLoss` (`net_income_including_nci`, `concept_map.csv`), which under US GAAP is consolidated net income including the non-controlling (minority) interests' share, and which Apple, Microsoft and Johnson & Johnson (since 2015) don't tag. The textbook net margin is net income attributable to the parent's shareholders over revenue (CFA Institute, Level I, *Financial Analysis Techniques*; IAS 1.81B and ASC 810 split profit into the parent's and the non-controlling interests' parts), which seven of the eight tag as `us-gaap:NetIncomeLoss` (Caterpillar since 2012 only as `NetIncomeLossAvailableToCommonStockholdersBasic`).

A second trap: net income includes discontinued operations. Johnson & Johnson's 2023 net income holds about $21bn from the Kenvue exit (#140 analyst), so its net margin is about 41% against about 16% from continuing operations. A student must be told, not left to find it.

## The catch: the concept map's fingerprint

Every run stores the SHA-256 of `concept_map.csv` (`runs.concept_map_sha256`). `runs.rebuild` refuses a run whose map differs ("concept_map.csv changed since the run, it can't be rebuilt", `domains/analysis/runs.py`), the pipeline reuses a run only when the map is the same (`domains/orchestration/nodes.py`), and a run warns `concept_map_changed` when the last ingest used another map (`math_engine.build_inputs`). The fingerprint is of the whole file, so adding one row to it would make all of the 903 stored runs impossible to rebuild (`runs.rebuild`) and warn `concept_map_changed` on every new one, although the valuation never reads the new items (it asks `get_facts` for its own `ITEMS` only; `math_engine.py`).

So the new items go in a **second file, `domains/fundamentals/concept_map_reported.csv`**: same columns and rules, for items that only the reported-figures query reads. `load_concept_map()` reads both and validates them as one map (a tag still maps to one name across both files; a name lives in one file), so ingest and the `concepts` table see every item. `concept_map_sha256()` stays the fingerprint of `concept_map.csv` alone, the file that can change a valuation, so every stored hash still matches. A test fails if any name in the reported-only file appears in the valuation's `ITEMS`, the evaluation's or the AI step's item lists, so an item can't move into a valuation without moving files and changing the fingerprint.

## What changes

**New items** (`concept_map_reported.csv`, both `gate` optional so a company without them never fails the M1 quality gate):

| Item | Tags, by priority | Meaning |
|---|---|---|
| `net_income` | `us-gaap:NetIncomeLoss`, then `us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic` (Caterpillar 2012+; after preferred dividends, equal for a company with no preferred stock, and none of the eight has any) | Net income attributable to the parent's shareholders (after the non-controlling interests' share; includes discontinued operations) |
| `discontinued_operations` | `us-gaap:IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity` (the parent's share, net income's basis; JNJ, KO), then `us-gaap:IncomeLossFromDiscontinuedOperationsNetOfTax` (PG to 2019, WMT to 2017) | Income (loss) from discontinued operations, net of tax |

**New ratio** in `reported.py`: `net_margin`, `formula_id` `net_income_to_parent_over_revenue`, formula "net income attributable to the parent ÷ revenue", through `financial_math.ratio` like the others. It can be negative (a loss). When `net_income` is not reported: `missing` `not_reported`. `uses` lists `net_income` and `revenue`. When the period reports discontinued operations that are not exactly zero, a coded note `includes_discontinued_operations` with params `amount` (raw, unscaled, in `currency`), `currency` and, only when it is a share, `share_of_net_income`; `uses` then lists `discontinued_operations` between the two, so the app can show both lines. The share is computed by `financial_math.ratio`; the key is absent (not null) when net income is zero or negative, or the discontinued amount is negative or larger than net income (then it is not a share). Missing net income gives `missing` = `{code: not_reported, params: {items: [net_income]}, text}`, the #140 shape. A quarter that can't be derived (no line) gets no note.

**No ProfitLoss fallback.** A net margin that silently mixed in minority interests for some companies and not others would break a cross-company comparison (brief Q2); a gap is honest.

## Steps

- **Step 0.** This design doc; the issue's ask restated with the fingerprint catch.
- **Step 1.** The second file and its loader: `concepts.CONCEPT_MAP_REPORTED_PATH`, `load_concept_map(path=None)` reading both (a `path` argument still reads one file, for tests), cross-file validation, `concept_map_sha256()` unchanged. Tests (`tests/fundamentals/test_concepts.py`): the shipped maps load together and hold `net_income`; a tag in both files is rejected; a name split across both files is rejected; the fingerprint equals the SHA-256 of `concept_map.csv`'s bytes (so an edit of the reported file leaves it alone); no reported-only name is in the valuation, evaluation or AI item lists. Exit: every stored run's fingerprint still matches.
- **Step 2.** `net_margin` in `reported.py`, with the note. Test Corp gains `NetIncomeLoss` (75% of pretax) in `tests/analysis/conftest.py`. Tests (`tests/analysis/test_reported.py`): net margin on a year and a derived Q4 equals net income ÷ revenue by construction; a fixture without `NetIncomeLoss` gives the coded gap; a fixture with discontinued operations gives the note with amount and share, and its line in `uses`; a loss gives a negative margin and a note without a share; existing Test Corp runs reproduce to the cent (the fixture change touches no valuation item).
- **Step 3.** Real data: re-ingest the eight companies from the cached filings (`fundamentals ingest --all`; the cache holds the filings, so no download), then: the M1 quality report still passes its gate; `analysis reproduce --all` reproduces every stored run; `reproduce --rebuild` on a sample of runs still rebuilds (the fingerprint holds); net margins for each company's last three fiscal years, checked against the 10-K for at least Walmart (non-controlling interests), Caterpillar FY2024 (10,792 / 64,809), Johnson & Johnson 2023 (Kenvue) and 2022 as of before and after the FY2023 10-K (the restated 1,571m), and Apple. JNJ before FY2010 shows the coded gap (it tagged ProfitLoss then). The re-ingest adds an `ingest_runs` row, so, as after any ingest, the pipeline builds fresh runs rather than reusing stored ones (`nodes.py`); that is the ingest's effect, not the map's. Results in "Results on real data".

**Exit criterion:** all tests pass; on real data every stored run reproduces, a rebuild sample still rebuilds, and the net margins match the filings; `docs/team-sync.md` names the new ratio, items and note.

## Design review (nov.05.2026)

- **Analyst** (accept with changes). Blockers, both fixed: (1) Caterpillar tags `NetIncomeLoss` only to FY2010 and since then its profit to common shareholders as `NetIncomeLossAvailableToCommonStockholdersBasic` (FY2024 10,792m), so it would have had no net margin: added as priority 2. (2) Coca-Cola tags both discontinued tags and they differ (2017: 101m total, 67m the parent's): the parent's share now ranks first, on net income's basis. Changes taken: the doc no longer claims the second file keeps pipeline reuse (any ingest ends it, `nodes.py:180`); JNJ 2022 restated and the pre-2010 gap added to Step 3; counts corrected (ProfitLoss is tagged by 5 of 8; 903 stored runs, all on today's fingerprint). Ideas to the follow-up issue: a hint on quarters that can't be derived; storing the reported file's hash in `ingest_runs`.
- **Professor** (accept with changes). Discontinued tag order (same as the analyst's, fixed). Wording "non-controlling (minority) interests" for IFRS-trained students (IAS 1.81B; ASC 810, since SFAS 160), and the `net_income` definition says why `ProfitLoss` is not the bottom line a student knows from IAS 1: done in the CSV notes. A share above 100% or below 0 is left out, with a test. The split is explained in `concepts.py`'s docstring and the build plan's Concept map entry. Penman citation dropped; CFA Institute and IAS 1 cited. Ideas (Spanish terms "utilidad neta atribuible a la controladora", a GAAP vs IFRS lesson) go to the front-end team.
- **Explainer.** Gaps closed in the text above: the note's params and when the share is absent, `uses`, "not zero" means exactly zero, which tag wins when both are present (priority), `missing`'s shape, and that `load_concept_map(path)` with one path reads that file alone (cross-file checks apply to the files given).
- **Product lead.** Codes and params now stated as the #140 shape; `uses` stated; Q2 as written asks for operating margin, so net margin *adds to* Q2 (the brief's §5 said no question needs it yet) rather than being required by it; amounts are raw, unscaled, with `currency`.

## Results on real data (Step 3, nov.05.2026)

Snapshot `warren-20261104T202442Z` restored. `fundamentals ingest --all` from the cached filings added 2,775 facts, all of them the two new items (2,463 net income, 312 discontinued operations); no other fact changed. The M1 quality report still has 0 unexplained gaps for all eight. `analysis reproduce --all`: 903 of 903 runs reproduced to the cent, and all 903 still carry today's fingerprint (`2a2636…`). `reproduce --rebuild` on the two newest runs of each company (16): all rebuilt to identical rows.

Net margin by fiscal year as known on 2026-11-04, each net income and revenue checked against the 10-K's income statement:

| Company | Three latest fiscal years | Note |
|---|---|---|
| Apple | 25.3%, 24.0%, 26.9% (FY2023–25; FY2024 93,736 / 391,035) | |
| Microsoft | 36.0%, 36.2%, 40.3% (FY2024–26) | |
| Walmart | 2.4%, 2.9%, 3.1% (FY2024–26; FY2024 15,511 to the parent, against 16,270 consolidated) | |
| Coca-Cola | 23.4%, 22.6%, 27.3% (2023–25) | |
| P&G | 17.7%, 19.0%, 18.4% (FY2024–26) | FY2017: 23.6%, with 5,217m from the Beauty sale to Coty (34% of net income) |
| Johnson & Johnson | 41.3%, 15.8%, 28.5% (2023–25) | 2023: 21,827m from discontinued operations (Kenvue), 62% of net income; so about 15.6% without it |
| Caterpillar | 15.4%, 16.7%, 13.1% (2023–25; 2024 10,792 / 64,809, through the priority-2 tag) | |
| Exxon | 10.4%, 9.6%, 8.7% (2023–25) | |

Johnson & Johnson FY2022, point in time: as of 2024-02-15 (before the FY2023 10-K), 18.9% on revenue of 94,943m and no note; as of 2024-02-17, 22.4% on the restated revenue of 79,990m, with 1,571m of discontinued operations (9% of net income) and the `uses_changed_line` note for revenue. JNJ FY2009 gives the coded gap `not_reported` (it tagged only ProfitLoss then). JNJ's FY2023 Q4 (tagged in the 10-K) carries the note with −83m and no share (a loss). Apple's latest quarter (FY2026 Q3, a 10-Q) gives 27.2%.

## Alternatives considered

- **Add the rows to `concept_map.csv`** (the issue's ask as written). Rejected: it changes the fingerprint every run stores, so no stored run could be rebuilt again and the pipeline would rebuild everything (above).
- **Fingerprint only the valuation's items inside one file.** Works, but the rule would live in code and a reader of the CSV couldn't see which rows count; old fingerprints are of the whole file's bytes, so matching them would need the new rows to sit last and be cut out by text. Two files say it plainly.
- **Net margin on `ProfitLoss`, labelled "including minority interests".** Rejected in #140 and again here: few of the eight tag it and it is not the textbook ratio.
- **Net margin from continuing operations** (`IncomeLossFromContinuingOperations`). It mostly includes minority interests, and companies tag it unevenly. The note with the discontinued amount lets the app show both numbers without a second definition.
- **Exxon's tax-rate note** (analyst idea in #157). Different item and needs equity-method income; left for a follow-up issue.

## Product impact

Adds to brief Q2 (margins by fiscal year; Q2 as written asks for operating margin, and the brief's §5 said no question needed net margin yet) the ratio students ask about most; moves no other question. Adds to `ReportedPeriod.to_dict()`: a ratio named `net_margin` (`formula_id` `net_income_to_parent_over_revenue`), the lines `net_income` and `discontinued_operations` when reported, and the note code `includes_discontinued_operations` (`amount` raw in `currency`, `currency`, `share_of_net_income` as a fraction or absent), each `{code, params, text}` as in #140; `uses` lists `net_income`, `discontinued_operations` (only with the note) and `revenue`. Nothing is renamed or removed; existing ratios keep their values. The app must translate the new note code.

## Files to change

New: `domains/fundamentals/concept_map_reported.csv`, `docs/designs/backlog-157-net-margin.md`. Changed: `domains/fundamentals/concepts.py`, `domains/analysis/reported.py`, `tests/fundamentals/test_concepts.py`, `tests/analysis/conftest.py`, `tests/analysis/test_reported.py`; at merge `docs/versions.md`, `docs/team-sync.md`.
