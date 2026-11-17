"""
Deterministic answer verifier. Decides whether a final answer is correct
using the item's AnswerSpec. The LLM is never asked this question.

Order of checks:
    1. empty answer                      -> EMPTY
    2. safe parse fails                  -> UNSUPPORTED (with a readable reason)
    3. wrong variable ("x = 7" for u)    -> INCORRECT
    4. numeric answer: |student - correct| <= max(abs_tol, rel_tol * |correct|)
    5. symbolic answer: SymPy simplifies (student - correct) to 0, with a
       numeric spot-check at random points as a second opinion
Reasoning text is NOT checked here; it is assessed separately.
"""

from __future__ import annotations

import random
import re

import sympy

from qmtutor.domain.models import AnswerSpec, MathVerification, VerificationStatus
from qmtutor.mathcheck.safe_parser import MathParseError, parse_answer

EXACT_TOLERANCE = 1e-9
MAX_SYMBOLIC_OPS = 200    # skip simplify() on very large expressions (time limit)


def allowed_variables_for(spec: AnswerSpec) -> set[str]:
    """Variables a student may use: the answer's own variable plus any in the canonical form."""
    names = {spec.variable} if spec.variable else set()
    # Standalone letters only: in "p(1+r)^2" -> {p, r}; a word like "import" adds nothing.
    names |= set(re.findall(r"(?<![a-z])[a-z](?![a-z])", spec.canonical_expression.lower()))
    return {n for n in names if n and n.isalpha() and len(n) == 1}


def verify_answer(student_text: str, spec: AnswerSpec) -> MathVerification:
    """Check a final answer. Never raises for bad student input."""
    if not str(student_text or "").strip():
        return MathVerification(status=VerificationStatus.EMPTY, method="none",
                                reason_code="empty", message="Please type an answer.")

    allowed = allowed_variables_for(spec)
    try:
        student = parse_answer(student_text, allowed, spec.unit_words)
    except MathParseError as error:
        return MathVerification(status=VerificationStatus.UNSUPPORTED, method="safe_parser",
                                reason_code=error.code, message=error.message)

    # The canonical form is lecturer-authored; a parse failure here is a content error.
    correct = parse_answer(spec.canonical_expression, allowed, spec.unit_words)

    if student.assigned_variable and spec.variable and student.assigned_variable != spec.variable:
        # Checked before the value, so this message never reveals whether the value is right.
        return _result(VerificationStatus.INCORRECT, student, "variable_check", "wrong_variable",
                       f"The answer should be for {spec.variable}, not {student.assigned_variable}. "
                       f"Write it as {spec.variable} = ... and submit again.")

    s_expr, c_expr = student.expression, correct.expression
    if c_expr.is_number:
        if not s_expr.is_number:
            return _result(VerificationStatus.INCORRECT, student, "numeric_tolerance",
                           "not_a_number", "The answer should be a number.")
        return _compare_numbers(student, float(s_expr.evalf(30)), float(c_expr.evalf(30)), spec)
    return _compare_symbolic(student, s_expr, c_expr)


def _compare_numbers(student, s_value: float, c_value: float, spec: AnswerSpec) -> MathVerification:
    tolerance = max(spec.absolute_tolerance, spec.relative_tolerance * abs(c_value), EXACT_TOLERANCE)
    assumptions = f"tolerance={tolerance:g}; rounding_rule={spec.rounding_rule}"
    if abs(s_value - c_value) <= tolerance:
        return _result(VerificationStatus.CORRECT, student, "numeric_tolerance", "within_tolerance",
                       "Correct.", assumptions)
    return _result(VerificationStatus.INCORRECT, student, "numeric_tolerance", "outside_tolerance",
                   "Not correct yet.", assumptions)


def _compare_symbolic(student, s_expr, c_expr) -> MathVerification:
    difference = s_expr - c_expr
    if sympy.count_ops(difference) <= MAX_SYMBOLIC_OPS and sympy.simplify(difference) == 0:
        return _result(VerificationStatus.CORRECT, student, "symbolic_difference", "equivalent", "Correct.")
    # Second opinion: evaluate both at random points. Equal everywhere -> equivalent.
    symbols = sorted(difference.free_symbols, key=str)
    rng = random.Random(0)   # fixed seed so the check is reproducible
    for _ in range(5):
        point = {s: rng.uniform(0.5, 3.0) for s in symbols}
        try:
            if abs(complex(difference.evalf(subs=point))) > 1e-8:
                return _result(VerificationStatus.INCORRECT, student, "numeric_spot_check",
                               "not_equivalent", "Not correct yet.")
        except (TypeError, ValueError):
            return _result(VerificationStatus.UNSUPPORTED, student, "numeric_spot_check",
                           "cannot_evaluate", "I couldn't check that form automatically.")
    return _result(VerificationStatus.CORRECT, student, "numeric_spot_check", "equivalent_numerically",
                   "Correct.", "equal at 5 random points")


def _result(status, student, method, reason, message, assumptions=None) -> MathVerification:
    return MathVerification(status=status, normalised_answer=str(student.expression), method=method,
                            reason_code=reason, message=message, assumptions=assumptions)


def numbers_in_text(text: str) -> list[float]:
    """All plain numbers in free text (used by checkpoint matching and leak checks)."""
    import re
    cleaned = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", str(text))
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", cleaned)]
