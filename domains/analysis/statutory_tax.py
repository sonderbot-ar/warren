"""Statutory corporate income tax rates as data (backlog #385): the rate a run falls back to when
the company's own effective rate means little (three years of pretax income at or near zero).

One row per law, by jurisdiction. A run reads the newest row enacted on or before its as-of date,
so a law signed after that date is not known to it (point-in-time); a law signed but not yet
applying is the rate future profits will pay, which is what a forecast needs (deferred taxes are
remeasured on the enactment date too, ASC 740-10-35-4). Federal only: state and local
taxes are left out, and the run's lesson says so.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class StatutoryRate:
    jurisdiction: str
    rate: float
    enacted_on: date
    applies_from: date  # the first day of the tax years it applies to
    law: str
    source: str


RATES = (
    StatutoryRate(
        "US",
        0.35,
        date(1993, 8, 10),
        date(1993, 1, 1),
        "Pub. L. 103-66 (26 U.S.C. §11(b) before 2018)",
        "Omnibus Budget Reconciliation Act of 1993, Pub. L. 103-66 §13221: 35% on taxable income "
        "over $10 million (flat 35% above $18,333,333)",
    ),
    StatutoryRate(
        "US",
        0.21,
        date(2017, 12, 22),
        date(2018, 1, 1),
        "Pub. L. 115-97 (the Tax Cuts and Jobs Act)",
        "Pub. L. 115-97 §13001, 26 U.S.C. §11(b) as amended: a flat 21% for tax years beginning "
        "after December 31, 2017",
    ),
)


class StatutoryRateError(LookupError):
    """No statutory rate is known for a jurisdiction on a date."""


def statutory_rate(jurisdiction: str, as_of: date) -> StatutoryRate:
    """The newest statutory rate of `jurisdiction` enacted on or before `as_of`."""
    known = [r for r in RATES if r.jurisdiction == jurisdiction and r.enacted_on <= as_of]
    if not known:
        raise StatutoryRateError(f"no statutory tax rate for {jurisdiction!r} on {as_of}")
    return max(known, key=lambda r: r.enacted_on)


JURISDICTIONS = frozenset(r.jurisdiction for r in RATES)
