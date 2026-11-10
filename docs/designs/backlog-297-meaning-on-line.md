# Backlog #297: a tag that changed meaning, said on the line, and quarters that mix both meanings

Issue: https://github.com/sonderbot-ar/warren/issues/297 · Branch `backlog-297-meaning-on-line` · Status: in review.

Items built here: 1 (first half: "mixed"), 3 (the note on the line), 8, 9 and 10 (gatekeeper tidy-ups from PR #298). Item 6 was answered by the front-end in the brief (PR #303). Items 1 (second half: a run note), 2 (sums and series), 4 (like-for-like growth), 5 (line labels) and 7 (a change first shown in a Q1 10-Q) stay open in #297.

## Problem

v0.9.46 (#295 item 3) flags revenue growth whose two periods carry different meanings of a tag that changed meaning: Exxon's `us-gaap:Revenues`, sales until 2019, total revenues and other income from the 10-Q of 2019-11-06 on. Two gaps remain.

1. **The level reads as a restatement (item 3).** `reported_period(XOM, FY2018, 2026-11-09)` shows revenue 290,212 with `changed` on and first reported 279,332. The brief's side panel can only say "cambió respecto de la primera cifra publicada", and a student reads that as Exxon restating its revenue. It did not: it moved the tag to a broader line and still files 279,332 under `RevenueFromContractWithCustomerExcludingAssessedTax`.
2. **A derived quarter can mix both meanings (item 1).** `meaning_of` judges a derived quarter by its newest input alone. Exxon FY2017Q4 plain is 72,513 = 244,363 (the 2017 year from the 10-K of 2020-02-26, new) − 171,850 (nine months from 2017, old): neither meaning. `meaning_of` says "new". The reported view's own figure for that quarter is on one basis (65,312, old), but the plain derivation it shows beside it is the mix, and a company that does not file nine-month figures (Test Corp below) gets a mixed quarter as the line's own value.

## Plan

**Step 0. This doc.**

**Step 1. Old, new or mixed (`facts.meaning_state`), and the tidy-ups.**

- `meaning_state(fact, changes, filed_at=None) -> ("old" | "new" | "mixed", change | None)`. "new": as `meaning_of` in v0.9.46 (same item, its tag among the fact's tags, its newest input filed on or after the change). "mixed": a derived quarter whose newest input is on or after the change while another input was filed before it; it needs `filed_at`, a map from each input's accession number to its filing date. Without the map, a derived quarter is judged on its newest input alone, as before. "old": anything else; the change is returned when the fact's tag is one that changed later, None when its tag never changed.
- `meaning_of` keeps its signature and meaning ("new" throughout), with the optional map; with it, a mixed quarter is not "new".
- Item 10: when one tag shows more than one change (two "other tags"), the earliest filed dates the fact (then the accession number), not the first in the list.
- Item 8: the quality report's section and the comment above `MEANING_CHANGE_MIN_PERIODS` no longer say "redefined"; they use the student note's neutral words (the two values measure different lines). The `MeaningChange` docstring already did.
- Item 9: the quality report keeps only the periods of each change that end within its fiscal years (from the earliest start to the latest end of its cells), as `disagreements` are filtered; a change with no period left is dropped; its filing date stays the first filing's.
- Tests (`tests/fundamentals/test_meaning_change.py`): a derived quarter with inputs on both sides is mixed and `meaning_of` gives None; inputs all after is new, all before is old; without the map it is new as before; a reported value is never mixed; another tag has no change; two changes of one tag are dated by the earliest in either list order; the quality report's cut by year and its wording.
- Exit: the full suite passes; v0.9.46's tests pass unchanged except one assertion that lists the growth note's params, which gains the new `mixed` param (additive).

**Step 2. Say so on the line (`reported_period`), and on growth with a mixed quarter.**

- Each line in `lines` and `prior_lines` gains `meaning_note` (a `Coded` or null). Code `tag_changed_meaning` (the code the growth note uses, on a different field), params: `item`, `period` (`FYyyyy[Qn]`), `tag`, `other_tag`, `changed_on` (ISO), `form`, `accession_no`, `meaning` (the line's value: `old`, `new` or `mixed`), `first_reported_meaning`, `plain_meaning` (the plain derivation's, when the line is on one basis, else null) and `first_reported_differs` (bool: the change from the first-reported figure is, at least in part, a different line, not a restatement). Present only when those meanings are not all the same, or one is mixed; a line whose figures all carry one meaning, or whose tag never changed, has none.
- Growth (`revenue_growth_yoy`): `meaning_state` with the filings' dates replaces `meaning_of`. Two periods on different meanings, or one mixed, get the note. New param `mixed` (list of period labels, usually empty); `new_meaning` or `old_meaning` is null when no period carries that meaning alone. For old against new the text is v0.9.46's; with a mixed period it says the quarter is worked out from figures filed before and after the change.
- The terminal view prints the line's note under the line.
- Tests (`tests/analysis/test_reported.py`, Test Corp's `Revenues` 4% higher from its Q3 2019 10-Q, the old figures kept under the contract-revenue tag): the note on FY2018Q3, FY2018, FY2017 and FY2019Q1 (each first reported old and refiled new; `changed` on, value 1.04 × first reported); none on FY2019Q2 (never refiled), FY2019 and FY2019Q3 (first reported new), FY2020Q1 and FY2017Q1; none on FY2018Q3 on 2019-12-31 (one period shows the change so far); FY2017Q4 on one basis old, its plain derivation mixed; FY2018Q4 mixed (the 2018 year from the FY2019 10-K less Q1 and Q2 2018, never refiled, and Q3 2018, refiled) with growth against FY2017Q4 noted as a mix; no other line, and nothing for the unedited Test Corp; the JSON and the terminal carry it.
- Exit: on the real data as of 2026-11-09, every period FY2009–FY2026 of the eight companies: Exxon's lines and prior lines as in the table below, nothing for the other seven; Exxon's growth notes exactly v0.9.46's five, none mixed.

## Real data (snapshot of nov.05.2026, as of 2026-11-09)

Every period FY2009–FY2026, quarters and years, for the eight companies. Only Exxon's revenue gets a line note; nothing for the other seven.

| Exxon revenue | Value | First reported | Meaning (value / first reported / plain) | `changed` |
|---|---|---|---|---|
| FY2017 | 244,363 | 237,162 | new / old / – | on |
| FY2017Q4 | 65,312 (one basis) | 65,312 | old / old / mixed (plain 72,513) | off |
| FY2018 | 290,212 | 279,332 | new / old / – | on |
| FY2018Q3 | 76,605 | 74,187 | new / old / – | on |
| FY2018Q4 | 71,895 | 68,253 | new / old / – | on |
| FY2019Q1 | 63,625 | 61,646 | new / old / – | on |
| FY2019Q2 | 69,091 | 67,491 | new / old / – | on |

(Millions of dollars.) Each shows on its own period and as the prior line of the period a year later (FY2018, FY2018Q4, FY2019, FY2019Q3, FY2019Q4, FY2020Q1, FY2020Q2). In every "new / old" row the whole change from the first reported is the move to the broader line: the first-reported figure is the one still filed under the contract-revenue tag (279,332 for FY2018; FY2018Q4's 68,253 = 279,332 − 211,079). Exxon files nine-month figures, so its line values are never mixed; only FY2017Q4's plain derivation is.

Growth notes: Exxon FY2017, FY2018Q3, FY2018Q4, FY2019Q1 and FY2019Q2, the same five as v0.9.46 with the same values, `mixed` empty. None elsewhere.

Runs are untouched: no run reads `meaning_state`, and no stored number changes.

## Alternatives considered

- **Turn `changed` off when the whole change is the new meaning.** `changed` means "the latest figure differs from the first reported", which stays true; hiding it would lose a fact the app relies on. The note explains it instead.
- **A separate code for the line (`line_tag_changed_meaning`).** The two notes sit on different fields (`Line.meaning_note`, `Ratio.notes`) and the front-end already ranks `tag_changed_meaning` first; one code keeps that rule simple.
- **Store each input's filing date on the derived `Fact`.** Cleaner for "mixed", but `Fact` is part of every run's stored inputs; a new field risks the reproduce invariants for a note. The reported view already has every accession's date (`_Filings`), so `meaning_state` takes the map.
- **Count an input as old only if its own tag is the changed one.** A derived quarter's inputs can carry different tags; the map only has dates. No derived quarter on the real data mixes tags across Exxon's change, so this is left as a limit.

## Files

`domains/fundamentals/facts.py`, `domains/fundamentals/quality.py`, `domains/analysis/reported.py`, `domains/analysis/__main__.py`, `tests/fundamentals/test_meaning_change.py`, `tests/analysis/test_reported.py`, this doc. At merge: `docs/versions.md`, `docs/team-sync.md`.

## Product impact

Serves brief Q1 and Q2 (what a company reported, and how it grew).

- **Added:** `reported_period(...).lines[].meaning_note` and `prior_lines[].meaning_note` (`Coded` or null), code `tag_changed_meaning`, params as in Step 2. English fallback text, for Exxon FY2018: "revenue FY2018 is us-gaap:Revenues with the meaning the 10-Q filed 2019-11-06 gave the tag; the first-reported 279,332,000,000 has the tag's earlier meaning, whose figures are still filed under us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax. The change from the first reported is a different line, not a restatement".
- **Added:** param `mixed` (list of period labels) on the growth note `tag_changed_meaning`; `new_meaning` or `old_meaning` can now be null, only when `mixed` is not empty. No real-data period has a mixed growth note today.
- **Nothing renamed or removed; no value changes.**
- For the app: in the side panel, when `meaning_note.params.first_reported_differs` is true, replace "cambió respecto de la primera cifra publicada" with the meaning note (suggested Spanish: "Exxon cambió lo que mide esta etiqueta en el 10-Q del 6 de noviembre de 2019: la primera cifra publicada (279.332 millones) medía otra línea, que se sigue presentando con otra etiqueta. La diferencia no es una reexpresión."). Keep "reexpresión" only in the negative. Rank it with the growth note, first (brief, "Notes on a reported figure"). When `plain_meaning` is `mixed`, add to the plain derivation's panel: "este cálculo mezcla cifras de antes y después del cambio". When `meaning` is `mixed` (no real case today): "este trimestre mezcla dos definiciones de la línea".

## Limits

- A derived quarter is judged mixed by its inputs' filing dates, not their tags (above).
- Runs still read the same numbers and carry no note (#297 item 1, second half); sums, series and track records across the change mix the two meanings (item 2); no like-for-like growth (item 4); no line labels (item 5); a change first shown in a Q1 10-Q is noted only from the Q2 10-Q (item 7).
- Only revenue is scanned for a change of meaning in the reported view, as in v0.9.46.

## Where the work stopped

nov.10.2026: Steps 0–2 built, full suite green (2,036 passed, 10 skipped). Next: design review, PR, gatekeeper, merge.
