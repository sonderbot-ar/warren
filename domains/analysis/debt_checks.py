"""Where the debt-due-within-a-year rules fire, and where they come close (backlog #421 item 3).

For every balance date at which a company files its total debt due within one year
(`DebtCurrent`, map item `debt_current_total`), list the parts filed for the same date, which of
the three rules fired (#408 the current portion inside short-term borrowings, #412 commercial
paper beside them, #415 the total in place of its parts), and how far the total is from the sum
of the same-date parts. A date where no rule fired and the total and the parts disagree is a near
miss: Exxon's 2011-03-31, with a mis-tagged part of 12,316M against a total of 3,560M, was found
by hand before #415's rule caught it.

Read-only and point-in-time: every figure is one public on `as_of`. For the engine team's
measurements, not for the app.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date
from functools import partial

from domains.analysis.math_engine import (
    TOO_BIG,
    current_debt_inside,
    load_history,
    paper_beside,
    total_in_place,
)

NEAR = 0.01
PARTS = ("debt_current", "short_term_borrowings", "commercial_paper")


@dataclass(frozen=True)
class DebtCheck:
    ticker: str
    period_end: date
    total: float
    parts: dict[str, float | None]  # each part filed for the same date (None: not filed)
    rules: tuple[str, ...]  # "inside" (#408), "beside" (#412), "in_place" (#415)

    @property
    def parts_sum(self) -> float:
        return sum(v for v in self.parts.values() if v is not None)

    @property
    def gap(self) -> float:
        """The total less the same-date parts (the current leases, a rounding, a part inside)."""
        return self.total - self.parts_sum

    @property
    def largest_share(self) -> float | None:
        """The largest same-date part as a multiple of the total (#415's mis-tag line is
        `TOO_BIG`)."""
        filed = [v for v in self.parts.values() if v is not None]
        return max(filed) / self.total if filed and self.total > 0 else None

    @property
    def near_miss(self) -> bool:
        """No rule fired, some part is filed, and the total and the same-date parts differ by
        more than `NEAR` of the total (a total rounded to a tenth of a billion, as JNJ's, is
        within it)."""
        if self.rules or self.parts_sum == 0:
            return False
        return abs(self.gap) > NEAR * abs(self.total)


def debt_checks(conn: sqlite3.Connection, ticker: str, cik: str, as_of: date) -> list[DebtCheck]:
    history = load_history(conn, cik, as_of)
    out = []
    for total in history.instants.get("debt_current_total", []):
        day = total.period_end
        on = {item: history.on(item, day) for item in PARTS}
        rules = []
        inside = current_debt_inside(on["debt_current"], on["short_term_borrowings"], history.on)
        if inside:
            rules.append("inside")
        if paper_beside(on["short_term_borrowings"], on["commercial_paper"], history.on, inside):
            rules.append("beside")
        if total_in_place(partial(history.latest_before, day=day), day):
            rules.append("in_place")
        parts = {item: (f.value if f else None) for item, f in on.items()}
        out.append(DebtCheck(ticker, day, total.value, parts, tuple(rules)))
    return out


def all_debt_checks(conn: sqlite3.Connection, as_of: date, ticker: str | None = None):
    rows = conn.execute("SELECT ticker, cik FROM companies ORDER BY ticker").fetchall()
    for name, cik in rows:
        if ticker is None or name == ticker:
            yield from debt_checks(conn, name, cik, as_of)


def line(check: DebtCheck) -> str:
    def m(v):
        return "-" if v is None else f"{v / 1e6:,.0f}"

    share = check.largest_share
    flag = "  NEAR MISS" if check.near_miss else ""
    big = f", largest part {share:.2f}x (line {TOO_BIG}x)" if share is not None else ""
    return (
        f"{check.ticker:5} {check.period_end}  total {m(check.total)}  parts "
        + " / ".join(m(check.parts[p]) for p in PARTS)
        + f"  gap {m(check.gap)}{big}  rules {','.join(check.rules) or 'none'}{flag}"
    )
