# Backlog #322: skip a part a filing tagged as the whole

Issue: https://github.com/sonderbot-ar/warren/issues/322 · Branch `backlog-322-part-as-whole` · Status: in review.

Owner decision (nov.13.2026, decision card): "General rule (recommended)": a general rule in the selection, recorded as an amendment to Decision 2, rather than a one-off fix for P&G.

## Problem

P&G's 10-K filed 2014-08-08 (`0000080424-14-000057`) tags three years of one segment's revenue as `us-gaap:Revenues` (28,400, 29,200 and 29,400 million for FY2012 to FY2014) and the company's net sales as `us-gaap:SalesRevenueNet` (82,006, 82,581 and 83,062). Warren ranks `Revenues` first (`concept_map.csv`), so Decision 2's rule (best tag first, then its newest filing) reads the segment as the company's revenue from that filing on, and keeps doing so after the 2015 and 2016 10-Ks recast the years under `SalesRevenueNet` only, since no later filing uses the higher-ranked tag. Today, as of any date after 2014-08-08, P&G's FY2012 to FY2014 revenue is a third of the real figure, its FY2015 growth is +160%, and every margin on those years is three times too large.

A scan of every item, period and filing for the eight companies (issue #322) finds 24 rows where two mapped tags of one item in one filing differ by more than twice. In 21 (MSFT and CAT cost of revenue) the best-ranked tag is the larger and the smaller one is a lower-ranked part, which the rule already ignores. Only P&G's three rows have the best tag as the smaller one. No stored run is affected (P&G has no runs dated 2012-08-08 to 2015-08-07).

## Plan

**Step 0. This doc, and Decision 2 amended** (`docs/structure-guide.md`, body and log row, nov.13.2026, owner decision).

**Step 1. The skip** (`domains/fundamentals/facts.py`).

- `_parts_as_whole(rows)`: one filing's rows for one period. While the filing's best-ranked row is positive and another row in the same filing is more than `PART_AS_WHOLE_RATIO` (2.0) times as large, that row is skipped and the next-ranked one is tested. Returns (kept, skipped).
- `_rows_by_period` applies it to every filing by default, so every reader of the rows agrees: latest and first-reported selection, quarterly derivations, `_versions` and `_tagged` (one basis, #329's own-tag check), recasts, meaning changes, disagreements and sign flips. `keep_parts=True` returns the raw rows.
- Only the filing's best-ranked tag is tested, then the next if that one is skipped: a lower-ranked part beside a larger best tag (MSFT, CAT) is left alone, as now.
- Only rows in the same filing are compared: a larger figure in a later filing is a restatement question, which the existing rule and recast checks own.
- Skipping a part removes that filing's figure only. If an older filing gave the period under the best tag, its figure is still the newest version of the best tag and is used, as for a skipped sign flip.
- `skipped_parts_as_whole(conn, cik, names, as_of)`: (selected, skipped) for each skipped row whose tag ranks at or above the selected one's (so it would have been read), as known on `as_of`.
- The quality report (`domains/fundamentals/quality.py`) counts the skips in its summary and lists them in a section "Parts skipped as tagged as the whole".
- Tests (`tests/fundamentals/test_facts.py`, `tests/fundamentals/test_quality.py`): 921 beside 460 in one filing is read in both modes; exactly twice (920) is not a part; a larger figure of the other sign is not a whole; a loss is never read as a part (a net loss of 10 beside a loss to common holders of 30, analyst); a smaller lower-ranked figure is left alone; a larger figure in another filing does not skip; the skip falls through two parts to the third tag; a later recast of the whole under the next tag is followed (P&G FY2013: 82,581 then 80,116); an older version of the best tag still wins; the listing, and nothing listed before the filing is public; the report section.
- Exit: full suite passes; the real-data scan below changes P&G's three revenue years and nothing else.

**Step 2. Saying so on the line** (`domains/analysis/reported.py`, `domains/analysis/__main__.py`).

- `Line.part_notes`: one `part_as_whole_skipped` note per skipped part the line rests on (its own period, a derivation input, or its first-reported filing). Params: `item`, `period`, `input_start`, `input_end`, `used` and `skipped` (each `accession_no`, `form`, `filed_at`, `value`, `xbrl_concept`), `first_reported_skipped` (the line's first-reported figure comes from the filing whose part was skipped, as for `sign_flip_skipped`; product lead). English: "revenue FY2013: the 10-K filed 2014-08-08 tagged 29,200,000,000 as us-gaap:Revenues for 2012-07-01–2013-06-30, less than half of what the same filing gives under another tag of the item; treated as a part tagged as the whole and skipped, so the figure is 82,581,000,000 (us-gaap:SalesRevenueNet, 10-K filed 2014-08-08)".
- A ratio that uses such a line carries `uses_part_checked_line` (`items`, `periods`), as `uses_sign_checked_line` does (#282); growth includes the prior year's line.
- The terminal view adds "(a part tagged as the whole, … as us-gaap:Revenues in 10-K … filed …, was skipped)".
- Tests (`tests/analysis/test_reported.py`): the year whose own filing has the part (value, tag, params, ratio notes, no note elsewhere); a prior year where the older whole is kept still notes the skip, on its line and on the next year's prior line; no note before the filing is public; the terminal and JSON.
- Exit: full suite passes.

**Tests changed.** Four existing tests put a second tag at more than twice the first in one filing as a convenience, which the rule now reads as a part. Their assertions are unchanged except one string: `test_priority_decides_between_tags_in_the_same_filing` uses 470 instead of 999 beside 460 (the case of 999 is now its own test); `test_a_move_within_the_recast_threshold_still_agrees`, `test_a_quarter_near_zero_is_checked_against_an_average_quarter` and `test_a_quarter_kept_on_its_own_tag_is_listed` scale the fixture's `Revenues` rows (×10, ×1,000,000) so the narrow tag stays within twice of them; the last one's "on Revenues it would be 0M" is now "130M", the figure in the same units.

## Real-data scan (Step 1)

`data/warren.db` (snapshot of nov.10.2026). Every item, all eight companies, as of 2010-06-01, 2011-06-01, 2012-06-01, 2013-06-01, 2014-08-08, 2015-06-01, 2015-08-07, 2015-08-10, 2019-06-01, 2023-06-01 and 2026-11-09; reported latest and first-reported, quarterly latest with and without one basis and first-reported; with the rule against without it (`PART_AS_WHOLE_RATIO` set to infinity). **28 differences, all P&G revenue, all three years:**

| P&G revenue | Before (Revenues, segment) | After, from 2014-08-08 | After, from 2015-08-07 | After, from 2016-08-09 |
|---|---|---|---|---|
| FY2012 | 28,400 | 82,006 | 82,006 | 82,006 |
| FY2013 | 29,200 | 82,581 | 80,116 | 80,116 |
| FY2014 | 29,400 | 83,062 | 80,510 | 74,401 |

First-reported FY2014 (the 2014 10-K is its first filing) goes from 29,400 to 83,062. Quarterly figures do not change: the quarters and the nine months are under `SalesRevenueNet` throughout. Recasts now read 83,680 → 82,006 for FY2012 in the 2014 10-K (was → 28,400) and find the 2015 and 2016 10-Ks' recasts of FY2013 and FY2014. Disagreements fall (P&G, 2026: 5,295 to 3,641 pairs), as the newest filings no longer disagree with a segment. Meaning changes and sign flips: no change. `skipped_parts_as_whole` lists exactly the three P&G rows.

## Alternatives considered

- **A one-off override for P&G's filing** (the card's other option). Fixes the three years but leaves the next filing that tags a part as the whole to the same error; the rule is one line in Decision 2 and catches only this case on real data.
- **Re-rank `SalesRevenueNet` above `Revenues`.** Breaks Walmart, where `Revenues` is the total beside a contract-revenue subtotal (`concept_map.csv`), and every company that uses both.
- **Prefer the largest tag in a filing.** Would read a total over its line in the wrong direction where a lower-ranked tag is broader (cash including restricted cash, the #295 meaning changes); the rule only stops a best tag that is less than half another.
- **A tighter ratio (1.5×) or a looser one (3×).** In one filing, for one item and period, another mapped tag is larger than the best-ranked one with the same sign 387 times across the eight companies: 371 within 10% (net sales against total revenues and the like), 13 between 1.1× and 1.73×, and P&G's three at 2.8–2.9×. The 13 are legitimate broader lines the rule must leave alone: KO's discontinued operations, the total against the part attributable to the company (8 rows, 1.12× to 1.73×); JNJ's marketable securities, the total against the current part (1.62×); Apple's D&A against D&A and accretion (3 rows, about 1.25×); JNJ's cash against cash with restricted cash (1.40×). 1.5× would skip KO's and JNJ's rightly ranked figures; 3× would miss P&G. Twice sits between the largest legitimate gap (1.73×) and the smallest part (2.8×), and is the plain reading of "the best tag is less than half of another". The line is calibrated in-sample, on the same eight companies, not taken from a published threshold (professor).
- **Compare against the item's other filings** (the year in the 10-K before). Tells a part from a whole too, but mixes the rule with restatement; one filing's own figures share a basis.

## Limits

- **Why the rule is needed at all.** A fact with no dimension stands for the whole entity; a segment's figure belongs on a segment axis (XBRL US DQC_0001, DQC_0041). P&G's 10-K left the axis off. Warren reads only undimensioned facts, so it cannot see the missing axis, and the size test stands in for that dimension check (professor).
- **Gross and net revenue.** A company that reports revenue both including and net of excise taxes can have the gross figure more than twice the net (Philip Morris International 2012: 77,393 against 31,377 million, 2.47×). If both tags ever map to `revenue` with the net one ranked first, the rule would skip the right figure. No Phase 1 company does this (professor).
- **The concept map.** The rule compares only mapped tags, so adding a broad tag to `concept_map.csv` can switch a skip on with no new filing. The quality report lists every skip, so it would show there (professor).
- The margin below the line is thin: a legitimate broader line more than twice the best tag (a total against an attributable part when the minority share is over half) would be skipped. The largest today is KO's 1.73×. The quality report lists every skip, so a wrong one shows there.
- **Positive figures only.** In a loss a narrower line can be larger in size than the best tag (a loss to common holders after preferred dividends against the net loss; P&G has ESOP preferred stock), so a negative best-ranked figure is never skipped (analyst; **taken**, with a test).
- **Broader tags by definition.** Some items map a lower-ranked tag that is by definition a total of the best one (marketable securities current and noncurrent, cash with restricted cash, capex as productive assets, discontinued operations in total against attributable). A minority or noncurrent share above half would cross 2× and skip the right figure. None does today (largest 1.73×). A per-pair flag in `concept_map.csv` marking which tags can stand for the whole is the sturdier fix: follow-up issue (analyst).
- **An older figure under the best tag still wins after a skip.** If an older filing had given the period under the best tag, it would be read over the skipping filing's newer whole, which may be on a later basis (a recast for discontinued operations), and growth could mix bases. P&G's 2012 and 2013 10-Ks use `SalesRevenueNet` only, so it does not arise today; a practitioner would take the skipping filing's whole. Same follow-up issue (analyst).
- A part that is more than half of its whole (a segment with 60% of revenue tagged as the total) is not caught. No such case in the scan; the quality report's disagreement section still lists it when a later filing reports the whole.
- A filing that tags only the part, with no whole beside it, is not caught: there is nothing in the filing to compare.

## Files

`domains/fundamentals/facts.py`, `domains/fundamentals/quality.py`, `domains/analysis/reported.py`, `domains/analysis/__main__.py`, `tests/fundamentals/test_facts.py`, `tests/fundamentals/test_quality.py`, `tests/fundamentals/test_quarterly.py`, `tests/analysis/test_reported.py`, `docs/structure-guide.md`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q1 and Q2 (a period's figures and ratios), Q3 and later questions on growth.

- **Changed:** P&G's revenue for FY2012 to FY2014, as known from 2014-08-08 on, is the company's (82,006 / 82,581 / 83,062, then the later recasts) instead of one segment's (28,400 / 29,200 / 29,400). Every ratio on those years, and FY2015's growth, changes with it.
- **Added:** `part_notes` on a reported line (list, usually empty), code `part_as_whole_skipped`, params as in Step 2; ratio note `uses_part_checked_line` (`items`, `periods`). Only P&G's three revenue years carry them today.
- Nothing renamed or removed.

## Design review (nov.13.2026)

Analyst, professor and the product lead in parallel, on the built branch (the change is small and was built with its tests before review; the explainer was not run).

- **Analyst: GO.** Re-ran the scan independently: only P&G's three pairs are above 1.73× (2.83–2.89×); P&G's quarterly revenue is the same with and without the rule; the notes sit on the right lines (FY2014 as of 2014-09-01 and its FY2013 prior line, the six ratios; FY2015 only on the prior line and growth; a reported Q4 carries none). Ideas: (1) losses: a loss to common holders is larger than the net loss, so a small loss year would trip the rule: **taken**, the rule reads positive figures only, with a test; tags broader by definition (cash with restricted cash, all marketable securities, total discontinued operations) should never count as the whole: Limits, follow-up; (2) after a skip an older, unrecast best-tag figure would win over the skipping filing's whole: Limits, same follow-up.
- **Professor: GO.** The undimensioned `Revenues` is a known kind of error (an entity-wide fact that should carry a segment axis; DQC_0001, DQC_0041, DQC_0161), and comparing two figures in one filing keeps restatement out (Debreceny et al. 2010; Du, Vasarhelyi and Zheng 2013; Chychyla and Kogan 2015 on as-filed versus standardized data). Suggestions, all **taken** in Alternatives and Limits: say why the dimension is missing; say 2× is calibrated in-sample; name gross and net revenue (PMI) as a possible false positive; note the concept map's role. Lesson idea: P&G FY2013, 29,200 against 82,581, which made FY2015 growth +160%.
- **Product lead: GO.** Nothing the app relies on breaks (`webapp/` reads no line notes yet; the brief does not quote P&G's old figures). Brief Q2 (Coca-Cola's operating margin against P&G's) gets more correct. Asked for `first_reported_skipped` on the note, as `sign_flip_skipped` has, so the screen can say whether the skip explains a first-reported difference: **taken**, with tests. The brief gets the note in its "why it comes from where it does" group, after `sign_flip_skipped`, on the front end's next update. Spanish: "Ingresos del ejercicio {period}: {used.value}. El {skipped.form} presentado el {skipped.filed_at} marca {skipped.value} con la etiqueta XBRL {skipped.xbrl_concept} para el período {input_start}–{input_end}. Esa cifra es menos de la mitad de lo que el mismo informe da para esta línea con otra etiqueta. Warren la toma como una parte marcada como si fuera el total, la deja de lado y usa {used.value} ({used.xbrl_concept}, {used.form} presentado el {used.filed_at}). No es una corrección de cifras: Warren no revisó qué incluye cada etiqueta, solo que una es mucho menor que la otra." Ratio: "Este ratio usa {items} de {periods}. En esos períodos, Warren dejó de lado una cifra que un informe marcó como el total pero que parece ser solo una parte (ver la línea)."
