"""Measuring the news data (M5): coverage per case window, match precision, labeller agreement.

Precision comes from a labelled sample, never from a number written in code. Each draw of the
sample keeps its seed, and every draw is reported, so fixing aliases and drawing again can't hide
an earlier failure. Two labellers label part of the sample independently; their agreement is
Cohen's kappa (Cohen 1960). Intervals are Wilson's (Wilson 1927; Brown, Cai & DasGupta 2001).

With the headline rule (Step 6), draws take only articles whose headline passes it, since those
feed events, plus a recall check: `org_exact` articles that fail it, labelled to estimate the
stories the rule throws away. Agreement is read on `about` against the rest, the split precision
reads (Artstein & Poesio 2008), with raw agreement beside it, since one dominant label can sink
kappa when labellers mostly agree (Feinstein & Cicchetti 1990).
"""

import csv
import math
import random
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from domains.news.gdelt import CASE_TZ, window_bounds
from domains.news.matching import HeadlineRule, about_headline
from domains.news.store import iso

SAMPLE_PATH = Path(__file__).parent / "match_sample.csv"
SAMPLE_FIELDS = (
    "draw ticker method article_id seen_at url title label reason second_label second_reason"
).split()
LABELS = ("about", "related", "not")
DROPPED = "org_exact_dropped"  # recall check: org_exact articles the headline rule drops
PER_METHOD = {"org_exact": 50, "org_subsidiary": 25, "title_alias": 25, DROPPED: 20}
SECOND_SHARE = 0.4  # share of each draw the second labeller labels
GATE = 0.80
KAPPA_FLOOR = 0.6  # below it the sample goes to the owner before the gate is read
KAPPA_MIN_ROWS = 10  # fewer shared rows in a cell: raw agreement only
Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def cohen_kappa(first: list[str], second: list[str]) -> float:
    """Agreement beyond chance between two labellers on the same items."""
    if len(first) != len(second) or not first:
        raise ValueError("kappa needs two equal, non-empty label lists")
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    ca, cb = Counter(first), Counter(second)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def coverage(conn: sqlite3.Connection, case_date: date, days: int = 7) -> dict:
    """Expected vs read files for a case window."""
    start, end = window_bounds(case_date, days)
    expected = int((end - start).total_seconds() // 900)
    counts = dict(
        conn.execute(
            "SELECT status, COUNT(*) FROM news_files WHERE file_ts >= ? AND file_ts < ? "
            "GROUP BY status",
            (iso(start), iso(end)),
        ).fetchall()
    )
    ok = counts.get("ok", 0)
    sightings, url_titles = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(title_from_url), 0) FROM article_sightings "
        "WHERE seen_at >= ? AND seen_at < ?",
        (iso(start), iso(end)),
    ).fetchone()
    return {"expected": expected, "ok": ok, "missing": counts.get("missing", 0),
            "fetch_error": counts.get("fetch_error", 0),
            "bad_md5": counts.get("bad_md5", 0), "share": ok / expected,
            "sightings": sightings, "url_titles": url_titles}  # fmt: skip


def candidates(
    conn: sqlite3.Connection,
    windows: list[tuple[str, date]],
    rule: HeadlineRule | None = None,
    skip: frozenset[str] = frozenset(),
) -> list[dict]:
    """Matched sightings inside the case windows: (ticker, case date) pairs. With a rule, only
    articles whose headline passes it, and `org_exact` ones that fail it as `DROPPED`. Articles
    in `skip` (earlier draws) are left out."""
    out = []
    for ticker, case_date in windows:
        start, end = window_bounds(case_date)
        out += [
            dict(r)
            for r in conn.execute(
                """
                SELECT co.ticker, c.cik, c.method, s.article_id, s.seen_at, a.url, s.title,
                       s.title_from_url
                FROM article_companies c
                JOIN companies co ON co.cik = c.cik
                JOIN article_sightings s ON s.article_id = c.article_id AND s.file_url = c.file_url
                JOIN articles a ON a.article_id = s.article_id
                WHERE co.ticker = ? AND s.seen_at >= ? AND s.seen_at < ?
                ORDER BY s.article_id, s.seen_at
                """,
                (ticker, iso(start), iso(end)),
            )
        ]
    seen, unique = set(), []
    for r in out:  # an article once per company and method, as its earliest sighting
        key = (r["ticker"], r["method"], r["article_id"])
        if key in seen or r["article_id"] in skip:
            continue
        seen.add(key)
        if rule is not None:
            seen_on = datetime.fromisoformat(r["seen_at"]).astimezone(CASE_TZ).date()
            if not about_headline(rule, r["cik"], r["title"], seen_on):
                if r["method"] != "org_exact":
                    continue
                r["method"] = DROPPED
        unique.append(r)
    return unique


def headline_pass(
    conn: sqlite3.Connection, ticker: str, case_date: date, rule: HeadlineRule
) -> dict:
    """For a case's company and window: matched articles, how many pass the rule, and how
    many of them have only URL words for a headline."""
    rows = candidates(conn, [(ticker, case_date)])
    first: dict[str, dict] = {}
    for r in rows:
        first.setdefault(r["article_id"], r)
    passed = sum(
        about_headline(rule, r["cik"], r["title"],
                       datetime.fromisoformat(r["seen_at"]).astimezone(CASE_TZ).date())
        for r in first.values()
    )  # fmt: skip
    url_words = sum(r["title_from_url"] for r in first.values())
    return {"matched": len(first), "passed": passed, "url_words": url_words}


def draw(pool: list[dict], seed: int) -> list[dict]:
    """The sample for one draw: up to PER_METHOD rows per company and method, by seed."""
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in sorted(pool, key=lambda r: (r["ticker"], r["method"], r["article_id"])):
        groups[(r["ticker"], r["method"])].append(r)
    rows = []
    for (_, method), group in sorted(groups.items()):
        picked = rng.sample(group, min(PER_METHOD[method], len(group)))
        second = set(rng.sample(range(len(picked)), round(SECOND_SHARE * len(picked))))
        for i, r in enumerate(picked):
            rows.append(
                {"draw": seed, **{k: r[k] for k in ("ticker", "method", "article_id", "seen_at",
                 "url", "title")}, "label": "", "reason": "",
                 "second_label": "" if i in second else "-", "second_reason": ""}
            )  # fmt: skip
    return rows


def append_draw(rows: list[dict], path: Path | None = None) -> None:
    """A draw is added, never replaces an earlier one."""
    path = path or SAMPLE_PATH
    if not rows:
        return
    if any(int(r["draw"]) == rows[0]["draw"] for r in read_sample(path)):
        raise ValueError(f"draw {rows[0]['draw']} is already in {path.name}")
    new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


def read_sample(path: Path | None = None) -> list[dict]:
    path = path or SAMPLE_PATH
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def precision(rows: list[dict]) -> list[dict]:
    """Per draw, company and method: share labelled `about`, its interval, and agreement."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["label"] not in LABELS:
            raise ValueError(f"unlabelled or unknown label in draw {r['draw']}: {r['article_id']}")
        groups[(int(r["draw"]), r["ticker"], r["method"])].append(r)
    out = []
    for (d, ticker, method), group in sorted(groups.items()):
        k, n = sum(r["label"] == "about" for r in group), len(group)
        both = [r for r in group if r["second_label"] in LABELS]
        first = [r["label"] for r in both]
        second = [r["second_label"] for r in both]
        about_first = [x == "about" for x in first]
        about_second = [x == "about" for x in second]
        agree = (
            sum(a == b for a, b in zip(about_first, about_second, strict=True)) / len(both)
            if both
            else None
        )
        low, high = wilson(k, n)
        out.append({"draw": d, "ticker": ticker, "method": method, "n": n, "about": k,
                    "precision": k / n, "low": low, "high": high,
                    "kappa": cohen_kappa(first, second) if both else None,
                    "shared": len(both), "agree": agree,
                    "kappa_about": (cohen_kappa(about_first, about_second)
                                    if len(both) >= KAPPA_MIN_ROWS else None),
                    "passes": k / n >= GATE})  # fmt: skip
    return out


def write_report(
    conn: sqlite3.Connection,
    windows: list[tuple[str, date]],
    out: Path,
    rule: HeadlineRule | None = None,
) -> Path:
    lines = ["# News data report (M5)", "", "## Coverage per case window", "",
             "| Case | Expected files | Read | Missing | Fetch errors | Bad MD5 | Share "
             "| Sightings | URL words |",
             "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for ticker, case_date in windows:
        c = coverage(conn, case_date)
        flag = "" if c["share"] >= 0.98 else " ⚠"
        lines.append(f"| {ticker}_{case_date} | {c['expected']} | {c['ok']} | {c['missing']} | "
                     f"{c['fetch_error']} | {c['bad_md5']} | {c['share']:.1%}{flag} | "
                     f"{c['sightings']} | {c['url_titles']} |")  # fmt: skip
    lines += ["", "Missing: GDELT has no file for the slot, or no longer serves it. Fetch errors: "
              "we failed to download it; `ingest` again reads them. Either lowers the share, and "
              "a window under 98% is flagged ⚠.",
              ""]  # fmt: skip
    if rule is not None:
        lines += ["## Headline rule per case window", "",
                  "| Case | Matched articles | Pass | Share | URL-word headlines |",
                  "|---|---|---|---|---|"]  # fmt: skip
        for ticker, case_date in windows:
            h = headline_pass(conn, ticker, case_date, rule)
            share = h["passed"] / h["matched"] if h["matched"] else 0.0
            mark = " (URL words)" if h["url_words"] * 2 > h["matched"] else ""
            lines.append(f"| {ticker}_{case_date} | {h['matched']} | {h['passed']} | "
                         f"{share:.0%} | {h['url_words']}{mark} |")  # fmt: skip
        lines += ["", "Only articles that pass feed events. Windows marked (URL words) are "
                  "mostly before GDELT kept page titles; they pass less often.", ""]  # fmt: skip
    lines += ["## Events per case (latest event run)", "",
              "| Case | Event runs | Events | Articles | Largest event |",
              "|---|---|---|---|---|"]  # fmt: skip
    for ticker, case_date in windows:
        run = conn.execute(
            "SELECT r.event_run_id, COUNT(*) OVER () AS runs FROM event_runs r "
            "JOIN companies c ON c.cik = r.cik WHERE c.ticker = ? AND r.as_of = ? "
            "ORDER BY r.created_at DESC, r.event_run_id LIMIT 1",
            (ticker, case_date.isoformat()),
        ).fetchone()
        if run is None:
            lines.append(f"| {ticker}_{case_date} | 0 | | | |")
            continue
        n, total, top = conn.execute(
            "SELECT COUNT(*), SUM(article_count), MAX(article_count) FROM events "
            "WHERE event_run_id = ?",
            (run["event_run_id"],),
        ).fetchone()
        lines.append(f"| {ticker}_{case_date} | {run['runs']} | {n} | {total or 0} | {top or 0} |")
    lines += ["", "## Match precision (every draw)", "",
              "| Draw | Company | Method | n | Precision | 95% interval | Shared rows "
              "| Agreement on about | Kappa on about | Kappa, 3 labels | Gate 0.80 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    sample = read_sample()
    draws = sorted({r["draw"] for r in sample}, key=int)
    pending = [d for d in draws if any(r["label"] not in LABELS for r in sample if r["draw"] == d)]
    for p in precision([r for r in sample if r["draw"] not in pending]):

        def fmt(x):
            return "" if x is None else f"{x:.2f}"

        kappa = fmt(p["kappa_about"])
        if p["kappa_about"] is not None and p["kappa_about"] < KAPPA_FLOOR:
            kappa += " (below 0.6: the owner labels this sample)"
        gate = "recall check" if p["method"] == DROPPED else "pass" if p["passes"] else "FAIL"
        lines.append(f"| {p['draw']} | {p['ticker']} | {p['method']} | {p['n']} | "
                     f"{p['precision']:.2f} | {p['low']:.2f}–{p['high']:.2f} | {p['shared']} | "
                     f"{fmt(p['agree'])} | {kappa} | {fmt(p['kappa'])} | {gate} |")  # fmt: skip
    for d in pending:
        rows = [r for r in sample if r["draw"] == d]
        done = sum(r["label"] in LABELS for r in rows)
        lines.append(f"\nDraw {d} is not fully labelled yet ({done} of {len(rows)} rows).")
    lines += ["", f"Kappa on `about` is read on cells with {KAPPA_MIN_ROWS} or more shared rows. "
              f"`{DROPPED}` rows are articles the headline rule drops: their precision is the "
              "share of real stories lost, not a gate.",
              "Recall of matching itself is not measured: it needs every relevant article, which "
              "nobody has.",
              f"Case calendar: {CASE_TZ}. Only GDELT's English stream is read."]  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out
