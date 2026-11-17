"""
Logic behind the on-screen maths keypad and calculator (no Streamlit here,
so it can be unit-tested).

The keypad types "pretty" maths (2¹⁰, log₁₀(1000), √(16), 1.05², π). These
functions evaluate it with the same safe parser that marks answers, so the
calculator and the answer checker can never disagree about what an
expression means, and nothing typed is ever executed as code.
"""

from __future__ import annotations

from dataclasses import dataclass

import sympy

from qmtutor.mathcheck.reasoning_format import render_expression
from qmtutor.mathcheck.safe_parser import MathParseError, parse_answer


@dataclass(frozen=True)
class KeypadResult:
    ok: bool
    expression: str          # what the student typed, unchanged
    value_text: str = ""     # decimal result, e.g. "2205" or "13382.25578"
    latex: str = ""          # preview of the typed expression
    message: str = ""        # friendly error when ok is False


def format_value(value: sympy.Expr) -> str:
    """Up to 10 significant figures, without trailing zeros or scientific notation for normal sizes."""
    number = float(value.evalf(15))
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    text = f"{number:.10g}"
    return text if "e" not in text else f"{number:.6e}"


def calculate(expression: str, allowed_variables: set[str] | None = None) -> KeypadResult:
    """
    Evaluate a keypad expression. Expressions with letters (e.g. "15u") cannot be
    evaluated to a number; they still get a preview so they can be sent as an answer.
    """
    if not expression.strip():
        return KeypadResult(False, expression, message="Type a calculation first.")
    try:
        parsed = parse_answer(expression, allowed_variables or set())
    except MathParseError as error:
        return KeypadResult(False, expression, message=error.message)
    latex = render_expression(expression)    # the student's own symbols and order (see reasoning_format)
    if not parsed.expression.is_number:
        return KeypadResult(True, expression, latex=latex,
                            message="This contains a letter, so it has no single numeric value.")
    return KeypadResult(True, expression, value_text=format_value(parsed.expression), latex=latex)


def text_for_answer(result: KeypadResult) -> str:
    """What "Put in answer" places in the answer box: the number if there is one, else the expression."""
    return result.value_text or result.expression


def text_for_workings(result: KeypadResult) -> str:
    """What "Add to workings" appends: the calculation as one line, e.g. "2000×1.05² = 2205"."""
    return f"{result.expression} = {result.value_text}" if result.value_text else result.expression


def text_for_tutor(result: KeypadResult) -> str:
    """What "Send to tutor" posts in the chat: the working, so the tutor can respond to it."""
    if result.value_text:
        return f"I calculated {result.expression} = {result.value_text}"
    return f"My working: {result.expression}"
