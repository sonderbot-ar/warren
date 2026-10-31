"""Words a reader sees for the analysis engine's codes, kept apart from the logic so reports can
later be translated (Decision 11, guardrail 5). Phase 1 is in English."""

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
