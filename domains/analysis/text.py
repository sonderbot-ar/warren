"""Words a reader sees for the analysis engine's codes, kept apart from the logic so reports can
later be translated (Decision 11, guardrail 5). Phase 1 is in English."""

import math
from dataclasses import dataclass

from domains.analysis import math_engine
from domains.analysis.coded import REFUSAL_GROUPS
from domains.market import erp

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
        "missing a filing, the company filed late, or it filed a late-filing notice by the next "
        "business day, which keeps the report on time if it arrives within {nt_10q} more "
        "calendar days for a quarterly report or {nt_10k} for an annual one: check the "
        "company's list of filings.",
        {
            "days": math_engine.STALE_AFTER.days,
            "days_q3": math_engine.STALE_AFTER_Q3.days,
            "deadline_10k": math_engine.DEADLINE_10K_DAYS,
            "deadline_10q": math_engine.DEADLINE_10Q_DAYS,
            "nt_10q": math_engine.NT_EXTENSION_10Q_DAYS,
            "nt_10k": math_engine.NT_EXTENSION_10K_DAYS,
        },
        "SEC Form 10-Q, General Instruction A.1, and Form 10-K, General Instruction A(2)(a) "
        "(large accelerated filers); Exchange Act Rule 0-3 (a deadline on a weekend or holiday "
        "moves to the next business day); Exchange Act Rule 12b-25(b) (Form NT 10-K and NT 10-Q, "
        "the late-filing notice)",
        f"both lines are working rules (math_engine.STALE_AFTER and STALE_AFTER_Q3): "
        f"{math_engine.STALE_AFTER.days} days is a {math_engine.QUARTER_DAYS}-day quarter plus "
        f"the {math_engine.DEADLINE_10Q_DAYS}-day 10-Q deadline plus "
        f"{math_engine.DEADLINE_SLACK_DAYS} days; {math_engine.STALE_AFTER_Q3.days} days is a "
        f"{math_engine.LONG_QUARTER_DAYS}-day fourth quarter (14 weeks, in a 53-week year) plus "
        f"the {math_engine.DEADLINE_10K_DAYS}-day 10-K deadline plus "
        f"{math_engine.DEADLINE_SLACK_DAYS} days; the late-filing notice's "
        f"{math_engine.NT_EXTENSION_10Q_DAYS} and {math_engine.NT_EXTENSION_10K_DAYS} extra days "
        "are not added to either line, so a run can warn about a report that is still on time",
    ),
    "newer_report_not_read": Lesson(
        "data",
        "A company files no report for its fourth quarter, so Warren works that quarter's revenue "
        "out as the year's revenue from the annual report minus the first three quarters, and "
        "reads every other quarter from its own report. Here a newer report is loaded but that "
        "revenue could not be read or worked out, so the run starts from an earlier quarter and "
        "is at least one report behind: check the revenue line in the report this warning names.",
        {},
        None,
        "Warren's own check (math_engine._last_actual_quarter): a figure for a period that ends "
        "after the newest quarter with revenue means a newer report is loaded; balances are not "
        "counted, since the cover page's share count is dated after its quarter",
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
    "debt_current_inside_short_term": Lesson(
        "data",
        "This company's short-term borrowings already include the part of its long-term debt "
        "due within a year (its total debt due within a year is closer to short-term borrowings "
        "alone than to the two added), so Warren counted that part once instead of adding it "
        "again from the debt note. Counted twice, it would overstate debt and working capital "
        "and understate the cost of debt, effects that partly offset each other, so the value "
        "per share moves much less than the debt.",
        {},
        "Koller, Goedhart and Wessels, Valuation (7th ed.), Moving from Enterprise Value to "
        "Value per Share (each debt claim counted once); US GAAP Taxonomy, ShortTermBorrowings "
        "and LongTermDebtCurrent; FASB ASC 470-10-45 (debt classified as current)",
        "rule D3, balance sheet (docs/build-plan.md); the check is Warren's own "
        "(math_engine.current_debt_inside, backlog #408)",
    ),
    "commercial_paper_beside_short_term": Lesson(
        "data",
        "This company lists its commercial paper (short IOUs sold to investors for a few "
        "weeks or months) as a line of its own beside its short-term bank loans, as its total "
        "debt due within a year shows, so Warren counted both; when a filing gives no such "
        "total, Warren assumes the paper is part of the loans. Left out, the paper would "
        "understate debt and working capital and, because Warren's cost of debt is interest "
        "divided by average debt, overstate the cost of debt.",
        {},
        "Koller, Goedhart and Wessels, Valuation (7th ed.), Moving from Enterprise Value to "
        "Value per Share (every debt claim counted) and Reorganizing the Financial Statements "
        "(short-term debt kept out of operating working capital); US GAAP Taxonomy, "
        "CommercialPaper, ShortTermBankLoansAndNotesPayable and DebtCurrent",
        "rule D3, balance sheet (docs/build-plan.md); the check is Warren's own "
        "(math_engine.paper_beside, backlog #412)",
    ),
    "debt_current_total_in_place": Lesson(
        "data",
        "On this balance sheet date the company filed only its total debt due within a year, "
        "not the pieces it adds up (debt due soon, bank loans, commercial paper), which come "
        "once a year in the annual report or were not yet filed in a form Warren reads, so "
        "Warren counted that total instead of older pieces from another date or none at all. "
        "A valuation needs only the sum of short-term debt, so the total costs detail, not "
        "accuracy, while old or missing pieces would misstate debt, working capital and the "
        "cost of debt.",
        {},
        "Koller, Goedhart and Wessels, Valuation (7th ed.), Moving from Enterprise Value to "
        "Value per Share (every debt claim counted, at the valuation date); Penman, Financial "
        "Statement Analysis and Security Valuation (5th ed.), the reformulated balance sheet "
        "(short-term debt as a financial obligation); US GAAP Taxonomy, DebtCurrent",
        "rule D3, balance sheet (docs/build-plan.md); the rule is Warren's own "
        "(math_engine.total_in_place, backlog #415)",
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
    "shares_scale_mismatch": Lesson(
        "data",
        "Two share counts for the company are about a thousand or a million times apart "
        "(within {tolerance}%), which no buyback does (splits are already adjusted for), so one "
        "was filed in the wrong unit (thousands or millions, with nothing saying so). Warren "
        "leaves that count out; used, it would put the market value and every per-share figure "
        "off by the same factor, so check any share count against the cover page before "
        "dividing by it.",
        {"tolerance": math_engine.SHARES_TOLERANCE},
        "SEC Office of Structured Disclosure, Scaling Errors Between Entity Common Stock Shares "
        "Outstanding and Common Stock Shares Outstanding (Nov 19, 2020)",
        "math_engine.share_scale (backlog #343); the 10% line is a working rule, "
        "math_engine.SHARES_TOLERANCE",
    ),
    "shares_not_positive": Lesson(
        "data",
        "A share count was filed as zero or below, which no listed company can have, so the "
        "figure is a filing error. Divided by, it would make the value per share infinite or "
        "meaningless, so Warren leaves that count out and divides by another count above zero; "
        "the shares assumption's source names which one.",
        {},
        None,
        "math_engine._shares (backlog #364)",
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
    "tax_rate_statutory": Lesson(
        "assumption",
        "The company's pretax income over the years the run reads added up to {floor}% of "
        "revenue or less, or to a loss, and a tax rate worked out on so little profit says "
        "nothing about the tax future profits will pay, so Warren uses the statutory corporate "
        "rate, the rate a profitable company pays on each extra dollar, as an analyst would. It "
        "simplifies three things: it is the US federal rate only (state taxes add a few "
        "percentage points), profits earned abroad pay other countries' rates, and a company "
        "coming out of losses can usually deduct them from later profits and pay less for a while.",
        {"floor": math_engine.PRETAX_MARGIN_FLOOR},
        "Damodaran, Investment Valuation (3rd ed.), chapter 10 (the tax effect, net operating "
        "losses); 26 U.S.C. §11(b) and §172; Koller, Goedhart and Wessels, Valuation (7th ed.)",
        "the 1% pretax-margin line is a working rule, math_engine.PRETAX_MARGIN_FLOOR",
    ),
    "tax_rate_loss_year_left_out": Lesson(
        "assumption",
        "In a year that ended in a loss the company books a tax benefit, a refund on the loss "
        "that depends on carrybacks and on what it expects to recover, which is not the rate its "
        "profits pay, so adding that year to the others mixes the two and Warren reads the tax "
        "rate from the profitable years only (when only one is left, the rate rests on that year "
        "alone, a thinner base). One thing is still left out: a company coming out of losses can "
        "usually deduct them from later profits and pay less tax for a while.",
        {},
        "Damodaran, Investment Valuation (3rd ed.), chapter 10 (the tax effect, net operating "
        "losses); 26 U.S.C. §172; Koller, Goedhart and Wessels, Valuation (7th ed.)",
        "a year with pretax income of zero or below is left out of the three-year tax rate",
    ),
    "tax_rate_outside_year_left_out": Lesson(
        "assumption",
        "In one of the years the run reads, the company made a profit but booked a tax rate "
        "outside {low}% to {high}% on it, which comes from a one-off (a tax reform's one-time "
        "charge on profits kept abroad or its revaluation of deferred taxes, a settlement with "
        "the tax authority, a write-off the law doesn't let it deduct) rather than the rate its "
        "profits pay, so Warren reads the tax rate from the other years, unless every profitable "
        "year is that far out. An analyst would remove only the one-off item and keep the year, "
        "but filings don't tag those items reliably, so Warren drops the whole year; it is a "
        "screen, not a cure, since a smaller one-off that leaves a year inside the range stays "
        "in, and when only one year is left the rate rests on that year alone, a thinner base.",
        {"low": math_engine.TAX_RATE_BOUNDS[0], "high": math_engine.TAX_RATE_BOUNDS[1]},
        "Koller, Goedhart and Wessels, Valuation (7th ed., 2020), ch. 20 (taxes) and ch. 21 "
        "(nonoperating items); Damodaran, Investment Valuation (3rd ed.), chapter 10 (the tax "
        "effect); Pub. L. 115-97 (the 2017 US tax reform)",
        "the 0% to 50% range a profitable year's own rate must fall in is a working rule, "
        "math_engine.TAX_RATE_BOUNDS, left out unless every profitable year is outside it",
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


# A lesson per refusal group, and per refusal code where the group's lesson isn't enough
# (backlog #382): why Warren refuses, why a real company or date can hit it, and what the
# student can do next. Same `Lesson` as the run warnings; its `group` is the refusal group
# (`coded.REFUSAL_GROUPS`), and `refusal_lesson(code)` picks the code's own lesson or its group's.
_POINT_IN_TIME = "point-in-time data (Structure Guide, Decision 7)"
_CURRENT_ASSETS = (
    "AICPA Accounting Research Bulletin No. 43, chapter 3A, paragraph 4 (current assets include "
    "cash and marketable securities held as a resource for current operations; now FASB ASC "
    "210-10-45-1)"
)
_ELEMENTS = (
    "FASB Concepts Statement No. 8, chapter 4 (December 2021; the definitions of an asset and a "
    "liability, replacing Concepts Statement No. 6)"
)
_INCONSISTENT_RULE = (
    "Warren's checks on the balance sheet it reads (math_engine, the balance sheet step); the "
    "app links the filing so the figure can be seen"
)

REFUSAL_GROUP_LESSONS = {
    "later_date": Lesson(
        "later_date",
        "Warren builds an estimate only from what was public on its date, and a forecast needs "
        "a few years of reports and market prices behind it. On an early date that history is "
        "too short, so a later date, when more of it has been published, will work.",
        {},
        None,
        f"{_POINT_IN_TIME}; the history each input needs (math_engine.build_inputs)",
    ),
    "earlier_date": Lesson(
        "earlier_date",
        "Warren uses only days that have ended in New York and whose market prices it has "
        "already downloaded, so that nothing in an estimate comes from after its date. The "
        "newest day it can use is a little behind today: pick that day or an earlier one.",
        {},
        None,
        f"{_POINT_IN_TIME}; the day-end rule (shared_kernel.calendar)",
    ),
    "company_data": Lesson(
        "company_data",
        "The company's reports up to this date leave out a figure the forecast needs, or give "
        "one it can't divide by, such as revenue of zero. Real filings have gaps like this (a "
        "line filed under a name Warren doesn't read, a quarter never reported on its own), so "
        "another date or another company usually works.",
        {},
        None,
        "the concept map, domains/fundamentals/concept_map.csv (Structure Guide, Decision 2), "
        "and the figures each input needs (math_engine.build_inputs)",
    ),
    "inconsistent_data": Lesson(
        "inconsistent_data",
        "Some facts about a balance sheet hold for every company: a balance the company holds "
        "or owes can't be below zero, and cash and short-term securities are part of current "
        "assets, so together they can't be larger than them. When a figure Warren read breaks "
        "one of these, it most likely belongs to a different measure, through the line Warren "
        "chose to read or the way the figure was tagged in the filing's data, so Warren refuses "
        "rather than value the company on it: open the report to compare its balance sheet, or "
        "try another date.",
        {},
        f"{_ELEMENTS}; {_CURRENT_ASSETS}",
        _INCONSISTENT_RULE,
    ),
    "no_value": Lesson(
        "no_value",
        "A DCF's terminal value adds up cash flows that grow forever, and that sum has a value "
        "only while the cost of capital is above zero and long-term growth stays below it; the "
        "familiar formula, next year's cash flow divided by the cost of capital minus growth, "
        "gives that sum. With the assumptions Warren reads from the data on this date one of "
        "those conditions fails, so the model has no value to show.",
        {},
        _GORDON,
        None,
    ),
    "setup": Lesson(
        "setup",
        "Warren's own data for this estimate isn't there yet: a company's filings, its market "
        "prices, the Treasury rate, or a country's tax rate in Warren's table of tax laws. This "
        "doesn't depend on the student or the company; whoever runs Warren has to load or add it.",
        {},
        None,
        "Warren's data loads (the fundamentals ingest and the market load) and its table of "
        "statutory tax rates, which come before any estimate",
    ),
}

# The annual standard deviation of stock returns, rounded to 20% as Damodaran does, standing in
# for the premium's own (about 21%, his footnote 68); returns assumed uncorrelated year to year.
_ERP_SD = 0.2
_ERP_SE = _ERP_SD / math.sqrt(erp.MIN_YEARS)

REFUSAL_LESSONS = {
    "balance_item_negative": Lesson(
        "inconsistent_data",
        "Each balance sheet line Warren reads (cash, securities, current assets and "
        "liabilities, debt) is an amount the company holds or owes, so none can be below zero. "
        "A negative one most likely means a change or an adjustment was tagged as the balance, "
        "or Warren read a line meant for something else, so Warren refuses rather than guess "
        "which number was meant: open the report to compare, or try another date.",
        {},
        _ELEMENTS,
        _INCONSISTENT_RULE,
    ),
    "securities_exceed_current_assets": Lesson(
        "inconsistent_data",
        "Short-term securities, and cash with them, are part of current assets, so together "
        "they can't be larger than current assets. When they are, a figure Warren read most "
        "likely holds a different measure (a total that also counts long-term holdings or "
        "restricted cash), or comes from an older balance sheet than the current assets it is "
        "set against. Warren refuses rather than count cash the company may not have: open the "
        "report to compare, or try another date.",
        {},
        _CURRENT_ASSETS,
        _INCONSISTENT_RULE,
    ),
    "erp_too_few_years": Lesson(
        "later_date",
        "Warren estimates how much more stocks earn than government bonds as the average of "
        "past years, and needs at least {min_years} full years of it. Stock returns swing by "
        "about {sd}% from year to year, so a {min_years}-year average has a standard error of "
        "about {se} percentage points, and the true premium could plausibly be {two_se} points "
        "higher or lower; a shorter window would be noisier still. A later date adds years, "
        "and the refusal names the first date with enough of them.",
        {
            "min_years": erp.MIN_YEARS,
            "sd": _ERP_SD,
            "se": round(_ERP_SE, 2),
            "two_se": round(2 * _ERP_SE, 2),
        },
        "Damodaran (2022), Equity Risk Premiums (ERP): Determinants, Estimation and "
        "Implications, The 2022 Edition, Table 2 (standard errors in historical risk "
        "premiums: 20% over the square root of the years)",
        f"the {erp.MIN_YEARS}-year minimum is a working rule, domains/market/erp.py MIN_YEARS",
    ),
}


def refusal_lesson(code: str) -> Lesson:
    """The lesson for a refusal code: its own when it has one, otherwise its group's."""
    return REFUSAL_LESSONS.get(code) or REFUSAL_GROUP_LESSONS[REFUSAL_GROUPS[code]]
