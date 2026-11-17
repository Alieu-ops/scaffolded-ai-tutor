"""
Tests for the line-by-line workings check (qmtutor/mathcheck/step_check.py) and
for how it is combined with the final-answer check, so that a correct answer
with wrong workings is recorded as such.
"""

import json

import pytest

from qmtutor.domain.models import AnswerSpec
from qmtutor.mathcheck.step_check import ARITHMETIC_ERROR, INCONSISTENT, NOT_CHECKED, OK, check_workings, summarise
from qmtutor.services.exercise_service import ExerciseService

LINEAR = AnswerSpec(canonical_expression="7", variable="u", unit_words=["units"])
COMPOUND = AnswerSpec(canonical_expression="13382.26", absolute_tolerance=0.005)


def statuses(workings, spec):
    return [r.status for r in check_workings(workings, spec)]


def test_correct_workings_all_ok():
    assert statuses("40 + 15u = 145\n15u = 145 - 40 = 105\nu = 105/15 = 7", LINEAR) == [OK, OK, OK]


def test_arithmetic_error_is_pinpointed():
    results = check_workings("15u = 145 - 40 = 115", LINEAR)
    assert results[0].status == ARITHMETIC_ERROR and "'145 - 40 = 115'" in results[0].detail


def test_carried_error_is_inconsistent_with_the_answer():
    assert statuses("u = 115/15", LINEAR) == [INCONSISTENT]


def test_rounding_at_written_precision_is_accepted():
    assert statuses("1.06^5 = 1.3382\n10000 x 1.3382 = 13382", COMPOUND) == [OK, OK]
    assert statuses("1.06^5 = 1.34", COMPOUND) == [OK]
    assert statuses("1.06^5 = 1.35", COMPOUND) == [ARITHMETIC_ERROR]


def test_words_and_untestable_formulas_are_not_checked():
    assert statuses("I took away the fixed fee first", LINEAR) == []
    assert statuses("A = P(1 + r)^n", COMPOUND) == [NOT_CHECKED]


def test_summary_flags_errors():
    summary = summarise(check_workings("15u = 145 - 40 = 115\nu = 7", LINEAR))
    assert summary["has_errors"] and summary[ARITHMETIC_ERROR] == 1 and summary[OK] == 1


def test_correct_answer_with_wrong_workings_is_recorded(ctx, student):
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-001")
    outcome = service.submit_attempt(student, session.session_id, "7", "40 + 15u = 145\n15u = 145 - 40 = 115\nu = 7")
    assert outcome.completed and outcome.mismatch
    evidence = ctx.evidence.for_student("S001")[0]
    assert evidence.final_answer_correct and "workings contain errors" in evidence.note
    stored = json.loads(ctx.db.query_one("SELECT step_check_json FROM attempt")["step_check_json"])
    assert [s["status"] for s in stored] == [OK, ARITHMETIC_ERROR, OK]


def test_assessor_receives_step_evidence_but_tutor_never_does(ctx, student, fake):
    ctx.settings["features"]["assess_reasoning_with_llm"] = True
    fake.replies = [{"method_selection": 2, "mathematical_steps": 1, "conceptual_explanation": 1,
                     "comment": "Arithmetic slip on line 2.", "confidence": 0.7}]
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-001")
    service.submit_attempt(student, session.session_id, "7", "15u = 145 - 40 = 115\nu = 7")
    assessor_prompt = fake.calls[-1]["system"]
    assert "arithmetic_error" in assessor_prompt and "REFERENCE SOLUTION" in assessor_prompt
    comment = ctx.db.query_one("SELECT comment FROM reasoning_assessment")["comment"]
    assert comment == "Arithmetic slip on line 2."


def test_incorrect_attempts_are_assessed_too(ctx, student, fake):
    ctx.settings["features"]["assess_reasoning_with_llm"] = True
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-001")
    service.submit_attempt(student, session.session_id, "8", "u = 120/15 = 8")
    assert ctx.db.query_one("SELECT COUNT(*) n FROM reasoning_assessment")["n"] == 3   # three rubric dimensions


def test_lecturer_sees_workings_check_and_flag(ctx, student):
    from qmtutor.services.lecturer_service import LecturerService
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-001")
    service.submit_attempt(student, session.session_id, "7", "15u = 145 - 40 = 115\nu = 7")
    row = LecturerService(ctx).student_evidence_review(ctx.users.get("L001"), "S001")[0]
    assert row["flag"] == "correct answer, workings errors"
    assert "Line 1" in row["workings_check"] and "145 - 40 = 115" in row["workings_check"]


@pytest.mark.regression
def test_rule_caps_llm_steps_score_when_software_found_an_error(ctx, student, fake):
    """Regression from the live browser test: the 3B model gave full marks for flawed steps."""
    ctx.settings["features"]["assess_reasoning_with_llm"] = True
    fake.replies = [{"method_selection": 1, "mathematical_steps": 2, "conceptual_explanation": 2}]
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-002")
    service.submit_attempt(student, session.session_id, "x = 16", "5x - 3x = 20 + 12\n2x = 34\nso x = 16")
    rows = {(r["assessor_type"], r["dimension"]): r["score"]
            for r in ctx.db.query("SELECT assessor_type, dimension, score FROM reasoning_assessment")}
    assert rows[("llm_provisional", "mathematical_steps")] == 2      # raw LLM score kept
    assert rows[("rule_cap", "mathematical_steps")] == 1             # rule applied and recorded
    assert ctx.evidence.for_student("S001")[0].reasoning_score == 4  # 1 + 1 (capped) + 2


# What students may see
from qmtutor.mathcheck.step_check import student_feedback  # noqa: E402


def test_student_sees_only_arithmetic_before_finishing():
    workings = "40 + 15u = 145\n15u = 145 - 40 = 115\nu = 6\nu = 7\nu = 8"
    lines = student_feedback(check_workings(workings, LINEAR, use_answer=False), exercise_finished=False)
    shown = {line.line_number: line for line in lines}
    assert shown[2].good is False and "145 - 40 = 115" in shown[2].message
    # Lines that could only be judged against the answer get no tick or cross:
    assert all(shown[n].good is None for n in (1, 3, 4, 5))


@pytest.mark.regression
def test_answer_fishing_is_not_possible_before_finishing():
    """A student must not learn which of u = 6 / 7 / 8 is right from the workings check."""
    lines = student_feedback(check_workings("u = 6\nu = 7\nu = 8", LINEAR, use_answer=False), False)
    assert len({line.good for line in lines}) == 1          # all identical: nothing to tell them apart


def test_full_check_shown_after_finishing_without_the_answer_value():
    lines = student_feedback(check_workings("15u = 145 - 40 = 115\nu = 115/15", LINEAR), exercise_finished=True)
    assert [line.good for line in lines] == [False, False]
    assert all("u = 7" not in line.message and " 7" not in line.message for line in lines)


def test_numbers_in_a_line_with_unknown_letters_are_still_checked():
    assert statuses("A = 10000 x 1.06^5 = 13382.26", COMPOUND) == [OK]
    assert statuses("A = 10000 x 1.06^5 = 13000", COMPOUND) == [ARITHMETIC_ERROR]


def test_service_returns_safe_student_lines(ctx, student):
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-001")
    wrong = service.submit_attempt(student, session.session_id, "8", "15u = 145 - 40 = 105\nu = 8")
    assert [line.good for line in wrong.student_lines] == [True, None]   # arithmetic only, u = 8 not judged
    right = service.submit_attempt(student, session.session_id, "7", "15u = 145 - 40 = 105\nu = 7")
    assert [line.good for line in right.student_lines] == [True, True]
