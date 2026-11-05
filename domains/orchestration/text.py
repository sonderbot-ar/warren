"""Words a reader sees in the pipeline report, kept apart from the code that fills them in, so the
report can later be translated (Decision 11, guardrail 5). Phase 1 is in English."""

TRACE_MARKER = "<!-- trace: below this line comes from the telemetry file, not the database -->"

RANGE = (
    "p10, p50 and p90 are the low, middle and high of the values the shocks allow: 10,000 "
    "draws of each shock's size, valued one by one. They are not a forecast of the share price, "
    "and the baseline's own drivers are not sampled, so the true uncertainty is wider."
)
VARIANTS = {
    "named": "**named**: the model read the headlines with the company's name and the dates",
    "masked": (
        "**masked**: the same headlines with the name, ticker and dates hidden, so the model "
        "leans less on what it may remember happened next (it reduces that leak, it can't "
        "remove it)"
    ),
}
SAME_SEED = (
    "Every variant uses the pipeline's one seed, so their ranges differ only by their shocks."
)

NO_SHOCK = {
    "no_events": "no news event in the window had two or more sources",
    "no_impact": "the model found no material impact",
    "failed": "the model gave no valid proposal after three tries",
    "rejected": "every proposal was rejected in review",
    "unreviewed": "the proposals were not reviewed",
}
NO_SHOCK_LINE = "No shock: {why}. The value is the baseline's."

HINDSIGHT = (
    "reviewed by a person on {when}, after the as-of date: they may have known what happened next"
)
INHERITED = "reviewed before this pipeline started ({when}), so the earlier verdict stands"

DRIVER_UNITS = {"risk_premium": "bp"}
LINE_LABELS = {"revenue": "Revenue", "ebit": "Operating income (EBIT)", "fcff": "Free cash flow"}

HINDSIGHT_HEADING = "6. Forecast against what was reported"
HINDSIGHT_INTRO = (
    "Hindsight, for comparison only: nothing below fed the forecast. Each forecast quarter "
    "beside its value as first reported (the number in the first 10-Q or 10-K that reported it, "
    "not a later restatement), from the filings public by {actuals_on}. Revenue misses are in % "
    "of the actual; EBIT misses are in points of margin (the gap over actual revenue). A positive "
    "miss means the forecast was too high. Warren's error ruler (M3) measured quarters 1 to 4 "
    "only; quarters 5 to 8 are shown but were never scored."
)
HINDSIGHT_NONE = "No forecast quarter was in a 10-Q or 10-K by {actuals_on}."
