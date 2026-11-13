"""Backlog #365: the reading rules' version, its fingerprint and its log agree."""

import textwrap

import pytest

from domains.analysis import reading_rules as rr

FIX = (
    "The reading rules' code changed (fingerprint {fp}). In the same commit, add a row to "
    "domains/analysis/reading_rules.md: with READING_RULES_VERSION + 1 if the change can change "
    "what a run reads, or under the same version, saying why, if it cannot (a refactor, or only "
    "a Python upgrade that changed the syntax tree). Print it with "
    "`python -m domains.analysis.reading_rules`."
)


def test_todays_fingerprint_is_logged_under_the_current_version():
    fp = rr.rules_fingerprint()[:12]
    logged = dict(rr.logged_versions())
    assert fp in logged, FIX.format(fp=fp)
    assert logged[fp] == rr.READING_RULES_VERSION, (
        f"Fingerprint {fp} is logged under v{logged[fp]}, but READING_RULES_VERSION is "
        f"v{rr.READING_RULES_VERSION}: the code went back to an older version's rules, or the "
        "constant wasn't bumped with its row."
    )


def test_log_versions_start_at_one_never_go_down_and_never_skip():
    versions = [v for _fp, v in rr.logged_versions()]
    assert versions and versions[0] == 1
    for before, after in zip(versions, versions[1:], strict=False):
        assert after in (before, before + 1), versions
    assert rr.READING_RULES_VERSION == max(versions)


def test_each_fingerprint_is_logged_once():
    fps = [fp for fp, _v in rr.logged_versions()]
    assert len(fps) == len(set(fps))


def test_rules_cover_the_engine_and_what_it_imports():
    modules = rr.rules_modules()
    for module in (
        "domains/fundamentals/facts.py",
        "domains/analysis/math_engine.py",
        "domains/market/erp.py",  # the equity risk premium (professor)
        "domains/market/yields.py",
        "domains/market/prices.py",
        "domains/fundamentals/quality.py",  # CONSISTENCY_TOLERANCE
        "domains/analysis/dcf.py",  # QUARTERS, YEARS, SEED
    ):
        assert module in modules
    assert not set(modules) & rr.NOT_RULES.keys()
    assert all((rr.REPO_ROOT / m).exists() for m in rr.NOT_RULES)


def _module(tmp_path, body: str) -> str:
    (tmp_path / "m.py").write_text(textwrap.dedent(body))
    return rr.rules_fingerprint(("m.py",), root=tmp_path)


BASE = '''
    """Module docstring."""
    LIMIT = 2.0


    def pick(a, b):
        """Pick one."""
        return a if a > LIMIT * b else b
'''


def test_fingerprint_ignores_comments_docstrings_and_layout(tmp_path):
    base = _module(tmp_path, BASE)
    assert _module(tmp_path, BASE.replace('"""Pick one."""', '"""Pick the bigger."""')) == base
    assert _module(tmp_path, BASE.replace("LIMIT = 2.0", "LIMIT = 2.0  # a comment")) == base
    assert _module(tmp_path, BASE.replace("a > LIMIT * b", "a > (LIMIT * b)")) == base
    no_docs = "\n".join(line for line in BASE.splitlines() if '"""' not in line)
    assert _module(tmp_path, no_docs) == base


def test_fingerprint_changes_with_the_code(tmp_path):
    base = _module(tmp_path, BASE)
    assert _module(tmp_path, BASE.replace("LIMIT = 2.0", "LIMIT = 2.5")) != base
    assert _module(tmp_path, BASE.replace("a > LIMIT", "a >= LIMIT")) != base
    assert _module(tmp_path, BASE.replace("else b", "else -b")) != base


def test_a_new_import_joins_the_rules(tmp_path):
    pkg = tmp_path / "domains" / "x"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text("from domains.x.b import f\n")
    (pkg / "b.py").write_text("import domains.x.c\n")
    (pkg / "c.py").write_text("V = 1\n")
    (pkg / "d.py").write_text("V = 2\n")
    root_modules = rr.ROOT_MODULES
    try:
        rr.ROOT_MODULES = ("domains/x/a.py",)
        assert rr.rules_modules(tmp_path) == ("domains/x/a.py", "domains/x/b.py", "domains/x/c.py")
    finally:
        rr.ROOT_MODULES = root_modules


# Step 2: stored on every run, read back by rebuild, the reproduce line and the report.


def _version(conn, run_id):
    sql = "SELECT reading_rules_version FROM runs WHERE run_id = ?"
    return conn.execute(sql, (run_id,)).fetchone()[0]


def _baseline(conn):
    from domains.analysis.runs import run_baseline
    from tests.analysis.conftest import AS_OF, CHOICES

    return run_baseline(conn, "TST", AS_OF, choices=CHOICES, today=AS_OF)


def test_a_new_run_stores_todays_reading_rules(company):
    run_id = _baseline(company)
    assert _version(company, run_id) == rr.READING_RULES_VERSION


def test_a_what_if_stores_its_parents_reading_rules(company):
    from domains.analysis.whatif import Change, revalue

    parent = _baseline(company)
    child = revalue(company, parent, [Change("beta", value=1.5)]).run_id
    assert _version(company, child) == rr.READING_RULES_VERSION
    # a parent stored before #365 has none, and neither has its child
    company.execute("UPDATE runs SET reading_rules_version = NULL WHERE run_id = ?", (parent,))
    child = revalue(company, parent, [Change("beta", value=1.4)]).run_id
    assert _version(company, child) is None


def test_the_column_takes_no_version_below_one(company):
    import sqlite3

    run_id = _baseline(company)
    with pytest.raises(sqlite3.IntegrityError):
        company.execute("UPDATE runs SET reading_rules_version = 0 WHERE run_id = ?", (run_id,))


@pytest.mark.parametrize(
    ("stored", "older", "words"),
    [
        (None, True, "; reading rules not recorded"),
        (0, True, "; made under older reading rules (v0, today v{now})"),
        ("now", False, ""),
    ],
)
def test_rebuild_and_the_reproduce_line_say_which_rules(
    company, monkeypatch, capsys, stored, older, words
):
    from contextlib import contextmanager

    from domains.analysis import __main__ as cli
    from domains.analysis.runs import rebuild

    run_id = _baseline(company)
    now = rr.READING_RULES_VERSION
    if stored is None:
        company.execute("UPDATE runs SET reading_rules_version = NULL WHERE run_id = ?", (run_id,))
    elif stored == 0:
        # an older version than today's: pretend today's code is one version on
        monkeypatch.setattr("domains.analysis.runs.READING_RULES_VERSION", now + 1)
        monkeypatch.setattr(cli, "READING_RULES_VERSION", now + 1)
        stored, words = now, f"; made under older reading rules (v{now}, today v{now + 1})"
    else:
        stored = now
    rebuilt = rebuild(company, run_id)
    assert rebuilt.ok  # same code here: the rows still match; only the label differs
    assert rebuilt.rules_version == stored and rebuilt.older_rules is older

    @contextmanager
    def same_connection(*args):
        yield company

    monkeypatch.setattr(cli, "get_db_connection", same_connection)
    assert cli.main(["reproduce", "--all", "--rebuild"]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "rebuild OK" in x)
    assert line.endswith("rows" + words.format(now=now))


def test_the_report_names_the_reading_rules(company, tmp_path):
    from domains.analysis import report

    run_id = _baseline(company)
    text = report.write_report(company, run_id, tmp_path).read_text()
    assert f"reading rules v{rr.READING_RULES_VERSION}" in text
    company.execute("UPDATE runs SET reading_rules_version = NULL WHERE run_id = ?", (run_id,))
    text = report.write_report(company, run_id, tmp_path).read_text()
    assert "reading rules not recorded (made before v0.9.67)" in text
