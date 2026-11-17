"""
Answer checking: decides whether a student's typed answer matches the
correct answer in items.csv.

Students type answers in many forms, so we accept equivalent ones:
    "5", "x=5", "x = 5"          -> same
    "3/8", "0.375"               -> same (numbers compared by value)
    "600", "D600", "600 dalasi"  -> same (units are ignored)
    "x = 2 or x = 3", "3, 2"     -> same (order does not matter)
    "(x-3)(x+3)", "(x+3)(x-3)"   -> same (factor order does not matter)
    "13,382.26", "13382.26"      -> same (thousands commas ignored)
    "820.6-879.4", "820.6, 879.4" -> same (a dash between numbers is a separator)

How close a number must be depends on how the correct answer is written:
    decimal, e.g. "0.0214"   -> must round to it (0.0214 yes, 0.02 no)
    whole number, e.g. "60"  -> must be exactly equal
    fraction, e.g. "1/3"     -> within 0.005, so "0.33" is accepted

The same helpers are used to check whether the AI tutor has LEAKED the
final answer in one of its messages (see `reveals_answer`).
"""

import math
import re
from fractions import Fraction

from tutor.mathtext import to_plain

# Units and words removed before comparing. Order matters: longer first.
UNITS = ["cm^3", "cm^2", "cm³", "cm²", "cm", "degrees", "degree", "deg", "°", "dalasi"]

# A number: optional minus, digits, optional decimal part,
# optionally followed by "/ denominator" (a fraction).
# The minus only counts as a sign when it does not come straight after a
# digit, so in "820.6-879.4" the dash separates two positive numbers.
NUMBER = r"(?:(?<!\d)-)?\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?"

# Allowed difference for fractions (so "0.33" matches "1/3") and for the
# leak check, which is deliberately loose.
TOLERANCE = 0.005


def normalise(text):
    """Lower-case, remove units, currency, thousands commas and spaces."""
    text = to_plain(text).lower().strip()   # "2¹⁰" -> "2^10", "√" -> "sqrt"
    for unit in UNITS:
        text = text.replace(unit, "")
    text = re.sub(r"\bd(?=\s*\d)", "", text)   # "D600" -> "600" (dalasi)
    text = text.replace("×", "x").replace("−", "-").replace("–", " to ")
    # "13,382.26" -> "13382.26": a comma followed by exactly 3 digits.
    # (A list like "10, 50" has a space or fewer digits, so it is kept.)
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return re.sub(r"\s+", "", text)


def to_number(token):
    """Turn "3/8", "0.375" or "12" into an exact Fraction value."""
    if "/" in token:
        top, bottom = token.split("/")
        return Fraction(top.strip()) / Fraction(bottom.strip())
    return Fraction(token)


def numbers_in(text):
    """All numbers in a piece of text, as Fraction values."""
    return [to_number(t) for t in re.findall(NUMBER, text)]


def close(a, b):
    """True if two numbers are equal, allowing for rounding (loose)."""
    return abs(float(a) - float(b)) <= TOLERANCE * max(1, abs(float(b)))


def marking_tolerance(token):
    """
    How far a student's number may be from this correct number, based on
    how the correct number is written in items.csv.
    """
    if "/" in token:                           # fraction: "0.33" ok for "1/3"
        return TOLERANCE * max(1, abs(float(to_number(token))))
    if "." in token:                           # decimal: must round to it
        places = len(token.split(".")[1])      # "0.0214" -> 4 places
        return 0.5 * 10 ** -places + 1e-9      # 0.02135 to 0.02145 accepted
    return 1e-9                                # whole number: exact


def correct_numbers(text):
    """Numbers in a correct answer, each with its marking tolerance."""
    return [(to_number(t), marking_tolerance(t)) for t in re.findall(NUMBER, text)]


def same_numbers(student, correct):
    """
    True if both lists hold the same numbers, in any order.
    `student` is a list of numbers; `correct` is a list of
    (number, tolerance) pairs from correct_numbers().
    """
    if len(student) != len(correct):
        return False
    remaining = list(student)
    for value, tol in correct:
        match = next((s for s in remaining if abs(float(s) - float(value)) <= tol), None)
        if match is None:
            return False
        remaining.remove(match)
    return True


def is_expression_answer(answer):
    """
    True for answers that are algebraic expressions, e.g. "(x - 3)(x + 3)",
    rather than numbers or "x = 5" style values.
    """
    return "(" in answer and "=" not in answer


def factors(text):
    """Split "(x-3)(x+3)" into a sorted list of factors: ["x+3", "x-3"]."""
    return sorted(re.findall(r"\(([^()]*)\)", normalise(text)))


def variable_values(text):
    """
    Pairs like "x=4, y=3" -> {("x", 4), ("y", 3)}.
    Returns an empty set if the text has no "letter = number" parts.
    """
    pairs = re.findall(r"([a-z])=(" + NUMBER + ")", normalise(text))
    return {(var, to_number(val)) for var, val in pairs}


def evaluate_powers(text):
    """
    Replace simple powers of numbers with their value: "2^7" -> "128".
    Letters are left alone, so "x^2" is unchanged.
    """
    def power(match):
        base, exponent = int(match.group(1)), int(match.group(2))
        return str(base ** exponent) if exponent <= 20 else match.group(0)
    return re.sub(r"(?<![a-z\d.])(\d+)\^(\d+)", power, text)


def evaluate_roots(text):
    """Replace square roots of numbers with their value: "sqrt25" or "sqrt(25)" -> "5"."""
    def root(match):
        value = math.sqrt(float(match.group(1)))
        return str(int(value)) if value.is_integer() else f"{value:.6f}"
    text = re.sub(r"sqrt\(\s*(\d+(?:\.\d+)?)\s*\)", root, text)   # sqrt(25)
    return re.sub(r"sqrt(\d+(?:\.\d+)?)", root, text)             # sqrt25


def prepare(text):
    """Plain, lower-case text with simple powers and roots worked out."""
    return evaluate_powers(evaluate_roots(to_plain(text).lower()))


def check_answer(student_text, correct_answer):
    """Main function: is the student's answer correct? Returns True/False."""
    if not str(student_text).strip():
        return False
    # Accept equivalent forms: "2^7" or "2⁷" for 128, "√25" for 5.
    student_text = prepare(student_text)
    correct_answer = prepare(correct_answer)

    # 1. Algebraic expressions (e.g. factorisation): compare the factors.
    if is_expression_answer(correct_answer):
        return factors(student_text) == factors(correct_answer)

    # 2. If BOTH answers name their variables ("x=4, y=3"), the
    #    variable-value pairs must match, so "x=3, y=4" is marked wrong.
    student_pairs = variable_values(student_text)
    correct_pairs = variable_values(correct_answer)
    if student_pairs and correct_pairs and len(correct_pairs) > 1:
        vars_student = {v for v, _ in student_pairs}
        vars_correct = {v for v, _ in correct_pairs}
        if len(vars_correct) > 1:  # e.g. x and y: each must match its value
            student_map = dict(student_pairs)
            return vars_student == vars_correct and all(
                close(student_map[v], val) for v, val in correct_pairs
            )

    # 3. Otherwise compare the numbers, ignoring order.
    return same_numbers(numbers_in(normalise(student_text)),
                        correct_numbers(normalise(correct_answer)))


def reveals_answer(ai_text, correct_answer, question):
    """
    Does an AI message give away the final answer? Used as a safety check
    on the scaffolded tutor. Deliberately strict: when in doubt, say yes.

    - Expression answers: leak if the full expression appears.
    - Number answers: leak if every answer number that is NOT already in
      the question appears in the AI message. (Numbers already printed in
      the question, like the "3" in "3 red balls", cannot give anything away.)
    """
    ai_norm = normalise(ai_text)

    if is_expression_answer(correct_answer):
        wanted = factors(correct_answer)
        found = factors(ai_text)
        return all(f in found for f in wanted)

    question_numbers = numbers_in(normalise(question))
    answer_numbers = [n for n in numbers_in(normalise(correct_answer))
                      if not any(close(n, q) for q in question_numbers)]
    if not answer_numbers:
        return False   # every answer number is already in the question

    # Compare sizes ignoring the sign, so "(x - 2)(x - 3)" counts as
    # revealing the roots 2 and 3. Stricter, but safer.
    ai_numbers = [abs(a) for a in numbers_in(ai_norm)]
    return all(any(close(a, abs(n)) for a in ai_numbers) for n in answer_numbers)


# How many tokens in a row must match the worked solution to count as copying.
COPY_RUN = 6


def tokens(text):
    """Split text into words, numbers and maths symbols: "q = 40" -> ["q", "=", "40"]."""
    text = to_plain(text).lower().replace("×", "x").replace("*", "x").replace("−", "-")
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+|[=+\-/^()]", text)


def copies_solution(ai_text, worked_solution, known_text):
    """
    Does an AI message copy part of the hidden worked solution? This catches
    the tutor doing middle steps for the student, e.g. writing
    "-2q + 80 = 0 gives q = 40" without ever stating the final answer.

    A leak is a run of COPY_RUN tokens that appears in both the AI message
    and the worked solution AND contains a new number: one that is not in
    `known_text` (the question plus everything the student has typed).
    So the tutor may still name a formula, restate the question, or repeat
    the student's own working. 0, 1 and 2 are ignored: they are in every
    formula (x^2, 1 + r, n/2).
    """
    known = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", to_plain(known_text))}

    def is_new_number(token):
        return (token[0].isdigit() and float(token) not in known
                and float(token) not in (0, 1, 2))

    def runs(text):
        t = tokens(text)
        return {tuple(t[i:i + COPY_RUN]) for i in range(len(t) - COPY_RUN + 1)}

    shared = runs(ai_text) & runs(worked_solution)
    return any(any(is_new_number(tok) for tok in run) for run in shared)
