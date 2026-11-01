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
