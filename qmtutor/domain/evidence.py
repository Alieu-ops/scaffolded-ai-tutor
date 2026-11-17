"""
Learner evidence rules: turn evidence records into a per-outcome summary a
student and lecturer can read and challenge.

Why rules and not a model (BKT, DKT, IRT)? There is no pilot data to fit or
validate a model yet, and the summary must be explainable to the student
whose profile it is. These rules are transparent and every line of the
summary points back to the evidence records that produced it.

Principles enforced here:
    - evidence belongs to a learning outcome, never a global ability score;
    - independent, low-support and high-support successes are kept apart;
    - final-answer correctness and reasoning quality are separate;
    - evidence a lecturer excluded after a challenge is not counted, but kept;
    - few records means high uncertainty, and the summary says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qmtutor.domain.models import CompetenceEvidence, SupportCategory

MIN_RECORDS_FOR_MODERATE_CONFIDENCE = 3


@dataclass
class OutcomeSummary:
    outcome_id: str
    independent_correct: int = 0
    supported_correct: int = 0          # low or high support
    high_support_correct: int = 0
    incorrect_or_unfinished: int = 0
    transfer_correct: int = 0
    transfer_attempted: int = 0
    reasoning_scores: list[int] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    label: str = ""
    uncertainty: str = ""
    explanation: str = ""

    @property
    def total(self) -> int:
        return len(self.evidence_ids)


def summarise_outcome(outcome_id: str, records: list[CompetenceEvidence]) -> OutcomeSummary:
    """Build the readable summary for one outcome from its (non-excluded) evidence."""
    summary = OutcomeSummary(outcome_id)
    for record in records:
        if record.excluded:
            continue
        summary.evidence_ids.append(record.evidence_id)
        if record.task_type == "transfer":
            summary.transfer_attempted += 1
            summary.transfer_correct += int(record.final_answer_correct)
        if not record.final_answer_correct:
            summary.incorrect_or_unfinished += 1
        elif record.support == SupportCategory.INDEPENDENT:
            summary.independent_correct += 1
        else:
            summary.supported_correct += 1
            summary.high_support_correct += int(record.support == SupportCategory.HIGH_SUPPORT)
        if record.reasoning_score is not None:
            summary.reasoning_scores.append(record.reasoning_score)

    summary.label, summary.explanation = _label(summary)
    summary.uncertainty = ("high: very little evidence yet" if summary.total < MIN_RECORDS_FOR_MODERATE_CONFIDENCE
                           else "moderate: based on a few practice tasks, not an assessment")
    return summary


def _label(s: OutcomeSummary) -> tuple[str, str]:
    """
    Plain-language label. The thresholds are a first proposal for review, not
    validated cut-offs, and the profile is formative only (never for grading).
    """
    if s.total == 0:
        return "No evidence yet", "You have not completed a task for this outcome."
    if s.transfer_correct >= 1 and s.independent_correct >= 1:
        return ("Independent success, including an unfamiliar problem",
                f"{s.independent_correct} correct without hints and {s.transfer_correct} correct transfer task(s).")
    if s.independent_correct >= 2:
        return ("Independent success on practice tasks",
                f"{s.independent_correct} correct without hints; try an unfamiliar problem next.")
    # Found in the browser check (3 Oct 2026): one unaided success used to fall through to
    # "mostly with support", contradicting its own evidence line.
    if s.independent_correct >= 1 and s.independent_correct >= s.supported_correct:
        return ("Early independent success",
                f"{s.independent_correct} correct without hints and {s.supported_correct} with hints; "
                "more tasks will make this clearer.")
    if s.independent_correct + s.supported_correct >= 1:
        return ("Developing: success mostly with support",
                f"{s.independent_correct} correct without hints, {s.supported_correct} correct with hints "
                f"({s.high_support_correct} after strong support).")
    return "Not yet: keep practising", f"{s.incorrect_or_unfinished} task(s) not yet answered correctly."
