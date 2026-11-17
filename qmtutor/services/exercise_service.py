"""
Exercise service: everything a student does inside a protected exercise.

Flow for one request (e.g. "Give me a hint"):
    1. load the server-side session and check the student owns it and it is in progress;
    2. ask the deterministic scaffold controller what support is allowed;
    3. produce that support:
         levels 1-4  -> the lecturer's approved hint text (no LLM needed);
         level 5     -> restate only checkpoints the student already wrote;
         level 6     -> the linked analogue worked example, after a leak check;
         chat        -> LLM reply within the level, then the leak guard;
    4. write the session update, decision, message and events in ONE transaction.

Fail-safe rule: if the LLM is unavailable, times out or returns invalid or
leaking output, the student receives approved lecturer text and the failure
is logged. The system never invents feedback.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from qmtutor.domain import adaptivity
from qmtutor.domain import scaffold_policy as policy_rules
from qmtutor.domain.evidence import summarise_outcome
from qmtutor.domain.exercise_state import InvalidTransition, check_transition
from qmtutor.domain.models import (
    CompetenceEvidence, ExerciseSession, ExerciseState, Item, MathVerification, Role, ScaffoldDecision,
    ScaffoldLevel, StudyArm, UserAccount, VerificationStatus,
)
from qmtutor.labels import EXERCISE_STATES
from qmtutor.llm import prompts
from qmtutor.llm.leak_guard import check_reply, states_formula, verified_checkpoints
from qmtutor.llm.providers import ProviderError, generate_with_retry
from qmtutor.llm.schemas import ReasoningAssessment, TutorReply, UnrestrictedReply
from qmtutor.mathcheck.step_check import StepResult, StudentLine, check_workings, student_feedback
from qmtutor.mathcheck.step_check import summarise as summarise_steps
from qmtutor.mathcheck.step_check import to_json_ready as steps_to_json
from qmtutor.mathcheck.verifier import verify_answer
from qmtutor.services.auth import PermissionDenied, require_role
from qmtutor.services.context import AppContext
from qmtutor.storage.db import utc_now
from qmtutor.storage.events import log_event

L = ScaffoldLevel

# Verifier reasons that are notation slips rather than maths errors: the student is told
# how to fix them, and they do not use up an attempt (design decision D06).
FORMAT_SLIP_REASONS = {"wrong_variable"}


class ExerciseError(Exception):
    """A request that the exercise rules do not allow (shown to the student as a message)."""


@dataclass
class TutorTurn:
    """What the page should display after a request."""
    text: str
    response_type: str
    level: ScaffoldLevel
    decision: ScaffoldDecision | None = None
    notes_used: list[str] = field(default_factory=list)


@dataclass
class AttemptOutcome:
    verification: MathVerification
    completed: bool
    feedback: str
    proactive_turn: TutorTurn | None = None
    steps: list[StepResult] = field(default_factory=list)   # line-by-line check of the workings
    mismatch: bool = False         # final answer correct but workings contain errors
    student_lines: list[StudentLine] = field(default_factory=list)   # safe feedback for the student


def _new_id() -> str:
    return uuid.uuid4().hex


class ExerciseService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # -
    # Lookup helpers
    # -
    def arm_for(self, student: UserAccount) -> StudyArm:
        arm = self.ctx.users.arm_for(student.user_id)
        if arm is None:
            raise ExerciseError("You have not been assigned to a study condition yet. Please contact the researcher.")
        return arm

    def available_items(self, student: UserAccount, task_type: str = "practice") -> list[Item]:
        """Approved, non-analogue items. Transfer items only for the independent check."""
        require_role(student, {Role.STUDENT})
        items = self.ctx.content.items(status=None, include_analogues=False)
        latest = {}
        for item in items:
            if item.status.value == "approved":
                latest[item.item_id] = item      # ordered by version, so the last approved wins
        wanted_transfer = task_type == "transfer"
        return [i for i in latest.values() if i.transfer_flag == wanted_transfer]

    # -
    # Adaptive practice: focus on each student's weaknesses (domain/adaptivity.py)
    # -
    def adaptive_enabled(self, student: UserAccount) -> bool:
        """Adaptivity is part of the tutor intervention: by default only the scaffolded group."""
        arms = self.ctx.settings["features"].get("adaptive_practice_arms", ["scaffolded"])
        arm = self.ctx.users.arm_for(student.user_id)
        return arm is not None and arm.value in arms

    def focus(self, student: UserAccount, limit: int = 3):
        """(topics in priority order, recommended exercises). Empty lists when adaptivity is off."""
        require_role(student, {Role.STUDENT})
        if not self.adaptive_enabled(student):
            return [], []
        items = self.available_items(student)
        evidence = self.ctx.evidence.for_student(student.user_id)
        outcomes = {o.outcome_id: o.description for o in self.ctx.content.outcomes()}
        summaries = {oid: summarise_outcome(oid, [e for e in evidence if e.outcome_id == oid]) for oid in outcomes}
        counts = self.ctx.evidence.misconception_counts(student.user_id)
        library = {m.misconception_id: m for m in self.ctx.content.misconceptions(list(counts))}
        topics = adaptivity.topic_priorities(outcomes, summaries, items, counts, library)
        completed = {s.item_id for s in self.ctx.exercises.for_student(student.user_id, {ExerciseState.COMPLETED})}
        return topics, adaptivity.recommend(topics, items, completed, counts, library, limit)

    def _record_possible_misconceptions(self, session, item: Item, answer: str, attempt_id: str) -> None:
        """A wrong answer matching a lecturer's typical wrong answer -> a POSSIBLE misconception."""
        found = adaptivity.matching_misconceptions(item, answer)
        if not found:
            return
        with self.ctx.db.transaction() as conn:
            for misconception_id in found:
                self.ctx.evidence.add_misconception_candidate(conn, _new_id(), session.student_id, misconception_id,
                                                              "typical_wrong_answer", 0.6, attempt_id)
            log_event(conn, "misconception_candidate_created", subject_id=session.student_id,
                      correlation_id=session.session_id, item_key=item.key, payload={"misconceptions": found})

    def _focus_notes(self, student_id: str, item: Item) -> list[str]:
        """Lecturer-approved feedback for possible misconceptions this student has shown on this kind of item."""
        counts = self.ctx.evidence.misconception_counts(student_id)
        relevant = [m for m in item.misconception_ids if counts.get(m)]
        return [f"{m.label}: {m.approved_feedback}" for m in self.ctx.content.misconceptions(relevant)]

    def active_session(self, student: UserAccount) -> ExerciseSession | None:
        return self.ctx.exercises.active_for(student.user_id)

    def saved_sessions(self, student: UserAccount) -> list[ExerciseSession]:
        return self.ctx.exercises.for_student(student.user_id, {ExerciseState.SAVED})

    def item_for(self, session: ExerciseSession) -> Item:
        return self.ctx.content.get_item(session.item_id, session.item_version)

    def task_type(self, session: ExerciseSession) -> str:
        return self.ctx.exercises.task_type(session.session_id)

    def _owned_session(self, student: UserAccount, session_id: str,
                       required_state: ExerciseState | None = ExerciseState.IN_PROGRESS) -> ExerciseSession:
        require_role(student, {Role.STUDENT})
        session = self.ctx.exercises.get(session_id)
        if session is None or session.student_id != student.user_id:
            raise PermissionDenied("This exercise does not belong to you.")
        if required_state and session.state != required_state:
            raise ExerciseError(f"This exercise is no longer open "
                                f"({EXERCISE_STATES.get(session.state.value, '').lower()}).")
        return session

    def history(self, student: UserAccount, session_id: str) -> list[dict]:
        self._owned_session(student, session_id, required_state=None)
        return [dict(r) for r in self.ctx.exercises.messages(session_id)]

    def attempts(self, student: UserAccount, session_id: str) -> list[dict]:
        self._owned_session(student, session_id, required_state=None)
        return [dict(r) for r in self.ctx.exercises.attempts(session_id)]

    def _student_texts(self, session_id: str) -> list[str]:
        """Everything the student has written in this exercise (answers, reasoning, chat)."""
        texts = [f"{a['final_answer_raw']} {a['reasoning_text']}" for a in self.ctx.exercises.attempts(session_id)]
        texts += [m["content"] for m in self.ctx.exercises.messages(session_id) if m["sender"] == "student"]
        return texts

    # -
    # Start, save, resume, terminate, refer
    # -
    def start(self, student: UserAccount, item_id: str, task_type: str = "practice") -> ExerciseSession:
        require_role(student, {Role.STUDENT})
        if not self.ctx.users.has_consent(student.user_id):
            raise ExerciseError("Please read and acknowledge the study notice first.")
        if self.active_session(student):
            raise ExerciseError("You already have an exercise in progress. Save or end it first.")
        item = self.ctx.content.latest_approved(item_id)
        if item is None or item.is_analogue or item.must_not_be_assigned_as_active_pair:
            raise ExerciseError("That exercise is not available.")
        if item.transfer_flag != (task_type == "transfer"):
            raise ExerciseError("That exercise is not available in this mode.")
        policy = self.ctx.policies.active()
        now = datetime.now(timezone.utc)
        session = ExerciseSession(session_id=_new_id(), student_id=student.user_id, item_id=item.item_id,
                                  item_version=item.item_version, policy_version=policy.policy_version,
                                  arm=self.arm_for(student), state=ExerciseState.IN_PROGRESS,
                                  started_at=now, updated_at=now)
        with self.ctx.db.transaction() as conn:
            self.ctx.exercises.create(conn, session, task_type)
            log_event(conn, "exercise_started", actor_id=student.user_id, subject_id=student.user_id,
                      correlation_id=session.session_id, item_key=item.key, policy_version=policy.policy_version,
                      payload={"arm": session.arm.value, "task_type": task_type})
        return session

    def _change_state(self, student: UserAccount, session_id: str, target: ExerciseState, event_type: str,
                      reason: str | None = None, from_state: ExerciseState = ExerciseState.IN_PROGRESS):
        session = self._owned_session(student, session_id, required_state=from_state)
        try:
            check_transition(session.state, target)
        except InvalidTransition:
            # The domain message uses machine names; students get plain words.
            raise ExerciseError(f"This exercise can't be changed now: it is "
                                f"{EXERCISE_STATES.get(session.state.value, '').lower()}.")
        if target == ExerciseState.IN_PROGRESS and self.active_session(student):
            raise ExerciseError("You already have an exercise in progress. Save or end it first.")
        stage = {"level": int(session.current_level), "max_level": int(session.max_level_reached),
                 "attempts": session.attempts, "hints_shown": session.hints_shown}
        session.state = target
        with self.ctx.db.transaction() as conn:
            self.ctx.exercises.update(conn, session)
            if target in (ExerciseState.TERMINATED, ExerciseState.REFERRED):
                self.ctx.exercises.add_termination(conn, session_id, target.value, stage, reason)
            log_event(conn, event_type, actor_id=student.user_id, subject_id=student.user_id,
                      correlation_id=session_id, item_key=f"{session.item_id}@{session.item_version}",
                      policy_version=session.policy_version, payload={**stage, "reason_given": bool(reason)})
        return session

    def save(self, student, session_id):
        return self._change_state(student, session_id, ExerciseState.SAVED, "exercise_saved")

    def resume(self, student, session_id):
        """Resume with the SAME item and policy versions as when it started."""
        return self._change_state(student, session_id, ExerciseState.IN_PROGRESS, "exercise_resumed",
                                  from_state=ExerciseState.SAVED)

    def terminate(self, student, session_id, reason: str | None = None):
        """End without the answer. Termination is never rewarded with the solution."""
        session = self._owned_session(student, session_id, required_state=None)
        self._change_state(student, session_id, ExerciseState.TERMINATED, "exercise_terminated", reason,
                           from_state=session.state)
        self._record_evidence(session, correct=False, note="terminated")

    def refer(self, student, session_id, reason: str | None = None):
        """Request human help (level 7). Lecturers see referrals on their dashboard."""
        session = self._owned_session(student, session_id)
        self._change_state(student, session_id, ExerciseState.REFERRED, "exercise_referred", reason)
        self._record_evidence(session, correct=False, note="referred to human support")

    # -
    # Attempts
    # -
    def submit_attempt(self, student: UserAccount, session_id: str, final_answer: str,
                       reasoning: str = "") -> AttemptOutcome:
        session = self._owned_session(student, session_id)
        item = self.item_for(session)
        verification = verify_answer(final_answer, item.answer_specification)
        # Format slips (design decision D06) are saved and logged but do not count as attempts.
        format_slip = verification.reason_code in FORMAT_SLIP_REASONS
        counted = verification.status in (VerificationStatus.CORRECT, VerificationStatus.INCORRECT) \
            and not format_slip
        if counted:
            session.attempts += 1
        correct = verification.status == VerificationStatus.CORRECT
        wrong_attempt = counted and not correct
        # Workings and final answer are marked separately, as on paper: the step check is
        # deterministic; the LLM's rubric score (below) is provisional and lecturer-facing.
        steps = check_workings(reasoning, item.answer_specification) if counted else []
        # The student sees the full check only once the exercise is finished; before that,
        # an arithmetic-only check that never uses the answer (see step_check.student_feedback).
        student_lines = student_feedback(
            steps if correct else check_workings(reasoning, item.answer_specification, use_answer=False),
            exercise_finished=correct) if counted else []
        step_summary = summarise_steps(steps)
        mismatch = correct and step_summary["has_errors"]
        attempt_id = _new_id()
        with self.ctx.db.transaction() as conn:
            self.ctx.exercises.add_attempt(conn, {
                "attempt_id": attempt_id, "session_id": session_id, "attempt_number": session.attempts,
                "final_answer_raw": final_answer, "reasoning_text": reasoning,
                "normalised_answer": verification.normalised_answer,
                "verification_status": verification.status.value, "verification_method": verification.method,
                "verification_reason": verification.reason_code, "scaffold_level": int(session.current_level),
                "created_at": utc_now(), "step_check_json": json.dumps(steps_to_json(steps))})
            if correct:
                check_transition(session.state, ExerciseState.COMPLETED)
                session.state = ExerciseState.COMPLETED
            self.ctx.exercises.update(conn, session)
            common = dict(actor_id=student.user_id, subject_id=student.user_id, correlation_id=session_id,
                          item_key=item.key, policy_version=session.policy_version)
            log_event(conn, "attempt_submitted", **common,
                      payload={"attempt_id": attempt_id, "has_reasoning": bool(reasoning.strip())})
            log_event(conn, "math_verification_completed", **common,
                      payload={"status": verification.status.value, "method": verification.method,
                               "reason": verification.reason_code, "workings": step_summary,
                               "correct_answer_with_working_errors": mismatch})
            if correct:
                completion_event = log_event(conn, "exercise_completed", **common,
                                             payload={"attempts": session.attempts,
                                                      "max_level": int(session.max_level_reached)})

        score = self._assess_reasoning(session, item, attempt_id, reasoning, final_answer, verification, steps) \
            if counted else None
        if correct:
            note = "final answer correct, but the workings contain errors" if mismatch else None
            self._record_evidence(session, correct=True, reasoning_score=score, source_event_id=completion_event,
                                  note=note)
            return AttemptOutcome(verification, True, "Correct. Well done.", steps=steps, mismatch=mismatch,
                                  student_lines=student_lines)

        if wrong_attempt:
            self._record_possible_misconceptions(session, item, final_answer, attempt_id)
        feedback = verification.message
        if wrong_attempt and session.arm == StudyArm.SCAFFOLDED and self.task_type(session) == "practice":
            feedback += " Check your working, or ask for a hint."
        proactive = None
        if wrong_attempt and self.task_type(session) == "practice":
            decision = policy_rules.decide_after_wrong_answer(
                session.arm, session.current_level, session.attempts, session.hints_shown,
                self.ctx.users.proactive_hints_on(student.user_id), self.ctx.policies.active())
            if decision:
                proactive = self._deliver_hint(student, session, item, decision)
        return AttemptOutcome(verification, False, feedback, proactive, steps=steps, student_lines=student_lines)

    def _assess_reasoning(self, session, item, attempt_id, reasoning, final_answer, verification,
                          steps) -> int | None:
        """
        Provisional LLM rubric score for the workings, given the deterministic evidence
        (answer verdict and line-by-line step check). Lecturer-facing only; may be None.
        The assessor may see the worked solution because its output never reaches the student.
        """
        if not reasoning.strip() or not self.ctx.settings["features"]["assess_reasoning_with_llm"]:
            return None
        system = prompts.reasoning_prompt(item, reasoning, final_answer, verification.status.value, steps)
        try:
            result = generate_with_retry(self.ctx.provider, system,
                                         [{"role": "user", "content": "Assess the workings."}], ReasoningAssessment)
        except ProviderError as error:
            self._log_provider_failure(session, error)
            return None
        # Rule over model: found in a live browser test (3 Oct 2026), llama3.2:3b gave full marks
        # for steps even though its prompt listed an inconsistent line. Where software has PROVED
        # a step wrong, the steps score is capped at 1. The raw LLM score is kept for comparison.
        step_errors = [s for s in steps if s.status in ("arithmetic_error", "inconsistent")]
        steps_score = min(result.mathematical_steps, 1) if step_errors else result.mathematical_steps
        capped = steps_score != result.mathematical_steps
        total = result.method_selection + steps_score + result.conceptual_explanation
        with self.ctx.db.transaction() as conn:
            if capped:
                conn.execute("INSERT INTO reasoning_assessment (assessment_id, attempt_id, dimension, score, "
                             "confidence, evidence_span, assessor_type, assessor_id, model, created_at, comment) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (_new_id(), attempt_id, "mathematical_steps", steps_score, 1.0, step_errors[0].text,
                              "rule_cap", None, None, utc_now(),
                              f"LLM gave {result.mathematical_steps}; capped because line "
                              f"{step_errors[0].line_number} failed the software step check"))
            for dimension in ("method_selection", "mathematical_steps", "conceptual_explanation"):
                conn.execute("INSERT INTO reasoning_assessment (assessment_id, attempt_id, dimension, score, "
                             "confidence, evidence_span, assessor_type, assessor_id, model, created_at, comment) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (_new_id(), attempt_id, dimension, getattr(result, dimension), result.confidence,
                              result.evidence_quote, "llm_provisional", None, self.ctx.model_label, utc_now(),
                              result.comment))
            log_event(conn, "reasoning_assessment_completed", subject_id=session.student_id,
                      correlation_id=session.session_id, model=self.ctx.model_label,
                      prompt_version=prompts.prompt_version(),
                      payload={"total_0_6": total, "confidence": result.confidence,
                               "steps_capped_by_rule": capped, "llm_steps_score": result.mathematical_steps})
        return total

    def _record_evidence(self, session: ExerciseSession, correct: bool, reasoning_score: int | None = None,
                         source_event_id: str | None = None, note: str | None = None) -> None:
        policy = self.ctx.policies.active()
        item = self.item_for(session)
        evidence = CompetenceEvidence(
            evidence_id=_new_id(), student_id=session.student_id, outcome_id=item.outcome_id, item_key=item.key,
            task_type=self.task_type(session), final_answer_correct=correct, reasoning_score=reasoning_score,
            reasoning_assessor="llm_provisional" if reasoning_score is not None else None,
            support=policy_rules.support_category(session.max_level_reached, policy),
            max_scaffold_level=session.max_level_reached, attempts=session.attempts,
            source_event_id=source_event_id or session.session_id, created_at=datetime.now(timezone.utc), note=note)
        with self.ctx.db.transaction() as conn:
            self.ctx.evidence.add(conn, evidence)

    # -
    # Hints (deterministic content)
    # -
    def set_proactive_hints(self, student: UserAccount, on: bool) -> None:
        require_role(student, {Role.STUDENT})
        with self.ctx.db.transaction() as conn:
            self.ctx.users.set_proactive_hints(conn, student.user_id, on)
            log_event(conn, "proactive_hint_setting_changed", actor_id=student.user_id,
                      subject_id=student.user_id, payload={"on": on})

    def request_hint(self, student: UserAccount, session_id: str) -> TutorTurn:
        session = self._owned_session(student, session_id)
        if self.task_type(session) == "transfer":
            raise ExerciseError("The independent check has no hints.")
        if session.arm != StudyArm.SCAFFOLDED:
            raise ExerciseError("Hints are not part of this study condition.")
        item = self.item_for(session)
        decision = policy_rules.decide_hint(session.arm, session.current_level, session.attempts,
                                            session.hints_shown, self.ctx.policies.active())
        with self.ctx.db.transaction() as conn:
            log_event(conn, "hint_requested", actor_id=student.user_id, subject_id=student.user_id,
                      correlation_id=session_id, item_key=item.key, policy_version=session.policy_version)
        return self._deliver_hint(student, session, item, decision)

    def _deliver_hint(self, student, session: ExerciseSession, item: Item, decision: ScaffoldDecision) -> TutorTurn:
        student_texts = self._student_texts(session.session_id)
        if decision.action == "show_consolidation":
            text, response_type = self._consolidation_text(item, student_texts), "consolidation_level_5"
        elif decision.action == "show_analogue":
            text, response_type = self._analogue_text(item, student_texts, session)
            if response_type != "analogue_level_6":       # analogue failed the leak check
                decision = decision.model_copy(update={"level": L.STEP_HINT, "action": "show_hint",
                                                       "reason_code": "analogue_blocked_leak_check"})
        else:
            text = prompts.approved_cue(item, decision.level)
            response_type = f"hint_level_{int(decision.level)}"
        session.current_level = decision.level
        session.max_level_reached = max(session.max_level_reached, decision.level)
        session.hints_shown += 1
        self._store_turn(session, decision, response_type, text, student_message=None)
        return TutorTurn(text, response_type, decision.level, decision)

    @staticmethod
    def _consolidation_text(item: Item, student_texts: list[str]) -> str:
        """Level 5: restate only what the student wrote and the checkpoint confirms."""
        verified = verified_checkpoints(item, student_texts)
        if not verified:
            return ("I can't confirm a correct step in your work yet. "
                    + (item.scaffold_sequence.step_hint if item.scaffold_sequence else "Try the first step."))
        parts = "; ".join(f"{cp.label}: you wrote {value}" for cp, value in verified)
        return f"Here is what you have already worked out correctly: {parts}. What should happen next?"

    def _analogue_text(self, item: Item, student_texts: list[str], session) -> tuple[str, str]:
        """Level 6: a different, structurally similar worked example, checked for leaks first."""
        analogue_id = item.scaffold_sequence.analogous_example_id if item.scaffold_sequence else None
        analogue = self.ctx.content.latest_approved(analogue_id) if analogue_id else None
        if analogue is None:
            return (item.scaffold_sequence.step_hint if item.scaffold_sequence else "Try the next step.",
                    "hint_level_4_no_analogue")
        steps = "\n".join(f"{n}. {s}" for n, s in enumerate(analogue.worked_solution, start=1))
        text = (f"Here is a similar problem worked through (different numbers):\n\n{analogue.stem}\n\n{steps}\n\n"
                f"{analogue.return_instruction or 'Now return to your question.'}")
        leak = check_reply(text, item, student_texts)
        if leak.leaked:
            self._log_leak(session, item, f"analogue:{leak.reason}")
            return item.scaffold_sequence.step_hint, "hint_level_4_analogue_blocked"
        return text, "analogue_level_6"

    # -
    # Chat (LLM within the allowed level)
    # -
    def chat(self, student: UserAccount, session_id: str, message: str) -> TutorTurn:
        session = self._owned_session(student, session_id)
        message = message.strip()[:1000]
        if not message:
            raise ExerciseError("Please type a message.")
        if self.task_type(session) == "transfer":
            raise ExerciseError("The independent check has no tutor chat.")
        if session.arm == StudyArm.EXISTING_SUPPORT:
            raise ExerciseError("An AI tutor is not part of this study condition.")
        item = self.item_for(session)
        policy = self.ctx.policies.active()
        decision = policy_rules.decide_chat(session.arm, session.current_level, message, session.attempts,
                                            session.hints_shown, policy)
        history = self._llm_history(session.session_id)

        if decision.action == "unrestricted_reply":
            return self._unrestricted_reply(session, item, decision, history, message)

        if decision.action == "refuse_and_offer_hint":
            offer_level = ScaffoldLevel(max(int(session.current_level), int(L.SELF_EXPLANATION)))
            text = prompts.load_prompts()["refusal_exercise"].strip() + " " + prompts.approved_cue(item, offer_level)
            self._store_turn(session, decision, "refusal", text, student_message=message)
            return TutorTurn(text, "refusal", decision.level, decision)

        student_texts = self._student_texts(session.session_id) + [message]
        passages = self.ctx.retriever.search(f"{item.stem} {message}",
                                             self.ctx.settings["retrieval"]["passages_per_reply"])
        system = prompts.scaffolded_exercise_prompt(item, decision.level,
                                                    verified_checkpoints(item, student_texts), passages,
                                                    focus_notes=self._focus_notes(session.student_id, item))
        messages = history + [{"role": "user", "content": message}]
        text, response_type = self._guarded_generation(session, item, system, messages, student_texts, decision)
        self._store_turn(session, decision, response_type, text, student_message=message)
        return TutorTurn(text, response_type, decision.level, decision, [p.note_id for p in passages])

    def _guarded_generation(self, session, item, system, messages, student_texts, decision) -> tuple[str, str]:
        """Generate, check for leaks, regenerate up to N times, then fall back to approved text."""
        fallback = prompts.approved_cue(item, decision.level)
        last_problem = "fallback_leak_blocked"
        for _ in range(self.ctx.settings["features"]["max_leak_retries"] + 1):
            try:
                reply = generate_with_retry(self.ctx.provider, system, messages, TutorReply)
            except ProviderError as error:
                self._log_provider_failure(session, error)
                return f"(The tutor is unavailable right now. Here is your lecturer's hint.) {fallback}", "fallback_provider"
            text = reply.message.strip()
            if reply.question_to_student and reply.question_to_student.strip() not in text:
                text = f"{text} {reply.question_to_student.strip()}"
            leak = check_reply(text, item, student_texts)
            if leak.leaked:
                self._log_leak(session, item, leak.reason)
                last_problem = "fallback_leak_blocked"
                continue
            # Level guard: below "plan hint" (level 3) the tutor may not hand over the formula.
            if decision.level < L.STRATEGIC_HINT and states_formula(text, student_texts):
                with self.ctx.db.transaction() as conn:
                    log_event(conn, "reply_above_level_blocked", subject_id=session.student_id,
                              correlation_id=session.session_id, item_key=item.key, model=self.ctx.model_label,
                              payload={"level": int(decision.level), "reason": "formula_before_level_3"})
                last_problem = "fallback_above_level"
                continue
            return text, f"tutor_reply_level_{int(decision.level)}"
        return fallback, last_problem

    def _unrestricted_reply(self, session, item, decision, history, message) -> TutorTurn:
        """Unrestricted arm: same model, neutral prompt, no scaffold policy or leak guard."""
        try:
            reply = generate_with_retry(self.ctx.provider, prompts.unrestricted_prompt(item),
                                        history + [{"role": "user", "content": message}], UnrestrictedReply)
            text, response_type = reply.message.strip(), "unrestricted_reply"
        except ProviderError as error:
            self._log_provider_failure(session, error)
            text, response_type = "The AI assistant is unavailable right now. Please try again later.", "fallback_provider"
        self._store_turn(session, decision, response_type, text, student_message=message)
        return TutorTurn(text, response_type, decision.level, decision)

    def _llm_history(self, session_id: str) -> list[dict]:
        turns = self.ctx.settings["features"]["chat_history_turns"]
        rows = self.ctx.exercises.messages(session_id)[-turns:]
        return [{"role": "user" if r["sender"] == "student" else "assistant", "content": r["content"]} for r in rows]

    # -
    # Persistence helpers
    # -
    def _store_turn(self, session: ExerciseSession, decision: ScaffoldDecision, response_type: str, text: str,
                    student_message: str | None) -> None:
        item_key = f"{session.item_id}@{session.item_version}"
        with self.ctx.db.transaction() as conn:
            self.ctx.exercises.update(conn, session)
            self.ctx.exercises.add_decision(conn, _new_id(), session.session_id, decision)
            if student_message is not None:
                self.ctx.exercises.add_message(conn, _new_id(), session.session_id, session.student_id, "exercise",
                                               "student", None, student_message)
            self.ctx.exercises.add_message(conn, _new_id(), session.session_id, session.student_id, "exercise",
                                           "tutor", response_type, text)
            common = dict(subject_id=session.student_id, correlation_id=session.session_id, item_key=item_key,
                          policy_version=decision.policy_version)
            log_event(conn, "scaffold_decision_made", **common,
                      payload={"level": int(decision.level), "action": decision.action,
                               "reason": decision.reason_code, "inputs": decision.inputs})
            log_event(conn, "tutor_feedback_shown", **common, model=self.ctx.model_label,
                      prompt_version=prompts.prompt_version(), payload={"response_type": response_type})

    def _log_leak(self, session, item, reason) -> None:
        with self.ctx.db.transaction() as conn:
            log_event(conn, "leak_blocked", subject_id=session.student_id, correlation_id=session.session_id,
                      item_key=item.key, model=self.ctx.model_label, payload={"reason": reason})

    def _log_provider_failure(self, session, error: ProviderError) -> None:
        with self.ctx.db.transaction() as conn:
            log_event(conn, "provider_failure", subject_id=session.student_id, correlation_id=session.session_id,
                      model=self.ctx.model_label, payload={"code": error.code})
