"""
Exercise state machine. The server-side record of where a student is in an
exercise; Streamlit session state is never the source of truth.

    in_progress --save-------> saved --resume--> in_progress
    in_progress --complete---> completed            (final)
    in_progress --terminate--> terminated           (final, answer NOT revealed)
    in_progress --refer------> referred             (final, human help requested)
    saved       --terminate--> terminated

Only IN_PROGRESS is "protected": while a student has one, study mode is locked
(see services/study_service.py). That reduces an in-app bypass; it does not
pretend to stop a student using an outside AI.
"""

from __future__ import annotations

from qmtutor.domain.models import ExerciseState

ALLOWED_TRANSITIONS: dict[ExerciseState, set[ExerciseState]] = {
    ExerciseState.IN_PROGRESS: {ExerciseState.SAVED, ExerciseState.COMPLETED,
                                ExerciseState.TERMINATED, ExerciseState.REFERRED},
    ExerciseState.SAVED: {ExerciseState.IN_PROGRESS, ExerciseState.TERMINATED},
    ExerciseState.COMPLETED: set(),
    ExerciseState.TERMINATED: set(),
    ExerciseState.REFERRED: set(),
}

OPEN_STATES = {ExerciseState.IN_PROGRESS, ExerciseState.SAVED}


class InvalidTransition(Exception):
    """A requested state change is not allowed (e.g. resuming a completed exercise)."""


def check_transition(current: ExerciseState, target: ExerciseState) -> None:
    """Raise InvalidTransition unless current -> target is in the table above."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"Cannot move an exercise from {current.value} to {target.value}.")
