"""
Study mode: explanations of approved course concepts, with sources.

Mode lock (requirement REQ-003): while a student has an exercise IN PROGRESS,
study mode refuses to answer. This is checked here, on the server, not just
by hiding the page. When an exercise is SAVED, study is allowed, but a query
that is essentially a copy of that saved exercise is refused, so saving is
not a way around the protection. Neither rule can stop a student using an
outside AI; the evaluation measures that instead of claiming to prevent it.

Arm differences: the existing-support arm sees the matching approved notes
only (no AI); the AI arms get an LLM explanation grounded in those notes.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from qmtutor.domain.models import ExerciseState, Role, StudyArm, UserAccount
from qmtutor.llm import prompts
from qmtutor.llm.providers import ProviderError, generate_with_retry
from qmtutor.llm.schemas import StudyReply
from qmtutor.retrieval.search import Passage
from qmtutor.services.auth import require_role
from qmtutor.services.context import AppContext
from qmtutor.storage.events import log_event

OVERLAP_THRESHOLD = 0.6   # share of a saved question's content words found in the query


class StudyLocked(Exception):
    """Study mode is not available right now (active exercise, or query copies a saved exercise)."""


@dataclass
class StudyAnswer:
    text: str
    sources: list[Passage] = field(default_factory=list)
    used_ai: bool = False
    response_type: str = "study_explanation"


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+|\d+", text.lower()) if len(w) > 2 or w.isdigit()}


class StudyService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def is_locked(self, student: UserAccount) -> bool:
        return self.ctx.exercises.active_for(student.user_id) is not None

    def _copies_saved_exercise(self, student: UserAccount, query: str) -> bool:
        query_words = _content_words(query)
        for session in self.ctx.exercises.for_student(student.user_id, {ExerciseState.SAVED}):
            stem_words = _content_words(self.ctx.content.get_item(session.item_id, session.item_version).stem)
            if stem_words and len(stem_words & query_words) / len(stem_words) >= OVERLAP_THRESHOLD:
                return True
        return False

    def ask(self, student: UserAccount, query: str) -> StudyAnswer:
        require_role(student, {Role.STUDENT})
        query = query.strip()[:800]
        if self.is_locked(student):
            with self.ctx.db.transaction() as conn:
                log_event(conn, "study_blocked_active_exercise", actor_id=student.user_id,
                          subject_id=student.user_id, payload={"reason": "active_exercise"})
            raise StudyLocked("Study mode is closed while an exercise is in progress. Save or end the exercise first.")
        if self._copies_saved_exercise(student, query):
            with self.ctx.db.transaction() as conn:
                log_event(conn, "study_blocked_active_exercise", actor_id=student.user_id,
                          subject_id=student.user_id, payload={"reason": "copies_saved_exercise"})
            raise StudyLocked("That looks like one of your saved exercises. Resume it to get hints, "
                              "or ask about the general concept.")

        passages = self.ctx.retriever.search(query, 3)
        arm = self.ctx.users.arm_for(student.user_id)
        with self.ctx.db.transaction() as conn:
            log_event(conn, "study_query_submitted", actor_id=student.user_id, subject_id=student.user_id,
                      payload={"sources_found": [p.note_id for p in passages]})

        if arm == StudyArm.EXISTING_SUPPORT or not passages:
            text = ("Here are the approved course notes that match your question." if passages else
                    "I couldn't find approved notes on that. Try other words, or ask your lecturer.")
            answer = StudyAnswer(text, passages, used_ai=False, response_type="notes_only")
        else:
            answer = self._ai_explanation(student, query, passages)
        self._store(student, query, answer)
        return answer

    def _ai_explanation(self, student: UserAccount, query: str, passages: list[Passage]) -> StudyAnswer:
        try:
            reply = generate_with_retry(self.ctx.provider, prompts.study_prompt(passages),
                                        [{"role": "user", "content": query}], StudyReply)
        except ProviderError as error:
            with self.ctx.db.transaction() as conn:
                log_event(conn, "provider_failure", subject_id=student.user_id, model=self.ctx.model_label,
                          payload={"code": error.code, "mode": "study"})
            return StudyAnswer("The tutor is unavailable right now. Here are the approved notes instead.",
                               passages, used_ai=False, response_type="fallback_provider")
        known_ids = {p.note_id for p in passages}
        # Only cite notes that were actually provided (the model cannot invent a source).
        cited = [p for p in passages if p.note_id in set(reply.source_ids) & known_ids] or passages
        parts = [reply.explanation.strip()]
        if reply.example.strip():
            parts.append(f"**Example:** {reply.example.strip()}")
        if reply.check_question.strip():
            parts.append(f"**Check your understanding:** {reply.check_question.strip()}")
        return StudyAnswer("\n\n".join(parts), cited, used_ai=True)

    def _store(self, student: UserAccount, query: str, answer: StudyAnswer) -> None:
        with self.ctx.db.transaction() as conn:
            self.ctx.exercises.add_message(conn, uuid.uuid4().hex, None, student.user_id, "study", "student",
                                           None, query)
            self.ctx.exercises.add_message(conn, uuid.uuid4().hex, None, student.user_id, "study", "tutor",
                                           answer.response_type, answer.text)
            log_event(conn, "study_response_shown", subject_id=student.user_id, model=self.ctx.model_label,
                      prompt_version=prompts.prompt_version(),
                      payload={"used_ai": answer.used_ai, "sources": [p.note_id for p in answer.sources]})

    def history(self, student: UserAccount) -> list[dict]:
        require_role(student, {Role.STUDENT})
        return [dict(r) for r in self.ctx.exercises.study_messages(student.user_id)]
