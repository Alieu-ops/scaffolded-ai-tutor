"""
Scaffold controller: decides WHICH kind of support is allowed next.

This is deliberately plain Python, not an LLM. The LLM may only phrase a reply
inside the level chosen here; it cannot raise the level, reveal the answer or
change the policy. Every decision carries a reason code and the policy version
so a researcher can reconstruct why a student saw what they saw.

Inputs used (and nothing else): attempts so far, hints shown, the current
level, whether the student's message asks for the answer, the study arm, and
the student's proactive-hint preference. No inferred emotion or ability label.

Level summary (04_SCAFFOLDING_POLICY.md):
    0 independent attempt        4 step-focused hint
    1 self-explanation prompt    5 partial consolidation (student's own verified work)
    2 conceptual cue             6 analogous worked example (last resort)
    3 strategic hint             7 save / terminate / referral (student action)
"""

from __future__ import annotations

import re

from qmtutor.domain.models import PolicyConfig, ScaffoldDecision, ScaffoldLevel, StudyArm, SupportCategory

L = ScaffoldLevel

# Phrases that ask for the active answer or a full solution. Matching is a
# heuristic; the leak guard on the model's reply is the second, stronger layer.
ANSWER_REQUEST_PATTERNS = [
    r"\b(give|tell|show|send|just)\b.{0,25}\b(answer|solution|result)\b",
    r"\bwhat is the (final )?(answer|result|value)\b",
    r"\b(solve|work out|calculate|compute|do) (it|this|the question|the problem)( for me)?\b",
    r"\b(all|full|complete|every|each) (the )?(steps|working|solution)\b",
    r"\bignore (your|the|all|previous) (rules|instructions)\b",
    r"\b(pretend|act as|you are now|role.?play)\b",
    r"\bsystem prompt\b",
    r"\b(translate|encode|base64|in french|in wolof)\b.{0,30}\banswer\b",
]


def asks_for_answer(message: str) -> bool:
    """True when a chat message looks like a request for the answer or a policy bypass."""
    text = message.lower()
    return any(re.search(pattern, text) for pattern in ANSWER_REQUEST_PATTERNS)


def next_hint_level(current: ScaffoldLevel, attempts: int, hints_shown: int,
                    policy: PolicyConfig) -> tuple[ScaffoldLevel, str]:
    """
    The level a "Give me a hint" press may move to. Moves up one step at a time
    and stops at the highest level the evidence permits.
    Returns (level, reason_code).
    """
    proposed = ScaffoldLevel(min(int(current) + 1, int(policy.max_hint_level)))

    if proposed >= L.ANALOGOUS_EXAMPLE and not (
            attempts >= policy.min_attempts_for_analogue and hints_shown >= policy.min_hints_before_analogue):
        # Persistent struggle not yet shown: stay at the highest lower level.
        proposed = L.PARTIAL_CONSOLIDATION
        reason = "analogue_requires_persistent_struggle"
    else:
        reason = "escalate_one_level"

    if proposed == L.PARTIAL_CONSOLIDATION and attempts < policy.min_attempts_for_consolidation:
        # Nothing of the student's to consolidate yet: repeat the step hint.
        proposed = L.STEP_HINT
        reason = "consolidation_requires_student_work"

    if proposed == current and reason == "escalate_one_level":
        reason = "at_policy_ceiling"
    return proposed, reason


def decide_hint(arm: StudyArm, current: ScaffoldLevel, attempts: int, hints_shown: int,
                policy: PolicyConfig) -> ScaffoldDecision:
    """Decision for an explicit hint request (button press)."""
    inputs = {"attempts": attempts, "hints_shown": hints_shown, "current_level": int(current)}
    if arm != StudyArm.SCAFFOLDED:
        return ScaffoldDecision(level=current, action="no_scaffold_in_arm", reason_code=f"arm_{arm.value}",
                                policy_version=policy.policy_version, allowed=False, inputs=inputs)
    level, reason = next_hint_level(current, attempts, hints_shown, policy)
    action = {L.PARTIAL_CONSOLIDATION: "show_consolidation",
              L.ANALOGOUS_EXAMPLE: "show_analogue"}.get(level, "show_hint")
    return ScaffoldDecision(level=level, action=action, reason_code=reason,
                            policy_version=policy.policy_version, inputs=inputs)


def decide_chat(arm: StudyArm, current: ScaffoldLevel, message: str, attempts: int, hints_shown: int,
                policy: PolicyConfig) -> ScaffoldDecision:
    """
    Decision for a free-text chat message during an exercise. A chat message
    never escalates the level by itself; a direct-answer request is refused
    briefly and the student is offered the next permitted hint.
    """
    inputs = {"attempts": attempts, "hints_shown": hints_shown, "current_level": int(current)}
    if arm == StudyArm.UNRESTRICTED:
        return ScaffoldDecision(level=current, action="unrestricted_reply", reason_code="arm_unrestricted",
                                policy_version=policy.policy_version, inputs=inputs)
    if arm == StudyArm.EXISTING_SUPPORT:
        return ScaffoldDecision(level=current, action="no_ai_in_arm", reason_code="arm_existing_support",
                                policy_version=policy.policy_version, allowed=False, inputs=inputs)
    if asks_for_answer(message):
        return ScaffoldDecision(level=current, action="refuse_and_offer_hint", reason_code="direct_answer_request",
                                policy_version=policy.policy_version, inputs=inputs)
    # Replies stay within the current level's support (at least a self-explanation prompt).
    level = max(current, L.SELF_EXPLANATION)
    return ScaffoldDecision(level=level, action="tutor_reply", reason_code="reply_within_current_level",
                            policy_version=policy.policy_version, inputs=inputs)


def decide_after_wrong_answer(arm: StudyArm, current: ScaffoldLevel, attempts: int, hints_shown: int,
                              proactive_hints_on: bool, policy: PolicyConfig) -> ScaffoldDecision | None:
    """
    Proactive hints (off by default): after a wrong answer, show the next level
    automatically, still obeying the same ladder. Returns None when off.
    """
    if arm != StudyArm.SCAFFOLDED or not proactive_hints_on:
        return None
    decision = decide_hint(arm, current, attempts, hints_shown, policy)
    decision.reason_code = f"proactive:{decision.reason_code}"
    return decision


def support_category(max_level: ScaffoldLevel, policy: PolicyConfig) -> SupportCategory:
    """Map the highest level reached before success to independent / low / high support."""
    if max_level == L.INDEPENDENT:
        return SupportCategory.INDEPENDENT
    if max_level <= policy.low_support_max_level:
        return SupportCategory.LOW_SUPPORT
    return SupportCategory.HIGH_SUPPORT
