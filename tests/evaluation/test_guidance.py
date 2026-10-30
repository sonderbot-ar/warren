"""Company guidance turned into shocks by code, and the with_shocks variant (M4 Step 4)."""

from datetime import date

import pytest

from domains.analysis.runs import load_assumptions
from domains.evaluation import guidance
from domains.evaluation.guidance import GuidanceError, Guide
from domains.evaluation.harness import evaluate_case, run_batch
from tests.evaluation.conftest import CHOICES
from tests.evaluation.test_harness import TODAY, case, evaluate

ACCN = "0000000123-19-000099"


def guide(**fields) -> Guide:
    values = {
        "case_id": "TST_2019-06-30",
        "guide_id": "g1",
        "item": "revenue",
        "basis": "amount",
        "fiscal_year": 2019,
        "first_quarter": 2,
        "last_quarter": 2,
        "old_low": 100.0,
        "old_high": 110.0,
        "new_low": 90.0,
        "new_high": 100.0,
        "source_date": date(2019, 6, 28),
        "accession": ACCN,
        "quote": "revenue of $90 to $100 million, previously $100 to $110 million",
    }
    return Guide(**values | fields)


def run_rows(company):
    run_id, _ = evaluate(company)
    return load_assumptions(company, run_id)


def growth(rows, period):
    return next(a.value for a in rows if a.name == "revenue_growth" and a.period == period)


def test_a_revenue_revision_becomes_a_level_change_scaled_to_growth(company):
    rows = run_rows(company)
    [shock] = guidance.to_shocks([guide()], rows)
    # Δlevel 95 / 105 − 1; the growth shock that moves the level by Δ is Δ × (1 + g), in points
    level = 95 / 105 - 1
    g = growth(rows, "FY2019Q2")
    assert shock.driver == "revenue_growth" and shock.start_period == 1 and shock.horizon == 1
    assert shock.base == pytest.approx(100 * level * (1 + g))
    assert shock.low == pytest.approx(100 * (90 / 105 - 1) * (1 + g))
    assert shock.high == pytest.approx(100 * (100 / 105 - 1) * (1 + g))
    assert shock.source == "computed" and ACCN in shock.rationale


def test_operating_income_guidance_is_a_margin_change_not_counted_twice(company):
    # Microsoft's fiscal Q4 2022 table: revenue 52.4–53.2 → 51.94–52.74, income mids 21.25 → 20.95;
    # the margin moves 20.95 / 52.34 − 21.25 / 52.80 = −0.22 points (not −0.30 / 52.34 = −0.57)
    rev = guide(old_low=52.4, old_high=53.2, new_low=51.94, new_high=52.74,
                quote="revenue 51.94 to 52.74, was 52.4 to 53.2")  # fmt: skip
    inc = guide(item="operating_income", old_low=21.0, old_high=21.5, new_low=20.7, new_high=21.2,
                quote="operating income 20.7 to 21.2, was 21.0 to 21.5")  # fmt: skip
    shocks = guidance.to_shocks([rev, inc], run_rows(company))
    margin = next(s for s in shocks if s.driver == "operating_margin")
    assert margin.base == pytest.approx(100 * (20.95 / 52.34 - 21.25 / 52.80))
    assert margin.base == pytest.approx(-0.22, abs=0.005)


def test_a_full_year_guide_lands_on_the_unreported_quarters_only(company):
    rows = run_rows(company)
    q1 = next(a.value for a in rows if a.period == "FY2019Q1" and a.name in
              ("revenue_seed", "history:revenue"))  # fmt: skip
    full = guide(first_quarter=1, last_quarter=4, old_low=2000, old_high=2000, new_low=1900,
                 new_high=1900, quote="year revenue about $1,900m, was $2,000m")  # fmt: skip
    shocks = guidance.to_shocks([full], rows)
    assert [s.start_period for s in shocks] == [1, 2, 3]  # Q2–Q4; Q1 is already reported
    level = (1900e6 - q1) / (2000e6 - q1) - 1
    assert shocks[0].base == pytest.approx(100 * level * (1 + growth(rows, "FY2019Q2")))


def test_a_growth_guide_becomes_an_amount_on_the_prior_year(company):
    rows = run_rows(company)
    rate = guide(basis="growth", old_low=8, old_high=8, new_low=5, new_high=5,
                 quote="sales growth of about 5%, was about 8%")  # fmt: skip
    [shock] = guidance.to_shocks([rate], rows)
    assert shock.base == pytest.approx(100 * (1.05 / 1.08 - 1) * (1 + growth(rows, "FY2019Q2")))
    assert shock.low == shock.base == shock.high  # a point guide: the range is empty


def test_a_margin_guide_over_partly_reported_quarters_is_not_used(company):
    margin = guide(item="operating_margin", basis="margin", first_quarter=1, last_quarter=4,
                   old_low=20, old_high=21, new_low=19, new_high=19,
                   quote="margin of 19%, was 20% to 21%")  # fmt: skip
    with pytest.raises(GuidanceError, match="partly reported"):
        guidance.to_shocks([margin], run_rows(company))


def test_a_guide_in_billions_is_the_same_guide_in_millions(company):
    rows = run_rows(company)
    [millions] = guidance.to_shocks([guide()], rows)
    billions = guide(unit="billions", old_low=0.1, old_high=0.11, new_low=0.09, new_high=0.1,
                     quote="revenue $0.09 to $0.1 billion, was $0.1 to $0.11")  # fmt: skip
    [shock] = guidance.to_shocks([billions], rows)
    assert (shock.low, shock.base, shock.high) == pytest.approx(
        (millions.low, millions.base, millions.high)
    )


def test_only_amounts_take_a_unit():
    with pytest.raises(ValueError, match="only amounts"):
        guide(basis="growth", unit="billions")


def test_operating_income_in_another_unit_than_revenue_is_refused(company):
    income = guide(item="operating_income", unit="billions", old_low=0.02, old_high=0.02,
                   new_low=0.01, new_high=0.01, quote="income 0.01, was 0.02")  # fmt: skip
    with pytest.raises(GuidanceError, match="same unit"):
        guidance.to_shocks([guide(), income], run_rows(company))


def _write(path, **fields):
    row = guide(**fields).model_dump()
    cols = guidance.FIELDS + list(guidance.OPTIONAL)
    values = ",".join(f'"{"" if row[f] is None else row[f]}"' for f in cols)
    path.write_text(",".join(cols) + "\n" + values + "\n")


def test_an_old_guide_from_an_earlier_release_is_read_in_its_own_quote(tmp_path):
    path = tmp_path / "guidance.csv"
    old = "0000000123-19-000001"
    _write(path, quote="now $90 to $100 million", old_accession=old,
           old_quote="revenue of $100 to $110 million")  # fmt: skip
    [loaded] = guidance.load_guides(path)
    assert loaded.old_accession == old
    _write(path, quote="now $90 to $100 million, was $100 to $110", old_accession=old,
           old_quote="revenue of $100 to $111 million")  # fmt: skip
    with pytest.raises(GuidanceError, match="old_high"):
        guidance.load_guides(path)


def test_old_quote_needs_its_accession():
    with pytest.raises(ValueError, match="go together"):
        guide(old_quote="revenue of $100 to $110 million")


def test_a_dash_percentage_reads_as_zero_but_a_negative_does_not():
    assert guidance._numbers("FY 2019 (Estimate) -% to +1%") >= {0, 1}
    assert guidance._numbers("(-1)% to 1%") == {-1, 1}
    assert 0 not in guidance._numbers("(-1)% to 1%")


def test_the_checked_in_guidance_parses():
    guides = guidance.load_guides()
    assert guides and all(g.source_date <= date.fromisoformat(g.case_id[-10:]) for g in guides)


def test_every_figure_must_be_in_its_quote(tmp_path):
    path = tmp_path / "guidance.csv"
    row = guide().model_dump() | {
        "quote": "revenue of $90 to $100 million, previously $100 to $111"
    }
    path.write_text(
        ",".join(guidance.FIELDS) + "\n" + ",".join(f'"{row[f]}"' for f in guidance.FIELDS) + "\n"
    )
    with pytest.raises(GuidanceError, match="old_high"):
        guidance.load_guides(path)
    path.write_text(path.read_text().replace("$111", "$110"))
    assert guidance.load_guides(path)[0].old_high == 110


def test_with_shocks_rows_carry_the_band_and_seed(company):
    _, rows = evaluate_case(company, case(), CHOICES, TODAY, TODAY, [guide()], n_samples=300)
    shocked = [r for r in rows if r["variant"] == "with_shocks"]
    assert {r["item"] for r in shocked} == {"revenue", "ebit"}
    first = next(r for r in shocked if r["item"] == "revenue" and r["horizon"] == 1)
    base = next(r for r in rows if r["variant"] == "baseline" and r["item"] == "revenue")
    assert first["p10"] <= first["p50"] <= first["p90"] and first["seed"] is not None
    assert first["forecast"] == first["p50"] < base["forecast"]


def test_no_guidance_no_with_shocks_rows(company):
    _, rows = evaluate(company)
    assert not [r for r in rows if r["variant"] == "with_shocks"]


def test_guidance_dated_after_the_case_date_fails_the_case(company):
    late = guide(source_date=date(2019, 7, 1))
    batch = run_batch(company, [case()], "sha", CHOICES, TODAY, TODAY, [late], "gsha", 100)
    reason = company.execute(
        "SELECT reason FROM eval_failures WHERE batch_id = ?", (batch,)
    ).fetchone()["reason"]
    assert "after the case date" in reason
