"""What a Gordon terminal value assumes about year 5's reinvestment, in one place for the
sensitivity grid and the what-if (backlog #216), so the two can't tell a student different things
about the same run.

The Gordon formula grows year 5's free cash flow, so it holds year 5's reinvestment rate
(1 − FCFF ÷ NOPAT) while growth runs on. Growth g at a reinvestment rate implies a return on new
investment of g ÷ rate (g = reinvestment rate × RONIC; Koller, Goedhart and Wessels, *Valuation*,
ch. 14; Damodaran, *Investment Valuation*, ch. 12). With NOPAT at or below zero there is no rate;
at a rate of zero or below, growth comes from no investment and implies no return. The arithmetic
is in `financial_math`; this module says when it applies and which notes follow."""

import math

from domains.analysis import financial_math as fm
from domains.analysis.reported import Coded

HOLDS = "gordon_holds_reinvestment"
NOT_POSITIVE = "gordon_reinvestment_not_positive"


def year5_reinvestment(fcff: float, nopat: float) -> float | None:
    """Year 5's reinvestment rate, or None when there is no rate: NOPAT at or below zero, or a
    cash flow that isn't a finite number (stored runs never have one; the grid and the what-if
    used to read a NaN differently, backlog #216)."""
    if not (math.isfinite(fcff) and math.isfinite(nopat)):
        return None
    try:
        return fm.reinvestment_rate(fcff, nopat)
    except fm.FinancialMathError:
        return None


def reinvests(rate: float | None) -> bool:
    """True when year 5 puts capital in: a rate above zero."""
    return rate is not None and rate > 0


def implied_ronic(growth: float, rate: float | None) -> float | None:
    """The return on new investment growth implies at `rate`, or None when it doesn't reinvest."""
    return fm.implied_ronic(growth, rate) if reinvests(rate) else None


def reinvestment_notes(rate: float | None, held_text: str, not_positive_text: str) -> list[Coded]:
    """The note that Gordon holds year 5's reinvestment, then, when year 5 doesn't reinvest, the
    note that its growth comes from no investment. Codes and params are shared; each caller keeps
    its own English sentence."""
    notes = [Coded(HOLDS, {"reinvestment_rate": rate}, held_text)]
    if not reinvests(rate):
        notes.append(Coded(NOT_POSITIVE, {"reinvestment_rate": rate}, not_positive_text))
    return notes
