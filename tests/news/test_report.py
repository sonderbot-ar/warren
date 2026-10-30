"""Precision with intervals, labeller agreement, coverage and the CLI end to end (M5 Step 4)."""

import json
from datetime import UTC, date, datetime

import pytest

from domains.news import __main__ as cli
from domains.news import gdelt, report
from tests.news.test_store import COMPANIES, gkg_file, gkg_line


def test_wilson_interval_matches_published_values():
    # Brown, Cai & DasGupta (2001): 20 of 25 gives about 0.609–0.911
    low, high = report.wilson(20, 25)
    assert low == pytest.approx(0.6087, abs=1e-3) and high == pytest.approx(0.9114, abs=1e-3)
    assert report.wilson(0, 0) == (0.0, 1.0)


def test_cohen_kappa():
    assert report.cohen_kappa(["about"] * 4, ["about"] * 4) == 1.0
    # observed 0.5, chance 0.5: no agreement beyond chance
    assert (
        report.cohen_kappa(["about", "not", "about", "not"], ["about", "about", "not", "not"]) == 0
    )  # noqa: E501
    with pytest.raises(ValueError):
        report.cohen_kappa([], [])


def pool(n: int, ticker="MSFT", method="org_exact") -> list[dict]:
    return [{"ticker": ticker, "method": method, "article_id": f"a{i:03d}", "seen_at": "t",
             "url": f"https://x.com/{i}", "title": f"title {i}"} for i in range(n)]  # fmt: skip


def test_a_draw_is_seeded_capped_and_marks_a_second_labeller_share():
    rows = report.draw(pool(80) + pool(10, method="title_alias"), seed=7)
    assert rows == report.draw(pool(80) + pool(10, method="title_alias"), seed=7)
    exact = [r for r in rows if r["method"] == "org_exact"]
    assert len(exact) == 50 and len([r for r in rows if r["method"] == "title_alias"]) == 10
    assert sum(r["second_label"] == "" for r in exact) == 20  # 40% for the second labeller


def test_draws_are_appended_never_replaced(tmp_path):
    path = tmp_path / "sample.csv"
    report.append_draw(report.draw(pool(5), 1), path)
    report.append_draw(report.draw(pool(5), 2), path)
    assert {r["draw"] for r in report.read_sample(path)} == {"1", "2"}
    with pytest.raises(ValueError, match="already"):
        report.append_draw(report.draw(pool(5), 1), path)


def test_precision_per_draw_with_interval_and_kappa():
    rows = [
        {"draw": "7", "ticker": "MSFT", "method": "org_exact", "article_id": str(i),
         "label": "about" if i < 8 else "not", "second_label": "about" if i < 2 else "-"}
        for i in range(10)
    ]  # fmt: skip
    [p] = report.precision(rows)
    assert (p["n"], p["about"], p["precision"], p["passes"]) == (10, 8, 0.8, True)
    assert p["kappa"] == 1.0  # both labellers said `about` on the two shared rows
    rows[0]["label"] = ""
    with pytest.raises(ValueError, match="unlabelled"):
        report.precision(rows)


def test_cli_end_to_end_on_fixtures(tmp_path, monkeypatch, db_path):
    monkeypatch.setattr("shared_kernel.database.DB_PATH", db_path)
    monkeypatch.setattr(report, "SAMPLE_PATH", tmp_path / "sample.csv")
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path / "reports")
    from shared_kernel.database import apply_migrations, get_db_connection

    with get_db_connection(db_path) as conn:
        apply_migrations(conn)
        for cik, ticker, names in COMPANIES:
            conn.execute(
                "INSERT INTO companies (cik, ticker, name, aliases_json) VALUES (?, ?, ?, ?)",
                (cik, ticker, names[0], json.dumps(names)),
            )
        conn.commit()
    slot = datetime(2022, 6, 2, 15, tzinfo=UTC)
    url = f"http://data.gdeltproject.org/gdeltv2/{slot:%Y%m%d%H%M%S}.gkg.csv.zip"
    entry, content = gkg_file(url, [
        gkg_line(f"https://news{i}.com/msft", ["microsoft"], "Microsoft cuts revenue forecast")
        for i in range(3)
    ])  # fmt: skip
    master = f"{entry.size} {entry.md5} {url}\n".encode()
    monkeypatch.setattr(
        gdelt, "http_download", lambda u: master if u == gdelt.MASTER_LIST_URL else content
    )  # noqa: E501

    assert cli.main(["ingest", "--case", "MSFT_2022-06-02"]) == 0
    assert cli.main(["events", "--case", "MSFT_2022-06-02"]) == 0
    with get_db_connection(db_path) as conn:
        [run] = [r[0] for r in conn.execute("SELECT event_run_id FROM event_runs")]
        counts = conn.execute("SELECT article_count, source_count FROM events").fetchone()
        assert tuple(counts) == (3, 1)  # three URLs, one source domain in the fixture
        cov = report.coverage(conn, date(2022, 6, 2))
    assert (cov["expected"], cov["ok"], cov["missing"]) == (672, 1, 671)
    assert cli.main(["rebuild-events", run]) == 0
    assert cli.main(["sample", "--seed", "7"]) == 0
    assert len(report.read_sample()) == 3
    assert cli.main(["report", "--case", "MSFT_2022-06-02"]) == 0
    text = (tmp_path / "reports" / "news" / "news_report.md").read_text()
    assert "| MSFT_2022-06-02 | 1 | 1 | 3 | 3 |" in text
    assert "Draw 7 is not fully labelled yet (0 of 3 rows)." in text
