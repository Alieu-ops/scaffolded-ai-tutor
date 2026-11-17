"""
Tests for the reasoning preview (qmtutor/mathcheck/reasoning_format.py).
The key rule: maths is typeset, but the student's work is never reordered,
simplified or corrected, and plain words are left alone.
"""

import pytest

from qmtutor.mathcheck.reasoning_format import format_reasoning


@pytest.mark.parametrize("typed,expected", [
    ("so 2x = 32 and x = 16", "so $2x = 32$ and $x = 16$"),
    ("5x - 3x = 20 + 12", "$5x - 3x = 20 + 12$"),                 # order kept (SymPy would write -3x + 5x)
    ("15u = 145 - 40 = 105", "$15u = 145 - 40 = 105$"),
    ("2000 x 1.05 = 2100", r"$2000 \times 1.05 = 2100$"),         # spaced x between numbers means times
    ("A = P(1 + r)^n", "$A = P(1 + r)^{n}$"),                     # capital letters kept
    ("r = 5%", r"$r = 5\%$"),
    ("log₂(8) = 3", r"$\log_{2}(8) = 3$"),
    ("√(16) = 4", r"$\sqrt{16} = 4$"),
    ("2¹⁰ = 1024", "$2^{10} = 1024$"),
])
def test_maths_is_typeset_as_written(typed, expected):
    assert format_reasoning(typed).replace("\\log _", "\\log_") == expected


@pytest.mark.parametrize("typed", [
    "I am not sure what to do", "a 3 step plan", "I took away the fee first", "Year 1 then year 2",
])
def test_plain_words_are_unchanged(typed):
    assert format_reasoning(typed) == typed


def test_wrong_working_is_shown_wrong_not_corrected():
    # The student's arithmetic error must stay visible in the preview.
    assert format_reasoning("145 - 40 = 115") == "$145 - 40 = 115$"


def test_markdown_characters_in_words_are_escaped():
    assert format_reasoning("cost is $5 and *very* high") == r"cost is \$5 and \*very\* high"


def test_line_breaks_are_kept():
    assert format_reasoning("15u = 105\nu = 7") == "$15u = 105$  \n$u = 7$"


def test_unparseable_maths_is_left_as_text():
    assert format_reasoning("x = = 3") == "x = = 3"


@pytest.mark.regression
def test_tutor_formulas_are_typeset_and_bold_headings_kept():
    """Owner request (3 Oct 2026): formulas in tutor and study answers look like the calculator's."""
    assert format_reasoning("The formula is A = P(1 + r/m)^(nm)", keep_markdown=True) == \
        "The formula is $A = P(1 + r/m)^{nm}$"
    out = format_reasoning("**Example:** 3000 x 1.10^2 = 3630 (the rate is 10%)", keep_markdown=True)
    assert out.startswith(r"**Example:** $3000 \times 1.10^{2} = 3630$")
    assert format_reasoning("It costs $5", keep_markdown=True) == r"It costs \$5"    # never starts a formula
