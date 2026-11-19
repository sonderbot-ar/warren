# Backlog #451, part 2: the label tie, CAT's maturities tag, the placed read, FY and Q4 at two dates

Issue: https://github.com/sonderbot-ar/warren/issues/451 (items 2, 3, 6 and 7; part 1 was v0.10.7, `docs/designs/backlog-451-rounding-note-reach.md`) · Branch `backlog-451-labels-and-q4` · Version v0.10.8, merged nov.18.2026 (PR #464, merge `e177063`, after CI green and a gatekeeper GO). Reading rules stay v11: no read changes (Step 3), so each step's new fingerprint (Steps 2 and 3) gets a row under v11 in `domains/analysis/reading_rules.md` (the fingerprint is the hash of the reading modules' code, `python -m domains.analysis.reading_rules`).

## Problem

Part 1 (v0.10.7) closed items 1 and 5 and the carried-forward item. Six items stayed open. Four are engine items this part settles (three built, one declined with a reason):

- **Item 2 (analyst, #430 review).** When the plain and the lease-inclusive current portion label one balance date differently, `facts._labels` prefers an `FY` label over a quarter's. The analyst suggested settling the tie from the company's fiscal year end, stored in `companies.fiscal_year_end` (KO `1231`, AAPL `0925`, JNJ `0103`).
- **Item 3 (analyst).** Caterpillar's current portion comes only from `LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` (the debt note's principal due within a year), not the balance-sheet line. If CAT ever filed the lease-inclusive current tag too, `_within_rounding` would compare a balance-sheet figure with a note figure.
- **Item 6 (gatekeeper, PR #452).** Since #430, annual and quarterly reads of `debt_current` come from `facts._placed` over a reported read, not from `_get_facts`'s own annual and quarterly path. They matched `main` on all 672 survey reads, but no unit test pins that, with two tags mapped to `debt_current` itself, the placed read ranks them as the single-item read does.
- **Item 7 (gatekeeper, PR #452).** In quarterly mode a balance labelled `FY` and one labelled `Q4` of the same fiscal year at two dates both come back as `Q4`, for every balance item: `_flow_years` (and `_placed`) keep one fact per label first (`_one_per_period`) and relabel `FY` as `Q4` after, so the two labels never meet.

Items 4 (the app's number line, front-end) and 8 (revisit the 10^7 floor the first time the note fires on a figure rounded to exactly 10^7) are not engine work now; see Step 4.

## Plan

- **Step 0.** This design doc. No build plan change (a backlog item).

- **Step 1. Pin the placed read (item 6).** Tests only, in `tests/analysis/test_current_lease_debt.py`: the fixture company gets CAT's maturities tag (25; priority 2 in today's map, `concept_map.csv` line 24, priority 3 in #341's older map; written straight into `financial_facts`, since the map's `companies` scope acts at ingest only) beside every plain current figure (20), and the plain figure dropped at 2019-12-31, so that date has only the second-ranked tag. For `latest` and `first_reported`, `annual` and `quarterly`, and a plain or lease-inclusive non-current tag (no lease-inclusive current figure, so the merge has nothing to choose): `get_facts(["debt_current"])` (the merged, placed read) equals `_get_facts(["debt_current"])` (the single-item read) in date, labels, value and tag; the plain tag wherever both are filed, the maturities tag at 2019-12-31. Exit: 8 new cases pass; full suite, `ruff check .`, `ruff format --check .` clean.

- **Step 2. FY and Q4 at two dates are one quarter (item 7).** `facts._as_q4` relabels a balance's `FY` as `Q4` *before* `_one_per_period` in `_flow_years` and in `_placed`'s quarterly branch, so two dates under `FY` and `Q4` of one fiscal year meet under one label and the later date wins, the rule `_one_per_period` already applies to two dates under one label. The annual read is unchanged (it keeps `FY` only). Tests: either order of the two labels gives one `Q4`, the later date, through `_quarterly` and `_placed`; the annual read keeps the `FY` one; a `FY` and a `Q3` balance are untouched. Both fail on `main`. On real data the collision cannot happen today: ingest stores every year-end balance as `FY`, never `Q4` (`ingest.py` around line 383; the database has no instant labelled `Q4`, analyst), so the fix guards the read against a future ingest or map change, and the survey must report 0. Why one year can have both labels at two dates: each filing labels the dates it shows from its own cover (`fiscal_year`, `fiscal_period`), so a 52–53-week filer whose 10-K tags the year end on its Saturday while a later 10-Q's comparative tags a calendar-month end, or a filer that moved its year end, can leave one fiscal year's year end under `FY` at one date and `Q4` at another. A survey (Step 3) says whether any read changes; the reading-rules log gets a row (a new version only if a read changes). Exit: as Step 1, plus the survey.

- **Step 3. Item 3: a note figure is never a rounded twin, and the surveys.**
  - Survey of CAT's filed tags (restored snapshot `warren-20261117T154255Z`, read-only): CAT files `LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths` at 16 year ends (2010-12-31 to 2025-12-31), `LongTermDebtNoncurrent` at 18 dates, and none of `LongTermDebtCurrent`, `LongTermDebtAndCapitalLeaseObligationsCurrent`, `LongTermDebtAndCapitalLeaseObligations` or `DebtCurrent`; its raw company facts have no current debt or finance-lease liability tag besides lease *payment schedules*. So the merge never sees a lease-inclusive figure for CAT, and its non-current debt is plain (the margin only applies beside a lease-inclusive non-current, `lease_inclusive(noncurrent)`). The risk needs two changes in CAT's tagging.
  - Guard anyway, since the cost is one line: `facts.NOTE_TAGS` (the maturities tag) and `current_on_noncurrent_basis` never applies the rounding margin when the plain figure's tag is in it. A note's principal and a balance-sheet carrying amount are different measures (unamortised discounts and issue costs, ASC 835-30), so a precise lease-inclusive figure below a rounded-looking principal is not the same line rounded. A lease-inclusive figure *above* it is still taken, as for any plain figure: that comparison mixes the two measures too (professor), but there the lease-inclusive figure is the balance-sheet line itself, which is what a balance sheet's current debt should be, and it can hold finance leases the principal lacks; preferring it over a note figure is the better reading either way, so the guard blocks only the margin, which assumes the two figures are one line rounded twice. Sources: ASC 470-10-50-1 (the maturities disclosure, the tag's reference) and ASC 835-30 (debt shown net of discount and issue costs). Test: with the plain figure under the maturities tag, 6,195M below 6,200M is not taken and carries no `rounded_plain`; 6,250M above is taken; the same figures under the balance-sheet tag still take 6,195M and carry `rounded_plain` 6,200M (the field the note is built from); 6,200M equal to the principal keeps the principal, as for any plain figure.
  - Item 7 survey (script below, run against `data/warren.db`): every instant item, every company, every date a stored run uses, in `latest`, `first_reported` and `latest` one-basis quarterly mode: the read with Step 2 against the read with the relabel after `_one_per_period` (`main`). Count reads that differ and list them.
  - `python -m domains.analysis reproduce --all`: every stored run reproduces to the cent.

- **Step 4. Item 2 declined; items 4 and 8 moved; #451 closed.** Item 2 is declined (see Alternatives). Item 4 joins the front-end's app ideas on #344 (a comment linking #451). Item 8 is a watch item with no work until the note fires; it moves to #463. Then #451 is closed.

## Alternatives considered

- **Item 2: settle the label tie from `companies.fiscal_year_end`.** Declined, for two reasons. (1) It is not point-in-time: `edgar_client.py` line 72 stores `fiscalYearEnd` from today's SEC submissions file, the company's fiscal year end *now*, while a read is as of a past date (CLAUDE.md: every query is point-in-time). A company that changed its year end would have its old dates settled by its new calendar. (2) It is one day, but 52–53-week filers end their year on a weekday, not a date: Apple's fiscal years end on the last Saturday of September (2019-09-28, 2020-09-26, 2021-09-25, 2022-09-24, 2023-09-30), JNJ's on the Sunday nearest 31 December (stored year ends 2021-01-03, 2022-01-02, 2023-01-01, 2023-12-31, 2024-12-29, 2025-12-28). In the database, AAPL's `0925` matches only 2021-09-25 of its eight stored year ends and JNJ's `0103` only 2021-01-03 (analyst), so an `MMDD` match would call most year ends quarters. The analyst noted (#451 body, item 2) that the outcome equals `main` in the one case it would differ (a September date labelled FY by a 10-Q's comparative before the 10-K is public), so the present rule is kept.
- **Item 7: keep the earlier date, or the FY-labelled one.** The FY label comes from a 10-K and might seem the stronger claim. Rejected: `_one_per_period` already settles two dates under one label by the later date (an amended cover, two balance dates in one period), and the quarterly read treats a year end as Q4; one rule for both keeps the read explainable.
- **Item 7: drop both and refuse the quarter.** Rejected: it would remove a balance a run needs to keep a rare labelling mismatch visible; the reading-rules log records the rule instead.

## Files to change

- `domains/fundamentals/facts.py` (Step 2: `_as_q4`, `_flow_years`, `_placed`; Step 3: `NOTE_TAGS`, `current_on_noncurrent_basis`).
- `domains/analysis/reading_rules.md` (Step 2: a row for the new fingerprint).
- `tests/analysis/test_current_lease_debt.py` (Steps 1, 2 and 3).
- After the merge: `docs/versions.md` (v0.10.8), `docs/team-sync.md` (log entry), the issue comments (#344 for item 4, a new issue for item 8). No build plan row changes (a backlog item).
- `docs/designs/backlog-451-labels-and-q4.md` (this doc, with the results).

## Product impact

- **Brief questions served, changed or broken.** Step 1 adds tests only. Step 2 can change which balance date a quarterly read takes only where one fiscal year's year end sits under `FY` at one date and `Q4` at another; the survey (Step 3) found **0** of 2,697 quarterly reads change (every instant item, every company, every date a stored run uses, three modes), so no run, series or reported figure moves and `READING_RULES_VERSION` stays 11 (a row under the same version in `reading_rules.md`). Had a read changed, the version would go to 12 and a fresh run beside a stored v11 run would get the brief's "Two runs of the same date" first case; the questions in reach were Q3, Q5 and Q8 and Q1–Q2's reported quarterly balances (`net_debt`). Step 3's `NOTE_TAGS` narrows when `debt_current_within_rounding` can fire (Q3, Q4, Q5, Q8 and Q1/Q2 `net_debt`, brief line 173): never on a plain figure from the debt note (CAT's). No filing fires the note today (CAT files no lease-inclusive current tag), so nothing a student sees changes.
- **Outputs added, renamed or removed:** none. No code, param, note, lesson or field.
- **Front-end:** item 4 (the number line for `debt_current_within_rounding`, drawn from the params the engine already sends: `gap`, `rounding_unit`, `rounding_margin`; brief line 176's "parece redondeada a {rounding_unit}") moves to #344 with the other app ideas for warnings. It appears only when the note fires, and after Step 3 never for a debt-note figure.

## Results (Step 3, nov.18.2026)

On the restored snapshot `warren-20261117T154255Z` (schema 23; no ingest), read-only:

- Item 7: **0 of 2,697** quarterly reads differ (8 companies × each distinct date of the 903 stored runs × `latest`, `first_reported` and `latest` one-basis; every instant item of the map). No balance date moves; reading rules stay v11.
- Item 3: CAT files only the maturities tag for its current portion (16 year ends) and a plain non-current tag (18 dates); no lease-inclusive current or non-current tag, and none in its raw company facts. The guard changes no read.
- `python -m domains.analysis reproduce --all`: **903 of 903** stored runs reproduced to the cent.
- The new tests: item 7's two cases fail on `main` (`_flow_years` returns two Q4 balances), and so does item 3's 6,195M case (gatekeeper); all pass here.
- The whole database holds 0 balance-sheet rows labelled Q4 (6,161 labelled FY; gatekeeper), so no read on any date can change, not only on stored-run dates.
- Gatekeeper (PR #464): GO, no blockers. Its idea to tie `NOTE_TAGS` to the concept map with a test is #465.

The item 7 survey, as run (`python survey.py data/warren.db` from the repo root):

```python
"""#451 item 7 survey: quarterly reads before and after relabelling FY balances as Q4 first."""

import sqlite3, sys
from collections import Counter

sys.path.insert(0, "/home/user/warren")
from domains.fundamentals import facts as F

db = sys.argv[1]
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cos = conn.execute("SELECT cik, ticker FROM companies").fetchall()
names = [
    r[0]
    for r in conn.execute(
        "SELECT DISTINCT canonical_name FROM concepts WHERE period_type='instant'"
    )
]
dates = {r[0]: [] for r in cos}
for r in conn.execute("SELECT DISTINCT cik, as_of FROM runs"):
    dates[r[0]].append(r[1])
new_as_q4 = F._as_q4


def key(fs):
    return sorted(
        (f.canonical_name, f.fiscal_year, f.fiscal_period, str(f.period_end), f.value) for f in fs
    )


def old_read(*a, **k):
    F._as_q4 = lambda fs: fs
    try:
        out = F.get_facts(*a, **k)
    finally:
        F._as_q4 = new_as_q4
    return [
        f.model_copy(update={"fiscal_period": "Q4"})
        if f.period_start is None and f.fiscal_period == "FY"
        else f
        for f in out
    ]


reads = diffs = 0
seen = Counter()
for r in cos:
    cik, t = r[0], r[1]
    ds = sorted(set(dates[cik]))
    for as_of in ds:
        for mode, ob in (("latest", False), ("first_reported", False), ("latest", True)):
            new = F.get_facts(conn, cik, names, as_of, mode, "quarterly", ob)
            old = old_read(conn, cik, names, as_of, mode, "quarterly", ob)
            reads += 1
            if key(new) != key(old):
                diffs += 1
                a, b = set(key(new)), set(key(old))
                for x in (b - a) | (a - b):
                    seen[(t, x[0], x[1])] += 1
                if diffs <= 5:
                    print(
                        t,
                        as_of,
                        mode,
                        ob,
                        "new-only",
                        sorted(a - b)[:4],
                        "old-only",
                        sorted(b - a)[:4],
                    )
print("reads", reads, "differing", diffs)
for k, v in sorted(seen.items()):
    print(k, v)
```

## Review notes

Design review nov.18.2026 (explainer, analyst, professor; product lead on *Product impact*).

- **Analyst: GO, no blockers.** Accepted: the JNJ example was wrong (no 2025-01-03 date; corrected with the stored year ends, which strengthen the decline); stated that ingest never stores an instant as `Q4`, so item 7 cannot change a real read today (the survey's 0 confirms it). Filed as #462: XOM's `OperatingLeaseLiability` at 2019-01-01 (the ASC 842 adoption-day balance from its 2019 10-Qs) sits under FY2018, so FY2018's annual read shows a lease liability that was not on its 2018 balance sheet (older behaviour, not this design).
- **Professor: approve, no blockers.** Accepted: one sentence on why one year can have both labels (Step 2); why a lease-inclusive figure *above* a note principal is still taken, and ASC 470-10-50-1 beside ASC 835-30 (Step 3). The principal-beside-carrying-amount idea for the app goes to #344 with item 4.
- **Product lead: two blockers on wording, both fixed.** *Product impact* now names the version outcome (v11 kept, since no read changes; what v12 would have meant) and the questions in reach, and the questions where `NOTE_TAGS` narrows the note (Q3, Q4, Q5, Q8, Q1/Q2 `net_debt`). The Spanish is the brief's (line 176), not a new phrase. A team-sync line will say no balance date moved.
- **Explainer: three blockers, all gaps in the doc, fixed.** The survey is now in the doc as run, with its command and dates; the version (v0.10.8, reading rules v11 with a row under it) and the post-merge files are named; item 2 is "declined with a reason" in the summary and the analyst's case is cited. Ideas taken: where the fixture's maturities tag comes from and its priority (2 today; 3 in #341's older map, which is why `CHANGES.md` says 3); what the 6,195M test checks (`rounded_plain`, the field the note is built from); the equal case. Item 8 is #463; the XOM lease issue is #462.

