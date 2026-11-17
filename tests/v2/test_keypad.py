"""
Tests for the maths keypad's calculator logic (qmtutor/mathcheck/keypad.py)
and the keypad notation the safe parser must understand.
The on-screen buttons themselves are checked manually in a browser.
"""

import pytest

from qmtutor.domain.models import AnswerSpec, VerificationStatus
from qmtutor.mathcheck.keypad import calculate, text_for_answer, text_for_tutor
from qmtutor.mathcheck.safe_parser import MathParseError, parse_answer
from qmtutor.mathcheck.verifier import verify_answer


@pytest.mark.parametrize("typed,value", [
    ("2000×1.05²", "2205"), ("10000×1.06⁵", "13382.25578"), ("2¹⁰", "1024"), ("√(16)", "4"), ("√16", "4"),
    ("log₁₀(1000)", "3"), ("log₂(8)", "3"), ("ln(e)", "1"), ("5%×2000", "100"), ("12 ÷ 4", "3"),
    ("2(3+4)", "14"), ("1,250 + 750", "2000"), ("(1+0.05)⁽²⁾", "1.1025"), ("2log₂(8)", "6"),
])
def test_keypad_calculations(typed, value):
    result = calculate(typed)
    assert result.ok and result.value_text == value, result


def test_keypad_errors_are_friendly_not_crashes():
    for typed in ["", "2 +", "log₁(5)", "import os", "1/0"]:
        result = calculate(typed)
        assert not result.ok and result.message


def test_expression_with_variable_has_preview_but_no_value():
    result = calculate("40 + 15u", {"u"})
    assert result.ok and result.value_text == "" and "u" in result.latex


def test_what_gets_sent_to_answer_and_tutor():
    numeric = calculate("2000×1.05²")
    assert text_for_answer(numeric) == "2205"
    assert text_for_tutor(numeric) == "I calculated 2000×1.05² = 2205"
    algebra = calculate("u = 105/15", {"u"})
    assert text_for_answer(algebra) == "7"


@pytest.mark.regression
def test_keypad_symbols_are_accepted_by_the_answer_checker():
    spec = AnswerSpec(canonical_expression="2205", absolute_tolerance=0.01)
    assert verify_answer("2000×1.05²", spec).status == VerificationStatus.CORRECT
    assert verify_answer("2000(1+5%)²", spec).status == VerificationStatus.CORRECT


def test_log_base_must_be_valid():
    with pytest.raises(MathParseError):
        parse_answer("log_1(5)")
    with pytest.raises(MathParseError):
        parse_answer("log_2 8")


@pytest.mark.regression
def test_previews_keep_log_base_and_the_students_order():
    """Regression: SymPy's LaTeX dropped the base of log_2(8) (found while checking session notes)."""
    from qmtutor.mathcheck.safe_parser import latex_preview
    assert latex_preview("log_2(8)") == r"\log_{2}(8)"
    assert latex_preview("u = 105/15", {"u"}) == "u = 105/15"
    assert calculate("log_2(8) + 2^10").latex == r"\log_{2}(8) + 2^{10}"
