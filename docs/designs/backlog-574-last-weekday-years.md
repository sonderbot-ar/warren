# Backlog #574: 52/53-week years that end on the last weekday of a month

Issue: https://github.com/sonderbot-ar/warren/issues/574 (from the #571 professor) · Branch `backlog-574-last-weekday-years` · Version v0.10.49 when merged.

Status: In progress (nov.26.2026).

## Problem

`expected_year_end` (`domains/analysis/single_values.py`) gives the expected end of a fiscal year whose 10-K is not filed yet, for the cost-of-debt chart's `not_filed_yet` point (#564). For a 52/53-week year it assumes every end is the weekday nearest one fixed anchor date, at most `WEEK_YEAR_REACH = 3` days off, and takes the middle of the dates all filed ends allow.

26 U.S.C. §441(f) also allows the *last* given weekday of a month, which can end a year six days before the month's end (the last Saturday of January: 2024-01-27, 2025-01-25, 2026-01-31). From those two filed years the band's middle gives 2026-01-24, a week early. Checked against pandas' own 52/53-week calendar (`pandas.tseries.offsets.FY5253`, the scout's note on #574) on every weekday, month and start year 1995–2029: on `main`, a last-weekday company is expected right 73% of the time from one or two filed years and 95% from eight; a weekday-nearest-the-month-end company (Johnson & Johnson's rule) 73% from one or two years and 96% from eight, because the band's middle is a guess until many years narrow it.

No Phase 1 company is live on the gap: Apple's last Saturday of September is also the Saturday nearest 27 September, and both Apple's and Johnson & Johnson's long filed histories already give the right date.

## Plan

**Step 0. This doc.**

**Step 1. Two rule anchors before the band's middle, with tests.**
- Compute the band as today. Then:
  - if the month end nearest the newest end falls inside the band, and the ends do not also fit the last-weekday rule, the anchor is that month end *in the target year* (so February's follows leap years);
  - if every filed end is the last of its weekday in one and the same month, and no month end fits, the expected end is that weekday's last day in the target month, read exactly;
  - otherwise (both rules fit, or neither) the band's middle, as today.
- Both rules fit only when every filed end sits in its month's last four days; then nothing tells them apart and the old reading stays, so no answer that was right on `main` turns wrong.
- Tests in `tests/analysis/test_single_values.py`:
  - `test_a_year_on_the_last_weekday_of_a_month`: last Saturday of January, one and two years ahead; last Friday of February into and out of a leap year (3 of 4 fail on `main`).
  - `test_week_years_against_pandas_once_the_rule_shows[nearest|last]`: the pandas oracle over 7 weekdays × 12 months × 35 start years × one, two and six filed years × one and two years ahead; a wrong answer only where both rules fit, or for the weekday nearest the end of February (the band is computed across leap days); the last-weekday rule is right from six years. Both fail on `main`.
  - `test_every_filed_apple_and_jnj_end_is_expected_from_the_years_before_it`: every run of two or more filed Apple and J&J years, one and two years ahead, gives the date they filed (passes on `main` and here: no Phase 1 answer changes).
  - `test_one_52_week_year_alone_reads_forward_a_year`: Apple's FY2022 alone now gives 30 September 2023, the date it filed (on `main` it pinned the week-early 23 September, as a documented guess); 27 September 2025 alone, where both rules fit, still gives 26 September 2026; a mid-October end fitting neither still reads from the newest end.

Exit: full suite, `ruff check`, `ruff format --check` green. On the oracle sweep, with no case right on `main` turning wrong: last weekday 100% / 90% / 89% / 96% / 100% from one / two / three / four / six filed years (was 73% / 73% / 77% / 86% / 96%); weekday nearest a month end 73% / 84% / 91% / 99.9% / 99.7% (was 73% / 73% / 76% / 85% / 96%).

## Alternatives considered

- **Widen `WEEK_YEAR_REACH` to 6 for week years** (the issue's first idea). The band then holds both anchors for almost any company and its middle drifts, so more guesses, not fewer.
- **Use `pandas.tseries.offsets.FY5253` in the engine.** It needs the rule and anchor month given; Warren must still infer them from filed ends, which is the whole problem. Kept as the test oracle instead (pandas is already pinned).
- **Always prefer the month-end rule when it fits.** Right on every nearest-month-end company from one year, but turns about 3,000 of the sweep's last-weekday answers from right to wrong where both rules fit; rejected.

## Files to change

`domains/analysis/single_values.py` (`expected_year_end`, three small helpers), `tests/analysis/test_single_values.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`.

## Product impact

None today. The only output is `period_end` on a `not_filed_yet` cost-of-debt point, which the brief already words as "alrededor del {period_end}"; for the eight Phase 1 companies it does not change (Apple's and Johnson & Johnson's long histories give the same dates as before, tested). No field, code or name is added, renamed or removed. A later company on a last-weekday calendar (many U.S. retailers) gets a right expected date sooner.

## Review notes

Explainer and analyst not run: one date helper, no financial number, no stored output.

Professor: GO. The two rules match Treas. Reg. §1.441-2(a)(1) exactly, (i) the weekday's last occurrence in a month and (ii) the weekday nearest a month's last day, and nothing more; the tie rule is sound, since with both fitting the band's middle always lands on one of the two legal answers and no answer right on `main` changes. Taken: the docstring now names the regulation's two forms first and presents the fixed-anchor band as the fallback (it had taught "the Saturday nearest 27 September", which is not one of the forms), and says an end fitting neither form is not a §441(f) calendar as filed. Idea for the lesson: the last-four-days overlap as a question the data cannot settle yet. The professor could not fetch the regulation live (law.cornell.edu is outside the cloud's allowed hosts) and worked from its text.

Remaining, not in this item: the weekday nearest the end of February with several filed years can still be a week off, because the band compares ends across leap days; no Phase 1 company has a February year end.
