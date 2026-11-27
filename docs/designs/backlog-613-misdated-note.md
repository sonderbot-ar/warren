# Backlog #613 item 4: say on the chart when a misdated figure was left out

Issue: https://github.com/sonderbot-ar/warren/issues/613 (item 4, the front-end team's ask in its comment of nov.27.2026; items 1 to 3 stay open in the issue) · Branch `backlog-613-misdated-note` · Version v0.10.55 when merged.

Status: In progress (nov.27.2026).

## Problem

Since v0.10.54 (#610) the cost of debt leaves out a filed figure that `domains/analysis/misdated_facts.csv` lists: a fact a filing put under the wrong fiscal year (Coca-Cola's FY2016 −320M in 0000021344-17-000009 and FY2019 +27M in 0000021344-21-000008, both the year before's gain or loss on paying debt off early). Only the English method text of the year's interest says so. A student who opens the 10-K sees the tagged figure under that year, finds no part for it on the cost-of-debt chart, and has no sentence in Spanish to tell them why. The front-end team asked for a coded point note so *Fuente* can say it (issue comment, serves brief Q5 and the `cost_of_debt` cell on Q3, Q4 and Q8).

## Plan

**Step 0. This doc.**

**Step 1. The note.**

- `misdated_facts.csv` gains a column `stated_fiscal_year`: the year the filing's own text gives the figure (2015 and 2018 today, each quoted in the row's evidence). The loader checks it is a whole number other than `fiscal_year`. `misdated_facts.misdated_fact(item, fiscal_year, accession)` returns the row (or None); `is_misdated` is unchanged in what it answers.
- New point note `misdated_fact_left_out` in `single_values.POINT_NOTES`, on a cost-of-debt point whose year's figure was left out because it is listed. Built in `_cost_of_debt_point` by asking the same question the engine asks (`is_misdated` on the year's fact of each checked item, read through the same history), so the chart and the run cannot disagree. Params: `fiscal_year`, `item` (`debt_extinguishment_in_interest`), `value` (the figure as filed, with its sign, the same as a part's value), `filing` (the #140 shape, `_filing_of`), `stated_fiscal_year`. English text: "FY2016's gain or loss on paying debt off early (-320,000,000 as filed in 0000021344-17-000009) is left out: the filing's own text puts it in FY2015 (misdated_facts.csv)". Added beside the other notes on the point, under the hedge-caveat branch too (a caveat company could have a misdated fact). Never a cell note: the cell shows the run's own year, whose point already carries it.
- No value changes: the note reads what the engine already did. The CSV's bytes are in the reading-rules fingerprint, so `reading_rules.md` gets a row under version 16 saying no run reads a different figure.
- Tests (`tests/analysis/test_misdated_note.py`, `tests/analysis/test_extinguishment_interest.py`): the shipped file loads with its stated years; the loader refuses a missing, non-numeric or equal stated year; Test Corp with a scoped extinguishment item and one year listed gets the note on that year only, with its params; an unlisted year gets none and its part instead; the run's rows and numbers do not change with the note; the code is in the closed list and every point code seen is.
- Exit: `python -m pytest -q`, `ruff check .`, `ruff format --check .` green.

**Step 2. Real data.** On the restored snapshot: Coca-Cola's newest run's chart carries the note on FY2016 and FY2019 and on no other year, with the values above; `reproduce --all` to the cent. Exit: as stated, no run row changes.

## Alternatives considered

- **Derive the stated year as `fiscal_year − 1`.** True of both rows, but by coincidence of these two errors; the year is the filing's words, so it belongs in the data file beside them.
- **Put the note in the engine's run notes.** A run note would be stored with the run and need a migration of what is stored; the chart's point is where the student meets the missing part, and the point is rebuilt from the same rule on every read.
- **Show the left-out figure as a part with a flag.** The parts add up to the point's interest; a part that is not counted breaks that rule the app relies on.

## Files to change

`domains/analysis/misdated_facts.csv`, `domains/analysis/misdated_facts.py`, `domains/analysis/single_values.py`, `domains/analysis/reading_rules.md`, new `tests/analysis/test_misdated_note.py`, `tests/analysis/test_extinguishment_interest.py`, this doc; on merge `docs/versions.md`, `docs/team-sync.md`. `docs/structure-guide.md` and `docs/build-plan.md` unchanged (a note on a read-only view; no decision changes).

## Product impact

Serves Q5 (the inputs behind an answer) and the `cost_of_debt` cell's chart on Q3, Q4 and Q8 (`docs/product/brief.md`). Adds one point note code, `misdated_fact_left_out`, on the cost-of-debt chart only, with params `fiscal_year`, `item`, `value`, `filing` (#140 shape: accession, form, filed date, link, filer), `stated_fiscal_year`. Today it shows on Coca-Cola's FY2016 and FY2019 points, on every run whose chart reaches those years. Needs its Spanish in the brief (title, sentence, lesson). No value, field or code is renamed or removed; no stored run changes.
