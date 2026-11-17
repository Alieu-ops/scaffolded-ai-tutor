"""
Domain models: the named shapes of data that move between components.

Why Pydantic: each model validates its own fields when it is created, so a
bad value (an unknown role, a scaffold level of 9, a malformed LLM reply)
fails loudly at the boundary instead of travelling silently through the app.
These models carry no Streamlit, SQL or LLM code, so they are easy to test.

Status words used across the project:
    Planned      described but not built
    Implemented  code exists
    Tested       a named test or review confirms the behaviour
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum, IntEnum

from pydantic import BaseModel, ConfigDict, Field


# -
# Enumerations (closed lists of allowed values)
# -
class Role(str, Enum):
    STUDENT = "student"
    LECTURER = "lecturer"
    RESEARCHER = "researcher"
    ADMINISTRATOR = "administrator"


class StudyArm(str, Enum):
    """The three evaluation conditions. Assigned server-side, never by the student."""
    SCAFFOLDED = "scaffolded"            # the proposed tutor
    UNRESTRICTED = "unrestricted"        # same model, no scaffold policy
    EXISTING_SUPPORT = "existing_support"  # no AI supplied by the study


class ContentStatus(str, Enum):
    """Lifecycle of an item or note version. Only APPROVED reaches students."""
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class ExerciseState(str, Enum):
    IN_PROGRESS = "in_progress"   # the protected state: study mode is locked
    SAVED = "saved"
    COMPLETED = "completed"
    TERMINATED = "terminated"
    REFERRED = "referred"         # student asked for human help


class ScaffoldLevel(IntEnum):
    """The policy ladder from 04_SCAFFOLDING_POLICY.md. Higher = more support."""
    INDEPENDENT = 0
    SELF_EXPLANATION = 1
    CONCEPTUAL_CUE = 2
    STRATEGIC_HINT = 3
    STEP_HINT = 4
    PARTIAL_CONSOLIDATION = 5
    ANALOGOUS_EXAMPLE = 6
    EXIT_OR_REFERRAL = 7


class SupportCategory(str, Enum):
    """How much help came before a success. Drives the learner profile."""
    INDEPENDENT = "independent"   # no tutor hints at all
    LOW_SUPPORT = "low_support"   # levels 1-3
    HIGH_SUPPORT = "high_support"  # levels 4-6


class VerificationStatus(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNSUPPORTED = "unsupported"   # notation the safe parser does not accept
    EMPTY = "empty"


class ChallengeStatus(str, Enum):
    OPEN = "open"
    UPHELD = "upheld"     # the evidence stands as recorded
    AMENDED = "amended"   # a correction or context note is added
    REMOVED = "removed"   # evidence excluded from the profile (history kept)


# -
# Users
# -
class UserAccount(BaseModel):
    """Operational identity. Never exported to research files."""
    model_config = ConfigDict(frozen=True)
    user_id: str
    display_name: str        # synthetic in the prototype, e.g. "Student S001"
    role: Role
    active: bool = True


# -
# Curriculum and content
# -
class LearningOutcome(BaseModel):
    outcome_id: str
    course_id: str
    unit_title: str
    description: str
    prerequisite_ids: list[str] = []
    status: ContentStatus = ContentStatus.DRAFT


class AnswerSpec(BaseModel):
    """
    How a final answer is checked. Read by the deterministic verifier only;
    it is never placed in the LLM's context.
    """
    canonical_expression: str
    acceptable_forms: list[str] = []
    variable: str | None = None          # e.g. "u" if "u = 7" should be accepted
    units: str | None = None             # shown to the student as a reminder
    unit_words: list[str] = []           # words stripped before parsing, e.g. "units"
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    rounding_rule: str = "exact"


class Checkpoint(BaseModel):
    """
    A verified intermediate value used by Level 5 (partial consolidation).
    The tutor may only restate a checkpoint if the STUDENT already wrote it.
    """
    label: str          # e.g. "the variable cost (total minus fixed fee)"
    value: str          # e.g. "105"


class WrongAnswerPattern(BaseModel):
    """
    A typical wrong answer that reveals a known misconception, written by the lecturer.
    Example: 2200 for a two-year compound interest question = simple interest used instead.
    A match is recorded as a POSSIBLE misconception (candidate), never as a fact.
    """
    value: str                      # the wrong answer, e.g. "2200" or "185/15"
    misconception_id: str
    note: str = ""                  # lecturer's explanation of how this answer arises


class ScaffoldSequence(BaseModel):
    """Lecturer-authored support text for levels 1-4 and the analogue link for 6."""
    self_explanation: str
    conceptual_cue: str
    strategic_hint: str
    step_hint: str
    analogous_example_id: str | None = None


class Item(BaseModel):
    """One exercise version. Immutable once approved: edits create a new version."""
    item_id: str
    item_version: str
    course_id: str
    outcome_id: str
    status: ContentStatus = ContentStatus.DRAFT
    skill: str
    subskill: str
    difficulty: str
    question_type: str
    stem: str
    answer_specification: AnswerSpec | None = None
    calculator_policy: str = "basic"
    misconception_ids: list[str] = []
    scaffold_sequence: ScaffoldSequence | None = None
    checkpoints: list[Checkpoint] = []
    common_wrong_answers: list[WrongAnswerPattern] = []   # diagnostic: wrong answer -> misconception
    worked_solution: list[str] = []       # used for leak checks, never shown in exercise mode
    transfer_flag: bool = False
    purpose: str | None = None
    must_not_be_assigned_as_active_pair: bool = False
    return_instruction: str | None = None

    @property
    def is_analogue(self) -> bool:
        return self.question_type == "worked_analogue"

    @property
    def key(self) -> str:
        return f"{self.item_id}@{self.item_version}"


class Misconception(BaseModel):
    misconception_id: str
    concept: str
    label: str
    observable_evidence: str
    approved_feedback: str
    status: ContentStatus = ContentStatus.DRAFT


# -
# Scaffold policy (versioned, human-approved)
# -
class PolicyConfig(BaseModel):
    """
    The numbers the scaffold controller uses. Stored as a versioned record;
    only a lecturer can approve a new version. The LLM never edits this.
    """
    policy_version: str
    max_hint_level: ScaffoldLevel = ScaffoldLevel.ANALOGOUS_EXAMPLE
    # Level 5 restates the student's own verified work, so it needs some work.
    min_attempts_for_consolidation: int = Field(1, ge=0)
    # Level 6 (worked analogue) is a last resort after persistent struggle.
    min_attempts_for_analogue: int = Field(2, ge=0)
    min_hints_before_analogue: int = Field(3, ge=0)
    # Proactive hints show the next level automatically after a wrong answer.
    proactive_hints_default: bool = False
    # Support levels that count as "low" vs "high" for learner evidence.
    low_support_max_level: ScaffoldLevel = ScaffoldLevel.STRATEGIC_HINT


# -
# Interaction records
# -
class MathVerification(BaseModel):
    status: VerificationStatus
    normalised_answer: str | None = None
    method: str                 # "numeric_tolerance", "symbolic_difference", ...
    reason_code: str            # machine-readable, e.g. "outside_tolerance"
    message: str                # short, student-safe explanation
    assumptions: str | None = None


class ScaffoldDecision(BaseModel):
    """What the controller allowed, and why. Logged with the policy version."""
    level: ScaffoldLevel
    action: str                 # e.g. "show_hint", "refuse_and_offer_hint", "show_analogue"
    reason_code: str
    policy_version: str
    allowed: bool = True
    inputs: dict = {}


class ExerciseSession(BaseModel):
    session_id: str
    student_id: str
    item_id: str
    item_version: str
    policy_version: str
    arm: StudyArm
    state: ExerciseState
    current_level: ScaffoldLevel = ScaffoldLevel.INDEPENDENT
    max_level_reached: ScaffoldLevel = ScaffoldLevel.INDEPENDENT
    attempts: int = 0
    hints_shown: int = 0
    started_at: datetime
    updated_at: datetime


class CompetenceEvidence(BaseModel):
    evidence_id: str
    student_id: str
    outcome_id: str
    item_key: str
    task_type: str                      # practice / transfer / retention
    final_answer_correct: bool
    reasoning_score: int | None = None  # provisional, may be None (not assessed)
    reasoning_assessor: str | None = None   # "llm_provisional" / "lecturer"
    support: SupportCategory
    max_scaffold_level: ScaffoldLevel
    attempts: int
    source_event_id: str
    created_at: datetime
    excluded: bool = False              # set only by a lecturer challenge decision
    note: str | None = None


class ProfileChallenge(BaseModel):
    challenge_id: str
    student_id: str
    evidence_id: str
    statement: str
    status: ChallengeStatus = ChallengeStatus.OPEN
    reviewer_id: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
