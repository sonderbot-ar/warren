"""A gap, note or warning as a stable code with parameters (front-end design principle "no text
hard-coded in logic"): the app owns the words; `text` is the English fallback."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Coded:
    """A gap, note or warning as a stable code with parameters; `text` is an English fallback."""

    code: str
    params: dict
    text: str


# Every code a run's notes can carry (backlog #172): build warnings, post-checks, missing bounds,
# and `note_text` for a stored line without one. The app's text catalogue covers this set.
RUN_NOTE_CODES = frozenset(
    {
        "beyond_history",
        "data_warning",
        "concept_map_changed",
        "fundamentals_stale",
        "balance_carried_forward",
        "balance_counted_zero",
        "balance_date_differs",
        "shares_cover_differs",
        "cost_of_debt_out_of_bounds",
        "tax_rate_clipped",
        "margin_outside_history",
        "thin_terminal_spread",
        "thin_terminal_spread_at_erp_bound",
        "no_value_per_share",
        "erp_bounds_not_computed",
        "wacc_outside_its_parts",
        "note_text",
    }
)

# Every code a run's simulation list can carry (backlog #201,
# `domains.orchestration.simulations`); the app's text catalogue covers this set too.
SIMULATION_NOTE_CODES = frozenset(
    {"pipeline_variant_differs", "shock_not_traced", "sized_elsewhere"}
)


def coded_warnings(caught) -> list[Coded]:
    """Warnings caught while reading facts, one per text (the first one's params): the
    fundamentals coverage warning as `beyond_history` with its fields, anything else as
    `data_warning` with its text only."""
    from domains.fundamentals.universe import CoverageWarning

    out: dict[str, Coded] = {}
    for w in caught:
        text = str(w.message)
        if text in out:
            continue
        if isinstance(w.message, CoverageWarning):
            out[text] = Coded("beyond_history", dict(w.message.fields), text)
        else:
            out[text] = Coded("data_warning", {}, text)
    return list(out.values())
