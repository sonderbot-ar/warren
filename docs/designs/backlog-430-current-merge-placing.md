# Backlog #430: the current portion merge, paired before it is placed, and a note when rounding decides

Issue: https://github.com/sonderbot-ar/warren/issues/430 (from the PR #429 gatekeeper and analyst reviews of `docs/designs/backlog-427-current-merge-followups.md`) · Branch `backlog-430-current-merge-placing`.

## Background

Since v0.9.81 (#421) the current portion of long-term debt is filed under two map items, `debt_current` (`LongTermDebtCurrent`) and `debt_current_with_leases` (`LongTermDebtAndCapitalLeaseObligationsCurrent`). `facts.get_facts` reads both with `debt_noncurrent` and merges them per balance date into one `debt_current` (`_merge_current`, choosing with `current_on_noncurrent_basis`). Since v0.9.82 (#427) the pairing is on the date alone, the merged item keeps one fact per fiscal label in annual and quarterly mode, and a lease-inclusive figure below a plain figure that looks rounded is taken when it lies within half the plain figure's rounding unit (`_within_rounding`).

## Problem

1. **Placed before paired.** In annual and quarterly mode `get_facts` asks `_get_facts` for the three items *already placed*: annual keeps only `FY`-labelled facts, quarterly keeps one fact per (item, fiscal label), the later date winning (`_one_per_period`). Only then does `_merge_current` pair them by date. So if one filing placed a year-end lease-inclusive figure under `Q3`, or left it unplaced, the annual read drops it before it meets the plain figure at the same date (the plain figure is read alone); the quarterly read is worse, since a year end mislabelled `Q3` displaces the real `Q3` lease-inclusive figure (the later date wins the label) and the September plain figure is read alone. The #427 guard test only shifted `fiscal_year`, which both reads keep.
2. **No `get_facts`-level test of one-per-label.** #427's test calls `_merge_current` directly; nothing pins that `get_facts` passes the frequency down.
3. **No note when the rounding margin decides.** When `_within_rounding` picks a lease-inclusive figure *below* the plain one, nothing in a run says so; #412 and #415 have run notes. Raised by the professor at #427's design review and by the gatekeeper at its PR review.
4. **Watch the 10^7 floor.** 77 of 610 current-portion facts look rounded to 10^7 or coarser. At 10^7 the margin is 5M. The note of item 3 is how a future filing that trips the margin becomes visible; nothing else changes.

**On today's data nothing changes:** across every filing, no date has the two current tags under different fiscal labels or periods, and no lease-inclusive figure sits below a plain one (#427's survey and analyst check). This is robustness: the merged item behaves like a single map item by construction, and the one judgement call the reads make on rounding is shown to the student.

## Plan

- **Step 0.** This design doc.

- **Step 1. Pair every filed date, then place.**
  - `facts.get_facts`: in annual and quarterly mode, the three current items are read *as filed* (`_get_facts(..., "reported")`: one fact per item per date, same mode, same point-in-time query), paired by date with `_merge_current`, and only then placed by `_placed`: annual keeps the `FY`-labelled facts, quarterly relabels a year end's `FY` as `Q4` (as `_flow_years` does for every balance item), and both keep one fact per label, the later date winning (`_one_per_period`). Every other item, and `debt_noncurrent` when asked, comes from the usual placed read, unchanged. Reported mode is unchanged.
  - Fiscal labels of a date filed under both tags (`_labels`): the plain figure's, as #427 set (where the single item before #421 placed the date), unless the lease-inclusive figure places the date and the plain one does not, or the lease-inclusive one places it as a fiscal year end (`FY`) and the plain one under a quarter. Then the lease-inclusive figure's labels. Otherwise a placed year end would be dropped from the annual read only because of which tag carried the label: on `main`, a plain year end mislabelled `Q3` was dropped by the filter and the lease-inclusive figure was read alone at `FY`; pairing first would have dropped the date entirely. The labels follow the dates, whichever figure is chosen.
  - `READING_RULES_VERSION` 10 → 11 with its row in `reading_rules.md`: on some data this changes which figure a run reads, though no filing does today.
  - Tests (`tests/analysis/test_current_lease_debt.py`, Exxon's presentation `lease_inclusive()` on the `make_company` fixture): with the lease-inclusive year ends relabelled `Q3` or unplaced, annual and quarterly reads in both modes give the same dates, labels and lease-inclusive values as before the relabel (each failed on `main`); the same with the plain year ends relabelled; both placed, neither `FY`: the plain labels win, and a chosen plain figure is returned unchanged; through `get_facts` (issue item 2), a lone lease-inclusive figure three days before the year end under the same label gives one fact per label in annual and quarterly mode, both modes, and one per date in reported mode; a plain-only company reads as before.
  - Exit: full suite and ruff clean.

- **Step 2. A run note when the rounding margin chooses the figure.**
  - `Fact` gains `rounded_plain: float | None` (default `None`): set by `current_on_noncurrent_basis` to the plain figure when the lease-inclusive figure is taken *below* it, through `_within_rounding`. Nothing is stored: facts are read at query time.
  - `math_engine._balance`: when the balance sheet's current portion carries `rounded_plain`, run note `debt_current_within_rounding` with params `period_end`, `debt_current` (the figure read), `debt_current_plain` (the rounded figure beside it), `rounding_unit`, `currency`, `accession_no`, `assumptions` (`debt`, `cost_of_debt`, `nwc_pct`), and an English text. The code joins `RUN_NOTE_CODES`; its lesson in `text.WARNING_LESSONS` (group `data`) says in lay words why a rounded figure in the text and a more precise one in the tables can both be right, and why Warren reads the precise one (XBRL 2.1, section 4.6). The note changes no figure, so the reading rules row stays under version 11.
  - Tests: the note on a fixture year end where the plain figure is a rounded 6,200 and the lease-inclusive one 6,180 (scaled to the fixture, in millions), with its params; no note when the lease-inclusive figure is above the plain one, equal to it, or chosen alone; the lessons test covers the new code.
  - Exit: full suite and ruff clean.

- **Step 3. Real data.** On the restored snapshot: every stored run date that is not a what-if built fresh in memory through today's map, pinned to its stored market downloads and choices, once on `main` and once on this branch: identical rows and note codes expected on every date. #427's fact survey (8 companies × 7 as-of dates × 2 modes × 3 frequencies × 2 name lists) repeated: identical facts, in the same order. `reproduce --all --rebuild`: every stored run reproduces to the cent and rebuilds as on `main`.

## Alternatives considered

- **Keep the plain figure's labels always (#427's rule).** Pairing before placing would then drop a year end from the annual read whenever only the plain figure is mislabelled, where `main` read the lease-inclusive figure there. Preferring a placed label, and a year end's over a quarter's, never drops a date either figure placed.
- **Place first and pair across labels** (match a dropped figure to a kept one at the same date). That re-reads facts the placed read threw away: it is the reported read with extra steps.
- **Refuse when the labels differ.** A refusal stops a run over a labelling difference that changes no figure (as #427 argued).
- **A note on every choice of the lease-inclusive figure.** That fires on every Exxon date since 2019 and teaches nothing new: #421's choice is the rule. Only the rounding margin is a judgement call.
- **Raise the floor to 10^8 now** (issue item 4). No filing trips the margin at 10^7 today; the note makes the first one visible before the floor is revisited.

## Files to change

`domains/fundamentals/facts.py`, `domains/fundamentals/schemas.py`, `domains/analysis/math_engine.py`, `domains/analysis/coded.py`, `domains/analysis/text.py`, `domains/analysis/reading_rules.py` and `.md`; `tests/analysis/test_current_lease_debt.py`; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

No figure moves on today's data, so no answer to any brief question changes. Serves Q1–Q5 and Q8 (debt, net debt, working capital, the cost of debt) on future filings only. **Added:** one run-note code, `debt_current_within_rounding` (group `data`), with its lesson and params (`period_end`, `debt_current`, `debt_current_plain`, `rounding_unit`, `currency`, `accession_no`, `assumptions`); the app's text catalogue needs its Spanish when it shows run notes. No filing triggers it today. Nothing renamed or removed. Runs record reading rules v11; a fresh v11 run beside a stored v10 run of the same date gets the brief's "Two runs of the same date" first case (`docs/product/brief.md`), with identical values on today's data.
