"""Words a reader sees for the analysis engine's codes, kept apart from the logic so reports can
later be translated (Decision 11, guardrail 5). Phase 1 is in English."""

from dataclasses import dataclass

from domains.analysis import math_engine

# Short cause of a missing value, per financial_math.REASONS code (backlog #9).
REASON_WORDS = {
    "growth_not_below_rate": "WACC ≤ terminal growth",
    "rate_not_positive": "WACC ≤ 0",
    "rate_not_above_minus_100": "WACC ≤ −100%",
    "invalid_input": "invalid input",
}

# The same cause in a sentence a student can learn from.
REASON_SENTENCES = {
    "growth_not_below_rate": (
        "WACC falls to terminal growth or below: cash flows that grow as fast as the rate they "
        "are discounted at add up to an infinite sum, so the DCF has no value"
    ),
    "rate_not_positive": (
        "WACC falls to zero or below: cash a year from now would be worth at least as much as cash "
        "today, so the terminal value has no finite value"
    ),
    "rate_not_above_minus_100": (
        "WACC falls to −100% or below, where discounting has no meaning, so the DCF has no value"
    ),
    "invalid_input": "an input makes the formula meaningless",
}


# A lesson per run-warning code (backlog #197): why the warning matters and what to look at, in
# English; the app translates it. Groups are codes, in the order a screen reads them.
WARNING_GROUPS = {
    "data": "The figures the run reads",
    "assumption": "An assumption outside its usual range",
    "valuation": "How far to trust the value",
}


@dataclass(frozen=True)
class Lesson:
    """Why one kind of run warning matters (`why`), where the idea comes from (`source`: a
    published reference, or "Warren working rule" for a threshold of Warren's own), and the
    group a screen sorts it under (a `WARNING_GROUPS` code)."""

    group: str
    why: str
    source: str


_COMPARABILITY = "FASB Concepts Statement No. 8, chapter 3 (comparability)"
_TERMINAL = "Damodaran, Investment Valuation (3rd ed.), chapter 12 (terminal value)"


def _pct(x: float) -> str:
    return f"{x * 100:g}%"


WARNING_LESSONS = {
    "beyond_history": Lesson(
        "data",
        "Warren's copy of this company's filings stops before the run's date (for example, "
        "when the company moved its reporting to a new parent company), so the run is built on "
        "older figures than its date suggests. Check what the company reported after the "
        "history ends before relying on the value.",
        "Warren rule: the coverage note in the company list (universe.csv); point-in-time data "
        "(Structure Guide, Decision 7)",
    ),
    "data_warning": Lesson(
        "data",
        "Something unusual came up while reading the filings that Warren has no specific "
        "warning for. Read the line itself and check the figure it names in the filing before "
        "relying on the value.",
        "Warren rule: a warning raised while reading the filings",
    ),
    "concept_map_changed": Lesson(
        "data",
        "Warren's list of which XBRL tag counts as which line (revenue, debt, capex and so on) "
        "changed after the filings were loaded, so this run may read some lines differently "
        "from a fresh load. Loading the filings again removes the doubt.",
        "Warren rule: the concept map (Structure Guide, Decision 2)",
    ),
    "fundamentals_stale": Lesson(
        "data",
        f"The newest quarter the run uses ended more than {math_engine.STALE_AFTER.days} days "
        "before the run's date. Companies file a quarter within 40 to 45 days and a year "
        "within 60 to 90, so a newer report probably exists that Warren did not load, and the "
        "forecast starts from older figures than an analyst would use.",
        "SEC Forms 10-Q and 10-K, general instructions (filing deadlines); "
        f"{math_engine.STALE_AFTER.days} days is a Warren working rule",
    ),
    "balance_carried_forward": Lesson(
        "data",
        "An item was missing from the newest balance sheet, so Warren took it from an earlier "
        "one, up to a year old. If the item changed since (new debt, a large cash move), the "
        "step from enterprise value to equity value, and so the value per share, is off by "
        "that change.",
        "Warren rule D3, balance sheet (Build Plan)",
    ),
    "balance_counted_zero": Lesson(
        "data",
        "An item was not reported within a year of the balance sheet, so Warren counted it as "
        "zero. Usually the company has none; if it does have some (debt or a minority interest "
        "reported under another name, for example), the value per share is off by that "
        "amount.",
        "Warren rule D3, balance sheet (Build Plan)",
    ),
    "balance_date_differs": Lesson(
        "data",
        "The balance sheet is from a different date than the last quarter the forecast starts "
        "after. Net debt and the other claims subtracted from enterprise value should be read "
        "on the date the cash flows are valued from, so a gap between the two dates can "
        "mismatch them.",
        "Koller, Goedhart and Wessels, Valuation (McKinsey & Company), from enterprise value "
        "to equity value",
    ),
    "shares_cover_differs": Lesson(
        "data",
        "The shares outstanding on the filing's cover page differ by more than "
        f"{_pct(math_engine.SHARES_TOLERANCE)} from the diluted share count in the income "
        "statement. Value per share is equity value divided by shares, so a buyback, a share "
        "issue or a split Warren missed moves it in proportion: check which count is current.",
        "Warren rule D4, shares (Build Plan); diluted shares as in ASC 260, Earnings per Share; "
        f"the {_pct(math_engine.SHARES_TOLERANCE)} line is a Warren working rule",
    ),
    "margin_quarter_two_bases": Lesson(
        "data",
        "One of the quarters the operating margin is averaged over divides figures on "
        "different footings: some as first reported, some as recast later (after a spin-off "
        "or a new accounting rule, for example). A margin built from mismatched figures can be "
        "too high or too low, and so can every forecast quarter that uses it.",
        _COMPARABILITY,
    ),
    "seed_year_two_bases": Lesson(
        "data",
        "The revenue quarters the forecast grows from are not all on the same footing: some "
        "as first reported, some as recast later. The forecast inherits the mix, so its "
        "starting point may match neither version of the company's results.",
        _COMPARABILITY,
    ),
    "run_mixes_meanings": Lesson(
        "data",
        "The XBRL tag behind revenue changed what it measures within the years this run reads, "
        "so some of its revenue figures count a different line from others. Growth, margins "
        "and shares worked out across the change compare unlike things, and Warren does not "
        "measure how much that moves the value.",
        _COMPARABILITY,
    ),
    "cost_of_debt_out_of_bounds": Lesson(
        "assumption",
        "The cost of debt, worked out as interest over average debt, came out outside "
        f"{_pct(math_engine.COST_OF_DEBT_BOUNDS[0])} to {_pct(math_engine.COST_OF_DEBT_BOUNDS[1])}"
        ". That usually means the interest or the debt figure is unusual (debt raised or "
        "repaid during the year, interest on items that are not debt), not that the company "
        "really borrows at that rate. Warren keeps the figure, so it feeds the WACC as is; a "
        "practitioner would check it against the yield on the company's bonds or its credit "
        "rating.",
        "Damodaran, Investment Valuation (3rd ed.), chapter 8 (cost of debt); the "
        f"{_pct(math_engine.COST_OF_DEBT_BOUNDS[0])} to "
        f"{_pct(math_engine.COST_OF_DEBT_BOUNDS[1])} range is a Warren working rule",
    ),
    "tax_rate_clipped": Lesson(
        "assumption",
        "The tax rate the company paid over the years the run reads (income tax over pretax "
        f"income) came out outside {_pct(math_engine.TAX_RATE_BOUNDS[0])} to "
        f"{_pct(math_engine.TAX_RATE_BOUNDS[1])}, so Warren held it at the nearest edge. Rates "
        "like that come from one-off items (a tax reform, a large loss, a settlement) that will "
        "not repeat every year; a practitioner would use a normalised or marginal rate.",
        "Damodaran, Investment Valuation (3rd ed.), chapter 10 (effective and marginal tax "
        f"rates); the {_pct(math_engine.TAX_RATE_BOUNDS[0])} to "
        f"{_pct(math_engine.TAX_RATE_BOUNDS[1])} range is a Warren working rule",
    ),
    "margin_outside_history": Lesson(
        "assumption",
        "A forecast quarter's operating margin is more than "
        f"{math_engine.MARGIN_SIGMAS} standard deviations away from the average of the last "
        f"{math_engine.HISTORY_QUARTERS} quarters. Margins tend to drift back toward their "
        "usual level, so a forecast far from history needs a reason (a new product, a cost "
        "programme); without one, an assumption is more likely wrong.",
        "Fama and French (2000), Forecasting Profitability and Earnings, Journal of Business "
        f"73(2); {math_engine.MARGIN_SIGMAS} standard deviations over "
        f"{math_engine.HISTORY_QUARTERS} quarters is a Warren working rule",
    ),
    "wacc_outside_its_parts": Lesson(
        "assumption",
        "The WACC set here lies outside the after-tax cost of debt and the cost of equity. A "
        "weighted average of two costs always sits between them, so this rate cannot be the "
        "company's average cost of capital: it is a rate chosen by hand, and the value "
        "reflects that choice.",
        "Brealey, Myers and Allen, Principles of Corporate Finance, the weighted-average cost "
        "of capital",
    ),
    "thin_terminal_spread": Lesson(
        "valuation",
        "WACC is less than "
        f"{math_engine.TERMINAL_SPREAD_WARNING * 100:g} points above terminal growth. The "
        "terminal value divides by that gap, so when it is small the value after the forecast "
        "years is most of the total, and a small change in either rate moves the value a lot. "
        "Read the value as a statement about those two rates more than about the forecast.",
        f"{_TERMINAL}; the {math_engine.TERMINAL_SPREAD_WARNING * 100:g}-point line is a "
        "Warren working rule",
    ),
    "thin_terminal_spread_at_erp_bound": Lesson(
        "valuation",
        "At one end of the equity risk premium's uncertainty band, WACC is less than "
        f"{math_engine.TERMINAL_SPREAD_WARNING * 100:g} points above terminal growth. The "
        "value at that end mostly shows how sensitive the terminal value is to the discount "
        "rate, so the width of the range says more about the formula than about the company.",
        f"{_TERMINAL}; the {math_engine.TERMINAL_SPREAD_WARNING * 100:g}-point line is a "
        "Warren working rule",
    ),
    "no_value_per_share": Lesson(
        "valuation",
        "At one end of the equity risk premium's uncertainty band the formula has no answer, "
        "most often because the discount rate falls to terminal growth or below: cash flows "
        "that grow at least as fast as they are discounted add up to no finite value. One end "
        "of the range is missing, a sign that the value is very sensitive to the premium.",
        f"Gordon (1962), The Investment, Financing, and Valuation of the Corporation; {_TERMINAL}",
    ),
    "erp_bounds_not_computed": Lesson(
        "valuation",
        "The WACC was set directly, so the equity risk premium no longer enters the discount "
        "rate and Warren cannot show how the value moves when the premium is a standard error "
        "higher or lower. The range that usually shows that uncertainty is missing, not zero.",
        "Damodaran, Equity Risk Premiums (ERP): Determinants, Estimation and Implications "
        "(annual update), the standard error of the historical premium",
    ),
}
