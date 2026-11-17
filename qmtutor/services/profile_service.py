"""
Student profile and challenges.

A student sees, for each learning outcome, a plain-language summary plus the
individual evidence records behind it (date, task, support used, result).
They can challenge any record. A lecturer then upholds, amends (adds a note)
or removes it from the profile, with a reason. Nothing is deleted: removed
evidence is flagged `excluded`, and every decision is logged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from qmtutor.domain.evidence import OutcomeSummary, summarise_outcome
from qmtutor.domain.models import ChallengeStatus, CompetenceEvidence, ProfileChallenge, Role, UserAccount
from qmtutor.services.auth import PermissionDenied, require_role, require_self_or_staff
from qmtutor.services.context import AppContext
from qmtutor.storage.events import log_event


class ProfileService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def profile(self, viewer: UserAccount, student_id: str) -> list[tuple[OutcomeSummary, list[CompetenceEvidence]]]:
        """Per-outcome summaries with their evidence. Students: own profile only."""
        require_self_or_staff(viewer, student_id)
        evidence = self.ctx.evidence.for_student(student_id)
        result = []
        for outcome in self.ctx.content.outcomes():
            records = [e for e in evidence if e.outcome_id == outcome.outcome_id]
            if records:
                result.append((summarise_outcome(outcome.outcome_id, records), records))
        with self.ctx.db.transaction() as conn:
            log_event(conn, "profile_viewed", actor_id=viewer.user_id, subject_id=student_id,
                      payload={"viewer_role": viewer.role.value})
        return result

    def submit_challenge(self, student: UserAccount, evidence_id: str, statement: str) -> ProfileChallenge:
        require_role(student, {Role.STUDENT})
        evidence = self.ctx.evidence.get(evidence_id)
        if evidence is None or evidence.student_id != student.user_id:
            raise PermissionDenied("You can only challenge your own evidence.")
        if not statement.strip():
            raise ValueError("Please explain what you think is wrong or missing.")
        challenge = ProfileChallenge(challenge_id=uuid.uuid4().hex, student_id=student.user_id,
                                     evidence_id=evidence_id, statement=statement.strip()[:1000],
                                     created_at=datetime.now(timezone.utc))
        with self.ctx.db.transaction() as conn:
            self.ctx.evidence.add_challenge(conn, challenge)
            log_event(conn, "profile_challenge_submitted", actor_id=student.user_id, subject_id=student.user_id,
                      payload={"challenge_id": challenge.challenge_id, "evidence_id": evidence_id})
        return challenge

    def my_challenges(self, student: UserAccount) -> list[ProfileChallenge]:
        require_role(student, {Role.STUDENT})
        return self.ctx.evidence.challenges(student_id=student.user_id)
