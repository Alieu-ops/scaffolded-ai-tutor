"""
Lecturer workflows: the human control points.

    Content   review -> approve (publish) -> retire; returns to draft with a reason.
              Approving a newer version supersedes the older approved one.
              Analogues are checked again for answer leakage at approval.
    Notes     approve or return the study notes used for retrieval.
    Evidence  resolve student challenges (uphold / amend / remove), with reasons.
    Patterns  class-level summaries: terminations, referrals, support use,
              leak blocks and provisional reasoning scores, aggregated by item.
    Policy    approve or reject proposed scaffold-policy versions. A proposal
              marked source='llm_suggestion' can be reviewed but never self-activates.

Every decision requires the lecturer role and is logged with an audit record.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict

from qmtutor.domain.models import ChallengeStatus, ContentStatus, Item, PolicyConfig, Role, UserAccount
from qmtutor.services.auth import require_role
from qmtutor.services.context import AppContext
from qmtutor.storage.db import utc_now
from qmtutor.storage.events import log_event

LECTURER = {Role.LECTURER}


class ReviewError(Exception):
    """A review action that the content workflow does not allow."""


def _audit(conn, actor_id, action, target, detail=None):
    conn.execute("INSERT INTO audit_event VALUES (?,?,?,?,?,?)",
                 (uuid.uuid4().hex, actor_id, action, target, detail, utc_now()))


class LecturerService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # -
    # Content workflow
    # -
    def items(self, lecturer: UserAccount) -> list[Item]:
        require_role(lecturer, LECTURER)
        return self.ctx.content.items()

    def review_history(self, lecturer: UserAccount, item_id: str) -> list[dict]:
        require_role(lecturer, LECTURER)
        return [dict(r) for r in self.ctx.content.reviews(item_id)]

    def decide_item(self, lecturer: UserAccount, item_id: str, item_version: str, decision: str, reason: str) -> None:
        """decision: 'reviewed', 'approved', 'returned' (back to draft) or 'retired'."""
        require_role(lecturer, LECTURER)
        if not reason.strip():
            raise ReviewError("Please give a reason for the decision.")
        item = self.ctx.content.get_item(item_id, item_version)
        if item is None:
            raise ReviewError("Item version not found.")
        target = {"reviewed": ContentStatus.REVIEWED, "approved": ContentStatus.APPROVED,
                  "returned": ContentStatus.DRAFT, "retired": ContentStatus.RETIRED}.get(decision)
        if target is None:
            raise ReviewError(f"Unknown decision '{decision}'.")
        if item.status in (ContentStatus.RETIRED, ContentStatus.SUPERSEDED) and target != ContentStatus.DRAFT:
            raise ReviewError("This version is retired or has been replaced, so it cannot be published. Publish the newer version instead.")
        if target == ContentStatus.APPROVED:
            self._check_publishable(item)

        with self.ctx.db.transaction() as conn:
            if target == ContentStatus.APPROVED:
                # A newly approved version supersedes earlier approved versions of the same item.
                for other in self.ctx.content.items(ContentStatus.APPROVED):
                    if other.item_id == item_id and other.item_version != item_version:
                        self.ctx.content.set_item_status(conn, item_id, other.item_version, ContentStatus.SUPERSEDED)
            self.ctx.content.set_item_status(conn, item_id, item_version, target)
            self.ctx.content.add_review(conn, uuid.uuid4().hex, item, lecturer.user_id, decision, reason.strip())
            event = {"approved": "item_published", "retired": "item_retired"}.get(decision, "item_reviewed")
            log_event(conn, event, actor_id=lecturer.user_id, item_key=item.key,
                      payload={"decision": decision, "new_status": target.value})
            _audit(conn, lecturer.user_id, f"item_{decision}", item.key, reason.strip())

    def _check_publishable(self, item: Item) -> None:
        """Re-run the analogue leak rule at approval time (content may have changed since import)."""
        if item.is_analogue:
            for practice in self.ctx.content.items(include_analogues=False):
                seq = practice.scaffold_sequence
                if seq and seq.analogous_example_id == item.item_id and practice.answer_specification:
                    from qmtutor.content.importer import validate_item
                    problems = validate_item(practice, {item.item_id: item, practice.item_id: practice},
                                             {practice.outcome_id}, set(practice.misconception_ids))
                    leaks = [p for p in problems if "analogue" in p]
                    if leaks:
                        raise ReviewError(f"Cannot approve: {leaks[0]} ({practice.item_id}).")

    def notes(self, lecturer: UserAccount) -> list[dict]:
        require_role(lecturer, LECTURER)
        return [dict(r) for r in self.ctx.db.query("SELECT * FROM knowledge_note ORDER BY note_id")]

    def decide_note(self, lecturer: UserAccount, note_id: str, approve: bool, reason: str) -> None:
        require_role(lecturer, LECTURER)
        if not reason.strip():
            raise ReviewError("Please give a reason for the decision.")
        status = ContentStatus.APPROVED.value if approve else ContentStatus.DRAFT.value
        with self.ctx.db.transaction() as conn:
            conn.execute("UPDATE knowledge_note SET status=? WHERE note_id=?", (status, note_id))
            conn.execute("DELETE FROM knowledge_fts WHERE note_id=?", (note_id,))
            if approve:    # only approved notes enter the search index
                conn.execute("INSERT INTO knowledge_fts SELECT note_id, heading, body FROM knowledge_note "
                             "WHERE note_id=?", (note_id,))
            _audit(conn, lecturer.user_id, "note_approved" if approve else "note_returned", note_id, reason.strip())

    # -
    # Evidence and challenges
    # -
    def open_challenges(self, lecturer: UserAccount):
        require_role(lecturer, LECTURER)
        return self.ctx.evidence.challenges(status=ChallengeStatus.OPEN)

    def resolve_challenge(self, lecturer: UserAccount, challenge_id: str, decision: ChallengeStatus,
                          reason: str) -> None:
        """Uphold, amend (note added) or remove (excluded from the profile). The record itself is kept."""
        require_role(lecturer, LECTURER)
        if decision == ChallengeStatus.OPEN or not reason.strip():
            raise ReviewError("Choose uphold, amend or remove, and give a reason.")
        challenge = next((c for c in self.ctx.evidence.challenges() if c.challenge_id == challenge_id), None)
        if challenge is None or challenge.status != ChallengeStatus.OPEN:
            raise ReviewError("Challenge not found or already resolved.")
        with self.ctx.db.transaction() as conn:
            self.ctx.evidence.resolve_challenge(conn, challenge_id, decision, lecturer.user_id, reason.strip())
            if decision == ChallengeStatus.REMOVED:
                self.ctx.evidence.annotate(conn, challenge.evidence_id, True, f"removed by lecturer: {reason.strip()}")
            elif decision == ChallengeStatus.AMENDED:
                self.ctx.evidence.annotate(conn, challenge.evidence_id, None, f"lecturer note: {reason.strip()}")
            log_event(conn, "profile_challenge_resolved", actor_id=lecturer.user_id, subject_id=challenge.student_id,
                      payload={"challenge_id": challenge_id, "decision": decision.value})
            _audit(conn, lecturer.user_id, f"challenge_{decision.value}", challenge_id, reason.strip())

    def students(self, lecturer: UserAccount) -> list[UserAccount]:
        require_role(lecturer, LECTURER)
        return self.ctx.users.list(Role.STUDENT)

    def class_patterns(self, lecturer: UserAccount) -> list[dict]:
        """Aggregated per item: no names, no raw chat. Supports teaching decisions, not surveillance."""
        require_role(lecturer, LECTURER)
        sessions = self.ctx.db.query("SELECT * FROM exercise_session")
        by_item: dict[str, Counter] = defaultdict(Counter)
        students: dict[str, set] = defaultdict(set)
        for s in sessions:
            key = f"{s['item_id']}@{s['item_version']}"
            by_item[key][s["state"]] += 1
            by_item[key]["hints"] += s["hints_shown"]
            by_item[key]["high_support"] += int(s["max_level_reached"] >= 4)
            students[key].add(s["student_id"])
        leaks = Counter(r["item_key"] for r in self.ctx.db.query(
            "SELECT item_key FROM event WHERE event_type='leak_blocked'"))
        reasoning = defaultdict(list)
        for r in self.ctx.db.query(
                """SELECT es.item_id || '@' || es.item_version AS item_key, ra.score
                   FROM reasoning_assessment ra JOIN attempt a ON a.attempt_id = ra.attempt_id
                   JOIN exercise_session es ON es.session_id = a.session_id"""):
            reasoning[r["item_key"]].append(r["score"])
        rows = []
        for key, counts in sorted(by_item.items()):
            scores = reasoning.get(key, [])
            rows.append({"item": key, "students": len(students[key]), "completed": counts["completed"],
                         "in_progress_or_saved": counts["in_progress"] + counts["saved"],
                         "terminated": counts["terminated"], "referred": counts["referred"],
                         "hints_shown": counts["hints"], "reached_high_support": counts["high_support"],
                         "leaks_blocked": leaks.get(key, 0),
                         "mean_provisional_reasoning_0_2": round(sum(scores) / len(scores), 2) if scores else None})
        return rows

    def referrals(self, lecturer: UserAccount) -> list[dict]:
        require_role(lecturer, LECTURER)
        return [dict(r) for r in self.ctx.db.query(
            """SELECT t.session_id, es.student_id, es.item_id, t.stage_json, t.reason, t.created_at
               FROM termination t JOIN exercise_session es ON es.session_id = t.session_id
               WHERE t.exit_type = 'referred' ORDER BY t.created_at DESC""")]

    def student_evidence_review(self, lecturer: UserAccount, student_id: str) -> list[dict]:
        """
        One row per attempt: final answer verdict (deterministic), workings check (deterministic,
        line by line), provisional LLM rubric scores and comment, and the support level.
        A correct answer with workings errors is flagged for the lecturer's judgement.
        """
        require_role(lecturer, LECTURER)
        rows = self.ctx.db.query(
            """SELECT es.item_id, a.attempt_number, a.final_answer_raw, a.verification_status,
                      a.reasoning_text, a.step_check_json, a.scaffold_level,
                      GROUP_CONCAT(CASE WHEN ra.assessor_type = 'rule_cap'
                                        THEN 'steps capped by rule=' || ra.score
                                        ELSE ra.dimension || '=' || ra.score END, ', ') AS provisional_scores,
                      MAX(ra.comment) AS provisional_comment
               FROM attempt a JOIN exercise_session es ON es.session_id = a.session_id
               LEFT JOIN reasoning_assessment ra ON ra.attempt_id = a.attempt_id
               WHERE es.student_id = ? GROUP BY a.attempt_id ORDER BY a.created_at""", (student_id,))
        result = []
        for r in rows:
            steps = json.loads(r["step_check_json"] or "[]")
            problems = [f"Line {s['line_number']}: {s['detail']}" for s in steps
                        if s["status"] in ("arithmetic_error", "inconsistent")]
            checked = sum(s["status"] != "not_checked" for s in steps)
            result.append({
                "item": r["item_id"], "attempt": r["attempt_number"], "final_answer": r["final_answer_raw"],
                "answer_check": r["verification_status"],
                "workings_check": "; ".join(problems) or (f"All {checked} checked line(s) correct" if checked
                                                          else "No equations the computer could check"),
                "flag": "correct answer, workings errors" if r["verification_status"] == "correct" and problems else "",
                "workings": r["reasoning_text"], "support_level": r["scaffold_level"],
                "provisional_llm_scores": r["provisional_scores"], "provisional_llm_comment": r["provisional_comment"]})
        return result

    # -
    # Scaffold policy governance
    # -
    def policies(self, user: UserAccount) -> list[dict]:
        require_role(user, {Role.LECTURER, Role.RESEARCHER})
        return [dict(r) for r in self.ctx.policies.all()]

    def propose_policy(self, user: UserAccount, config: PolicyConfig, rationale: str,
                       source: str = "human") -> None:
        """Anyone on the team may propose; proposals have no effect until a lecturer approves."""
        require_role(user, {Role.LECTURER, Role.RESEARCHER})
        if source not in ("human", "llm_suggestion"):
            raise ReviewError("Unknown proposal source.")
        if self.ctx.policies.get(config.policy_version):
            raise ReviewError("That policy version already exists; choose a new version number.")
        with self.ctx.db.transaction() as conn:
            self.ctx.policies.add(conn, config, "proposed", source, rationale, user.user_id)
            log_event(conn, "policy_change_proposed", actor_id=user.user_id, policy_version=config.policy_version,
                      payload={"source": source})

    def decide_policy(self, lecturer: UserAccount, version: str, approve: bool, reason: str,
                      regression_tests_confirmed: bool) -> None:
        """Approve (activate) or reject a proposal. Approval requires confirmation that tests passed."""
        require_role(lecturer, LECTURER)
        row = self.ctx.policies.get(version)
        if row is None or row["status"] != "proposed":
            raise ReviewError("Only proposed policy versions can be decided.")
        if approve and not regression_tests_confirmed:
            # For the technical team: "the automated safety tests" means running pytest on these rules.
            raise ReviewError("Please confirm that the automated safety tests were run and passed before approving.")
        with self.ctx.db.transaction() as conn:
            if approve:
                conn.execute("UPDATE scaffold_policy_version SET status='retired' WHERE status='active'")
                self.ctx.policies.set_status(conn, version, "active", lecturer.user_id)
                log_event(conn, "policy_version_approved", actor_id=lecturer.user_id, policy_version=version,
                          payload={"tests_confirmed": True})
            else:
                self.ctx.policies.set_status(conn, version, "rejected", lecturer.user_id)
                log_event(conn, "policy_change_rejected", actor_id=lecturer.user_id, policy_version=version)
            _audit(conn, lecturer.user_id, "policy_approved" if approve else "policy_rejected", version, reason)


def policy_from_row(row: dict) -> PolicyConfig:
    return PolicyConfig.model_validate(json.loads(row["config_json"]))
