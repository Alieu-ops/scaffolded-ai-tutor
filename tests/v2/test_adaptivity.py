"""
Adaptive practice: focus each student's practice on their weaknesses.
Checks that typical wrong answers become POSSIBLE misconceptions, that weak topics and
misconception-targeting exercises are recommended first with a reason, that strong topics
come last, that only the scaffolded group gets this, and that the tutor receives the
lecturer's approved feedback for a misconception it has seen.
"""

import pytest

from qmtutor.domain import adaptivity
from qmtutor.services.exercise_service import ExerciseService
from tests.v2.conftest import consented


@pytest.fixture
def svc(ctx):
    return ExerciseService(ctx)


def test_typical_wrong_answer_is_matched():
    from qmtutor.services.context import PROJECT_ROOT
    from qmtutor.content.importer import load_item_files
    items, _ = load_item_files(PROJECT_ROOT / "content" / "items")
    interest = next(i for i in items if i.item_id == "INT-001")
    linear = next(i for i in items if i.item_id == "LIN-001")
    assert adaptivity.matching_misconceptions(interest, "2200") == ["MIS-003"]
    assert adaptivity.matching_misconceptions(interest, "2205") == []             # correct answer: nothing
    assert adaptivity.matching_misconceptions(linear, "12.33") == ["MIS-002"]    # rounded form still matches


def test_wrong_answer_records_possible_misconception(ctx, svc, student):
    session = svc.start(student, "INT-001")
    svc.submit_attempt(student, session.session_id, "2200", "2000 x 0.05 x 2 = 200")
    row = ctx.db.query_one("SELECT * FROM misconception_evidence")
    assert row["misconception_id"] == "MIS-003" and row["status"] == "candidate"
    assert ctx.db.query_one("SELECT COUNT(*) n FROM event WHERE event_type='misconception_candidate_created'")["n"] == 1


def test_new_student_gets_untried_topics_with_reasons(svc, student):
    topics, recs = svc.focus(student)
    assert [t.label for t in topics] == ["No evidence yet", "No evidence yet"]
    assert recs and all(r.reason == "You have not tried this topic yet." for r in recs)


def test_weak_topic_and_its_misconception_come_first(ctx, svc, student):
    # Strong on linear equations (correct, no hints) ...
    done = svc.start(student, "LIN-001")
    svc.submit_attempt(student, done.session_id, "7")
    # ... but interest shows the simple-for-compound mix-up, and the exercise is ended unsolved.
    weak = svc.start(student, "INT-001")
    svc.submit_attempt(student, weak.session_id, "2200")
    svc.terminate(student, weak.session_id)
    topics, recs = svc.focus(student)
    assert topics[0].outcome_id == "LO-03" and "Simple and compound interest confused" in topics[0].possible_misconceptions
    assert recs[0].item.outcome_id == "LO-03"
    assert "mix-up" in recs[0].reason
    assert topics[-1].outcome_id == "LO-01"                        # the strength comes last
    assert "LIN-001" not in {r.item.item_id for r in recs}        # completed exercises are not repeated


def test_only_scaffolded_group_gets_recommendations(ctx, svc):
    for user_id in ("S002", "S003"):                              # unrestricted AI, existing support
        assert svc.focus(consented(ctx, user_id)) == ([], [])


def test_tutor_prompt_includes_lecturer_feedback_for_seen_misconception(ctx, svc, student, fake):
    first = svc.start(student, "INT-001")
    svc.submit_attempt(student, first.session_id, "2200")
    svc.chat(student, first.session_id, "I am confused about year two")
    prompt = fake.calls[-1]["system"]
    assert "possible difficulty" in prompt and "added to the base before the next period" in prompt
    assert "2205" not in prompt                                     # still never the answer
