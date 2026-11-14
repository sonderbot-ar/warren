"""A gap, note or warning as a stable code with parameters (front-end design principle "no text
hard-coded in logic"): the app owns the words; `text` is the English fallback."""

import warnings
from dataclasses import dataclass

from shared_kernel.data_warnings import DataWarning


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
        "newer_report_not_read",
        "balance_carried_forward",
        "balance_counted_zero",
        "balance_date_differs",
        "shares_cover_differs",
        "shares_scale_mismatch",
        "shares_not_positive",
        "cost_of_debt_out_of_bounds",
        "tax_rate_clipped",
        "margin_outside_history",
        "margin_quarter_two_bases",
        "seed_year_two_bases",
        "run_mixes_meanings",
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

# Every code a refused simulation can carry (backlog #212, `montecarlo.SimulationError.code`); a
# refusal without a code is text only. The app's text catalogue covers this set too.
SIMULATION_REFUSAL_CODES = frozenset({"wacc_set_with_risk_premium_shock"})

# Every code a refused run can carry (backlog #376): `math_engine.EngineError.code` and
# `market.store.MarketDataError.code`, raised on the way from a company and a date to a baseline
# run (`build_inputs`). A refusal without a code is text only: it can't be reached by picking a
# company and a date. The app's text catalogue covers this set too.
# What the student can do about each refusal, in the order a screen groups them (professor and
# product lead, #376 review): `later_date` and `earlier_date` (pick another date), `company_data`
# (the company's filings lack a figure: try another date or company), `inconsistent_data` (the
# filed figures break an accounting identity) and `setup` (Warren's own data isn't ready; never
# the student's doing).
REFUSAL_GROUPS = {
    "as_of_too_early": "later_date",
    "no_quarterly_revenue": "later_date",
    "history_too_short": "later_date",
    "too_few_comparatives": "later_date",
    "too_few_quarters": "later_date",
    "no_price_on_date": "later_date",
    "too_few_return_weeks": "later_date",
    "erp_too_few_years": "later_date",
    "as_of_in_future": "earlier_date",
    "market_data_not_refreshed": "earlier_date",
    "seed_quarter_not_reported": "company_data",
    "flow_item_not_reported": "company_data",
    "no_balance_sheet": "company_data",
    "balance_item_not_reported": "company_data",
    "no_share_count": "company_data",
    "no_interest_with_debt": "company_data",
    "balance_item_negative": "inconsistent_data",
    "securities_exceed_current_assets": "inconsistent_data",
    "company_not_ingested": "setup",
    "no_ingest_run": "setup",
    "market_data_not_loaded": "setup",
    "no_risk_free_rate": "setup",
    "market_year_end_missing": "setup",
}
REFUSAL_GROUP_ORDER = ("later_date", "earlier_date", "company_data", "inconsistent_data", "setup")
ENGINE_REFUSAL_CODES = frozenset(REFUSAL_GROUPS)


def refusal(exc: BaseException) -> Coded | None:
    """Why a run or a simulation was refused, as a code with params (backlog #376): any exception
    with a `code` (`EngineError`, `MarketDataError`, `SimulationError`); None when it has none,
    and the app shows its generic sentence."""
    code = getattr(exc, "code", None)
    if code is None:
        return None
    return Coded(code, dict(getattr(exc, "params", {}) or {}), str(exc))


def coded_warnings(caught) -> list[Coded]:
    """Warren's own data warnings caught while reading facts, one per text (the first one's
    params): the fundamentals coverage warning as `beyond_history` with its fields, any other
    `DataWarning` as `data_warning` with its text only. Any other warning (a library's) is not a
    note: `pass_on` hands it back to the log (backlog #196)."""
    from domains.fundamentals.universe import CoverageWarning

    out: dict[str, Coded] = {}
    for w in caught:
        text = str(w.message)
        if text in out or not isinstance(w.message, DataWarning):
            continue
        if isinstance(w.message, CoverageWarning):
            out[text] = Coded("beyond_history", dict(w.message.fields), text)
        else:
            out[text] = Coded("data_warning", {}, text)
    return list(out.values())


def pass_on(caught) -> None:
    """Warn again, after the recording block, with every caught warning that is not Warren's own
    data warning (backlog #196): it reaches the log and the tests as if never caught, and is
    never stored as a run's note."""
    for w in caught:
        if not isinstance(w.message, DataWarning):
            warnings.warn_explicit(w.message, w.category, w.filename, w.lineno, source=w.source)
