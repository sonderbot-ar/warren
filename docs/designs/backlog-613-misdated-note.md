# Backlog #613 item 4: say on the chart when a misdated figure was left out

Issue: https://github.com/sonderbot-ar/warren/issues/613 (item 4, the front-end team's ask in its comment of nov.27.2026; items 1 to 3 stay open in the issue) · Branch `backlog-613-misdated-note` · Version v0.10.55 when merged.

Status: In progress (nov.27.2026).

## Problem

Since v0.10.54 (#610) the cost of debt leaves out a filed figure that `domains/analysis/misdated_facts.csv` lists: a fact a filing put under the wrong fiscal year (Coca-Cola's FY2016 −320M in 0000021344-17-000009 and FY2019 +27M in 0000021344-21-000008, both the year before's gain or loss on paying debt off early). Only the English method text of the year's interest says so. A student who opens the 10-K sees the tagged figure under that year, finds no part for it on the cost-of-debt chart, and has no sentence in Spanish to tell them why. The front-end team asked for a coded point note so *Fuente* can say it (issue comment, serves brief Q5 and the `cost_of_debt` cell on Q3, Q4 and Q8).

## Plan

**Step 0. This doc.**

**Step 1. The note.**

- `misdated_facts.csv` gains a column `stated_fiscal_year`, between `accession_no` and `evidence`: the year the filing's own text gives the figure (2015 and 2018 today). `load_misdated_facts` refuses, with every problem listed at once as for the other columns (`MisdatedFactsError`), a value that is not a whole number, equals `fiscal_year`, or is not quoted in the row's evidence (analyst). `misdated_facts.misdated_fact(item, fiscal_year, accession_no)` (same arguments as `is_misdated`) returns the row or None; both read one cached table, so they cannot disagree.
- New point note `misdated_fact_left_out` in `single_values.POINT_NOTES`, on a cost-of-debt point whose year's figure was left out because it is listed. Built in `_cost_of_debt_point` (`_misdated_notes`) from the engine's own answer: for each item in `misdated_facts.CHECKED_ITEMS`, the year's fact in the run's point-in-time `History` (filings known on the run's date) gets the note only when it is listed, is not one of the year's interest facts, and the interest's method traces it, which `math_engine._without_extinguishment` does only when it leaves the figure out. The cash fallback and the cash-paid-on-debt path never read the figure, so they never get the note (analyst). Params: `fiscal_year`, `item` (`debt_extinguishment_in_interest`), `value` (US$, as filed, with its sign: a loss negative, as a part's value), `filing` (the #140 shape, `_filing_of`), `stated_fiscal_year`, `stated_year_value` (that year's own figure as known on the run's date, or None: it shows the figure is counted there; professor and analyst), `evidence` (the row's quoted filing words, English; product lead). English text: "FY2016's gain or loss on paying debt off early (-320,000,000 as filed in 0000021344-17-000009) is left out: the filing's own text puts it in FY2015 (misdated_facts.csv)". First among the point's notes, since it explains a missing part (product lead), on either branch of `_cost_of_debt_point` (with or without an interest caveat). Never a cell note: the cell shows the run's own year, whose point already carries it.
- No value changes: the note reads what the engine already did. The CSV's bytes and `misdated_facts.py` are in the reading-rules fingerprint, so `reading_rules.md` gets a new fingerprint row that stays at version 16 (the current one), saying no run reads a different figure.
- Tests (`tests/analysis/test_misdated_note.py`, `tests/analysis/test_extinguishment_interest.py`): the shipped file loads with its stated years; the loader refuses a missing, non-numeric, equal or unquoted stated year; Test Corp with the extinguishment item read for TST (the map row's `companies` widened) and one year listed gets the note on that year only, first, with its params; an unlisted year keeps the figure as a part and gets no note; a listed fact filed after the run's date gives no note and no part (professor); an interest that never read the figure gives no note (analyst); the listed year's value equals the same company's with no item; the code is in `POINT_NOTES` and not in `CELL_NOTES`.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot: every Coca-Cola run's cost-of-debt chart (ten years) carries the note on FY2016 and FY2019 only, FY2019's only on runs dated after the FY2020 10-K was filed; FY2015 and FY2018 keep their parts; `reproduce --all` to the cent. Exit: as stated, no run row changes.

## Results (Step 2, nov.27.2026)

On the restored snapshot `warren-20261127T002823Z`, every one of Coca-Cola's 115 stored runs, its cost-of-debt chart at ten years:

- **FY2016** (−320M as filed in 0000021344-17-000009, stated year 2015) carries the note on 103 runs, 2019-04-01 to 2026-04-01; later runs' ten-year charts start at FY2017.
- **FY2019** (+27M as filed in 0000021344-21-000008, stated year 2018, whose own +27M is counted on FY2018's point) carries it on 87 runs, from 2021-03-01, the first run date after the FY2020 10-K was filed (February 2021). No run dated earlier gets it.
- No other year carries the note on any run. On the newest run (2026-10-30) FY2018 still shows its +27M part, FY2017 its −38M, FY2020 −459M, FY2021 −559M and FY2024 +22M; FY2019's note is the first on its point.
- `reproduce --all`: 936 of 936 stored runs reproduced to the cent. No data was added, so no new snapshot.

## Design review (nov.27.2026)

- **Explainer.** Fifteen gaps, all wording; taken: the loader's refusal and function, the arguments of `misdated_fact`, the history (point in time), the checked items, the branch, the note's place, the value's sign and unit, the version (a row under the current 16), "read for TST", the closed list, the brief's owner. The column is not already on `main` (it was in the working copy the explainer read).
- **Analyst, GO, no blockers.** Confirmed on EDGAR's XBRL API that 0000021344-17-000009 is the only filing tagging −320M under 2016 and 0000021344-21-000008 the only one tagging +27M under 2019; the 2015 and 2018 figures are tagged in other filings and counted. Taken: the note follows the engine's own path (the trace check), with a test for an interest that never read the figure; the loader checks the stated year is quoted in the evidence; Step 2 checks FY2015's and FY2018's parts (FY2018's shown; FY2015 is outside every ten-year chart from 2026 and its −320M part was checked in #610).
- **Professor, GO, no blockers.** Filed XBRL has known context errors (Debreceny et al. 2010; Du, Vasarhelyi and Zheng 2013); ASC 470-50-40-2 puts the gain or loss in the year of the extinguishment, so the text wins. Taken: a test and a check that a run dated before the misdating filing gets no note; `stated_year_value`, so the screen can say the figure is counted in its own year. The lesson: tagged data is not the filing; when they disagree, the text decides.
- **Product lead, GO.** Taken: the note goes first on its point, and `evidence` carries the filing's words so *Fuente* never shows the file name. Spanish proposed for the brief: title "Cifra registrada en el año equivocado"; sentence "El informe anual (10-K) de {empresa} presentado el {fecha} registra en el año fiscal {fiscal_year} una pérdida o ganancia por liquidar deuda anticipadamente de {value}, pero su propio texto dice que corresponde al año fiscal {stated_fiscal_year}. Por eso Warren no la incluye en los intereses de {fiscal_year}."; lesson on why a figure tagged with the wrong year would distort the year's cost of debt, and that Warren keeps a hand-checked list with the filing's own words.

## Alternatives considered

- **Derive the stated year as `fiscal_year − 1`.** True of both rows, but by coincidence of these two errors; the year is the filing's words, so it belongs in the data file beside them.
- **Put the note in the engine's run notes.** A run note would be stored with the run and need a migration of what is stored; the chart's point is where the student meets the missing part, and the point is rebuilt from the same rule on every read.
- **Show the left-out figure as a part with a flag.** The parts add up to the point's interest; a part that is not counted breaks that rule the app relies on.

## Files to change

`domains/analysis/misdated_facts.csv`, `domains/analysis/misdated_facts.py`, `domains/analysis/single_values.py`, `domains/analysis/reading_rules.md`, new `tests/analysis/test_misdated_note.py`, `tests/analysis/test_extinguishment_interest.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` unchanged (a note on a read-only view; no decision changes).

## Product impact

Serves Q5 (the inputs behind an answer) and the `cost_of_debt` cell's chart on Q3, Q4 and Q8 (`docs/product/brief.md`). Adds one point note code, `misdated_fact_left_out`, on the cost-of-debt chart only, with params `fiscal_year`, `item`, `value`, `filing` (#140 shape: accession, form, filed date, link, filer), `stated_fiscal_year`. Today it shows on Coca-Cola's FY2016 and FY2019 points, on every run whose chart reaches those years and whose date is after the misdating filing. Needs its Spanish in the brief (title, sentence, lesson); the product lead proposed it in the review below, and the front-end team adds it to `docs/product/brief.md` after the merge, as for v0.10.53 and v0.10.54. No value, field or code is renamed or removed; no stored run changes.
