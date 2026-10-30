"""Command line for news ingestion and events (M5).

    python -m domains.news ingest --case MSFT_2022-06-02 [--days 7] | --all-cases
    python -m domains.news rematch
    python -m domains.news events --case MSFT_2022-06-02
    python -m domains.news rebuild-events EVENT_RUN_ID
    python -m domains.news sample --seed 7
    python -m domains.news report

`ingest` reads every GDELT file in each case window (the 7 New York days ending on the case
date), matching every Phase 1 company. `rematch` reads again the files matched under an older
alias set. `events`, `sample` and `report` apply the headline rule (only articles whose headline
names the company feed events); `sample` leaves out articles drawn before. `rebuild-events` exits
1 on any difference. The report goes to data/reports/news/.
"""

import argparse
import sys
from datetime import date

from domains.evaluation.cases import CASES_PATH, load_cases
from domains.news import cluster, gdelt, report, store
from domains.news.matching import load_aliases, load_headline_rule
from shared_kernel.config import REPORTS_DIR
from shared_kernel.database import apply_migrations, get_db_connection


def _cases(args) -> list[tuple[str, date]]:
    cases = load_cases(CASES_PATH)
    if not args.all_cases:
        cases = [c for c in cases if c.case_id in (args.case or [])]
    return [(c.ticker, c.event_date) for c in cases]


def _master() -> dict:
    return gdelt.parse_master_list(gdelt.http_download(gdelt.MASTER_LIST_URL).decode())


def cmd_ingest(args) -> int:
    windows = _cases(args)
    if not windows:
        print("No cases selected")
        return 2
    master = _master()
    with get_db_connection() as conn:
        apply_migrations(conn)
        aliases = load_aliases(conn)
        for ticker, case_date in windows:
            start, end = gdelt.window_bounds(case_date, args.days)
            results = store.ingest_window(conn, master, start, end, aliases)
            statuses = ("ok", "skipped", "missing", "fetch_error", "bad_md5")
            by = {s: sum(r.status == s for r in results) for s in statuses}
            kept = sum(r.rows_kept for r in results)
            print(f"{ticker}_{case_date}  files {by}  articles kept {kept}", flush=True)
    return 0


def cmd_rematch(args) -> int:
    master = {e.url: e for e in _master().values()}
    with get_db_connection() as conn:
        apply_migrations(conn)
        aliases = load_aliases(conn)
        stale = store.stale_files(conn, aliases)
        for url in stale:
            store.ingest_file(conn, master[url], aliases)
    print(f"{len(stale)} files matched again")
    return 0


def cmd_events(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        aliases = load_aliases(conn)
        rule = load_headline_rule(conn, aliases)
        for ticker, case_date in _cases(args):
            cik = conn.execute("SELECT cik FROM companies WHERE ticker = ?", (ticker,)).fetchone()[
                0
            ]
            run = cluster.run_events(conn, cik, case_date, aliases, rule=rule)
            print(f"{ticker}_{case_date}  event run {run}")
            for e in cluster.stored_events(conn, run):
                print(f"  {e['first_seen']}  {e['article_count']:4} articles  "
                      f"{e['source_count']:3} sources  {e['label']}")  # fmt: skip
    return 0


def cmd_rebuild(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        aliases = load_aliases(conn)
        problems = cluster.rebuild(
            conn, args.event_run_id, aliases, load_headline_rule(conn, aliases)
        )
    for p in problems:
        print(p)
    print("rebuilt: same events" if not problems else f"{len(problems)} differences")
    return 1 if problems else 0


def cmd_sample(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        rule = load_headline_rule(conn, load_aliases(conn))
        drawn = frozenset(r["article_id"] for r in report.read_sample())
        rows = report.draw(report.candidates(conn, _cases(args), rule, skip=drawn), args.seed)
    report.append_draw(rows)
    print(f"draw {args.seed}: {len(rows)} rows added to {report.SAMPLE_PATH.name}")
    return 0


def cmd_report(args) -> int:
    with get_db_connection() as conn:
        apply_migrations(conn)
        rule = load_headline_rule(conn, load_aliases(conn))
        path = report.write_report(
            conn, _cases(args), REPORTS_DIR / "news" / "news_report.md", rule
        )
    print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m domains.news")
    commands = parser.add_subparsers(dest="command", required=True)

    def with_cases(p):
        p.add_argument("--case", action="append", help="a case id (repeatable)")
        p.add_argument("--all-cases", action="store_true")
        return p

    ing = with_cases(commands.add_parser("ingest", help="read GDELT files for case windows"))
    ing.add_argument("--days", type=int, default=7)
    ing.set_defaults(func=cmd_ingest)
    commands.add_parser("rematch", help="re-read files matched under older aliases").set_defaults(
        func=cmd_rematch
    )
    with_cases(commands.add_parser("events", help="cluster as of case dates")).set_defaults(
        func=cmd_events
    )
    reb = commands.add_parser("rebuild-events", help="check a stored event run")
    reb.add_argument("event_run_id")
    reb.set_defaults(func=cmd_rebuild)
    sam = with_cases(commands.add_parser("sample", help="draw a precision sample"))
    sam.add_argument("--seed", type=int, required=True)
    sam.set_defaults(func=cmd_sample, all_cases=True)
    with_cases(commands.add_parser("report", help="coverage and precision")).set_defaults(
        func=cmd_report, all_cases=True
    )
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
