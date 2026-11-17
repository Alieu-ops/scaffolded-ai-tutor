"""
Answer-leak guard: the second, code-level defence after the prompt.

Even though the scaffolded prompt never contains the answer, a capable model
can simply solve the question from the stem. So every scaffolded reply is
checked here before the student sees it. A reply leaks if it:
    1. states the final answer (reused v1 check `reveals_answer`);
    2. copies a run of the hidden worked solution containing a new number
       (reused v1 check `copies_solution`); or
    3. states an intermediate checkpoint value the student has not written yet.
"Known" numbers (in the question or typed by the student) never count as leaks.
The check is deliberately strict: a false alarm costs one regenerated reply;
a missed leak costs the student the chance to think.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from qmtutor.domain.models import Item
from qmtutor.mathcheck.verifier import numbers_in_text
from tutor.answers import copies_solution, reveals_answer   # v1 checks, kept and tested


@dataclass(frozen=True)
class LeakCheck:
    leaked: bool
    reason: str | None = None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 0.005 * max(1.0, abs(b))


def check_reply(reply_text: str, item: Item, student_texts: list[str]) -> LeakCheck:
    """Return whether `reply_text` would reveal the active item's answer or hidden steps."""
    if item.answer_specification is None:
        return LeakCheck(False)
    answer = item.answer_specification.canonical_expression
    known_text = " ".join([item.stem, *student_texts])

    # 1. Final answer. Numbers the student typed themselves are treated as known.
    if reveals_answer(reply_text, answer, known_text):
        return LeakCheck(True, "final_answer")
    # 2. Copied worked-solution steps containing a new number.
    if item.worked_solution and copies_solution(reply_text, " ".join(item.worked_solution), known_text):
        return LeakCheck(True, "worked_solution_copy")
    # 3. A checkpoint value the student has not produced.
    known_numbers = numbers_in_text(known_text)
    reply_numbers = numbers_in_text(reply_text)
    for checkpoint in item.checkpoints:
        value = float(checkpoint.value)
        if any(_close(n, value) for n in reply_numbers) and not any(_close(n, value) for n in known_numbers):
            return LeakCheck(True, "intermediate_value")
    return LeakCheck(False)


# A formula statement: one letter, "=", then a right side with at least two different letters,
# e.g. "A = P(1 + r)^n" or "I = Prt". Naming the formula is level-3 help ("plan hint").
_FORMULA = re.compile(r"(?<![A-Za-z])([A-Za-z])\s*=\s*([^=.,;]*)")
_SHORT_WORDS = {"the", "of", "is", "a", "an", "to", "and", "in", "on", "for", "be", "as", "at", "by", "it",
                "you", "we", "per", "its", "how", "are", "can", "do", "so", "or", "if", "not"}


def states_formula(reply_text: str, student_texts: list[str]) -> bool:
    """
    True if the reply states a formula the student has not written themselves.
    Found in the owner's screenshot (3 Oct 2026): at level 1 ("explain your thinking") the
    model answered "What formula should I use?" with A = P(1 + r)^n, skipping two hint levels.
    """
    known = re.sub(r"\s+", "", " ".join(student_texts)).lower()
    for match in _FORMULA.finditer(reply_text):
        right = match.group(2)
        short_groups = [g for g in re.findall(r"(?<![A-Za-z])[A-Za-z]{1,3}(?![A-Za-z])", right)
                        if g.lower() not in _SHORT_WORDS]          # "P", "r", "Prt"; not "the", "of"
        letters = {letter.lower() for group in short_groups for letter in group}
        if len(letters) >= 2:
            written = re.sub(r"\s+", "", match.group(0)).lower()
            if written not in known:
                return True
    return False


def verified_checkpoints(item: Item, student_texts: list[str]):
    """
    Checkpoints the student has already written (in reasoning or chat). Only these
    may be restated at Level 5. Returns a list of (checkpoint, value_as_written).
    """
    numbers = numbers_in_text(" ".join(student_texts))
    found = []
    for checkpoint in item.checkpoints:
        value = float(checkpoint.value)
        if any(_close(n, value) for n in numbers):
            found.append((checkpoint, checkpoint.value))
    return found
