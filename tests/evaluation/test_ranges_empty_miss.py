"""Backlog #495: a stored past miss marked ok that is empty (a NaN, which SQLite keeps as NULL)
or not finite is refused by `ranges.load_pairs` with a coded error, never passed on to the range
maths; a clean store loads exactly as before."""

import json
from datetime import date

import pytest

from domains.analysis.coded import RANGE_REFUSAL_CODES, Coded
from domains.evaluation import ranges as R
from tests.evaluation.test_run_ranges import add_origin, history, scored


def _store(conn):
    history(conn)
    add_origin(conn, "AAA", date(2021, 3, 15), [scored(1, "FY2021Q1", date(2021, 5, 15), 104.0)])


def _set(conn, item, value, horizon=None):
    first = conn.execute("SELECT MIN(origin_id) FROM baseline_errors").fetchone()[0]
    sql = "UPDATE baseline_errors SET error = ? WHERE origin_id = ? AND item = ?"
    args = [value, first, item]
    if horizon is not None:
        sql += " AND horizon = ?"
        args.append(horizon)
    conn.execute(sql, args)
    return first


def test_a_clean_store_loads_every_ok_pair_as_stored(company):
    _store(company)
    pairs = R.load_pairs(company)
    want = company.execute(
        "SELECT r.origin_id, r.horizon, r.error AS rev, e.error AS ebit FROM baseline_errors r "
        "JOIN baseline_errors e ON e.origin_id = r.origin_id AND e.horizon = r.horizon "
        "AND e.item = 'ebit' JOIN forecast_origins o ON o.origin_id = r.origin_id "
        "WHERE r.item = 'revenue' AND r.status = 'ok' AND e.status = 'ok' AND o.status = 'ok' "
        "ORDER BY r.origin_id, r.horizon"
    ).fetchall()
    assert [(p.origin_id, p.horizon, p.revenue, p.ebit) for p in pairs] == [tuple(w) for w in want]
    assert len(pairs) > 20
    assert R.pairs_sha256(pairs) == R.pairs_sha256(R.load_pairs(company))


@pytest.mark.parametrize(
    "item, stored, seen",
    [
        ("revenue", float("nan"), None),
        ("ebit", None, None),
        ("ebit", float("nan"), None),
        ("revenue", float("inf"), "inf"),
        ("ebit", float("-inf"), "-inf"),
    ],
)
def test_an_empty_or_infinite_ok_miss_is_refused_with_its_row_named(company, item, stored, seen):
    _store(company)
    origin = _set(company, item, stored, horizon=1)
    with pytest.raises(R.RangeError) as e:
        R.load_pairs(company)
    err = e.value
    assert err.code == "stored_miss_not_finite" and err.code in RANGE_REFUSAL_CODES
    assert err.params == {"origin_id": origin, "horizon": 1, "item": item, "value": seen}
    assert origin in str(err) and item in str(err)
    assert err.coded() == Coded("stored_miss_not_finite", err.params, err.text)


def test_the_first_bad_row_in_the_reads_order_is_the_one_named(company):
    _store(company)
    origin = _set(company, "ebit", None)  # every horizon of the first origin
    _set(company, "revenue", None, horizon=2)
    with pytest.raises(R.RangeError) as e:
        R.load_pairs(company)
    # horizon 1 comes first; within a pair revenue is checked before EBIT
    assert e.value.params == {"origin_id": origin, "horizon": 1, "item": "ebit", "value": None}


def test_an_excluded_miss_that_is_empty_is_not_read(company):
    """Only rows marked ok are misses a range may use; an excluded row's empty error is normal."""
    _store(company)
    before = R.load_pairs(company)
    first = before[0]
    company.execute(
        "UPDATE baseline_errors SET error = NULL, status = 'excluded', reason = 'test' "
        "WHERE origin_id = ? AND horizon = ? AND item = 'ebit'",
        (first.origin_id, first.horizon),
    )
    assert R.load_pairs(company) == before[1:]


def test_a_range_error_without_a_code_is_text_only_and_unknown_codes_are_refused():
    assert R.RangeError("plain").coded() is None
    with pytest.raises(RuntimeError):
        R.RangeError("x", code="not_a_code")


@pytest.mark.parametrize("item, stored", [("revenue", None), ("ebit", float("inf")),
                                          ("revenue", float("-inf"))])  # fmt: skip
def test_the_refusal_params_are_strict_json(company, item, stored):
    """Backlog #519: an infinite miss is carried as text, never as a float JSON can't hold."""
    _store(company)
    _set(company, item, stored, horizon=1)
    with pytest.raises(R.RangeError) as e:
        R.load_pairs(company)
    assert json.loads(json.dumps(e.value.params, allow_nan=False)) == e.value.params
