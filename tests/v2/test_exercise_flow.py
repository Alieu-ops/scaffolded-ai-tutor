"""
Milestone 4/5 tests: the protected exercise end to end, with a FakeProvider
standing in for the LLM. Includes the adversarial cases: a model that leaks
the answer, a model that is down, malformed model output, direct-answer
requests, mode switching, and access to another student's exercise.
"""

import json

import pytest

from qmtutor.domain.models import ExerciseState, ScaffoldLevel as L, SupportCategory
from qmtutor.llm.providers import ProviderError
from qmtutor.services.auth import PermissionDenied
from qmtutor.services.exercise_service import ExerciseError, ExerciseService
from qmtutor.services.study_service import StudyLocked, StudyService
from tests.v2.conftest import consented


@pytest.fixture
def svc(ctx):
    return ExerciseService(ctx)


def events(ctx, event_type):
    return ctx.db.query("SELECT * FROM event WHERE event_type=?", (event_type,))


def test_requires_consent_before_starting(ctx, svc):
    with pytest.raises(ExerciseError):
        svc.start(ctx.users.get("S004"), "LIN-001")


def test_start_records_versions_and_blocks_second_active(ctx, svc, student):
    session = svc.start(student, "LIN-001")
    version = ctx.content.latest_approved("LIN-001").item_version
    assert session.item_version == version and session.policy_version == "SP-1.0"
    started = events(ctx, "exercise_started")[0]
    assert started["item_key"] == f"LIN-001@{version}" and started["policy_version"] == "SP-1.0"
    with pytest.raises(ExerciseError):
        svc.start(student, "LIN-002")


def test_analogues_and_transfer_items_cannot_be_started_as_practice(svc, student):
    for item_id in ("LIN-ANA-001", "LIN-004"):
        with pytest.raises(ExerciseError):
            svc.start(student, item_id)


def test_hint_button_gives_approved_text_without_calling_llm(ctx, svc, student, fake):
    session = svc.start(student, "LIN-001")
    item = svc.item_for(session)
    turn = svc.request_hint(student, session.session_id)
    assert turn.level == L.SELF_EXPLANATION
    assert turn.text == item.scaffold_sequence.self_explanation
    assert fake.calls == []
    decision = events(ctx, "scaffold_decision_made")[0]
    assert json.loads(decision["payload_json"])["reason"] == "escalate_one_level"


def test_full_ladder_to_analogue_then_return(ctx, svc, student):
    session = svc.start(student, "LIN-001")
    levels = [svc.request_hint(student, session.session_id).level for _ in range(4)]
    assert levels == [L.SELF_EXPLANATION, L.CONCEPTUAL_CUE, L.STRATEGIC_HINT, L.STEP_HINT]
    # No submitted work yet -> consolidation not allowed, step hint repeats.
    assert svc.request_hint(student, session.session_id).level == L.STEP_HINT
    svc.submit_attempt(student, session.session_id, "8", "40 + 15u = 145 so 15u = 105, u = 8")
    consolidation = svc.request_hint(student, session.session_id)
    assert consolidation.level == L.PARTIAL_CONSOLIDATION
    assert "you wrote 105" in consolidation.text            # only the student's own verified value
    # One wrong attempt is not yet "persistent struggle".
    assert svc.request_hint(student, session.session_id).level == L.PARTIAL_CONSOLIDATION
    svc.submit_attempt(student, session.session_id, "6", "")
    analogue = svc.request_hint(student, session.session_id)
    assert analogue.level == L.ANALOGOUS_EXAMPLE
    assert "25 + 10p = 85" in analogue.text and "go back to your question" in analogue.text
    assert "7" not in analogue.text.replace("p = 6", "")    # active answer never appears


def test_consolidation_never_introduces_unverified_values(svc, student):
    session = svc.start(student, "LIN-001")
    for _ in range(4):
        svc.request_hint(student, session.session_id)
    svc.submit_attempt(student, session.session_id, "9", "I am not sure")
    turn = svc.request_hint(student, session.session_id)
    assert turn.level == L.PARTIAL_CONSOLIDATION
    assert "105" not in turn.text and "can't confirm" in turn.text


def test_direct_answer_request_is_refused_without_llm(svc, student, fake):
    session = svc.start(student, "INT-001")
    turn = svc.chat(student, session.session_id, "Just give me the answer please")
    assert turn.response_type == "refusal"
    assert "2205" not in turn.text and fake.calls == []


def test_leaky_model_reply_is_blocked_and_replaced(ctx, svc, student, fake):
    fake.replies = [{"message": "The final amount is 2205 dalasis."},
                    {"message": "After year one you have 2100, so keep going."}]
    session = svc.start(student, "INT-001")
    turn = svc.chat(student, session.session_id, "I don't know where to begin")
    assert turn.response_type == "fallback_leak_blocked"
    assert "2205" not in turn.text and "2100" not in turn.text
    reasons = [json.loads(e["payload_json"])["reason"] for e in events(ctx, "leak_blocked")]
    assert reasons == ["final_answer", "intermediate_value"]


def test_student_supplied_numbers_are_not_leaks(svc, student, fake):
    fake.replies = [{"message": "Good: you found 2100 after year one. What happens in year two?"}]
    session = svc.start(student, "INT-001")
    turn = svc.chat(student, session.session_id, "I multiplied 2000 by 1.05 and got 2100")
    assert turn.response_type.startswith("tutor_reply")
    assert "2100" in turn.text


def test_provider_down_falls_back_to_approved_text(ctx, svc, student, fake):
    fake.replies = [ProviderError("unavailable", "Ollama is not running")]
    session = svc.start(student, "LIN-002")
    turn = svc.chat(student, session.session_id, "How do I start?")
    assert turn.response_type == "fallback_provider"
    assert svc.item_for(session).scaffold_sequence.self_explanation in turn.text
    assert json.loads(events(ctx, "provider_failure")[0]["payload_json"])["code"] == "unavailable"


def test_malformed_output_is_retried_once_then_safe(svc, student, fake):
    fake.replies = ["this is not json", {"message": "What do you want x to equal?"}]
    session = svc.start(student, "LIN-002")
    assert svc.chat(student, session.session_id, "help").text.startswith("What do you want")
    fake.replies = ["nope", "still not json"]
    assert svc.chat(student, session.session_id, "help again").response_type == "fallback_provider"


def test_save_resume_terminate_never_reveals_answer(ctx, svc, student):
    session = svc.start(student, "INT-002")
    svc.save(student, session.session_id)
    assert svc.active_session(student) is None
    svc.resume(student, session.session_id)
    assert svc.active_session(student).item_version == session.item_version   # same version on resume
    svc.terminate(student, session.session_id, "ran out of time")
    assert ctx.exercises.get(session.session_id).state == ExerciseState.TERMINATED
    termination = ctx.db.query_one("SELECT * FROM termination WHERE session_id=?", (session.session_id,))
    assert termination["reason"] == "ran out of time" and json.loads(termination["stage_json"])["level"] == 0
    all_tutor_text = " ".join(m["content"] for m in svc.history(student, session.session_id))
    assert "6000" not in all_tutor_text
    with pytest.raises(ExerciseError):
        svc.resume(student, session.session_id)


def test_referral_is_recorded_for_lecturer(ctx, svc, student):
    session = svc.start(student, "LIN-003")
    svc.refer(student, session.session_id, "I need to talk to someone")
    from qmtutor.services.lecturer_service import LecturerService
    referrals = LecturerService(ctx).referrals(ctx.users.get("L001"))
    assert referrals[0]["session_id"] == session.session_id


def test_study_mode_locked_during_active_exercise(ctx, svc, student):
    study = StudyService(ctx)
    session = svc.start(student, "INT-001")
    with pytest.raises(StudyLocked):
        study.ask(student, "explain compound interest")
    svc.save(student, session.session_id)
    with pytest.raises(StudyLocked):      # pasting the saved exercise into study is refused
        study.ask(student, svc.item_for(session).stem)
    answer = study.ask(student, "what is the difference between simple and compound interest")
    assert answer.sources and answer.used_ai


def test_other_students_cannot_touch_my_exercise(ctx, svc, student):
    session = svc.start(student, "LIN-001")
    intruder = consented(ctx, "S004")
    for action in (lambda: svc.request_hint(intruder, session.session_id),
                   lambda: svc.submit_attempt(intruder, session.session_id, "7"),
                   lambda: svc.history(intruder, session.session_id),
                   lambda: svc.terminate(intruder, session.session_id)):
        with pytest.raises(PermissionDenied):
            action()
    with pytest.raises(PermissionDenied):
        svc.start(ctx.users.get("L001"), "LIN-001")


def test_correct_answer_with_weak_reasoning_kept_separate(ctx, svc, student, fake):
    ctx.settings["features"]["assess_reasoning_with_llm"] = True
    fake.replies = [{"method_selection": 0, "mathematical_steps": 0, "conceptual_explanation": 0,
                     "evidence_quote": "i guessed", "confidence": 0.8}]
    session = svc.start(student, "LIN-001")
    outcome = svc.submit_attempt(student, session.session_id, "7", "i guessed")
    assert outcome.completed
    evidence = ctx.evidence.for_student("S001")[0]
    assert evidence.final_answer_correct is True and evidence.reasoning_score == 0
    assert evidence.support == SupportCategory.INDEPENDENT


def test_supported_success_recorded_as_supported(ctx, svc, student):
    session = svc.start(student, "LIN-002")
    for _ in range(4):
        svc.request_hint(student, session.session_id)
    svc.submit_attempt(student, session.session_id, "x = 16", "")
    evidence = ctx.evidence.for_student("S001")[0]
    assert evidence.support == SupportCategory.HIGH_SUPPORT and evidence.max_scaffold_level == L.STEP_HINT


def test_unsupported_notation_does_not_count_as_attempt(svc, student):
    session = svc.start(student, "LIN-001")
    outcome = svc.submit_attempt(student, session.session_id, "seven-ish", "")
    assert outcome.verification.status.value == "unsupported"
    assert svc.active_session(student).attempts == 0


def test_wrong_variable_is_a_format_slip_not_an_attempt(svc, student):
    """D06: 'x = 7' when the answer is for u is saved, explained, and not counted."""
    session = svc.start(student, "LIN-001")
    outcome = svc.submit_attempt(student, session.session_id, "x = 7", "")
    assert outcome.verification.reason_code == "wrong_variable"
    assert not outcome.completed and outcome.proactive_turn is None
    assert "u = ..." in outcome.feedback and "hint" not in outcome.feedback
    assert svc.active_session(student).attempts == 0
    outcome = svc.submit_attempt(student, session.session_id, "u = 7", "")
    assert outcome.completed
    assert [a["attempt_number"] for a in svc.attempts(student, session.session_id)] == [0, 1]


def test_proactive_hints_off_by_default_then_on(ctx, svc, student):
    assert ctx.users.proactive_hints_on("S001") is False
    session = svc.start(student, "LIN-002")
    assert svc.submit_attempt(student, session.session_id, "15").proactive_turn is None
    svc.set_proactive_hints(student, True)
    turn = svc.submit_attempt(student, session.session_id, "14").proactive_turn
    assert turn is not None and turn.level == L.SELF_EXPLANATION
    assert events(ctx, "proactive_hint_setting_changed")


def test_unrestricted_arm_uses_same_model_without_policy(ctx, svc, fake):
    s2 = consented(ctx, "S002")
    fake.replies = [{"message": "The answer is 7 units because 145 - 40 = 105 and 105/15 = 7."}]
    session = svc.start(s2, "LIN-001")
    turn = svc.chat(s2, session.session_id, "just give me the answer")
    assert turn.response_type == "unrestricted_reply" and "7" in turn.text
    with pytest.raises(ExerciseError):
        svc.request_hint(s2, session.session_id)


def test_existing_support_arm_has_no_ai(ctx, svc, fake):
    s3 = consented(ctx, "S003")
    session = svc.start(s3, "LIN-001")
    with pytest.raises(ExerciseError):
        svc.chat(s3, session.session_id, "help")
    svc.save(s3, session.session_id)        # study mode is locked while the exercise is active
    answer = StudyService(ctx).ask(s3, "how do I solve a linear equation")
    assert not answer.used_ai and answer.sources and fake.calls == []


def test_transfer_check_has_no_hints_or_chat(ctx, svc, student):
    session = svc.start(student, "LIN-004", task_type="transfer")
    with pytest.raises(ExerciseError):
        svc.request_hint(student, session.session_id)
    with pytest.raises(ExerciseError):
        svc.chat(student, session.session_id, "help")
    svc.submit_attempt(student, session.session_id, "60 shirts", "")
    assert ctx.evidence.for_student("S001")[0].task_type == "transfer"


@pytest.mark.regression
def test_formula_is_not_given_below_plan_hint_level(ctx, svc, student, fake):
    """Owner screenshot: at level 1 the model handed over A = P(1 + r)^n, skipping two hint levels."""
    fake.replies = [{"message": "Use the compound interest formula A = P(1 + r)^n."},
                    {"message": "Use A = P(1 + r)^n, where P is the principal."}]
    session = svc.start(student, "INT-001")
    turn = svc.chat(student, session.session_id, "What formula should I use?")
    assert turn.response_type == "fallback_above_level"
    assert "P(1 + r)" not in turn.text
    assert events(ctx, "reply_above_level_blocked")


def test_formula_allowed_from_plan_hint_level(ctx, svc, student, fake):
    session = svc.start(student, "INT-001")
    for _ in range(3):
        svc.request_hint(student, session.session_id)              # now at level 3 (plan hint)
    fake.replies = [{"message": "You could use A = P(1 + r)^n. What are P, r and n here?"}]
    turn = svc.chat(student, session.session_id, "What formula should I use?")
    assert turn.response_type == "tutor_reply_level_3" and "P(1 + r)" in turn.text


def test_level_guard_ignores_ordinary_sentences_and_student_formulas():
    from qmtutor.llm.leak_guard import states_formula
    assert not states_formula("Let x = the number of units. What is fixed here?", [])
    assert not states_formula("You wrote A = P(1+r)^n. What is P?", ["A = P(1+r)^n"])
