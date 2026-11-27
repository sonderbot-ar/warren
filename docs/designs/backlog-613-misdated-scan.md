# Backlog #613 item 1: catch the next misdated figure automatically

Issue: https://github.com/sonderbot-ar/warren/issues/613 (item 1, from the #610 analyst and professor) · Branch `backlog-613-misdated-scan` · Version v0.10.57 when merged.

Status: Done (nov.27.2026), merged as v0.10.57 in `86f6dc7` (PR #622).

## Problem

`domains/analysis/misdated_facts.csv` lists two Coca-Cola figures that a 10-K put under the wrong fiscal year (backlog #610): the FY2016 10-K (0000021344-17-000009) tags −320M of early-payoff charges under 2016 that its own text puts in 2015, and the FY2020 10-K (0000021344-21-000008) tags +27M under 2019 that its text puts in 2018. Both were found by hand, while reading Coca-Cola's notes. Nothing would catch a third.

SEC staff name this error in their data quality reminder of 2022-01-14 ("using an incorrect year when tagging comparative prior period information", https://www.sec.gov/structureddata/announcement/011422-incorrect-context-dates). No XBRL US Data Quality Committee rule we found tests for it, so this is Warren's own check. Both have the same shape, which the issue names: a 10-K's annual figure for year Y is exactly the figure already filed for year Y−1 under the same tag. A check for that shape, run on the facts as known on a date, would propose a candidate row for a person to read against the filing's text. It must never add a row on its own: only the filing's words can say the year is wrong, and the list's rows each quote them.

## What the data shows (snapshot `warren-20261127T002823Z`)

Over every annual, US-dollar, duration fact of the eight companies (all mapped items, required and optional), a figure for Y in filing F that equals a figure for Y−1 filed earlier under the same tag gives 27 hits. Twenty-five are ordinary: rounded figures that really were the same two years running (J&J's amortization of 1,200M, Microsoft's interest paid of 2,400M, both rounded to the hundred million) and a filing repeating what it filed before. Two conditions separate them from the two known errors, which hold for both errors and for none of the 25:

1. **F does not give Y−1 the same figure.** A filing that shows 1,200 for both years states both years; one that moves a figure to the wrong year leaves the year it belongs to without it, or with another figure. (17 of the 25 fail here.)
2. **No filing on another year gives Y the same figure.** A 10-K shows three years of income statement (Regulation S-X 3-02), so a true figure is usually given again by the next 10-Ks; a figure other filings repeat for the same year is corroborated, and each known error appears in its filing only (the FY2017 10-K presents 2016 with no charge; the FY2019 10-K tags no 2019 figure). A filing's year is the newest fiscal year it gives any annual figure for; an amendment of the same year's report is a copy, not a second source, so it does not corroborate (P&G's 10-K/A 0000080424-20-000059 re-files all 39 annual flow figures of the 10-K filed the day before; Exxon's 0001193125-11-050134 all 30). (The analyst's recount: 16 fail condition 1, all of which fail 2 as well, and 9 fail only 2.)

Scanned on the first of every month from 2009-01 to 2026-12, with only the facts filed by that day, the rule finds exactly the two listed rows and nothing else: FY2016 from 2017-03-01 (the 10-K was filed 2017-02-24) and FY2019 from 2021-03-01 (filed 2021-02-25).

The conditions were fitted on the only two known errors, so finding exactly those two with no false alarm is in sample by construction: a narrow tripwire, not a measured detector. Its known blind spots are written below. With the amendment rule, the monthly result is the same.

## Plan

**Step 0. This doc.**

**Step 1. The scan, in fundamentals.** New module `domains/fundamentals/misdating.py`:

- `MisdatingCandidate` (frozen): `ticker`, `canonical_name`, `xbrl_concept`, `fiscal_year` (Y, the year F's dates give), `value`, `accession_no`, `form`, `filed_at` (F), `prior_accession_no` and `prior_filed_at` (the earliest filing, before F, that gave Y−1 the same figure), and `stated_fiscal_year` (Y−1, the year a person should look for in F's text).
- `misdating_candidates(conn, cik, as_of)`: every annual (`fiscal_period = 'FY'`) fact in `USD` of a mapped duration item, filed on or before `as_of`, with a non-zero value, for which a filing before F (`filed_at` strictly earlier; two filings on the same day are never compared) gave Y−1 the same value under the same tag (exact equality, as stored), F gives no Y−1 figure equal to it under that tag, and no filing on another year (above) public on `as_of` gives Y that value under that tag. Rows with no `fiscal_year` are skipped. Every year filed is scanned, not only the report's FY2016–FY2025, as the sign-flip list does. One candidate per (item, tag, Y, F), sorted by item, year and filing. It reads the facts table directly (every tag of the item, not only the one the selection rule picks), so a figure is caught even where the engine would not use it. Point-in-time: only rows with `filed_at <= as_of` are read, so a candidate can appear on one date and go away on a later one, when another filing repeats the figure.
- The quality report (`python -m domains.fundamentals report`) gains a section "Possible misdated figures": each candidate with its filing, the earlier filing, and the sentence "check the filing's text for the year it gives this figure; if it names Y−1, add a row to `domains/analysis/misdated_facts.csv`". It is the report's last section; the summary line reads "Possible misdated figures: N (informational; see below)". The section's text names the blind spots; the module docstring gives the counts and the sources. Candidates are "informational": candidates do not change the report's exit code, which counts unexplained gaps only.
- Tests (`tests/fundamentals/test_misdating.py`), on a database built by hand with `financial_facts` rows: the Coca-Cola shape is found (Y's figure in F equals Y−1's from an earlier filing); not found when F also gives Y−1 the same figure, when another filing gives Y the same figure, when the earlier figure was filed after F or on the same filing, when the value is zero, when the figures differ by any amount, when the later filing is after `as_of` (and found again on a later date), on a different tag of the same item, or on a quarter; a later filing repeating Y's figure makes a candidate go away; the report section lists a candidate and its count, and says "None." when there is none; the exit code does not change.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Against the list, in analysis.** `domains/analysis/misdated_facts.py` gains `scan(conn, as_of, tickers=None)`, returning, per company, each candidate with the listed row it matches (same item, year and filing) or none, and each listed row the scan does not find (so a list row that no longer has the shape, after a refiling, shows up). New command `python -m domains.analysis misdated-scan [--ticker T] [--as-of D]`: one line per candidate, "listed" or "NOT LISTED", and for a candidate not listed on an item in `CHECKED_ITEMS`, the proposed CSV row with `evidence` left as `<quote the filing's own words that give the year>`; for any other item, "this item is not read against the list". A candidate matches a listed row with the same item, fiscal year and filing. A listed row whose filing is not yet public on the date is neither found nor missing (so on 2020-06-01 the FY2019 row is silent). Exit code 1 when anything needs a person: a candidate not listed (on any item) or a public listed row not found; never writes the file. The proposed row is a template, not a valid row: its placeholder evidence names neither the filing nor a year, so the loader refuses it until a person writes the filing's own words. `--as-of` defaults to the last ended New York day; a ticker not in `universe.csv` is refused with a one-line message and exit 2.
- Tests (`tests/analysis/test_misdated_scan.py`): a listed candidate prints "listed" and exits 0; an unlisted one prints the proposed row and exits 1, and the CSV is unchanged on disk; a candidate on an unchecked item says so; a listed row with no candidate is reported.
- Exit: as Step 1.

**Step 3. Real data.** On the restored snapshot: `misdated-scan --as-of` the latest day lists exactly Coca-Cola FY2016 and FY2019, both "listed", exit 0; on 2020-06-01 only FY2016; every company's quality report has the section, with the two Coca-Cola rows under Coca-Cola and "None." elsewhere. No run's figures change (the scan only reads); `reproduce --all` to the cent.

## Blind spots (said on the report and in the module)

- **A misdated figure that a later filing repeats** is read as corroborated and missed. Staff name this too ("context dates carried over from a prior period's filing").
- **A misdated figure that is not exactly last year's** (a figure moved two years, or moved and revised) is missed.
- **Quarters and balances** are not scanned: both known errors are annual flows.
- **Two years really equal and filed in separate filings only**, with F not restating Y−1, would be flagged: a person reads the text and leaves it out.

## Results (Step 3, nov.27.2026)

On the restored snapshot `warren-20261127T002823Z`:

- `misdated-scan` (as of 2026-11-26) lists Coca-Cola FY2016 (−320M, 0000021344-17-000009) and FY2019 (+27M, 0000021344-21-000008), both "listed", and "none" for the other seven; exit 0. As of 2020-06-01, FY2016 only; as of 2016-06-01, none. Exit 0 each time.
- `misdating_candidates` on the first of every month from 2009-01 to 2026-12, every company: FY2016 from 2017-03-01 (118 months) and FY2019 from 2021-03-01 (70 months), nothing else.
- Each company's quality report has the section: the two Coca-Cola lines under Coca-Cola, "None." for the others; exit codes unchanged.
- `reproduce --all`: 936 of 936 runs reproduce to the cent. No data was added, so no new snapshot.

## Design review (nov.27.2026)

- **Explainer.** Six gaps called blockers, all wording, all answered in the plan: whether a listed row not yet public counts (neither found nor missing); what sets the exit code (anything needing a person, including a candidate on an unchecked item); the template row is not valid by design; same-day filings are never compared; every year is scanned; where the blind spots are said. Ideas taken: matching is on item, year and filing; the `--as-of` default; an unknown ticker is refused; the section's place and summary wording.
- **Analyst, NO-GO on one blocker, fixed.** A 10-K/A that re-files its 10-K counted as a second source and would have hidden an error in that 10-K (P&G 0000080424-20-000059, Exxon 0001193125-11-050134). Now an amendment of the same year's report does not corroborate, with a test. Confirmed on real data: 27 raw hits and exactly two after the conditions, on all 216 month-starts; at ±0.1% the scan would add three ordinary restatement chains (Walmart cost of revenue 2010, P&G and Caterpillar cost of goods sold 2014), so exact equality stays. Taken: the 16/9 recount, a test that rows with no fiscal year are skipped, the note that candidates come and go between dates. To backlog: two-year shifts (0 extra candidates today), and one quarterly hit worth reading (P&G operating income Q3 2014 in 0000080424-14-000057 equals Q3 2013's first figure, maybe the pet-care recast).
- **Professor, GO.** The SEC staff reminder names the error; Debreceny et al. (2010, *JAPP* 29(3)) and Du, Vasarhelyi and Zheng (2013, *JIS* 27(1)) show such tagging errors were common. Taken: cite the reminder and say no DQC rule covers it, explain the three-year statements behind condition 2, call the fit in sample by construction, tie blind spot 1 to staff's "carried over" error, record the near-misses per condition. Ideas: an out-of-sample run on companies outside the eight (a universe change, the owner's call; filed as a backlog idea, not built), and a lesson on the 320M charge.
- **Gatekeeper (PR #622), GO.** 3066 passed, ruff clean, 936 of 936 reproduce, point-in-time checked, reading-rules row right. Ideas taken: the placeholder's wording in this doc, a one-line refusal (exit 2) for an unknown ticker instead of a traceback. To backlog (#623): a filing's year is its newest tagged fiscal year, which a later-year figure tagged as FY would mislead (none in today's data).
- **Product lead.** Not run: Product impact is "none" (no output, field or note changes).

## Alternatives considered

- **Flag any exact repeat of last year's figure.** 27 hits on today's data, 25 of them true repeats of rounded figures; a tripwire that fires that often stops being read.
- **Equality within the rounding of the figure** (`facts.rounding_unit`). Would catch a moved-and-rounded figure, but rounded figures are exactly where true repeats are common (J&J's 1,200M two years running); exact equality is what both known errors show.
- **Apply a candidate automatically** (leave the figure out). Only the filing's text can show the year is wrong, and a row without that quote would put an unreasoned guess into a cost of debt. The issue says "never apply it on its own".
- **Equality within ±0.1% or ±1%.** The analyst's run adds three and ten hits, all ordinary restatement chains, and no third real error.
- **Put the "listed" check in the fundamentals report.** It would make fundamentals read the analysis domain's list; fundamentals imports nothing from analysis today, so the comparison lives in an analysis command.

## Product impact

None. The scan reads facts and prints; no run, note, output or field changes. Serves the trust behind the cost-of-debt chart's `misdated_fact_left_out` note (brief Q5; the `cost_of_debt` cell on Q3, Q4 and Q8): a new misdated figure is more likely to be found and listed, and the note then shows it. Nothing for the front-end team to change.

## Files to change

New `domains/fundamentals/misdating.py`, `domains/fundamentals/quality.py`, `domains/analysis/misdated_facts.py`, `domains/analysis/__main__.py`, new `tests/fundamentals/test_misdating.py`, new `tests/analysis/test_misdated_scan.py`, `domains/analysis/reading_rules.md` (a row under version 16: read only, no run reads a different figure), this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` unchanged (no decision changes; backlog item).
