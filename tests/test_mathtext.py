"""Tests for maths symbols from the on-screen maths keyboard. Run: pytest"""

from tutor.answers import check_answer, reveals_answer
from tutor.mathtext import pretty, to_plain


def test_to_plain():
    assert to_plain("2¹⁰") == "2^10"
    assert to_plain("x²") == "x^2"
    assert to_plain("log₁₀(1000)") == "log_10(1000)"
    assert to_plain("√25") == "sqrt25"
    assert to_plain("3 ÷ 4") == "3 / 4"
    assert to_plain("x⁻¹") == "x^-1"


def test_pretty():
    assert pretty("Evaluate 2^3 x 2^4.") == "Evaluate 2³ × 2⁴."
    assert pretty("Factorise x^2 - 9.") == "Factorise x² - 9."
    assert pretty("Evaluate log (base 10) of 1000.") == "Evaluate log₁₀ of 1000."
    assert pretty("Solve 3x + 5 = 20.") == "Solve 3x + 5 = 20."    # 3x is not a multiplication sign
    assert pretty("Area = 1/2 x 10 x 6") == "Area = 1/2 × 10 × 6"


def test_keyboard_answers_are_checked():
    assert check_answer("2⁷", "128")
    assert check_answer("2¹⁰", "1024")
    assert check_answer("√25", "5")
    assert check_answer("√(25) cm", "5 cm")
    assert check_answer("720°", "720 degrees")
    assert check_answer("(x−3)(x+3)", "(x - 3)(x + 3)")   # unicode minus sign
    assert check_answer("3 ÷ 8", "3/8")
    assert not check_answer("10³", "3")


def test_leak_check_understands_superscripts():
    q = "Evaluate log (base 10) of 1000."
    assert reveals_answer("So log₁₀(1000) = 3.", "3", q)
