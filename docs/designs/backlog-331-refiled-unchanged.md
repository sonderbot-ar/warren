# Backlog #331: a period filed again unchanged is not "after" a recast

Issue: https://github.com/sonderbot-ar/warren/issues/331 · Branch `backlog-331-refiled-unchanged` · Status: merged as v0.9.57, won't fix (PR #334, merge `159ce6b`, nov.12.2026). **Outcome: the proposed rule is rejected after design review and a real-data trial; v0.9.54's rule is kept, now explained in code and pinned by tests.**

From the analyst's design review of #325 (`docs/designs/backlog-325-recast-tag-switch.md`, Limits).

## Problem

A series note `series_mixes_vintages` (v0.9.54) splits a series of reported periods around a recast: periods that keep figures filed before it, and periods on its side. `facts.side_of_recast` (`domains/fundamentals/facts.py:542`) calls a reported period "after" when **any** filing on or after the recast reported it under the fact's own tag, even when that filing repeated the old figure unchanged. A comparative period filed again as it was is still the old figure, so the note puts it on the wrong side and can even raise a note on a series the recast did not split.

That is how Johnson & Johnson's 10-Q of 2024-07-25 and P&G's 10-Q of 2013-01-25 produced false notes before v0.9.56: each moved only a six-month figure, and FY2023Q2 and FY2012Q2 were "after" only because the quarter was filed again unchanged. v0.9.56 removed those two by leaving half-year-only recasts out of a quarter series, but the path stays for any filing that refiles a period unchanged after a recast that moved something else, for example the recast 10-K's own earliest comparative year.

## Outcome (nov.11.2026)

The proposal below was built on the branch and tried on real data, then reverted. What ships instead:

- `side_of_recast` keeps v0.9.54's rule: a period reported on or after the recast's filing date under the fact's own tag is "after", even when its figure did not move. Its docstring now says why (ASC 250-10-45-5) and what the alternative did on real data.
- New test `test_a_period_filed_again_unchanged_sits_after_the_recast` (`tests/analysis/test_series_recast.py`) pins three cases on Coca-Cola's shape: refiled unchanged in a later filing (after), refiled unchanged in the recast's own filing (after), never filed again (before). The existing tests already pinned the recast 10-K's unchanged comparative year (FY2016 after; FY2016–FY2019 gets no note).

**Why it was rejected.**

1. **The accounting (professor, NO-GO).** A change of accounting principle is applied retrospectively to every prior period presented (ASC 250-10-45-5), and comparative statements must be comparable or the exception disclosed (ASC 205-10-45-2). A figure a filing presents unmoved beside recast figures is therefore presumed to be on the new basis: the change simply did not touch it. The design's case for "before" leaned on modified retrospective adoption (ASC 606, ASC 842), but that method moves no comparative figure, so `item_recasts` never finds a recast there (`facts.py`, its `RECAST_MOVE` check) and `side_of_recast` never runs on it. Old-basis comparatives under impracticability (ASC 250-10-45-6/7) are rare and disclosed.
2. **Real data (Step 2 trial).** Same scan as v0.9.54 and v0.9.56 (every five-year series starting FY2009–FY2021 and every eight-quarter series starting Q1 2009–2024, eight companies, as of 2026-11-09; snapshot of nov.10.2026, 903 of 903 stored runs reproduce to the cent). The proposed rule took notes from 38 on 31 series to **61 on 39 series**: 23 notes added on 14 series, none removed. Year series unchanged. The added notes are false in the cases checked: a quarter first reported **after** the basis change, in a filing that already used the new basis, and filed again unchanged a year later, became "before" a later 10-Q that recast older comparatives. Examples: Coca-Cola's FY2019Q2 (first filed 2019-07-25 in the 10-Q that itself recast 2018's Q2; "before" the 10-Q of 2019-10-24), Procter & Gamble's FY2014Q2 against the 10-Q of 2015-04-23 and five more P&G recasts of 2015–2016, Johnson & Johnson's FY2022Q3 and FY2023Q3 against the 10-K of 2024-02-16, Apple's FY2009 and FY2010 quarters against the 10-Q of 2010-07-21. A "before" side needs "first reported before the change took effect", which the tagged data cannot date; the filing that presents the figure is the best evidence there is.
3. **The original cause is already gone.** The two false notes that motivated #331 (J&J's 10-Q of 2024-07-25, P&G's 10-Q of 2013-01-25) were removed in v0.9.56 because those filings moved only half years.

No values, notes, fields or text change. #331 is closed with this doc.

## Plan (as proposed, not shipped)

**Step 0. This doc.**

**Step 1. "After" means a new figure, not a new filing** (`domains/fundamentals/facts.py`, `domains/analysis/reported.py`).

- `version_dates` becomes `tag_versions(conn, cik, canonical_name, as_of)`: (start, end, tag) -> `[(filed_at, value), ...]`, one entry per filing public on `as_of` that reported the period under that tag (the filing's last row of that tag, as `_best_tag_rows` reads a filing), in filing order (`_filing_order`: filing date, then accession). Its only caller is `_series_recast_notes`.
- `side_of_recast` for a reported fact, in order:
  1. the recast moved the period (its start and end are in `recast.periods`): "after";
  2. no filing reported it under the fact's tag on or after the recast's filing date: "before";
  3. no filing reported it under that tag before the recast's filing date (first reported in it or later): "after";
  4. otherwise "after" only when a filing on or after the recast gave a figure that moved by more than `RECAST_MOVE` (0.5%, the same threshold that finds a recast) from the last figure filed before it, else "before".
- A derived quarter is unchanged (by the filing dates of its inputs); see Limits.
- The note's English for "before" already says "keeps figures filed before it, with no later version in the filings' tagged data"; a period refiled unchanged has no later version, so the text stays true and is not changed.
- Tests (`tests/analysis/test_series_recast.py`, Test Corp, whose FY2018 10-K recasts periods ending in 2017 or later by −5% and repeats FY2016 unchanged):
  - the existing year test: FY2016 moves from `after_periods` to `before_periods` (it was filed again unchanged in the recast 10-K); the text reads "FY2015 and FY2016 keep figures filed before it";
  - unit tests of `side_of_recast` on hand-built versions: moved by the recast (after), refiled unchanged on and after the recast date (before), refiled 0.4% off (before), refiled 1% off (after), first reported on the recast date (after), never filed again (before);
  - a series of FY2015–FY2016 only (both before) gives no note (before this change: a note, FY2016 after);
  - the quarter test keeps FY2018Q1 after (its own 10-Q of 2019 recast it).
- Exit: the full suite passes; the real-data scan below lists every note that changes and why.

**Step 2. Real-data scan** (snapshot restored and checked first). The same scan as v0.9.54 and v0.9.56: every five-year series starting FY2009–FY2021 (13 per company) and every eight-quarter series starting Q1 2009–2024 (16 per company), eight companies, as of 2026-11-09; before is `main` (v0.9.56), after is this branch. Results below when built.

## Alternatives considered

- **Keep "refiled" as after** (v0.9.54's rule: a filing that presents both years has them on one basis). True for a full retrospective restatement, but then the refiled year would have moved too, unless the change did not touch it. Under a modified retrospective adoption (ASC 606, ASC 842) the earliest comparatives are kept on the old basis, and the note exists to flag exactly that. Calling an unchanged figure "before" can at worst give a cautious note on a pair that was comparable; calling it "after" can hide a real break. The note already hedges ("may not be like for like"); the cautious side fits a teaching tool.
- **Exact equality for "unchanged".** A rounding revision (a few thousand dollars, or a figure tagged in millions then in thousands) would count as a new basis. `RECAST_MOVE` is the threshold the engine already uses for a recast.
- **Compare with the figure `latest` mode showed across tags** (as #325 did for finding recasts). `side_of_recast` reads one tag, the fact's own, as before; the fact is the figure the series shows, so its tag is the shown one. Mixing tags here would add the lower-ranked tags' figures back.

## Files

Shipped: `domains/fundamentals/facts.py` (the `side_of_recast` docstring), `tests/analysis/test_series_recast.py`, this doc. The unshipped proposal also touched `domains/analysis/reported.py`. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q1 and Q2 ("Notes on a series"). As shipped: none. No values, notes, fields, codes or text change.

The proposal would have moved refiled-unchanged periods from `after_periods` to `before_periods` and added notes. The product lead gave GO on that and planned to reword the brief's {before} sentence; with the rule kept, the brief's "Warren no tiene una versión posterior" stays accurate in the sense the engine means it (a period in `before_periods` was not filed again by the recast or later).

## Limits

- A period first reported before a recast and presented again unchanged after it is presumed on the new basis. If a company left a comparative on the old basis (impracticability, ASC 250-10-45-6/7), the note will not say so; the filing's text does.
- A derived quarter sits by the filing dates of its inputs, the same presumption.

## Design review (nov.11.2026)

Explainer, analyst, professor and the product lead in parallel, on the proposal.

- **Professor: NO-GO, accepted.** The rationale contradicts ASC 250-10-45-5 and ASC 205-10-45-2 and rests on modified retrospective adoption, which this path never sees; the plan also missed that `test_a_series_on_one_side_has_no_note` (FY2016–FY2019) would flip to a note. Suggested keeping v0.9.54's rule or proving each changed split from a filing: the real-data trial above did the latter, and the changed splits were wrong.
- **Analyst: NO-GO, accepted.** Ran the same trial independently and got the same count (23 notes added on 14 quarter series, none removed, year series unchanged), every added note checked false. Real recasts are staged: one event (a business sold, a new revenue rule) is rolled through each later filing as its comparative comes up, so a quarter first filed on the new basis, or recast earlier in the chain, is refiled unchanged and the proposal called it "before". Examples with filings: J&J FY2023Q3 (first filed 2023-10-27 with Kenvue already out, 21,351) against the 10-K of 2024-02-16; Coca-Cola FY2019Q2 (9,997, filed 2019-07-25, after Coca-Cola Beverages Africa moved back into continuing operations) against the 10-Q of 2019-10-24; Apple FY2010Q2 (13,499, filed 2010-04-21, after the 10-K/A of 2010-01-25). Also: derived quarters left on the old rule would have mixed two rules in one Coca-Cola note; the split de-duplication would stop working on chains. Recommended closing #331 as won't-fix. Suggestion not taken here: its recast counts per company (revenue, as of 2026-11-09) differ from those quoted in #325's doc, which did not say which items or date it counted; recorded, no code depends on them.
- **Product lead: GO** on the proposal's Product impact (nothing breaks; would have reworded the brief's {before} line). Moot as shipped.
- **Explainer: NO-GO on clarity** (the tag in rule 4, signed or absolute move, the missing-key case, a pass rule for the scan). Moot as shipped; the prototype used the fact's own tag, an absolute move, and the old fallback for a missing key.

## PR review (nov.12.2026)

Gatekeeper: **GO**, conditional on CI completing green. Ruff clean; 831 passed in `tests/analysis` and `tests/fundamentals`, full suite 2131 passed, 10 skipped. Only the `side_of_recast` docstring and one test change; no test weakened; point-in-time reads untouched. Notes taken: the test's docstring now says `side_of_recast` reads dates, not values; the Files section lists only what shipped. The status line is updated at merge.

CI: the first run (nov.11 20:28 UTC) stayed queued with no jobs for over 16 hours and could not be cancelled; this commit starts a new one.
