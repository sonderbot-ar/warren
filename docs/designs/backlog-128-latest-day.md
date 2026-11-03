# Backlog #128: runs default to the latest ended day; a past date shows what happened next

Issue: https://github.com/sonderbot-ar/warren/issues/128 · Branch `backlog-128-latest-day` · Version v0.9.7 when merged.

## Problem

Asked by the owner on nov.02.2026; the front-end team names it as the second thing F2's first screen needs (brief questions 3 and 5, `docs/product/brief.md` §2 "Point in time").

1. Every command that values or reads a company needs `--as-of` (`domains/orchestration/__main__.py:198`, `domains/analysis/__main__.py:253` and `:288`). A user who wants "now" has to type a date, and if they type today's date the run is refused, because the day has not ended in New York (`nodes.check_closed`, backlog #112).
2. A forecast as of a past date forecasts quarters that are already reported, but the pipeline report never shows those actuals. A reader sees a forecast without the one thing that makes a past date worth asking about: how far off it was.

Item 2 of the issue (a completed period returns its reported figures) moved to #140 and shipped in v0.9.6. This item keeps items 1 and 3.

## What changes

- **The default date.** "Today" means the last day that has ended in New York: `shared_kernel.calendar.last_ended_day(now)`, the newest date whose `known_by` is at or before `now`. At 23:59 New York time on nov.03 that is nov.02; at 00:00 on nov.04 it is nov.03. The three user-facing commands use it when `--as-of` is left out, and print the date they used: `python main.py run`, `python -m domains.analysis dcf` (a run as of the latest day; `--as-of` still repeats) and `python -m domains.analysis reported`. `--as-of` given on purpose keeps today's behaviour exactly: that is the "past-date forecast as an explicit option" of the issue. Batch commands (`backtest`, `ranges`, `--all` grids) are unchanged: they always name their dates.
- **Forecast against what was reported.** A new call, `domains.evaluation.hindsight.against_actuals(conn, run_id, actuals_on)`, returns for each of a run's forecast quarters (Q1–Q8 of the stored run) its revenue and EBIT forecast and, when the quarter had been reported by `actuals_on`, the value as first reported (M3's rule, `harness.first_reported`, EBIT on the run's own definition), the filings it came from (accession, form, filing date, EDGAR link, the shape #140 uses), and the miss, scored as M3 scores it (`harness.score`: revenue in % of the actual, EBIT in margin points). A quarter not reported by then says so; a quarter reported only under another EBIT definition says that, instead of failing. Every gap is a code (`not_reported`, `other_ebit_definition`) with English text as fallback, as in #140.
- **In the pipeline report.** The report gets a section "6. Forecast against what was reported" (the trace becomes section 7) whenever a pipeline's `actuals_on` is set. `actuals_on` is a new, optional field of the pipeline state, set by `write_report` to the last ended day at the time of writing. It is stored, so the report renders to the same text every time and `reproduce` keeps comparing it; a later re-render shows actuals known by the same stored day, not by the day it was re-rendered. When no forecast quarter was reported by `actuals_on` (every run as of the latest day), the section has one line saying so. Pipelines written before this version have no `actuals_on`: their reports render as before, without the section, so they still reproduce.

**Point in time.** Nothing that feeds the forecast changes: the run, the news, the shocks and the simulation read only what was public by `as_of`, and the report's sections 1–5 are untouched. Section 6 is hindsight by design, labelled as such, read only for the report, and never written back into a run. It reads filings public by `actuals_on`, so it is point-in-time on its own date. This is the same split the evaluation harness has made since M3.

## Steps

- **Step 0.** This design doc; the build plan is unchanged (a backlog item).
- **Step 1.** `last_ended_day` in `shared_kernel/calendar.py`. Tests (`tests/shared_kernel/test_calendar.py`): one second before New York midnight gives the day before; New York midnight gives the day that just ended; the same at both clock changes (2026-03-08 and 2026-11-01, where New York midnight is 05:00 or 04:00 UTC); `known_by(last_ended_day(now)) <= now` and `known_by(last_ended_day(now) + 1 day) > now` for a sweep of instants across a year. Exit: green.
- **Step 2.** Defaults in the three commands. `main.py run` takes the day from `deps.now()`; the analysis commands from the clock. Each prints "as of <date> (the latest day that has ended in New York)" when it chose the date. Tests (`tests/orchestration/test_cli.py`, `tests/analysis/test_cli*.py`): with the world's clock at a known instant, `run` without `--as-of` starts a pipeline on the expected day and says so; with `--as-of` it is unchanged; `dcf` and `reported` without `--as-of` use the same day (clock monkeypatched). Exit: green; every existing CLI test unchanged.
- **Step 3.** `domains/evaluation/hindsight.py`: `against_actuals`, its dataclasses and `to_dict`. Tests (`tests/evaluation/test_hindsight.py`, Test Corp, whose numbers are known by construction): a run as of 2019-06-30 against actuals on 2020-06-30 has Q3 2019–Q1 2020 reported (Q4 derived from the 10-K, flagged with its filings) and the rest `not_reported`; each miss equals `harness.score` on the same numbers and equals the M3 harness's row for the same case; actuals on a day before a 10-Q's filing date leave that quarter unreported; an edited fixture whose EBIT is filed only as pretax + interest gives `other_ebit_definition` for that quarter and does not raise; `to_dict` round-trips through `json`. Exit: green.
- **Step 4.** The report section and `actuals_on`. `PipelineState.actuals_on: date | None = None`; `write_report` sets it; `report.render` adds section 6 when it is set; the trace's number follows. Tests (`tests/orchestration/test_graph.py`): a new pipeline's report has section 6 with the one-line "no forecast quarter reported by <day>" (Test Corp's data stops at the Q1 2020 10-Q); the report still renders the same twice and `reproduce` passes; a state without `actuals_on` renders without section 6 (an old pipeline); a rendered section on a state with a later `actuals_on` (unit test with a 2019 run) shows reported quarters and misses. Exit: green; ruff clean.
- **Step 5.** Real data, on the restored snapshot: `main.py run --ticker MSFT --offline` without `--as-of` is refused or runs on the latest ended day (offline needs stored prices for that day, so a refusal that names the missing data is the expected answer in a cloud run); `against_actuals` on the stored M7 pipelines (MSFT 2022-06-02, WMT) gives misses equal to the M8 batch's baseline rows for the same case and quarter. Written below.

**Exit criterion:** all tests pass with the existing suite; `reproduce` passes on the stored pipelines (no section 6, since they predate `actuals_on`); Step 5's misses equal the backtest's; `docs/team-sync.md` names the default and the new call.

## Alternatives considered

- *Default to the calendar's today.* Rejected: the engine refuses a day still in progress (#112), so the default would fail every time before midnight New York.
- *Render section 6 with the actuals known when the report is rendered.* Rejected: the report would change as new 10-Qs land and `reproduce` would report a mismatch on a correct pipeline. Storing `actuals_on` keeps the report reproducible; a fresh look is a new pipeline or, later, a `report --actuals-on` option (follow-up if the front-end asks).
- *Put the comparison in the `dcf` report too.* Deferred: the `dcf` report has no stored state to hold `actuals_on`, so it would change over time. The app gets the same numbers from `against_actuals` on any run.
- *A separate `backtest` mode flag instead of an explicit `--as-of`.* Rejected: the issue gives `--as-of` on purpose as the example, and a second flag that means "I typed a date" adds nothing.

## Files to change

`shared_kernel/calendar.py`, `domains/orchestration/{__main__,state,graph,report,text}.py`, `domains/analysis/__main__.py`, new `domains/evaluation/hindsight.py`, tests under `tests/shared_kernel`, `tests/orchestration`, `tests/analysis`, `tests/evaluation`; at merge `docs/versions.md`, `docs/team-sync.md`, `docs/product/brief.md` (Q3's "Hoy" line).

## Product impact

Serves brief §2 "Point in time" (the default is the latest ended day; a past date shows what happened afterwards) and question 3 (MSFT's value today): Q3's note "the default to the latest date is #128 item 1" is removed. Q5's forecast now has its misses on past dates. F2's first screen can call any of the three commands, or the library, without asking the student for a date.

Adds: `shared_kernel.calendar.last_ended_day(now)`; `domains.evaluation.hindsight.against_actuals(conn, run_id, actuals_on)` and its `to_dict`; the pipeline state field `actuals_on`; report section 6. Fields of `to_dict`: top `run_id`, `ticker`, `as_of`, `actuals_on`, `currency`, `quarters[]`; a quarter `period` (the run's label, e.g. `FY2019Q3`), `horizon` (1–8), `period_end` (when reported), `items[]`; an item `name` (`revenue` or `ebit`), `forecast`, `actual` (None when missing), `miss` (revenue: fraction of the actual; EBIT: fraction of actual revenue, i.e. margin points ÷ 100), `signed_miss` (forecast − actual on the same scale; positive means the forecast was too high), `filings[]` (each {`accession_no`, `form`, `filed_at`, `url`}, the #140 shape: every filing the actual came from, a derived quarter's inputs included; empty when missing), `derived`, `missing` (coded or None). Renamed or removed: the pipeline report's trace moves from section 6 to 7 on new reports only.

## Design review

To come.

## Where the work stopped

- nov.03.2026: design doc written; review and Step 1 next.
