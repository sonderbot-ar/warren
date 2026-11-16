"""The near-miss listing of the debt-due-within-a-year rules (backlog #421 item 3)."""

from domains.analysis.__main__ import main
from domains.analysis.debt_checks import debt_checks
from tests.analysis.conftest import AS_OF
from tests.analysis.test_debt_current_inside import FY2019, Q1, put


def test_each_total_is_listed_with_its_rule_and_gap(company):
    put(company, "ShortTermBorrowings", 30, FY2019)
    put(company, "DebtCurrent", 30, FY2019)  # the current portion (20) inside: #408 fires
    put(company, "DebtCurrent", 80, Q1)  # current portion 20 alone: no rule, a gap of 60
    checks = {c.period_end.isoformat(): c for c in debt_checks(company, "TST", "0000000123", AS_OF)}
    year_end, quarter = checks["2019-12-31"], checks["2020-03-31"]
    assert year_end.rules == ("inside",) and not year_end.near_miss
    assert quarter.rules == () and quarter.gap == 60 and quarter.near_miss
    assert quarter.parts == {"debt_current": 20, "short_term_borrowings": None,
                             "commercial_paper": None}  # fmt: skip


def test_a_rounded_total_is_not_a_near_miss(company):
    put(company, "DebtCurrent", 20.1, Q1)
    [check] = debt_checks(company, "TST", "0000000123", AS_OF)
    assert check.rules == () and not check.near_miss


def test_only_what_was_public_on_the_date_is_listed(company):
    put(company, "DebtCurrent", 80, Q1)  # filed 2020-04-30
    assert debt_checks(company, "TST", "0000000123", AS_OF.replace(month=4, day=29)) == []


def test_the_command_prints_near_misses(company, monkeypatch, capsys):
    import domains.analysis.__main__ as cli

    put(company, "DebtCurrent", 80, Q1)
    company.commit()
    monkeypatch.setattr(cli, "get_db_connection", lambda: _Same(company))
    assert main(["debt-checks", "--as-of", AS_OF.isoformat(), "--near-misses"]) == 0
    assert "2020-03-31" in capsys.readouterr().out


class _Same:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False
