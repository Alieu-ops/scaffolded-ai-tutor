"""
Milestone 2 tests: safe parsing and deterministic verification.
Covers alternative valid forms, tolerance and rounding, units, wrong
variables, unsupported notation and malicious input. Student text is never executed.
"""

import pytest

from qmtutor.domain.models import AnswerSpec, VerificationStatus as V
from qmtutor.mathcheck.safe_parser import MathParseError, evaluate_for_calculator, latex_preview, parse_answer
from qmtutor.mathcheck.verifier import verify_answer

UNITS = AnswerSpec(canonical_expression="7", variable="u", unit_words=["units", "unit"])
MONEY_2DP = AnswerSpec(canonical_expression="13382.26", absolute_tolerance=0.005)
EXACT_INT = AnswerSpec(canonical_expression="2205", absolute_tolerance=0.01)


@pytest.mark.parametrize("text", ["7", "7.0", "u = 7", "u=7", "7 units", "14/2", "  7  ", "49^(1/2)", "sqrt(49)",
                                  "3.5 x 2", "3.5*2", "(3+4)", "700%"])
def test_equivalent_forms_accepted(text):
    assert verify_answer(text, UNITS).status == V.CORRECT


@pytest.mark.parametrize("text", ["8", "6.99", "u = 8", "-7", "1/7"])
def test_wrong_values_rejected(text):
    assert verify_answer(text, UNITS).status == V.INCORRECT


@pytest.mark.parametrize("text", ["seven", "Seven", "seven units", "one hundred"])
def test_number_words_ask_for_digits(text):
    result = verify_answer(text, UNITS)
    assert result.status == V.UNSUPPORTED            # not counted as a wrong attempt
    assert result.reason_code == "number_word"
    assert "digits" in result.message


def test_wrong_variable_is_incorrect_not_crash():
    result = verify_answer("x = 7", UNITS)
    assert result.status == V.INCORRECT and result.reason_code == "wrong_variable"


@pytest.mark.parametrize("text,expected", [
    ("13382.26", V.CORRECT), ("13,382.26", V.CORRECT), ("GMD 13382.26", V.CORRECT), ("D13382.26", V.CORRECT),
    ("13382.256", V.CORRECT), ("10000*1.06^5", V.CORRECT), ("13382.3", V.INCORRECT), ("13382", V.INCORRECT),
])
def test_money_tolerance_and_rounding(text, expected):
    assert verify_answer(text, MONEY_2DP).status == expected


def test_compound_expression_equivalent():
    assert verify_answer("2000(1.05)^2", EXACT_INT).status == V.CORRECT
    assert verify_answer("2000(1+0.05)(1+0.05)", EXACT_INT).status == V.CORRECT
    assert verify_answer("2000 + 2000*0.05*2", EXACT_INT).status == V.INCORRECT   # simple interest misconception


def test_symbolic_equivalence():
    spec = AnswerSpec(canonical_expression="p(1+r)^2")
    assert verify_answer("p + 2pr + pr^2", spec).status == V.CORRECT
    assert verify_answer("(1+r)(1+r)p", spec).status == V.CORRECT
    assert verify_answer("p(1+2r)", spec).status == V.INCORRECT


@pytest.mark.parametrize("text", [
    "__import__('os').system('dir')", "import os", "lambda: 1", "exec('1')", "eval('2')",
    "open('x')", "().__class__", "2; 3", "x.y", "[1,2]", "{}", "a@b",
])
def test_malicious_or_code_like_input_is_rejected_not_run(text):
    result = verify_answer(text, UNITS)
    assert result.status == V.UNSUPPORTED


@pytest.mark.parametrize("text,code", [
    ("9^9^9^9", "too_complex"), ("2^100000", "too_complex"), ("(" * 40 + "1" + ")" * 40, "too_complex"),
    ("1/0", "division_by_zero"), ("1" * 300, "too_long"), ("sqrt 4", "function_needs_brackets"),
    ("(1+2", "unbalanced_brackets"), ("sqrt(-4)", "not_real"), ("7, 8", "multi_part_unsupported"),
])
def test_complexity_and_format_limits(text, code):
    with pytest.raises(MathParseError) as error:
        parse_answer(text, {"u"})
    assert error.value.code == code


def test_empty_answer():
    assert verify_answer("", UNITS).status == V.EMPTY
    assert verify_answer("   ", UNITS).status == V.EMPTY


def test_operator_precedence():
    assert parse_answer("-2^2").expression == -4
    assert parse_answer("2^3^2").expression == 512          # right-associative
    assert parse_answer("10 - 2 - 3").expression == 5
    assert parse_answer("12/3/2").expression == 2


@pytest.mark.regression
def test_percent_and_unicode():
    assert parse_answer("5%").expression * 100 == 5
    assert parse_answer("2³ × 5").expression == 40
    assert parse_answer("√16").expression == 4


def test_calculator_and_preview_use_the_same_safe_parser():
    value, latex = evaluate_for_calculator("10000*1.06^5")
    assert value.startswith("13382.25")
    assert "1.06" in latex
    with pytest.raises(MathParseError):
        evaluate_for_calculator("__import__('os')")
    assert latex_preview("u = 105/15", {"u"}).startswith("u =")
    assert latex_preview("2 +", {"u"}) is None


@pytest.mark.regression
def test_preview_always_shows_multiplication_sign_found_in_browser_check():
    preview = latex_preview("2000*1.05^2")
    assert r"\times" in preview and "20001.05" not in preview.replace(" ", "")
