# Backlog #331: a period filed again unchanged is not "after" a recast

Issue: https://github.com/sonderbot-ar/warren/issues/331 · Branch `backlog-331-refiled-unchanged` · Status: in progress (nov.11.2026).

From the analyst's design review of #325 (`docs/designs/backlog-325-recast-tag-switch.md`, Limits).

## Problem

A series note `series_mixes_vintages` (v0.9.54) splits a series of reported periods around a recast: periods that keep figures filed before it, and periods on its side. `facts.side_of_recast` (`domains/fundamentals/facts.py:542`) calls a reported period "after" when **any** filing on or after the recast reported it under the fact's own tag, even when that filing repeated the old figure unchanged. A comparative period filed again as it was is still the old figure, so the note puts it on the wrong side and can even raise a note on a series the recast did not split.

That is how Johnson & Johnson's 10-Q of 2024-07-25 and P&G's 10-Q of 2013-01-25 produced false notes before v0.9.56: each moved only a six-month figure, and FY2023Q2 and FY2012Q2 were "after" only because the quarter was filed again unchanged. v0.9.56 removed those two by leaving half-year-only recasts out of a quarter series, but the path stays for any filing that refiles a period unchanged after a recast that moved something else, for example the recast 10-K's own earliest comparative year.

## Plan

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

`domains/fundamentals/facts.py`, `domains/analysis/reported.py`, `tests/analysis/test_series_recast.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Brief Q1 and Q2 ("Notes on a series"). No values change; no field, code or param is added, renamed or removed.

- **Changed:** in `series_mixes_vintages`, a period whose figure was only filed again unchanged on or after the recast is listed in `before_periods`, not `after_periods`. A series whose only "after" periods were such refilings gets no note. Real-data effect in Step 2.
- `moved_periods`, `mixed_periods` and the text are unchanged.

## Limits

- A derived quarter still sits by the filing dates of its inputs: an input filed again unchanged after the recast counts as after. A `Fact` keeps only its inputs' accession numbers, not their periods, so the same rule needs the inputs' periods carried on the fact (a follow-up if the scan shows a case).
- An unchanged comparative is called "before" even when the company meant it as already on the new basis (a change that did not touch that year). The engine cannot tell the two apart from tagged data; the note hedges.
