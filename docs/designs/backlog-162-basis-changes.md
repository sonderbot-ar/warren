# Backlog #162: a change of reporting basis is shown apart from forecast error

Issue: https://github.com/sonderbot-ar/warren/issues/162 · Branch `backlog-162-basis-changes`.

## Problem

Sometimes the run's figure for a year-earlier quarter and the figure the actual's own filing gives for it disagree. Two causes, often together:

- **The company recast last year.** Johnson & Johnson moved Kenvue to discontinued operations in 2023 (ASC 205-20): the Q3 2023 10-Q gives FY2022Q3 revenue about 16% below what the run had (ratio 0.84). Coca-Cola moved an African bottler back from held-for-sale in 2019; Procter & Gamble's FY2019Q4 EBIT is about 3% off (a reclassification, likely ASU 2017-07 pensions).
- **The run's own figure was off** (design review, analyst). A fourth quarter is worked out as the year minus nine months. When the year comes from the old-basis 10-K and the nine months from a recast 10-Q, the result is on no basis: JNJ_2023-11-15's history row for FY2022Q4 is 34,892 million (FY2022 from 0000200406-23-000016, nine months from 0000200406-23-000102), against about 23.7 billion as reported then and 19,939 million on the new basis. The run forecasts 34,038 million for FY2023Q4 and is scored as a 59% miss: that miss is Warren's own, built from data public on the case date. KO_2019-11-15 (ratio 1.46) and XOM_2019-11-15 (1.18) are the same defect. Filed as its own issue (see Results).

So a flagged row is not "accounting, not forecast error": it can be either.

Since v0.9.7, `hindsight.against_actuals` spots this: the filing that reports a quarter also gives the year-earlier quarter, and when that value is more than 0.5% (`BASIS_TOLERANCE`) away from the run's own history row, the quarter is `restated_basis`. The track record (v0.9.14) and run ranges (v0.9.8) already count these rows. The evaluation reports (M3's `report.py`, M8's `backtest_report.py`) do not: every such row is in the headline as forecast error.

The issue asks to choose among three treatments: (a) drop these rows from the headline with a count, (b) keep them and report them apart, or (c) rescale the forecast to the new basis. This item takes (b): it changes no stored number and no headline, and needs no new decision. (a) and (c) are not taken (see Alternatives and the design review).

## Plan

- **Step 0.** This design doc.
- **Step 1. A basis flag on a stored row.** `harness.basis_change(row) -> bool | None`, from fields every `eval_results` row already stores: `comparative` (the year-earlier value in the actual's own filing, as of its filing date) and `prior_year_known` (the run's history row for that quarter). True when they differ by more than `BASIS_TOLERANCE` relative to `prior_year_known`; False within it; None when the row is not scored, or `comparative` is None (the comparative is mixed-vintage), or `prior_year_known` is 0 or None. `BASIS_TOLERANCE` moves to the harness and `hindsight` imports it, so the two checks share one number. The harness only scores horizons 1–4, whose year-earlier quarter is always a history row, so hindsight's "inherited" case (a change at a forecast quarter, horizons 5–8) cannot arise here. The flag is the baseline row's: every variant of a case quarter shares one actual and one comparative.
  Tests: True above the tolerance, False at and below it, None for a missing comparative, a zero or missing prior, a `missing` row; on a stored synthetic case, a quarter the hindsight call marks `restated_basis` is the quarter the row flag marks, and the other quarters agree too.
  Exit: tests pass.
- **Step 2. The reports show the flagged rows apart.** Headlines are unchanged. Counts are rows: revenue and EBIT of one quarter are flagged and counted apart (each has its own comparative), so a quarter can be flagged on revenue and not on EBIT. Only the count, a segment, the per-case flag and a section are added; the direction, band, by-horizon and with-shocks sections stay on all rows.
  - M3 report (`report.py`): a header line "Changes of basis: N of M scored rows (…; kept in the headline, shown apart under Segments) · unchecked: K"; a segment row "Without changes of basis" beside "Without scope changes"; the flag "basis change" in the per-case table; a glossary line.
  - M8 backtest report (`backtest_report.py`): population `no_basis` in `backtest.pairs` (drops a row whose baseline row is flagged; every variant of that case, item and quarter goes with it, so pairs stay matched), and a section "Without changes of basis" after "Without deals", with the same table and "context only: the headline keeps them"; the reference line ("the baseline's skill against the naive forecast") gains a `no_basis` figure beside `all` and `no_scope`.
  Tests: on synthetic rows, the count, the segment's medians, the flag and the new section; a batch with no flagged rows says "none"; existing report tests unchanged.
  Exit: tests pass; `reproduce --batch` still passes on every stored batch (the rows are unchanged; only reports read the flag).
- **Step 3. Real data** (latest snapshot): the three stored batches (`eval_2026-11-02_1`, the M8 backtest; `eval_2026-11-03_1` and `_2`, the M9/M10 grid baselines) re-rendered before (main) and after; counts compared with hindsight's (the issue's 104 of 2,016, 16 of 208 in the M8 batch), and the figures with and without the flagged rows written here.

**Point in time.** Nothing new is read: both values on the row were public when the actual was filed. **LLMs.** None. **Invariants.** No stored row, run or simulation changes; reproduce checks pass as before.

## Which treatment, and why no card

The first draft recommended (a) on an owner card. The design review turned it down, with evidence (below): (a) would drop Warren's own errors (JNJ, KO, XOM's fourth quarters) and real misses that merely sit beside a small recast (PG's Gillette impairment, a 46-point EBIT miss behind a 3% basis gap; XOM's 121% COVID quarter behind 2.4%), and dropping on a condition tied to error size is selection on the outcome. (b) keeps today's headline and shows the rest beside it, which changes no Accepted decision, so it goes ahead without a card. (c), scoring like for like, is the principled fix for a real recast but needs the history defect fixed first and the track record and run ranges to follow suit; it is filed as an issue, with the card to come when it is built.

## Alternatives considered

- **Call `against_actuals` per run in the reports.** Rejected: it re-reads every filing for every run (seconds per run) to recompute two numbers the harness already stored.
- **Store a flag column.** Rejected for now: a migration for a value derived from two stored columns; the rows of old batches would need a backfill and their reproduce checks would compare a new column.
- **(a) Drop the flagged rows from the headline.** Rejected in review: it hides Warren's own errors and real misses (above); on the M8 batch it moves median revenue error from 6.1% to 5.2%, mostly by dropping large misses.
- **(c) Rescale the forecast to the filing's basis** (forecast × comparative ÷ run's figure, per quarter; the same as scoring year-over-year growth on one filing's basis, Croushore 2006 on real-time data; Warren's own same-filing growth rule, build plan D2). Not built here: on JNJ it would also excuse the history defect, which is Warren's error; EBIT ratios are unstable near zero (JNJ FY2024Q1 EBIT ratio 2.06); and it should apply to the track record and run ranges at the same time. Filed.

## Files to change

`domains/evaluation/harness.py`, `domains/evaluation/hindsight.py` (import only), `domains/evaluation/report.py`, `domains/evaluation/backtest.py`, `domains/evaluation/backtest_report.py`, `tests/evaluation/test_harness.py`, `tests/evaluation/test_backtest.py`, a report test, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None for the brief's questions today: no call the app uses changes. Q6's track record already counts these rows beside its figures and keeps them in its summaries (`track_record.py`), and so does this item for the evaluation reports, so the two agree. The v0.9.7 promise ("a recast prior year is shown as a change of basis, never as a miss") is about `against_actuals` and still holds there. Wording for students: a flagged row means "the run's figure and the company's later figure for last year are not on the same basis", not "the company recast": for JNJ, KO and XOM's fourth quarters, the run's own figure was off. Spanish term for the brief, if a screen shows it: "cambio de base contable".

## Design review (nov.08.2026)

Explainer, analyst, professor and product lead, on the first draft of this doc (the reviewer could not start fresh-context subagents in its session and ran the four roles in turn; noted for the gatekeeper).

- **Analyst: blockers, taken.** The Problem misread JNJ: the 59% is Warren's own derived FY2022Q4 (34,892 million, two filings on two bases), not a company recast; KO_2019-11-15 and XOM_2019-11-15 the same. (a) would drop real misses (PG FY2019Q4 EBIT, XOM FY2020Q2) beside small basis gaps. Taken: the Problem rewritten, the docstrings and report text say either cause, (a) dropped, the history defect filed. Ideas filed with (c): the basis gap's share of each miss; an EBIT tolerance in margin points.
- **Professor: (c) over (a), taken in part.** (c) is same-filing growth scoring (Croushore 2006; Croushore and Stark 2001), Warren's own D2 rule, and dropping on an error-linked flag is selection on the outcome (Little and Rubin). Taken: (a) dropped, (c) filed with these sources; the accounting standards cited. Not built now: on JNJ it would excuse Warren's own defect.
- **Explainer: gaps, taken.** Counts are rows, not quarters, and the doc says so; `no_basis` drops a row (case, item, quarter) with every variant; the reference line's change stated; the three stored batches named; which sections stay on all rows stated.
- **Product lead: no blockers.** (a) would have made the evaluation headline disagree with Q6's track record; (b) keeps them consistent. Taken: the student wording must not say "the company recast"; PG added; the Spanish term noted. The "how good is Warren" screen is not in the brief: wording removed.

## Results (nov.08.2026)

Snapshot `warren-20261105T101750Z` (schema 21). Before = main at `3984fe0`, after = this branch. Reports of the three stored batches rendered from the same database: the only lines removed are per-case rows that gain the "basis change" flag (16, 44, 44) and the backtest's reference line, which gains a figure; every headline line is byte for byte main's. No row is written.

| Batch | Flagged rows | Revenue median, baseline vs naive: all → without | EBIT median, all → without |
|---|---|---|---|
| `eval_2026-11-02_1` (M8) | 16 of 208 (10 revenue, 6 EBIT) | 6.1% vs 7.2% → 5.2% vs 6.8% | 3.33 vs 4.06 pts → 3.17 vs 4.06 pts |
| `eval_2026-11-03_1` | 44 of 852 | 4.7% vs 7.1% → 4.3% vs 6.7% | 3.54 vs 3.89 pts → 3.33 vs 3.79 pts |
| `eval_2026-11-03_2` | 44 of 916 | 4.8% vs 6.9% → 4.5% vs 6.6% | 3.34 vs 3.70 pts → 3.28 vs 3.63 pts |

104 flagged in all, the same count as hindsight's in the issue; 0 unchecked among scored rows. Cases: JNJ 2023–24 (Kenvue), KO 2019–20, PG 2019 (EBIT), XOM 2019–20. The baseline still beats naive on median error without them; on the M8 batch its mean skill against naive moves from −17.2% to −11.5% (revenue) and 7.4% to 12.2% (EBIT).

Filed: the derived fourth quarter on two bases in a run's history, and like-for-like scoring (option c).

Exit met.
