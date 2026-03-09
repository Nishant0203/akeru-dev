import pytest

from agent.confirmation_gate import is_residual, resolve_selection


def test_residual_flagging() -> None:
    assert is_residual("Other parts and accessories")


def test_resolve_selection_by_index() -> None:
    options = [{"commodity_code": "8708301090"}, {"commodity_code": "8708309000"}]
    assert resolve_selection("2", options) == "8708309000"


def test_resolve_selection_by_manual_code() -> None:
    options = [{"commodity_code": "8708301090"}]
    assert resolve_selection("8708305555", options) == "8708305555"


def test_resolve_selection_accepts_6_digit_manual_code() -> None:
    options = [{"commodity_code": "8708301090"}]
    assert resolve_selection("870830", options) == "870830"


def test_resolve_selection_accepts_8_digit_manual_code() -> None:
    options = [{"commodity_code": "8708301090"}]
    assert resolve_selection("87083010", options) == "87083010"


def test_resolve_selection_rejects_invalid_input() -> None:
    options = [{"commodity_code": "8708301090"}]
    with pytest.raises(ValueError):
        resolve_selection("abc", options)
