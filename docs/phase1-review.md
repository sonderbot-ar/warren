# Phase 1 review: does news make Warren's forecasts better?

Written nov.02.2026 from backtest batch `eval_2026-11-02_1` (M8). Every number below is in that batch's report, `data/reports/eval/eval_2026-11-02_1_backtest.md` (and the M3 report `eval_2026-11-02_1.md`), and the batch reproduces from stored runs, shocks and seeds (`python -m domains.evaluation reproduce --batch eval_2026-11-02_1 --guidance domains/evaluation/guidance.csv`: 728 rows and 39 simulations, to the cent). Method: `docs/designs/m8-backtest.md`.

## The answer

**Not shown.** With the AI's news shocks added, Warren's forecasts of the next four quarters are a little better on average, but the gain is small and well inside what chance alone gives on 26 cases. Phase 1 has built a pipeline that can answer the question honestly; on today's evidence the answer is "maybe a little, can't tell yet".

The headline was fixed in the design before any result was seen: per item, the skill score against the baseline and the per-case sign test, on all 26 cases, for the masked variant (company name and dates hidden from the AI), with the named variant beside it.

| Variant | Item | Skill (mean / median) | Cases better / worse / unchanged | Sign test p | 90% interval of mean d |
|---|---|---|---|---|---|
| AI, masked | Revenue | +2.1% / −4.1% | 8 / 6 / 12 | 0.79 | −1.81 to +1.14 points |
| AI, masked | EBIT | +1.5% / +10.4% | 10 / 8 / 8 | 0.82 | −0.35 to +0.13 points |
| AI, named | Revenue | +5.4% / +18.1% | 7 / 4 / 15 | 0.55 | −2.19 to +0.59 points |
| AI, named | EBIT | +2.4% / +16.1% | 9 / 8 / 9 | 1.00 | −0.40 to +0.06 points |
| Guidance (3 cases) | Revenue | +1.1% / 0.0% | 2 / 1 / 0 | 1.00 | −0.40 to +0.14 points |
| Guidance (3 cases) | EBIT | −1.2% / −1.1% | 0 / 3 / 0 | 0.25 | +0.08 to +0.12 points |

Skill is 1 − mean error with shocks ÷ mean error without (above 0 is better). d is a case's mean error with shocks minus without (below 0 is better). Every interval for the AI's shocks includes zero. Guidance EBIT's (+0.08 to +0.12) does not: on all 3 guidance cases the shocked EBIT was slightly worse.

## What worked

- **The pipeline and the guardrails.** All 26 cases ran with no failure, in up to five variants (guidance shocks exist for 3 cases), on the same stored baseline per case, with every cited event checked against the case date in New York time. The AI produced no number: it picked classes, code sized them (M6), and the whole batch reproduces to the cent.
- **Shocks helped where the news was about this quarter's business.** Apple's China lockdown warning (AAPL_2022-11-06: revenue error 7.5 points lower, EBIT 1.9 lower), Caterpillar's outlook cut (CAT_2019-10-23: revenue 13 points lower), the 2020 oil price war (XOM_2020-03-09: revenue 2–4 points lower, EBIT 1.2–1.4 lower), Coca-Cola buying BodyArmor (KO_2021-11-01: 8.6 points lower), P&G's raised outlook (PG_2019-04-23: 2–3 points lower). Helping is not the same as being good: with the cut, Apple's 2022–23 revenue was still about 11% off, against under 3% for simply repeating last year's quarter, because the baseline was 16–22% too high in every quarter.
- **Direction improved.** The share of quarters where the forecast got up, flat or down right rose from 61% to 65% (masked) and 71% (named) for revenue, and from 62% to 66% for EBIT. For revenue, "always up" still scores 74%, so this is catching up, not beating a simple rule; for EBIT (52% of quarters rose) the forecast does beat it.
- **Quiet days stayed mostly quiet.** On the 8 control dates, 3 of 16 sets proposed a shock, and their effect on error was small (mean d −0.11 revenue, −0.06 EBIT points masked).

## What failed

- **Mergers.** The two biggest losses are deals: Microsoft's Activision close (MSFT_2023-10-13: revenue error 6.8 points worse) and Exxon's Pioneer deal (XOM_2023-10-11: 12 points worse masked). The shock size comes from how much revenue growth usually moves (σ, capped at 10 points, times the size class), not from the size of the company bought: the Activision shock adds about 10% to every quarter, where Microsoft's revenue in its first full quarter with Activision came in only about 3% above the baseline; the masked Pioneer shock, sized "large", adds 20% to Exxon's revenue, the named one 10%. And nothing ties the start to the closing date: the Activision shock already lifts the September 2023 quarter, which ended before the deal closed on Oct 13; the Pioneer shock starts in the first quarter of 2024 (masked) or the last of 2023 (named), one or two quarters before the May 2024 close. Backlog #102 (size M&A from the target's revenue share) is the fix, plus starting a deal's shock at its close.
- **News that wasn't material.** The AI cut Johnson & Johnson's revenue for the vaccine pause (JNJ_2021-04-13: 2.9 points worse). The vaccine was a small part of sales, and the cut also hit the March 2021 quarter, which had ended nine days before the pause.
- **Material news, wrong timing.** Apple's February 2020 warning (AAPL_2020-02-17: 2.6 points worse) was about the March quarter, but the AI started the cut in the next one, so it missed the March fall (revenue $58.3B against a forecast $61.9B). The cut helped the September quarter (error 5.6% to 1.8%) and hurt the June and December ones, which grew. In an earlier proposal set for the same case the model started the cut a quarter earlier, so the start quarter itself is unstable.
- **The bands are far too narrow.** Only 12–25% of actuals fall inside the AI variants' p10–p90 band, against the 80% Decision 7 asks for; 0 of 12 for guidance. This was expected: the band only covers the uncertainty in the shocks' size, not the baseline's own error (M4). Even on the quarters a shock widened, coverage is only 18–41%. The interval score shows the band still carries some information (masked revenue, on those quarters: 136 for the band against 169 for its own p50 as a point and 175 for the baseline), but it is not a calibrated range.
- **Guidance shocks don't help EBIT.** In all 3 guidance cases the shocked EBIT was slightly worse (+0.10 points). Three cases can't show anything (the smallest possible p is 0.25), but company guidance read at face value is not a free win.
- **Named and masked disagree.** In 2 cases the two variants moved an item in opposite directions (PG_2019-07-30 revenue and EBIT, WMT_2022-11-15 EBIT). The named variant does a little better on every headline number; that is what the model's memory of what came next would look like, but the distraction of the name can do the same (Glasserman & Lin 2023), and every case is before the models' training cutoff, so the gap can't be read as look-ahead.

## The baseline is the bigger problem

The news layer moves errors by fractions of a point on average; the baseline's own errors are several points. Against the naive forecast (same quarter last year), the baseline wins on medians (revenue 6.1% against 7.2%, EBIT 3.3 against 4.1 margin points) but loses on the mean for revenue (skill −17%), because a few cases are badly off, all but one of the worst eight at Exxon: in 2020 the baseline missed the oil collapse by 121–129% in the June quarter (XOM_2019-08-19, XOM_2020-03-09), and in 2023 it ran 53% too high after the 2022 price spike (XOM_2023-10-11). A commodity producer's revenue follows prices, which a growth-extrapolating baseline can't see.

## Which event types help, and which add noise (descriptive only)

One to eight cases per type, so this describes and can't prove anything. Mean d per case, masked (named in brackets), in points:

- **Supply chain** (1 case): revenue −7.5 (−7.5). Helped.
- **Macro** (1): revenue −2.1 (−4.1), EBIT −1.2 (−1.4). Helped.
- **Guidance** (6): revenue −2.1 (−2.5), EBIT +0.2 (+0.2). Helped revenue, not margins.
- **Litigation** (2): EBIT −0.4 (−0.2); revenue untouched. Small help.
- **Restructuring** (4): about zero, with the two variants pulling opposite ways on P&G.
- **M&A** (3): revenue +3.4 (+2.6). Hurt, for the sizing reason above.
- **Regulation** (1): revenue +2.9 (+2.9). Hurt (the vaccine pause).
- **Controls** (8): about zero. Little noise.

## What Phase 2 should tackle

In order of what the evidence says matters most:

1. **A band that includes the baseline's own error.** Without it, Decision 7's coverage check can't pass and "how sure are we?" has no honest answer. Build it point-in-time from the baseline's errors on dates before each case, and test it on held-out dates.
2. **More cases, and some after the models' cutoff.** 26 cases can't separate a 2–5% gain from zero. The one-command pipeline (M7) makes new dates cheap; cases dated after June 2026 are the only clean test of the model's memory.
3. **Deal sizing from deal facts** (backlog #102): target revenue share and the closing date.
4. **A baseline that knows about commodity prices** for producers like Exxon, or at least a flag that its baseline is weak.
5. **Calibrating the size scales on held-out cases** (backlog #73), only after (2), so the method isn't tuned on its own test.
6. **Stability of the AI's proposals:** named/masked flips and the earnings-versus-guidance line (backlog #103).

Changing Phase 2's goal or scope is the owner's decision; these are proposals.

## Limitations

The events were chosen in hindsight as notable (the controls and the naive benchmark are the check). With 26 cases most differences can't be told from chance, and the case bootstrap's intervals tend to be too narrow with this few cases (Efron & Tibshirani 1993, ch. 14). The AI may remember what happened next, masked or not. The bands cover shock size only. The shock sizes were set in M6, before any result, and were never tuned on these cases. The simulations of the named and masked variants share a seed but not their random draws when their shock lists differ (design, Seeds).

## For the decision log

No decision changes. Status notes were added to Decision 6 (shocks measured in M8: a small gain, not shown, mergers mis-sized) and Decision 7 (the M8 backtest: skill, sign test, direction, coverage; bands far from 80% because they cover shock size only).
