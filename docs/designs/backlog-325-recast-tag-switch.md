# Backlog #325: the recast note across a tag switch, and a quarter series' own moves

Issue: https://github.com/sonderbot-ar/warren/issues/325 · Branch `backlog-325-recast-tag-switch` · Status: In progress (nov.11.2026). Follow-up filed: #331.

Two follow-ups from the gatekeeper on PR #323 (v0.9.54, `series_mixes_vintages`, `docs/designs/backlog-297-series-vintages.md`). Neither misfires on today's data as far as v0.9.54's scan saw; both are holes a new filing could fall into.

## Problem

**1. Which figure a filing is compared with.** `facts.item_recasts` walks each period's filings in order and compares a filing's version (the last row of that filing's best-ranked tag) with the **previous filing's** version, whatever tag that filing used (`domains/fundamentals/facts.py:477-489`). A recast is only listed when the filing's tag is the one `latest` mode shows (`shown`), but the figure it is compared with may sit under a lower-ranked tag. Take three filings of one period:

- A gives 100 under the shown tag (`Revenues`);
- B gives 95 under a lower-ranked tag only (`SalesRevenueNet`, a narrower line; Walmart's 10-Ks tag quarters as net sales, its 10-Qs as total revenues);
- C gives 100 under `Revenues` again.

A reader of `latest` mode saw 100 after A, still 100 after B (the tag ranks before the filing, Decision 2), and 100 after C: nothing moved. Today C is compared with B's 95, moves 5.3%, holds no row at 95, and is listed as a recast: a false note. The reverse also happens: if C gives 95 under `Revenues` (a real recast of the shown figure) and B happened to give 95 under the lower tag, C is compared with 95 and the recast is missed.

The gatekeeper counted 7 tag switches at a recast in real data (Microsoft FY2016, FY2017 and FY2017Q4; Coca-Cola's 2018 H1 and Q2; P&G's #322 pair). In each, the earlier filings never used the shown tag, so the comparison is with the only figure a reader had, and the result is right.

**2. A quarter series and a 10-K that moved only years.** A series of years counts only recasts that moved a year (`ANNUAL_MIN_DAYS`, 300 days, `domains/analysis/reported.py:1252`). A series of quarters counts every recast, and its note says "by up to {largest_move}" over every period the filing moved, years and nine-month spans included (`largest_move(0)`, `reported.py:1285`). A 10-K that recast only the years then gives a quarter series a note whose size is a year's move, and dates a quarter break to a filing that changed no quarter.

## Plan

**Step 0. This doc.**

**Step 1. Compare with the figure a reader saw** (`domains/fundamentals/facts.py`).

- In `item_recasts`, the figure a filing is compared with becomes the figure `latest` mode showed from the filings before it: `_latest_of_best_tag(earlier rows, usual sign)`, the newest version of the best-ranked tag among every earlier filing's rows, skipping a version filed with a flipped sign (#280), exactly as `latest` mode picks. Today's rule (the previous filing's top tag) is the same whenever no earlier filing used a higher-ranked tag than the previous one, which covers the 7 real tag switches.
- The rest is unchanged: the filing's own version is its best-ranked tag's last row, it must be the shown tag, keep its sign, move by more than `RECAST_MOVE` (0.5%), and no row of the filing may hold the old figure within `MEANING_CHANGE_MATCH`.
- Tests (`tests/analysis/test_series_recast.py`, Test Corp): FY2017 filed under `Revenues` in the FY2017 10-K, only under `SalesRevenueNet` 5% lower in the FY2018 10-K, and under `Revenues` unchanged in the FY2019 10-K: no recast, no note (today: a note). Same, but the FY2019 10-K gives `Revenues` 5% lower, matching the lower tag's figure: a recast dated by the FY2019 10-K, against the `Revenues` figure (today: missed). A tag switch where earlier filings used only the lower tag still counts (the real cases' shape).
- Exit: the full suite passes; the real-data scan below lists the same recasts as v0.9.54 or says why one changed.

**Step 2. A quarter series counts quarter and year moves, not half years** (`domains/fundamentals/facts.py`, `domains/analysis/reported.py`). Revised after the design review (analyst blocker 1, professor blocker 1).

- `Recast.largest_move(min_days, max_days=None)`: the largest signed move among periods at least `min_days` and at most `max_days` days long (both inclusive; a period with no start, a balance, is never counted, as before). `QUARTER_SPAN = (80, 100)` beside `ANNUAL_MIN_DAYS` (300) in `reported.py` (named so as not to clash with `harness.QUARTER_DAYS`, professor). 100 takes a 14-week quarter (98 days, a 53-week year).
- A series of years: unchanged (recasts that moved a year, the year's move).
- A series of quarters counts a recast that moved a quarter-length period **or a year**. `largest_move` is the largest quarter move; when the recast moved no tagged quarter, it is the year's move, and the new param `largest_move_on` (`quarter` or `year`) says which. A restated year restates its quarters even when they are not tagged: Apple's 10-K/A of 2010-01-25 restated FY2007–FY2009 only, its FY2009 Q1 and Q2 first appear in XBRL already restated, so no 10-Q recast is ever found, and the quarter break (FY2009Q3 and FY2009Q4 on the old basis, about 17%) is carried only by the 10-K/A (analyst). The same rule covers the professor's case, a derived fourth quarter worked out across a year-only recast.
- A recast that moved only half years or nine months (101–299 days) is left out of a quarter series: it moved nothing the series shows. Today this removes two false notes (analyst): Johnson & Johnson's 10-Q of 2024-07-25 and P&G's 10-Q of 2013-01-25 moved only a six-month figure, and their notes called FY2023Q2 and FY2012Q2 "as filed in it or later" only because the quarter was filed again unchanged.
- English fallback: on a quarter series with `largest_move_on` `year`, "(by up to 5.0% on a full year; it moved no tagged quarter)"; otherwise the text is as in v0.9.54.
- Tests (`tests/analysis/test_series_recast.py`; `_recast_revenues` is that file's existing fixture edit, the 10-K and 10-Qs together): `_years_only` (a 10-K that lowers only years ending in 2017 or later) keeps the quarter series' note, dated by the 10-K, −5% on `year`, with the new words; a 10-K moving years by 5% and 10-Qs moving quarters by 3% gives the 10-Q notes on `quarter` at −3%; `_half_year_only` (the 2019 Q2 10-Q tags the six months to June 2018 5% lower, quarters unchanged) gives no note to a quarter or a year series; `largest_move` with spans of 365, 273, 98, 79 and 101 days; the existing params test gains `largest_move_on`.
- Exit: full suite passes; the real-data cases above and the scan below as stated.

**Step 3. Real-data scan** (snapshot of nov.10.2026, restored and checked: 903 of 903 stored runs reproduce to the cent; as of 2026-11-09 unless said). Before is `main` (v0.9.55), after is this branch.

Targeted, from the design review:

| Series | Before | After |
|---|---|---|
| AAPL FY2009Q1–FY2010Q2, as of 2010-06-01 | 10-K/A 2010-01-25, +17.4%; FY2009Q3, FY2009Q4 before | same, +17.4% on `year` |
| JNJ FY2022Q1–FY2023Q4, as of 2024-08-14 | 10-Q 2024-07-25 (a half year only), FY2023Q2 "after" | no note (false note gone) |
| PG FY2011Q1–FY2012Q4, as of 2013-02-14 | 10-Q 2013-01-25 (a half year only) | no note (false note gone) |
| KO FY2017Q1–FY2018Q4, as of 2020-03-15 | three notes: 10-Qs of 2019-07-25 (+7.0%) and 2019-10-24 (+6.8%), 10-K 2020-02-24 (+7.7%) | same three, same splits; the 10-Qs now give their quarter moves (+5.5%, +6.4%) instead of a half year's or nine months'; the 10-K +7.7% on `year` |
| MSFT FY2016Q1–FY2017Q4 | 10-Qs of 2017-10-26 and 2018-01-31 | 10-Q 2017-10-26; the second split is now dated by the 10-K of 2018-08-03 (+9.8% on its tagged fourth quarter), because the 10-Q of 2018-01-31 moved only the six months to December 2016 under the shown tag. Same split, a later date |

Full scan (every five-year run starting FY2009–FY2021, 13 per company, and every eight-quarter run starting Q1 2009–2024, 16 per company; eight companies):

- **Recasts found:** the same for all eight companies (Step 1 changes nothing today).
- **Year runs:** 22 noted before and after, identical notes and moves (only `largest_move_on: year` added).
- **Quarter runs:** 12 noted before, 9 after. Gone: J&J's runs starting FY2022Q1 and FY2023Q1 (10-Q 2024-07-25, half year only) and P&G's starting FY2011Q1 (10-Q 2013-01-25, half year only), all three false. Microsoft's runs starting FY2016Q1 and FY2017Q1: the second split is dated by the 10-K of 2018-08-03, not the 10-Q of 2018-01-31 (same periods). Moves that changed, same splits: Coca-Cola's 10-Qs of 2019 (+7.0% to +5.5%, +6.8% to +6.4%, quarters instead of a half year and nine months); P&G FY2010Q1 run (−1.70% to −1.67%), FY2012Q1 run (−66.1% to −2.0%: the 10-K of 2014-08-08's −66% was a year's move on #322's segment figures, its quarter move is −2.0%), FY2013Q1 run (−5.1% to −3.6%).

**Step 1 on real data.** The analyst re-ran `item_recasts` with the new comparison on all eight companies: the same recasts as today (AAPL 5, MSFT 6, WMT 0, KO 7, PG 33, JNJ 9, CAT 0, XOM 2). Step 1 is a guard for future filings and changes nothing today. It cannot create a Walmart note: the comparison figure is under a tag ranked at or below the shown tag, and `shown` is the best tag across every filing.

## Alternatives considered

- **Compare with the previous filing's version under the same tag as the new one** (the issue's first reading). Right for A, B, C, but wrong when an earlier filing used a tag ranking between the two; the figure a reader saw is what `latest` mode picks, so use that function.
- **Skip filings whose top tag is not the shown tag in the walk.** Loses the real tag switches (the earlier filings never used the shown tag, so nothing would be compared).
- **Count only quarter-length moves for a quarter series** (the first draft). Drops Apple's 10-K/A of 2010-01-25, the only filing that carries its FY2009 quarter break (analyst blocker 1), and a derived fourth quarter across a year-only recast (professor blocker 1).
- **Keep every recast for a quarter series** (v0.9.54). Keeps the two false half-year notes and gives a half year's or nine months' move as the size.

## Files

`domains/fundamentals/facts.py`, `domains/analysis/reported.py`, `tests/analysis/test_series_recast.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q1 and Q2 ("Notes on a series"). No value changes; nothing renamed or removed.

- **Added:** param `largest_move_on` on `series_mixes_vintages`: `quarter` or `year`, the span `largest_move` was measured on (always `year` on a year series). On a quarter series with `year`, the English text adds "on a full year; it moved no tagged quarter". Suggested Spanish: "(una baja de hasta {movimiento} en el año completo; no cambió ningún trimestre etiquetado)".
- **Changed:** on a quarter series, `largest_move` is a quarter's move whenever the recast moved a tagged quarter (it could be a half year's or nine months' before). A filing that moved only half years or nine months no longer gives a quarter series a note (J&J 10-Q 2024-07-25, P&G 10-Q 2013-01-25: both were false). A split first carried by such a filing is now dated by the next filing with the same split (Microsoft: the 10-K of 2018-08-03, not the 10-Q of 2018-01-31).
- `moved_periods` still lists only the series' periods the recast itself moved (product lead).
- Product lead (design review, GO): nothing the app relies on breaks; the brief's "de algunos años" wording on a quarter series is the front-end's to fix ("periodos" or "trimestres").

## Limits

- `side_of_recast` calls a quarter filed again unchanged "after" (the cause of the J&J and P&G false notes; analyst). This change removes those two by their half-year moves; the general fix (a recast marks only periods it moved, or that were filed after it, as after) is backlog #331.
- A filing that moved a half year whose quarter moved under another tag (Microsoft's 10-Q of 2018-01-31) is not counted for quarters; its split is dated by the next filing that moved a quarter or a year.
- 13- or 16-week fiscal quarters outside 80–100 days (a 12-12-12-16 calendar) would be missed; none in the Phase 1 universe (professor idea, for when the universe grows).

## Design review (nov.11.2026)

Explainer, analyst, professor and the product lead in parallel.

- **Product lead: GO.** Asked that Product impact list what changes on real data and say `moved_periods` is unchanged: done.
- **Analyst: NO-GO, accepted.** (1) Quarter-only counting hides Apple's real FY2009 quarter break (10-K/A of 2010-01-25): the rule now keeps year recasts and says the move is on a year. (2) Step 3 must list Apple, J&J, P&G and Coca-Cola's cases and say what each is: the table above. Suggestions taken: Step 1 is a guard with no effect today (said); the `side_of_recast` refiled-unchanged path filed as #331.
- **Professor: NO-GO, accepted.** (1) A derived fourth quarter across a year-only recast lost its note: covered by keeping year recasts, with a test. Suggestions taken: `QUARTER_SPAN` instead of a second `QUARTER_DAYS`; a 98-day quarter in the span test. Idea (16-week quarters) in Limits.
- **Explainer: NO-GO on clarity, accepted where right.** Bounds are inclusive and passed as `largest_move(*QUARTER_SPAN)` (said); "usual sign" is `_UsualSigns`, the same as `latest` mode's sign-flip skip (#280, `docs/designs/backlog-280-sign-check.md`); the comparison uses only earlier filings' rows, in filing order (`_filing_order`: filing date, then accession); `shown` is still computed over every filing public on `as_of`; the match check runs against the new comparison figure. A recast with no qualifying move is dropped before the note is built, so `abs(None)` cannot happen. Rejected: "`_recast_revenues` does not exist" (it is in `tests/analysis/test_series_recast.py`, line 24).

## Where the work stopped (nov.11.2026, 16:50 UTC)

PR #332 is ready: gatekeeper GO (its two clarity notes pushed in `4f151cc`), full suite green locally (2,128 passed). CI failed three times at the same step, before ruff or pytest ran: `playwright install --with-deps chromium` could not reach Ubuntu's package servers ("Temporary failure resolving 'azure.archive.ubuntu.com'"), a GitHub runner outage, not this PR. Not merged: never with a failing check. Next run: re-run the `tests` job (or push the next real change); when green, merge with a merge commit and record v0.9.56 (versions, team sync, this doc's status, build plan untouched), then the desk entry, lesson and email.
