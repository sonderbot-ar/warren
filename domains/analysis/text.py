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
# English; the app writes its own words for each code from the same params. Groups are codes,
# in the order a screen reads them.
WARNING_GROUPS = {
    "data": "The figures the run reads",
    "assumption": "An assumption outside its usual range",
    "valuation": "How far to trust the value",
}


@dataclass(frozen=True)
class Lesson:
    """Why one kind of run warning matters, for a student.

    `why` is one or two sentences, with {name} placeholders for `params`: the thresholds are
    Warren's constants, so a translation fills them from the same numbers. A float param is a
    fraction (0.1 for 10%, 0.03 for 3 percentage points); the English shows it times 100 and
    writes the unit itself. An int param is a count. `reference` is a published source, or
    None; `warren_rule` says where a rule or threshold of Warren's own is written, or None. At
    least one is set, so a Warren threshold is never passed off as a textbook law."""

    group: str
    why: str
    params: dict
    reference: str | None
    warren_rule: str | None

    def text(self) -> str:
        """The English sentence with its numbers filled in."""
        shown = {k: f"{v * 100:g}" if isinstance(v, float) else v for k, v in self.params.items()}
        return self.why.format(**shown)

    def source(self) -> str:
        """The reference and the Warren rule in one line, for the engine's own reports."""
        return "; ".join(s for s in (self.reference, self.warren_rule) if s)


_COMPARABILITY = "FASB Concepts Statement No. 8, chapter 3 (comparability)"
_TERMINAL = "Damodaran, Investment Valuation (3rd ed.), chapter 12 (terminal value)"
_GORDON = (
    "Gordon and Shapiro (1956), Capital Equipment Analysis: The Required Rate of Profit, "
    "Management Science 3(1); Gordon (1962), The Investment, Financing, and Valuation of the "
    f"Corporation; {_TERMINAL}"
)
_SPREAD = {"spread": math_engine.TERMINAL_SPREAD_WARNING}
_SPREAD_RULE = "the 3-point line is a working rule, math_engine.TERMINAL_SPREAD_WARNING (#84)"

WARNING_LESSONS = {
    "beyond_history": Lesson(
        "data",
        "Warren's copy of this company's filings stops before the run's date (for example, "
        "when the company moved its reporting to a new parent company), so the run is built on "
        "older figures than its date suggests. Check what the company reported after that "
        "before relying on the value.",
        {},
        None,
        "the coverage note in domains/fundamentals/universe.csv; point-in-time data "
        "(Structure Guide, Decision 7)",
    ),
    "data_warning": Lesson(
        "data",
        "Something unusual came up while reading the filings that Warren has no specific "
        "warning for. Read the line itself and check the figure it names in the filing before "
        "relying on the value.",
        {},
        None,
        "any other warning raised while reading the facts (math_engine, the fundamentals "
        "query); none is expected (backlog #172)",
    ),
    "concept_map_changed": Lesson(
        "data",
        "Warren's list of which reported item counts as revenue, debt, capex and the other "
        "lines changed after this company's filings were loaded. This value may differ "
        "slightly from a new run made today.",
        {},
        None,
        "the concept map, domains/fundamentals/concept_map.csv (Structure Guide, Decision 2)",
    ),
    "fundamentals_stale": Lesson(
        "data",
        "The newest quarter the run uses ended more than {days} days before the run's date "
        "({days_q3} after a third quarter, because no quarterly report is filed for the fourth "
        "quarter and the annual report that covers it is due {deadline_10k} days after the year "
        "ends, not {deadline_10q}), so the next report should already be out. Warren may be "
        "missing a filing, or the company filed late: check the company's list of filings.",
        {
            "days": math_engine.STALE_AFTER.days,
            "days_q3": math_engine.STALE_AFTER_Q3.days,
            "deadline_10k": math_engine.DEADLINE_10K_DAYS,
            "deadline_10q": math_engine.DEADLINE_10Q_DAYS,
        },
        "SEC Form 10-Q, General Instruction A.1, and Form 10-K, General Instruction A(2)(a) "
        "(large accelerated filers); Exchange Act Rule 0-3 (a deadline on a weekend or holiday "
        "moves to the next business day)",
        f"both lines are working rules (math_engine.STALE_AFTER and STALE_AFTER_Q3): "
        f"{math_engine.STALE_AFTER.days} days is a {math_engine.QUARTER_DAYS}-day quarter plus "
        f"the {math_engine.DEADLINE_10Q_DAYS}-day 10-Q deadline plus "
        f"{math_engine.DEADLINE_SLACK_DAYS} days; {math_engine.STALE_AFTER_Q3.days} days is a "
        f"{math_engine.LONG_QUARTER_DAYS}-day fourth quarter (14 weeks, in a 53-week year) plus "
        f"the {math_engine.DEADLINE_10K_DAYS}-day 10-K deadline plus "
        f"{math_engine.DEADLINE_SLACK_DAYS} days",
    ),
    "balance_carried_forward": Lesson(
        "data",
        "An item was missing from the newest balance sheet, so Warren took it from an earlier "
        "one, up to a year old. If the item changed since (new debt, a large cash move), the "
        "step from enterprise value to equity value, and so the value per share, is off by "
        "that change.",
        {},
        None,
        "rule D3, balance sheet (docs/build-plan.md)",
    ),
    "balance_counted_zero": Lesson(
        "data",
        "An item was not found within a year of the balance sheet, so Warren counted it as "
        "zero: either the company has none, or it reports the item under a name Warren does not "
        "read. A missing debt item makes the value per share too high, a missing cash or "
        "investment item makes it too low.",
        {},
        None,
        "rule D3, balance sheet (docs/build-plan.md)",
    ),
    "balance_date_differs": Lesson(
        "data",
        "The balance sheet Warren takes net debt from is dated differently from the last "
        "quarter the forecast starts from. Net debt and the other claims subtracted from "
        "enterprise value should match the date the cash flows start from, so the gap can mix "
        "figures from two dates.",
        {},
        "Koller, Goedhart and Wessels, Valuation (7th ed.), Moving from Enterprise Value to "
        "Value per Share",
        "rule D3, balance sheet (docs/build-plan.md)",
    ),
    "shares_cover_differs": Lesson(
        "data",
        "The shares outstanding on the filing's cover page, which Warren divides by, differ by "
        "more than {tolerance}% from the diluted share count. Some gap is normal (diluted "
        "shares are a period's average and include options), but a large one usually means a "
        "buyback, a share issue or a figure filed in the wrong unit: check which count is "
        "current.",
        {"tolerance": math_engine.SHARES_TOLERANCE},
        "FASB ASC 260, Earnings per Share (diluted shares)",
        "rule D4, shares (docs/build-plan.md); the 10% line is a working rule, "
        "math_engine.SHARES_TOLERANCE",
    ),
    "margin_quarter_two_bases": Lesson(
        "data",
        "In one of the quarters the operating margin is averaged over, the figures do not all "
        "follow the same criteria: some are as first published, some were changed later by a "
        "newer filing. A margin built from them can be too high or too low, and so can every "
        "forecast quarter that uses it.",
        {},
        _COMPARABILITY,
        "backlog #279 (math_engine, the quarterly margin method)",
    ),
    "seed_year_two_bases": Lesson(
        "data",
        "The revenue quarters the forecast grows from do not all follow the same criteria: "
        "some are as first published, some were changed later by a newer filing. The forecast "
        "inherits the mix, so its starting point may match neither version of the company's "
        "results.",
        {},
        _COMPARABILITY,
        "backlog #279 (math_engine, the seed quarters)",
    ),
    "run_mixes_meanings": Lesson(
        "data",
        "The revenue figure does not include the same things in every year this run reads: "
        "the company changed what it reports under that figure. Growth, margins and each "
        "quarter's share of the year worked out across the change compare unlike things, and "
        "Warren does not measure how much that moves the value.",
        {},
        _COMPARABILITY,
        "backlog #297 (facts.tag_meaning_changes)",
    ),
    "cost_of_debt_out_of_bounds": Lesson(
        "assumption",
        "The cost of debt, worked out as interest over average debt, came out outside {low}% "
        "to {high}%, which usually means the interest or the debt figure is unusual (debt "
        "raised or repaid during the year, interest on items that are not debt). Warren still "
        "uses it in the WACC, so an analyst would compare it with the yield on the company's "
        "bonds or its credit rating.",
        {"low": math_engine.COST_OF_DEBT_BOUNDS[0], "high": math_engine.COST_OF_DEBT_BOUNDS[1]},
        "Damodaran, Investment Valuation (3rd ed.), chapter 8 (the cost of debt)",
        "the 0% to 15% range is a working rule, math_engine.COST_OF_DEBT_BOUNDS",
    ),
    "tax_rate_clipped": Lesson(
        "assumption",
        "The tax rate the company booked over the years the run reads (tax expense over "
        "pretax income) came out outside {low}% to {high}%, so Warren replaced it with the nearest "
        "limit. Rates like that come from one-off items (a tax reform, a large loss, a "
        "settlement) that will not repeat every year, so an analyst would use a normal or "
        "marginal rate.",
        {"low": math_engine.TAX_RATE_BOUNDS[0], "high": math_engine.TAX_RATE_BOUNDS[1]},
        "Damodaran, Investment Valuation (3rd ed.), chapter 10 (the tax effect)",
        "the 0% to 50% range is a working rule, math_engine.TAX_RATE_BOUNDS",
    ),
    "margin_outside_history": Lesson(
        "assumption",
        "A forecast quarter's operating margin is more than {sigmas} standard deviations away "
        "from the average of up to {quarters} past quarters. Profit margins tend to drift back "
        "toward their usual level, so a forecast far from history needs a reason (a new "
        "product, a cost programme); without one, an assumption is more likely wrong.",
        {"sigmas": math_engine.MARGIN_SIGMAS, "quarters": math_engine.HISTORY_QUARTERS},
        "Nissim and Penman (2001), Ratio Analysis and Equity Valuation, Review of Accounting "
        "Studies 6; Fama and French (2000), Forecasting Profitability and Earnings, Journal of "
        "Business 73(2)",
        "2 standard deviations over 12 quarters is a working rule, math_engine.MARGIN_SIGMAS",
    ),
    "wacc_outside_its_parts": Lesson(
        "assumption",
        "The WACC set here lies outside the after-tax cost of debt and the cost of equity. A "
        "weighted average of two costs always sits between them, so this rate is not the "
        "company's average cost of capital but a rate chosen by hand, and the value reflects "
        "that choice.",
        {},
        "Brealey, Myers and Allen, Principles of Corporate Finance, the weighted-average cost "
        "of capital",
        None,
    ),
    "thin_terminal_spread": Lesson(
        "valuation",
        "WACC is less than {spread} percentage points above terminal growth, and the terminal "
        "value divides by that gap, so the years after the forecast make up most of the value "
        "and a small change in either rate moves it a lot. The value depends more on those two "
        "rates than on the forecast.",
        _SPREAD,
        _TERMINAL,
        _SPREAD_RULE,
    ),
    "thin_terminal_spread_at_erp_bound": Lesson(
        "valuation",
        "When Warren moves the equity risk premium up or down to show a range, at one end WACC "
        "is less than {spread} percentage points above terminal growth. The value at that end "
        "mostly shows how sensitive the terminal value is to the discount rate, so the width "
        "of the range says more about the formula than about the company.",
        _SPREAD,
        _TERMINAL,
        _SPREAD_RULE,
    ),
    "no_value_per_share": Lesson(
        "valuation",
        "When Warren moves the equity risk premium up or down to show a range, at one end the "
        "formula has no answer, most often because the discount rate falls to terminal growth "
        "or below: cash flows that grow at least as fast as they are discounted add up to no "
        "finite value. One end of the range is missing, a sign that the value is very "
        "sensitive to the premium.",
        {},
        _GORDON,
        None,
    ),
    "erp_bounds_not_computed": Lesson(
        "valuation",
        "The WACC was set directly, so the equity risk premium no longer enters it, and Warren "
        "cannot show the range it usually gives by moving the premium up and down. That range "
        "is missing, not zero: the premium's uncertainty is still there.",
        {},
        "Damodaran, Equity Risk Premiums (ERP): Determinants, Estimation and Implications "
        "(annual update), the standard error of the historical premium",
        None,
    ),
}
