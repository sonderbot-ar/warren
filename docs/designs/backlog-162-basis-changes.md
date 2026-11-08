# Backlog #162: a change of reporting basis is shown apart from forecast error

Issue: https://github.com/sonderbot-ar/warren/issues/162 · Branch `backlog-162-basis-changes`.

## Problem

A company sometimes recasts last year when it reports this year: Johnson & Johnson moved Kenvue to discontinued operations in its Q3 2023 10-Q, Coca-Cola moved an African bottler back from held-for-sale in 2019, Exxon's comparative uses a broader revenue line. The forecast was made on the old basis and the actual is on the new one, so part of the "miss" is the accounting, not the forecast. JNJ_2023-11-15 FY2023Q4 revenue is scored as a 59% miss for this reason.

Since v0.9.7, `hindsight.against_actuals` spots this: the filing that reports a quarter also gives the year-earlier quarter, and when that value is more than 0.5% (`BASIS_TOLERANCE`) away from the run's own history row, the quarter is `restated_basis`. The track record (v0.9.14) and run ranges (v0.9.8) already count these rows. The evaluation reports (M3's `report.py`, M8's `backtest_report.py`) do not: every such row is in the headline as forecast error.

The issue asks to decide among three treatments: drop these rows from the headline with a count, report them apart, or rescale the forecast to the new basis. Which one is the headline is a change to how Decision 7 scores, so it goes to the owner on a card. This item builds what every option needs and changes no stored number: the flag on each stored row, and the figures with and without the flagged rows side by side.

## Plan

- **Step 0.** This design doc.
- **Step 1. A basis flag on a stored row.** `harness.basis_change(row) -> bool | None`, from fields every `eval_results` row already stores: `comparative` (the year-earlier value in the actual's own filing, as of its filing date) and `prior_year_known` (the run's history row for that quarter). True when they differ by more than `BASIS_TOLERANCE` relative to `prior_year_known`; False within it; None when the row is not scored, or `comparative` is None (the comparative is mixed-vintage), or `prior_year_known` is 0 or None. `BASIS_TOLERANCE` moves to the harness and `hindsight` imports it, so the two checks share one number. The harness only scores horizons 1–4, whose year-earlier quarter is always a history row, so hindsight's "inherited" case (a change at a forecast quarter, horizons 5–8) cannot arise here. The flag is the baseline row's: every variant of a case quarter shares one actual and one comparative.
  Tests: True above the tolerance, False at and below it, None for a missing comparative, a zero or missing prior, a `missing` row; on a stored synthetic case, a quarter the hindsight call marks `restated_basis` is the quarter the row flag marks, and the other quarters agree too.
  Exit: tests pass.
- **Step 2. The reports show the flagged rows apart.** Headlines are unchanged.
  - M3 report (`report.py`): a header line "Changes of basis: N of M scored quarters (the year-earlier figure in the actual's filing differs from the run's by more than 0.5%); unchecked: K"; a segment row "Without changes of basis" beside "Without scope changes"; the flag "basis change" in the per-case table; a glossary line.
  - M8 backtest report (`backtest_report.py`): population `no_basis` in `backtest.pairs` (drops a case quarter whose baseline row is flagged; all variants of it go together, so pairs stay matched), and a section "Without changes of basis" after "Without deals", with the same table; the reference line gains its baseline skill against naive.
  Tests: on synthetic rows, the count, the segment's medians, the flag and the new section; a batch with no flagged rows says "none"; existing report tests unchanged.
  Exit: tests pass; `reproduce --batch` still passes on every stored batch (the rows are unchanged; only reports read the flag).
- **Step 3. Real data** (latest snapshot): the M3, M8 and M9-era batches re-rendered; counts per batch compared with hindsight's (the issue's 16 of 208 in the M8 batch, `eval_2026-11-02_1`), and the headline figures with and without the flagged rows written here.

**Point in time.** Nothing new is read: both values on the row were public when the actual was filed. **LLMs.** None. **Invariants.** No stored row, run or simulation changes; reproduce checks pass as before.

## Decision for the owner (card)

Which figure is the headline from M10 on: (a) the headline without changes of basis, with the count and the with-them figure beside it (recommended); (b) all rows as today, with the without figure beside it; (c) rescale the forecast to the new basis (forecast × filing's year-earlier value ÷ run's). Steps 1–3 are needed for (a) and (b) and do not choose between them. (c) is not built: the ratio assumes the recast scales every quarter evenly, which a divestiture (JNJ) does not.

## Alternatives considered

- **Call `against_actuals` per run in the reports.** Rejected: it re-reads every filing for every run (seconds per run) to recompute two numbers the harness already stored.
- **Store a flag column.** Rejected for now: a migration for a value derived from two stored columns; the rows of old batches would need a backfill and their reproduce checks would compare a new column.
- **Change the headline now.** Rejected: it moves the M3 and M8 numbers on the desk; that is the owner's card.

## Files to change

`domains/evaluation/harness.py`, `domains/evaluation/hindsight.py` (import only), `domains/evaluation/report.py`, `domains/evaluation/backtest.py`, `domains/evaluation/backtest_report.py`, `tests/evaluation/test_harness.py`, `tests/evaluation/test_backtest.py`, a report test, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None for the brief's questions today: no call the app uses changes (track record and run ranges already flag these rows). The evaluation reports, which the desk and a later "how good is Warren" screen draw on, gain the count and the without figure. If the owner picks (a), the headline error the app quotes for the engine's accuracy moves down for JNJ, KO and XOM.
