# Backlog #427: the current portion merge (#421), three follow-ups

Issue: https://github.com/sonderbot-ar/warren/issues/427 (from the #425 gatekeeper and analyst reviews of `docs/designs/backlog-421-current-lease-debt.md`) · Branch `backlog-427-current-merge-followups` · Version v0.9.82.

## Background

Since v0.9.81 (#421), the current portion of long-term debt is filed under two map items: `debt_current` (`LongTermDebtCurrent`, debt only) and `debt_current_with_leases` (`LongTermDebtAndCapitalLeaseObligationsCurrent`, debt plus the current finance-lease portion). When a reader asks for `debt_current` and the map in force has the second item, `facts.get_facts` reads both plus `debt_noncurrent` and merges them per balance date into one `debt_current` (`_merge_current`, `domains/fundamentals/facts.py` lines 1085–1105), choosing with `current_on_noncurrent_basis` (lines 1063–1082): the lease-inclusive figure when the same date's non-current debt is lease-inclusive, it is above the plain figure, and it is not the non-current debt again (a mis-tag). Only Exxon and Coca-Cola file the lease-inclusive tag.

## Problem

1. **Pairing on fiscal labels.** `_merge_current` keys each fact by `(period_start, period_end, fiscal_year, fiscal_period)`. Each item's fact for a date carries the fiscal labels of the filing row it was read from. If the plain and the lease-inclusive figure for one balance date ever carried different labels, they would not be paired: both would come back as `debt_current` at the same date, and every reader would see two current portions there. Separately, a single map item gets one fact per fiscal label in annual and quarterly mode (`_one_per_period`, line 891, the later date wins); the merged item is built from two items, each deduplicated on its own, so if the plain figure sat at one date and the lease-inclusive one at another date with the same label, both would come back under that label. Before #421 the two tags were one item and neither could happen.
2. **Order.** When the merge runs, `get_facts` sorts by the order the items were asked for, then by date (line 1104). Without the merge, `_get_facts` returns facts sorted by item name, then by start and end date (reported; `_facts`, line 142) or by item name and end date (annual and quarterly; lines 1166 and 1047). So asking for `["debt_noncurrent", "debt_current"]` returns the two items in a different order depending on whether the map has the new item.
3. **A rounded plain figure.** The lease-inclusive figure includes the plain one, so it can only be smaller when one of the two is rounded. If the plain figure is rounded up (Exxon's 2025 10-K tags "$6.2 billion" as 6,200M under `LongTermDebtCurrent`) and the lease-inclusive one is precise but lower (say 6,180M), the rule keeps the rounded plain figure because the lease-inclusive one is not above it. The same rule picked correctly at Exxon 2025-12-31 only because 6,234M happens to be above 6,200M.

**On today's data none of the three changes a figure.** A survey of all eight companies at seven as-of dates (2012-06-01 to 2026-11-15), both modes and all three frequencies: no balance date where the three items carry different fiscal labels; no date where an item has two facts; no date where the lease-inclusive figure is below the plain one. The order differs from the unmerged order on 676 of the survey's 1,008 query combinations (the merge runs for every company, since the item is in the map). This is a robustness item: it makes the merge behave like a single map item by construction.

## Plan

- **Step 0.** This design doc.

- **Step 1. The merged list in the unmerged order.**
  - `facts.py`: one function, `_in_query_order(facts, frequency)`, gives the order `_get_facts` returns: reported by (item, start or "", end), annual and quarterly by (item, end). `_get_facts` uses it in place of its inline sorts, and `_merge_current` sorts its result with it (it needs the frequency, passed down from `get_facts`). Python's sort is stable, so ties keep the order of the wide list, which `_get_facts` already sorted the same way.
  - The reading rules' fingerprint changes; the order of a list cannot change which figure a run reads (every reader picks facts by item and date), so a row under version 9 says so. The Step 3 builds are the backstop.
  - Tests (`tests/fundamentals/test_current_merge_order.py`, fixture `make_company` with Exxon's presentation from `tests/analysis/test_current_lease_debt.py`): for every mode and frequency, with the items asked in an unsorted order (`["debt_noncurrent", "debt_current", "cash"]`), `get_facts` returns the item and date sequence `_get_facts` returns for the same names, with only the current portion's value and tag differing where the merge chose the lease-inclusive figure.
  - Exit: full suite and ruff clean.

- **Step 2. Pairing on the date alone, one fact per fiscal label, and a rounding margin.**
  - `_merge_current` keys each fact by `(period_start, period_end)` only. Each item has at most one fact per date in every mode and frequency (`_rows_by_period` keys by item, start and end; `_one_per_period` only removes facts), so a date pairs at most one fact of each of the three items. The merged fact keeps the chosen figure's own tag, value, filing and fiscal labels, as today.
  - In annual and quarterly mode the merged `debt_current` facts then go through `_one_per_period`, the rule every single item already obeys: one fact per fiscal label, the later date wins. Reported mode keeps one fact per date, as for any item.
  - `current_on_noncurrent_basis`: with the other conditions unchanged (non-current lease-inclusive, plain figure not negative, lease-inclusive figure not equal to the non-current debt), the lease-inclusive figure is also taken when it is below the plain one by no more than half the plain figure's apparent rounding unit, and is itself more precise. The apparent rounding unit (`rounding_unit(value)`) is the largest power of ten, up to 10^12, that divides the figure in whole dollars (6,200,000,000 → 10^8; 1,617,000,000 → 10^6). So 6,180M beside a plain 6,200M (unit 10^8, half 50M; 6,180M's unit 10^7) is taken; 6,140M (60M below) is not; and a lease-inclusive figure below a plain figure precise to the million (unit 10^6, half 0.5M) never is, since filers in millions report nothing finer. Company facts carry no `decimals` attribute (`financial_facts` has no such column; inline XBRL's decimals −8 was read by hand in #421), so the unit is inferred from the figure.
  - `READING_RULES_VERSION` 9 → 10 with its row in `reading_rules.md`: both rules can change what a run reads on some data, though no fact does today.
  - Tests (in `tests/analysis/test_current_lease_debt.py`): the two items at one date with different fiscal labels give one `debt_current` there (the guard: built by editing one item's fiscal labels in the fixture database), in every mode and frequency; two dates under one fiscal label give one fact in annual mode (the later); `rounding_unit` on 6.2e9, 1.617e9, 0 and a negative figure; 6,180M beside 6,200M is taken; 6,140M is not; 1,616M beside a plain 1,617M is not; a rounded plain figure still loses to the mis-tag guard (a lease-inclusive figure equal to the non-current debt); the existing #421 tests unchanged.
  - Exit: full suite and ruff clean.

- **Step 3. Real data.** On a copy of the restored snapshot (concepts synced to today's map): every stored run's date (the 903 runs that are not what-ifs) built fresh in memory, same pinned market data and choices, before this branch and after it: expected identical rows and note codes on every date. The survey above repeated after the change: the merged facts the same as before for every company, mode, frequency and as-of date, now in the unmerged order. `reproduce --all --rebuild`: every stored run reproduces to the cent and rebuilds as before (each through its own map).

## Alternatives considered

- **Pair on the date, but refuse (raise) when the fiscal labels differ.** A refusal stops a run over a labelling difference that changes no figure; the labels come from one fiscal calendar per company (`ingest.place_period_end`), so a difference would be a calendar renumbering between two filings, which `_one_per_period` already settles for single items.
- **Return the merged list in the asked order and document it** (the issue's first option for item 2). Readers don't depend on the order today, but a merged and an unmerged read of the same names should not differ in anything but the chosen figure; matching costs one shared function.
- **A fixed rounding margin** (say 1% of the plain figure). It would also take a lease-inclusive figure that is below a precise plain figure, where the filing contradicts itself rather than rounds; the apparent unit only opens the margin when the plain figure looks rounded.
- **Read `decimals` from the filing.** The SEC's company facts API, Warren's source, does not carry it; reading each inline XBRL document is a new ingest for a case no filing shows today.

**Limits.** A plain figure that is precise but happens to end in zeros (1,700M exactly) looks rounded to 10^8, so a lease-inclusive figure up to 50M below it and more precise would be taken. A filer whose lease-inclusive current portion is below its debt-only one contradicts itself whichever is right; the lease-inclusive figure is the one consistent with the lease-inclusive non-current debt D3 counts.

## Files to change

`domains/fundamentals/facts.py`; `domains/analysis/reading_rules.py` and `.md`; `tests/fundamentals/test_current_merge_order.py` (new), `tests/analysis/test_current_lease_debt.py`; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None. Serves the same brief questions as #421 (Q1–Q5, Q8 through debt, working capital and the cost of debt) without changing any figure on today's data. No output, note, code, param, lesson or label is added, renamed or removed. Runs record reading rules v10, so a fresh run beside a stored one of the same date falls in the brief's "Two runs of the same date" case for rules versions (the app's existing wording).
