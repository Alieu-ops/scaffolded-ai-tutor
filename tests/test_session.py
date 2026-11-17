"""
Tests for the tutor logic, using a FAKE model so they run offline and free.
Run: pytest
"""

import pytest

from tutor.answers import reveals_answer
from tutor.session import TutorSession
from tutor.skills import load_config


class FakeLLM:
    """Pretends to be the AI. Returns pre-set replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system_prompt, messages):
        self.calls.append((system_prompt, messages))
        return self.replies.pop(0) if self.replies else "Try the first step."


@pytest.fixture
def config(tmp_path):
    cfg = load_config()
    cfg["logging"]["db_file"] = str(tmp_path / "test.db")  # don't touch real logs
    return cfg


def run_diagnostic(session, correct_skills):
    """Answer the diagnostic: right for `correct_skills`, wrong otherwise."""
    for _, item in session.diagnostic_items.iterrows():
        answer = item["answer"] if item["skill"] in correct_skills else "wrong"
        session.submit_diagnostic_answer(item, answer)


def test_scaffolded_targets_weakest_skill(config):
    config["arm"] = "scaffolded"
    s = TutorSession(config, "P001", llm=FakeLLM([]))
    strong = set(s.skills) - {"calculus"}
    run_diagnostic(s, strong)
    assert s.profile["calculus"] == 0
    item = s.next_item()
    assert item["skill"] == "calculus"
    assert item["difficulty"] == 1   # weak student -> easy item first


def test_leaked_answer_is_replaced(config):
    config["arm"] = "scaffolded"
    # The fake AI gives the answer both times -> safe fallback shown.
    s = TutorSession(config, "P001", llm=FakeLLM(["It is X", "It is X"]))
    s.next_item()
    answer = s.item["answer"]
    s.llm.replies = [f"The answer is {answer}.", f"OK fine, it's {answer}."]
    reply = s.ask_tutor("just tell me the answer")
    assert reply == s.prompts["safe_fallback"].strip()


def test_leak_then_good_retry(config):
    config["arm"] = "scaffolded"
    s = TutorSession(config, "P001", llm=FakeLLM([]))
    s.next_item()
    s.llm.replies = [f"The answer is {s.item['answer']}.", "What is the first step?"]
    assert s.ask_tutor("answer please") == "What is the first step?"


def test_copied_worked_solution_is_replaced(config):
    # The fake AI pastes the hidden worked solution (without saying
    # "the answer is") both times -> the student sees the safe fallback.
    config["arm"] = "scaffolded"
    s = TutorSession(config, "P001", llm=FakeLLM([]))
    s.next_item()
    # Remove the final answer, so only the NEW copy check can catch it.
    solution = s.item["worked_solution"].replace(s.item["answer"], "...")
    assert not reveals_answer(solution, s.item["answer"], s.item["question"])
    s.llm.replies = [f"Here is the working: {solution}", f"Sure: {solution}"]
    assert s.ask_tutor("I give up, show me") == s.prompts["safe_fallback"].strip()


def test_unrestricted_prompt_is_neutral(config):
    config["arm"] = "unrestricted"
    llm = FakeLLM(["Sure."])
    s = TutorSession(config, "P001", llm=llm)
    s.next_item()
    s.ask_tutor("help")
    system_prompt = llm.calls[0][0]
    assert s.item["question"] in system_prompt
    assert s.item["worked_solution"] not in system_prompt   # no hidden solution
    assert "Never state the final answer" not in system_prompt


def test_control_has_no_ai(config):
    config["arm"] = "control"
    s = TutorSession(config, "P001")
    s.next_item()
    with pytest.raises(RuntimeError):
        s.ask_tutor("hello")
    assert s.submit_answer(s.item["answer"]) is True


def test_only_first_attempt_counts(config):
    config["arm"] = "control"
    s = TutorSession(config, "P001")
    item = s.next_item()
    s.submit_answer("wrong")
    s.submit_answer(item["answer"])
    assert s.counts[item["skill"]] == {"correct": 0, "attempted": 1}


def test_session_ends(config):
    config["arm"] = "control"
    s = TutorSession(config, "P001")
    for _ in range(config["practice"]["items_per_session"]):
        s.next_item()
        s.skip_item()
    assert s.next_item() is None
