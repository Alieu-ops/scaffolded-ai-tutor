"""
Milestone 5 tests: what the LLM is allowed to see, and its output contracts.

The most important test here: for EVERY approved practice item and EVERY
scaffold level, the prompt sent to the model contains neither the answer, nor
the worked solution, nor an unverified checkpoint value.
"""

from collections import Counter

import pytest
from pydantic import ValidationError

from qmtutor.domain.models import ScaffoldLevel
from qmtutor.llm import prompts
from qmtutor.llm.leak_guard import check_reply
from qmtutor.llm.providers import FakeProvider, ProviderError, generate_with_retry
from qmtutor.llm.schemas import ReasoningAssessment, TutorReply
from qmtutor.mathcheck.verifier import numbers_in_text
from qmtutor.services.exercise_service import ExerciseService


TEMPLATE_NUMBERS = Counter(numbers_in_text(prompts.load_prompts()["scaffolded_exercise"]))


def test_prompt_never_contains_answer_or_hidden_steps(ctx, student):
    items = ExerciseService(ctx).available_items(student)
    assert items
    for item in items:
        answer = float(item.answer_specification.canonical_expression)
        hidden = {float(c.value) for c in item.checkpoints}
        for level in list(ScaffoldLevel)[:6]:
            system = prompts.scaffolded_exercise_prompt(item, level, verified=[], passages=[])
            # Ignore numbers that belong to the fixed template wording ("Rule 7", "70 words").
            numbers = list((Counter(numbers_in_text(system)) - TEMPLATE_NUMBERS).elements())
            assert not any(abs(n - answer) < 1e-9 for n in numbers), (item.item_id, level)
            assert not any(abs(n - h) < 1e-9 for n in numbers for h in hidden), (item.item_id, level)
            for step in item.worked_solution:
                assert step not in system


def test_prompt_includes_only_student_verified_work_at_level_5(ctx):
    item = ctx.content.latest_approved("LIN-001")
    verified = [(item.checkpoints[0], "105")]
    system = prompts.scaffolded_exercise_prompt(item, ScaffoldLevel.PARTIAL_CONSOLIDATION, verified, [])
    assert "the student wrote 105" in system


def test_exercise_chat_sends_no_answer_to_model(ctx, student, fake):
    service = ExerciseService(ctx)
    session = service.start(student, "INT-003")
    service.chat(student, session.session_id, "where do I start")
    sent = fake.calls[0]["system"] + " ".join(m["content"] for m in fake.calls[0]["messages"])
    assert "13382" not in sent and "10600" not in sent


def test_schema_rejects_bad_values():
    with pytest.raises(ValidationError):
        TutorReply(message="")
    with pytest.raises(ValidationError):
        TutorReply(message="ok", confidence=-1)
    with pytest.raises(ValidationError):
        ReasoningAssessment(method_selection=5, mathematical_steps=0, conceptual_explanation=0)


def test_generate_with_retry_bounds_retries():
    provider = FakeProvider(["bad", "bad", "bad"])
    with pytest.raises(ProviderError) as error:
        generate_with_retry(provider, "s", [], TutorReply, max_retries=1)
    assert error.value.code == "invalid_output" and len(provider.calls) == 2


def test_non_format_errors_are_not_retried():
    provider = FakeProvider([ProviderError("timeout", "slow"), {"message": "ok"}])
    with pytest.raises(ProviderError):
        generate_with_retry(provider, "s", [], TutorReply)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("reply,leaks", [
    ("The answer is 7.", True),
    ("So u equals seven, which is 7 units.", True),
    ("15u = 105, now divide.", True),           # intermediate value the student has not written
    ("What is left after removing the fixed fee?", False),
    ("Use the 40 dalasi fee and the 15 per unit.", False),   # numbers from the question are fine
])
def test_leak_guard_cases(ctx, reply, leaks):
    item = ctx.content.latest_approved("LIN-001")
    assert check_reply(reply, item, student_texts=[]).leaked is leaks


@pytest.mark.regression
def test_confidence_on_other_scales_is_rescaled_found_in_live_test():
    assert TutorReply(message="ok", confidence=8).confidence == 0.8
    assert TutorReply(message="ok", confidence=75).confidence == 0.75
    with pytest.raises(ValidationError):
        TutorReply(message="ok", confidence=500)
