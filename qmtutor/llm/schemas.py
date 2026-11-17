"""
Structured output contracts for the LLM.

The model is asked to reply in JSON matching one of these Pydantic models.
Ollama enforces the JSON shape (its `format` option takes a JSON schema), and
Pydantic then validates types, ranges and lengths. A reply that fails
validation is treated as a provider failure: it is retried once, then
replaced by safe, lecturer-approved text. It is never shown half-parsed.

Valid structure does NOT mean correct or safe content; that is why the leak
guard and the deterministic verifier still run afterwards.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _rescale_confidence(value):
    """
    Found in live testing (3 Oct 2026): llama3.2:3b often returns confidence on a
    0-10 or 0-100 scale. Ollama's JSON-schema mode enforces structure and types,
    NOT numeric ranges. Obvious rescalings are accepted; anything else still fails.
    """
    if isinstance(value, (int, float)) and 1 < value <= 10:
        return value / 10
    if isinstance(value, (int, float)) and 10 < value <= 100:
        return value / 100
    return value


class TutorReply(BaseModel):
    """Exercise-mode reply (scaffolded arm)."""
    message: str = Field(min_length=1, max_length=900, description="What the tutor says to the student.")
    question_to_student: str = Field(default="", max_length=300,
                                     description="One short question asking the student to take the next step.")
    confidence: float = Field(default=0.5, ge=0, le=1, description="How confident the tutor is that the reply helps.")
    risk_flags: list[str] = Field(default=[], description="e.g. 'student_asked_for_answer', 'off_topic'.")
    _confidence_scale = field_validator("confidence", mode="before")(_rescale_confidence)


class StudyReply(BaseModel):
    """Study-mode explanation grounded in approved notes."""
    explanation: str = Field(min_length=1, max_length=1500)
    example: str = Field(default="", max_length=800, description="A different worked example, if helpful.")
    check_question: str = Field(default="", max_length=300, description="A question to check understanding.")
    source_ids: list[str] = Field(default=[], description="note ids from the provided notes that were used.")
    confidence: float = Field(default=0.5, ge=0, le=1)
    _confidence_scale = field_validator("confidence", mode="before")(_rescale_confidence)


class UnrestrictedReply(BaseModel):
    """Unrestricted-AI arm: a general assistant reply, no tutoring policy."""
    message: str = Field(min_length=1, max_length=2500)


class ReasoningAssessment(BaseModel):
    """
    PROVISIONAL rubric scores for a student's written reasoning
    (content/reasoning_rubric.csv). Shown to lecturers as provisional only.
    """
    method_selection: int = Field(ge=0, le=2)
    mathematical_steps: int = Field(ge=0, le=2)
    conceptual_explanation: int = Field(ge=0, le=2)
    evidence_quote: str = Field(default="", max_length=300,
                                description="Short quote from the student's reasoning supporting the scores.")
    comment: str = Field(default="", max_length=400,
                         description="One or two sentences for the lecturer, e.g. where the method goes wrong.")
    confidence: float = Field(default=0.5, ge=0, le=1)

    _confidence_scale = field_validator("confidence", mode="before")(_rescale_confidence)
