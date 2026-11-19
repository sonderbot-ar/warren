# Backlog #480: Caterpillar's current debt in 2026 runs, checked

Issue: https://github.com/sonderbot-ar/warren/issues/480 (from the analyst's review of #476) · Branch `backlog-480-cat-current-debt-check` · Docs only.

## Problem

The #476 review saw two 2026 Caterpillar (CAT) runs count `debt_current` as zero (`CAT_2026-02-15_1` at the 2025-12-31 balance, `CAT_2026-10-30_1` at the 2026-06-30 balance), although CAT's 2025 10-K tags the principal due within a year (`LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths`, 7.12B) and the concept map reads that tag into `debt_current` for CAT since #341 (v0.9.77, merged nov.15.2026). The issue asked for three checks before changing any rule.

## Findings (snapshot `warren-20261119T102307Z`, schema 23)

1. **Filing date against `as_of`: known in time.** The FY2025 10-K (accession 0000018230-26-000008) was filed 2026-02-13, two days before `CAT_2026-02-15_1`'s `as_of`. So a run built on 2026-02-15 under today's map must read it. Not the explanation.
2. **Stored map: this is the explanation.** Every stored run keeps the concept map it was built with and is rebuilt through it (#357). Of the 115 stored CAT runs, 113 carry map fingerprint `2a263604…`, from before #341, which never read the maturities tag; all 113 count `debt_current` as zero. Both flagged runs are among them (created nov.03 and nov.04.2026). The two CAT runs built under today's map (`CAT_2026-10-30_2` and `_3`, map `91c71ab5…`, created nov.19.2026) read it: `balance:debt_current` 7,120,000,000 from the FY2025 10-K, debt 36.21B → 43.33B, and their `balance_counted_zero` note no longer names `debt_current`. This matches #341's own measurement (`docs/designs/backlog-341-cat-current-debt.md`, Step 2: all 113 dates rebuilt in memory through the new map count 5.3B to 9.1B more debt; stored runs do not move, by design).
3. **Balance date.** The maturities figure is tagged at year ends only (known gap `Q1;Q2;Q3`, #341). At a quarter-end balance (2026-06-30 for runs as of 2026-10-30) today's map carries the 2025-12-31 figure forward under the existing carry-forward rule, with the `balance_carried_forward` note naming `debt_current` (run `_3`). So a quarter-end run is not left at zero either.

**Conclusion: no bug and no rule change.** The zero in the flagged runs is the old map, kept on purpose so every stored run reproduces to the cent. A fresh CAT run counts its current debt. The principal-versus-carrying-value question the issue raises was settled in #341 (the map row's note: principal, a fallback only where nothing better exists, CAT only).

**What stays true, said plainly.** The 113 stored CAT runs (24 of them scored in `eval_results`, 91 behind `forecast_origins`) still understate CAT's debt by 5.3B to 9.1B and so overstate value per share (on 102 of 113 dates). The app shows the "same rules, different map fingerprints" note (`docs/product/brief.md`, line 109) when an older CAT run sits beside a newer one. The backtest scores revenue and operating profit, which current debt does not touch, so its errors stand; only value per share, net debt and working capital on those stored runs are off. Rebuilding the stored dates as new runs under today's map is not done here: it is a data refresh, not a docs fix, and is filed as a backlog follow-up.

## Plan

- **Step 0.** This note.
- **Step 1.** `docs/build-plan.md`, known gaps: the CAT row said the current portion "is not in companyfacts; counted as zero". It now says what is true since #341: read from the maturity note at year ends (principal), carried forward to quarter ends; runs stored before nov.15.2026 keep the zero. Exit: the row matches the findings above; CI green.

No test changes: the mechanism is already pinned (`tests/analysis/test_runs.py`, `test_a_run_rebuilds_through_its_own_map_after_the_map_is_edited`; `tests/fundamentals/test_concepts.py` for the CAT-only row).

## Alternatives considered

- **Rewrite the stored runs' debt.** Refused: it breaks the reproduce-to-the-cent invariant (CLAUDE.md, standing rules).
- **Change the stored `balance_counted_zero` text for old runs.** Refused for the same reason; the note was true for the map those runs used.

## Files to change

`docs/designs/backlog-480-cat-current-debt-check.md` (new), `docs/build-plan.md` (one known-gaps row).

## Product impact

None. No output, name or field changes. Brief Q3, Q5 and Q8 on CAT are right on fresh runs; an older CAT run beside a newer one already gets the map-fingerprint note (brief line 109).
