"""
Adaptive practice: help each student most where they are weakest.

Two transparent rules, no trained model (there is no pilot data to train one, and a
student must be able to see why something was recommended):

1. Spotting weaknesses
   - per learning outcome, from the evidence summary (domain/evidence.py):
     not yet / mostly with support  -> high priority
     no evidence yet                 -> medium (explore)
     early independent success       -> lower
     independent success             -> lowest
   - possible misconceptions: a wrong answer that matches a lecturer's "typical wrong
     answer" pattern (e.g. 2200 = simple interest used for a compound question). These are
     POSSIBLE only; one slip is not a diagnosis, so they add weight gradually.

2. Choosing practice
   - topics in priority order; inside a topic, exercises not yet completed, and first
     those that target the student's possible misconceptions; easier exercises first when
     the topic is weak.
   - every recommendation carries a plain-language reason.

Where this sits in the research design: adaptivity is part of the tutor intervention, so by
default only the scaffolded group gets recommendations (config: adaptive_practice_arms).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qmtutor.domain.evidence import OutcomeSummary
from qmtutor.domain.models import Item, Misconception, VerificationStatus
from qmtutor.mathcheck.verifier import verify_answer

PRIORITY_BY_LABEL = [               # first matching label prefix wins
    ("Not yet", 3.0), ("Developing", 3.0), ("No evidence", 2.0),
    ("Early independent", 1.0), ("Independent success on practice", 0.5), ("Independent success,", 0.0),
]
MISCONCEPTION_WEIGHT = 0.75         # per sighting, capped below
MISCONCEPTION_CAP = 2.0
MATCH_TOLERANCE = 0.01              # so "12.33" matches a pattern written as "185/15"


def matching_misconceptions(item: Item, student_answer: str) -> list[str]:
    """Misconception ids whose typical wrong answer matches what the student entered."""
    if item.answer_specification is None:
        return []
    found = []
    for pattern in item.common_wrong_answers:
        spec = item.answer_specification.model_copy(update={
            "canonical_expression": pattern.value, "acceptable_forms": [],
            "absolute_tolerance": max(item.answer_specification.absolute_tolerance, MATCH_TOLERANCE)})
        if verify_answer(student_answer, spec).status == VerificationStatus.CORRECT:
            found.append(pattern.misconception_id)
    return found


@dataclass
class TopicFocus:
    outcome_id: str
    description: str
    priority: float
    label: str                      # from the evidence summary, e.g. "Developing: success mostly with support"
    possible_misconceptions: list[str] = field(default_factory=list)   # misconception labels


@dataclass
class Recommendation:
    item: Item
    reason: str
    priority: float


def topic_priorities(outcomes: dict[str, str], summaries: dict[str, OutcomeSummary],
                     items: list[Item], misconception_counts: dict[str, int],
                     misconceptions: dict[str, Misconception]) -> list[TopicFocus]:
    """Every outcome that has practice items, most in need of practice first."""
    topics = []
    for outcome_id, description in outcomes.items():
        outcome_items = [i for i in items if i.outcome_id == outcome_id]
        if not outcome_items:
            continue
        summary = summaries.get(outcome_id)
        label = summary.label if summary else "No evidence yet"
        priority = next((p for prefix, p in PRIORITY_BY_LABEL if label.startswith(prefix)), 2.0)
        linked = {m for i in outcome_items for m in i.misconception_ids}
        seen = {m: n for m, n in misconception_counts.items() if m in linked}
        priority += min(MISCONCEPTION_CAP, MISCONCEPTION_WEIGHT * sum(seen.values()))
        topics.append(TopicFocus(outcome_id, description, round(priority, 2), label,
                                 [misconceptions[m].label for m in seen if m in misconceptions]))
    return sorted(topics, key=lambda t: (-t.priority, t.outcome_id))


def recommend(topics: list[TopicFocus], items: list[Item], completed_item_ids: set[str],
              misconception_counts: dict[str, int], misconceptions: dict[str, Misconception],
              limit: int = 3) -> list[Recommendation]:
    """Up to `limit` exercises, from the weakest topics first, each with a reason."""
    recommendations: list[Recommendation] = []
    for topic in topics:
        open_items = [i for i in items if i.outcome_id == topic.outcome_id and i.item_id not in completed_item_ids]
        if not open_items:
            continue
        weak = topic.priority >= 2.0

        def sort_key(item: Item):
            targets = sum(misconception_counts.get(m, 0) for m in item.misconception_ids)
            easier_first = 0 if item.difficulty == "Introductory" else 1
            return (-targets, easier_first if weak else -easier_first, item.item_id)

        best = sorted(open_items, key=sort_key)[0]
        recommendations.append(Recommendation(best, _reason(topic, best, misconception_counts, misconceptions),
                                              topic.priority))
        if len(recommendations) >= limit:
            break
    return recommendations


def _reason(topic: TopicFocus, item: Item, counts: dict[str, int], misconceptions: dict[str, Misconception]) -> str:
    targeted = [misconceptions[m].label.lower() for m in item.misconception_ids if counts.get(m) and m in misconceptions]
    if targeted:
        return f"Practises a possible mix-up seen in your answers: {targeted[0]}."
    if topic.label.startswith(("Not yet", "Developing")):
        return "You have needed help on this topic, so more practice here should help most."
    if topic.label.startswith("No evidence"):
        return "You have not tried this topic yet."
    if topic.label.startswith("Early independent"):
        return "A good start; one more on your own will make it clearer."
    return "You are doing well here; this keeps it fresh."
