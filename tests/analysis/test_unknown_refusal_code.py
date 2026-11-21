"""Backlog #519: every coded refusal class (and the simulation notes) refuses a code outside its
set the same way, with a `RuntimeError` that `python -O` keeps; a known code still works."""

import subprocess
import sys

import pytest

from domains.analysis.coded import (
    ENGINE_REFUSAL_CODES,
    RANGE_REFUSAL_CODES,
    SIMULATION_REFUSAL_CODES,
    require_code,
)
from domains.analysis.math_engine import EngineError
from domains.analysis.montecarlo import SimulationError
from domains.evaluation.ranges import RangeError
from domains.market.store import MarketDataError
from domains.orchestration import simulations

CLASSES = [
    (RangeError, RANGE_REFUSAL_CODES),
    (SimulationError, SIMULATION_REFUSAL_CODES),
    (EngineError, ENGINE_REFUSAL_CODES),
    (MarketDataError, ENGINE_REFUSAL_CODES),
]


@pytest.mark.parametrize("cls, codes", CLASSES, ids=lambda c: getattr(c, "__name__", ""))
def test_an_unknown_code_is_a_runtime_error(cls, codes):
    with pytest.raises(RuntimeError, match="unknown .* code 'no_such_code'"):
        cls("text", code="no_such_code")


@pytest.mark.parametrize("cls, codes", CLASSES, ids=lambda c: getattr(c, "__name__", ""))
def test_a_known_code_or_none_is_kept(cls, codes):
    code = sorted(codes)[0]
    err = cls("text", code=code, params={"a": 1})
    assert err.code == code and err.params == {"a": 1}
    assert cls("text").code is None and cls("text").coded() is None


def test_an_unknown_simulation_note_code_is_a_runtime_error():
    with pytest.raises(RuntimeError, match="unknown simulation note code"):
        simulations._note("no_such_code")


def test_the_check_is_not_an_assert_and_not_a_value_error():
    with pytest.raises(RuntimeError) as e:
        require_code("x", frozenset({"y"}), "test")
    assert not isinstance(e.value, ValueError | AssertionError)
    require_code(None, frozenset(), "test")
    require_code("y", frozenset({"y"}), "test")


def test_the_check_survives_python_dash_o():
    code = (
        "from domains.analysis.montecarlo import SimulationError\n"
        "try:\n    SimulationError('t', code='no_such_code')\n"
        "except RuntimeError:\n    print('refused')\n"
    )
    out = subprocess.run(
        [sys.executable, "-O", "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "refused"
