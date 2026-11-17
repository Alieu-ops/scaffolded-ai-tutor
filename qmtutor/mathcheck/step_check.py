"""
Deterministic check of a student's written workings, line by line.

On paper a marker looks at each step. This module does the part of that
which code can do exactly:

    "145 - 40 = 105"   -> both sides equal                      -> ok
    "145 - 40 = 115"   -> sides differ                           -> arithmetic_error
    "15u = 105"        -> true when u = 7 (the item's answer)    -> ok (consistent)
    "15u = 115"        -> false when u = 7                       -> inconsistent
    "I took away the fixed fee"  -> words only                   -> not_checked
    "A = P(1 + r)^n"   -> unknown letters, cannot be tested      -> not_checked

Rounding is allowed the way a marker would: "1.06^5 = 1.3382" is fine,
because 1.3382255... rounds to 1.3382 at the precision the student wrote.

This judges arithmetic and consistency, not whether the method is sensible
or well explained. That part goes to the LLM (provisional) and the lecturer.
The results are stored with the attempt and shown to lecturers; whether
students see them is a study-design decision (see config_v2.yaml).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import sympy

from qmtutor.domain.models import AnswerSpec
from qmtutor.mathcheck.reasoning_format import _SPAN, _OPERATOR
from qmtutor.mathcheck.safe_parser import MathParseError, parse_answer

OK, ARITHMETIC_ERROR, INCONSISTENT, NOT_CHECKED = "ok", "arithmetic_error", "inconsistent", "not_checked"


@dataclass(frozen=True)
class StepResult:
    line_number: int
    text: str           # the equation exactly as the student wrote it
    status: str
    detail: str = ""
    # True when the check substituted the item's answer (a consistency check). Such results
    # reveal information about the answer, so students only see them after finishing.
    uses_answer: bool = False


def _decimals_written(side: str) -> int | None:
    """Decimal places of a plain number like '1.3382' (used for rounding tolerance), else None."""
    match = re.fullmatch(r"\s*-?\d+(?:,\d{3})*(?:\.(\d+))?\s*", side)
    return None if match is None else len(match.group(1) or "")


def _equal(left_value: float, right_value: float, right_text: str, left_text: str) -> bool:
    """Equal, allowing rounding to the precision of whichever side is a plain written number."""
    tolerance = 1e-9 * max(1.0, abs(left_value), abs(right_value))
    for text in (right_text, left_text):
        places = _decimals_written(text)
        if places is not None:
            tolerance = max(tolerance, 0.5 * 10 ** -places + 1e-9)
    return abs(left_value - right_value) <= tolerance


def check_workings(workings: str, spec: AnswerSpec | None, use_answer: bool = True) -> list[StepResult]:
    """
    Check every equation in the workings. Never raises for odd student text.
    use_answer=False gives an arithmetic-only check that never touches the item's answer
    (safe to show a student before the exercise is finished).
    """
    answer_value = None
    if use_answer and spec is not None and spec.variable:
        try:
            answer_value = parse_answer(spec.canonical_expression, set()).expression
        except MathParseError:
            answer_value = None

    results: list[StepResult] = []
    for number, line in enumerate(str(workings).splitlines(), start=1):
        for match in _SPAN.finditer(line):
            span = match.group(0).strip(" ,")
            if "=" not in span or not _OPERATOR.search(span.replace("=", "", 1) + "="):
                continue
            results.append(_check_equation(number, span, spec, answer_value))
    return results


def _check_equation(number: int, span: str, spec: AnswerSpec | None, answer_value) -> StepResult:
    sides = [s.strip() for s in span.split("=")]
    if any(not s for s in sides):
        return StepResult(number, span, NOT_CHECKED, "incomplete equation")
    variables = {ch.lower() for ch in re.findall(r"(?<![a-zA-Z])[a-zA-Z](?![a-zA-Z])", span)}
    try:
        parsed = [parse_answer(s, variables, spec.unit_words if spec else None).expression for s in sides]
    except MathParseError:
        return StepResult(number, span, NOT_CHECKED, "could not read this line")

    item_variable = spec.variable if spec else None
    # Check each "=" separately (a = b = c means a = b AND b = c) and report the first
    # pair that fails, so "15u = 145 - 40 = 115" is reported as an ARITHMETIC error in
    # "145 - 40 = 115", not as a vague inconsistency. Pairs with letters that cannot be
    # tested are skipped, so "A = 10000 x 1.06^5 = 13382.26" still has its numbers checked.
    any_variable, checked_pairs = False, 0
    for i in range(len(parsed) - 1):
        left, right = parsed[i], parsed[i + 1]
        free = {str(sym) for sym in (left.free_symbols | right.free_symbols)}
        if free:
            if answer_value is None or free != {item_variable}:
                continue
            symbol = sympy.Symbol(item_variable)
            left, right = left.subs(symbol, answer_value), right.subs(symbol, answer_value)
            any_variable = True
        checked_pairs += 1
        try:
            l_value, r_value = float(left.evalf(20)), float(right.evalf(20))
        except (TypeError, ValueError):
            return StepResult(number, span, NOT_CHECKED, "could not evaluate")
        if not _equal(l_value, r_value, sides[i + 1], sides[i]):
            pair = f"{sides[i]} = {sides[i + 1]}"
            if free:
                return StepResult(number, span, INCONSISTENT,
                                  f"'{pair}' is not true when {item_variable} = {answer_value}", uses_answer=True)
            return StepResult(number, span, ARITHMETIC_ERROR, f"'{pair}': the two sides are not equal",
                              uses_answer=any_variable)
    if checked_pairs == 0:
        return StepResult(number, span, NOT_CHECKED, "contains letters that cannot be tested")
    return StepResult(number, span, OK, "consistent with the answer" if any_variable else "correct arithmetic",
                      uses_answer=any_variable)


def summarise(results: list[StepResult]) -> dict:
    """Counts used in evidence and lecturer views."""
    counts = {OK: 0, ARITHMETIC_ERROR: 0, INCONSISTENT: 0, NOT_CHECKED: 0}
    for r in results:
        counts[r.status] += 1
    return {**counts, "checked": counts[OK] + counts[ARITHMETIC_ERROR] + counts[INCONSISTENT],
            "has_errors": counts[ARITHMETIC_ERROR] + counts[INCONSISTENT] > 0}


def to_json_ready(results: list[StepResult]) -> list[dict]:
    return [asdict(r) for r in results]


@dataclass(frozen=True)
class StudentLine:
    line_number: int
    text: str        # the student's own equation
    good: bool | None   # True = tick, False = cross, None = not checked
    message: str     # plain language, never contains the answer


def student_feedback(results: list[StepResult], exercise_finished: bool) -> list[StudentLine]:
    """
    What a STUDENT may see about their workings.

    Safety rule: while the exercise is still open, only pure arithmetic checks are shown
    (both sides are the student's own numbers). Checks that substituted the answer are
    hidden until the exercise is finished; otherwise a student could write "u = 6",
    "u = 7", "u = 8" as workings and see which line gets a tick. Messages never include
    the answer's value.
    """
    lines = []
    for r in results:
        if r.uses_answer and not exercise_finished:
            continue
        if r.status == OK:
            lines.append(StudentLine(r.line_number, r.text, True,
                                     "Fits with correct working." if r.uses_answer else "The calculation is correct."))
        elif r.status == ARITHMETIC_ERROR:
            pair = r.detail.split("':")[0].strip("'") if "':" in r.detail else r.text
            lines.append(StudentLine(r.line_number, r.text, False,
                                     f"Check this calculation: {pair} is not equal on both sides."))
        elif r.status == INCONSISTENT:
            lines.append(StudentLine(r.line_number, r.text, False,
                                     "This line does not follow from correct working. Look at the step before it."))
        else:
            lines.append(StudentLine(r.line_number, r.text, None, "Not checked by the computer."))
    return lines
