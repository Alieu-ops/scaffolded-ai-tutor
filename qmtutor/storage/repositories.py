"""
Repositories: the only place that writes SQL. Each one turns rows into domain
models and back. Services call repositories; pages never do.

All queries use "?" placeholders, so user text is passed as data and can
never change the SQL (this is what prevents SQL injection).

Write methods take a `conn` argument so a service can group several writes
(state change + attempt + event) into one transaction.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from qmtutor.domain.models import (
    ChallengeStatus, CompetenceEvidence, ContentStatus, ExerciseSession, ExerciseState, Item,
    LearningOutcome, Misconception, PolicyConfig, ProfileChallenge, Role, ScaffoldLevel,
    StudyArm, SupportCategory, UserAccount,
)
from qmtutor.storage.db import Database, utc_now


def _dt(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, conn, user: UserAccount) -> None:
        conn.execute("INSERT INTO user_account VALUES (?,?,?,?,?)",
                     (user.user_id, user.display_name, user.role.value, int(user.active), utc_now()))

    def get(self, user_id: str) -> UserAccount | None:
        row = self.db.query_one("SELECT * FROM user_account WHERE user_id = ?", (user_id,))
        return None if row is None else UserAccount(user_id=row["user_id"], display_name=row["display_name"],
                                                    role=Role(row["role"]), active=bool(row["active"]))

    def list(self, role: Role | None = None) -> list[UserAccount]:
        sql, params = "SELECT user_id FROM user_account", ()
        if role:
            sql, params = sql + " WHERE role = ?", (role.value,)
        return [self.get(r["user_id"]) for r in self.db.query(sql + " ORDER BY user_id", params)]

    def set_research_id(self, conn, user_id: str, research_id: str) -> None:
        conn.execute("INSERT OR IGNORE INTO research_participant_link VALUES (?,?)", (user_id, research_id))

    def arm_for(self, user_id: str) -> StudyArm | None:
        row = self.db.query_one("SELECT arm FROM study_assignment WHERE user_id = ?", (user_id,))
        return StudyArm(row["arm"]) if row else None

    def assign_arm(self, conn, user_id: str, arm: StudyArm, method: str, assigned_by: str) -> None:
        conn.execute("INSERT OR REPLACE INTO study_assignment VALUES (?,?,?,?,?)",
                     (user_id, arm.value, method, assigned_by, utc_now()))

    def proactive_hints_on(self, user_id: str) -> bool:
        row = self.db.query_one("SELECT proactive_hints_on FROM user_preference WHERE user_id = ?", (user_id,))
        return bool(row["proactive_hints_on"]) if row else False   # default OFF

    def set_proactive_hints(self, conn, user_id: str, on: bool) -> None:
        conn.execute("INSERT OR REPLACE INTO user_preference VALUES (?,?,?)", (user_id, int(on), utc_now()))

    def has_consent(self, user_id: str) -> bool:
        row = self.db.query_one("SELECT decision FROM consent_record WHERE user_id = ? ORDER BY created_at DESC "
                                "LIMIT 1", (user_id,))
        return bool(row) and row["decision"] == "acknowledged"


class ContentRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert_outcome(self, conn, outcome: LearningOutcome) -> None:
        conn.execute("INSERT OR REPLACE INTO learning_outcome VALUES (?,?,?,?,?,?)",
                     (outcome.outcome_id, outcome.course_id, outcome.unit_title, outcome.description,
                      "|".join(outcome.prerequisite_ids), outcome.status.value))

    def outcomes(self) -> list[LearningOutcome]:
        return [LearningOutcome(outcome_id=r["outcome_id"], course_id=r["course_id"], unit_title=r["unit_title"],
                                description=r["description"],
                                prerequisite_ids=[p for p in r["prerequisite_ids"].split("|") if p],
                                status=ContentStatus(r["status"]))
                for r in self.db.query("SELECT * FROM learning_outcome ORDER BY outcome_id")]

    def upsert_misconception(self, conn, m: Misconception) -> None:
        conn.execute("INSERT OR REPLACE INTO misconception VALUES (?,?,?,?,?,?)",
                     (m.misconception_id, m.concept, m.label, m.observable_evidence, m.approved_feedback,
                      m.status.value))

    def misconception_ids(self) -> set[str]:
        return {r["misconception_id"] for r in self.db.query("SELECT misconception_id FROM misconception")}

    def misconceptions(self, ids: list[str]) -> list[Misconception]:
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        return [Misconception(**{k: r[k] for k in r.keys()})
                for r in self.db.query(f"SELECT * FROM misconception WHERE misconception_id IN ({marks})", tuple(ids))]

    def add_item_version(self, conn, item: Item) -> bool:
        """Insert a new item version as imported. Returns False if that version already exists."""
        cursor = conn.execute(
            "INSERT OR IGNORE INTO item_version VALUES (?,?,?,?,?,?,?,?)",
            (item.item_id, item.item_version, item.outcome_id, item.status.value, int(item.is_analogue),
             int(item.transfer_flag), item.model_dump_json(), utc_now()))
        return cursor.rowcount == 1

    def set_item_status(self, conn, item_id: str, item_version: str, status: ContentStatus) -> None:
        row = conn.execute("SELECT item_json FROM item_version WHERE item_id=? AND item_version=?",
                           (item_id, item_version)).fetchone()
        item = Item.model_validate_json(row["item_json"]).model_copy(update={"status": status})
        conn.execute("UPDATE item_version SET status=?, item_json=? WHERE item_id=? AND item_version=?",
                     (status.value, item.model_dump_json(), item_id, item_version))

    def get_item(self, item_id: str, item_version: str) -> Item | None:
        row = self.db.query_one("SELECT item_json FROM item_version WHERE item_id=? AND item_version=?",
                                (item_id, item_version))
        return Item.model_validate_json(row["item_json"]) if row else None

    def latest_approved(self, item_id: str) -> Item | None:
        row = self.db.query_one("SELECT item_json FROM item_version WHERE item_id=? AND status='approved' "
                                "ORDER BY imported_at DESC, item_version DESC LIMIT 1", (item_id,))
        return Item.model_validate_json(row["item_json"]) if row else None

    def items(self, status: ContentStatus | None = None, include_analogues: bool = True) -> list[Item]:
        sql, params = "SELECT item_json FROM item_version WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            params.append(status.value)
        if not include_analogues:
            sql += " AND is_analogue = 0"
        rows = self.db.query(sql + " ORDER BY outcome_id, item_id, item_version", tuple(params))
        return [Item.model_validate_json(r["item_json"]) for r in rows]

    def add_review(self, conn, review_id, item: Item, reviewer_id, decision, reason) -> None:
        conn.execute("INSERT INTO content_review VALUES (?,?,?,?,?,?,?)",
                     (review_id, item.item_id, item.item_version, reviewer_id, decision, reason, utc_now()))

    def reviews(self, item_id: str) -> list[sqlite3.Row]:
        return self.db.query("SELECT * FROM content_review WHERE item_id=? ORDER BY created_at", (item_id,))

    # Knowledge notes for retrieval
    def replace_notes(self, conn, notes: list[dict]) -> None:
        conn.execute("DELETE FROM knowledge_note")
        conn.execute("DELETE FROM knowledge_fts")
        for n in notes:
            conn.execute("INSERT INTO knowledge_note VALUES (?,?,?,?,?,?)",
                         (n["note_id"], n["source"], n["heading"], n["body"], n["version"], n["status"]))
            if n["status"] == ContentStatus.APPROVED.value:   # only approved notes are searchable
                conn.execute("INSERT INTO knowledge_fts VALUES (?,?,?)", (n["note_id"], n["heading"], n["body"]))


class PolicyRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, conn, config: PolicyConfig, status: str, source: str, rationale: str, proposed_by: str,
            approved_by: str | None = None) -> None:
        conn.execute("INSERT INTO scaffold_policy_version VALUES (?,?,?,?,?,?,?,?,?)",
                     (config.policy_version, config.model_dump_json(), status, source, rationale,
                      proposed_by, approved_by, utc_now(), utc_now() if approved_by else None))

    def active(self) -> PolicyConfig:
        row = self.db.query_one("SELECT config_json FROM scaffold_policy_version WHERE status='active'")
        if row is None:
            raise RuntimeError("No active scaffold policy. Run the seed script.")
        return PolicyConfig.model_validate_json(row["config_json"])

    def get(self, version: str) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM scaffold_policy_version WHERE policy_version=?", (version,))

    def all(self) -> list[sqlite3.Row]:
        return self.db.query("SELECT * FROM scaffold_policy_version ORDER BY created_at")

    def set_status(self, conn, version: str, status: str, decided_by: str | None = None) -> None:
        conn.execute("UPDATE scaffold_policy_version SET status=?, approved_by=COALESCE(?, approved_by), "
                     "decided_at=? WHERE policy_version=?", (status, decided_by, utc_now(), version))


class ExerciseRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _to_model(r) -> ExerciseSession:
        return ExerciseSession(session_id=r["session_id"], student_id=r["student_id"], item_id=r["item_id"],
                               item_version=r["item_version"], policy_version=r["policy_version"],
                               arm=StudyArm(r["arm"]), state=ExerciseState(r["state"]),
                               current_level=ScaffoldLevel(r["current_level"]),
                               max_level_reached=ScaffoldLevel(r["max_level_reached"]), attempts=r["attempts"],
                               hints_shown=r["hints_shown"], started_at=_dt(r["started_at"]),
                               updated_at=_dt(r["updated_at"]))

    def create(self, conn, s: ExerciseSession, task_type: str) -> None:
        conn.execute("INSERT INTO exercise_session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (s.session_id, s.student_id, s.item_id, s.item_version, s.policy_version, s.arm.value,
                      task_type, s.state.value, int(s.current_level), int(s.max_level_reached), s.attempts,
                      s.hints_shown, s.started_at.isoformat(), s.updated_at.isoformat()))

    def update(self, conn, s: ExerciseSession) -> None:
        conn.execute("UPDATE exercise_session SET state=?, current_level=?, max_level_reached=?, attempts=?, "
                     "hints_shown=?, updated_at=? WHERE session_id=?",
                     (s.state.value, int(s.current_level), int(s.max_level_reached), s.attempts, s.hints_shown,
                      utc_now(), s.session_id))

    def get(self, session_id: str) -> ExerciseSession | None:
        r = self.db.query_one("SELECT * FROM exercise_session WHERE session_id=?", (session_id,))
        return self._to_model(r) if r else None

    def task_type(self, session_id: str) -> str:
        return self.db.query_one("SELECT task_type FROM exercise_session WHERE session_id=?",
                                 (session_id,))["task_type"]

    def active_for(self, student_id: str) -> ExerciseSession | None:
        r = self.db.query_one("SELECT * FROM exercise_session WHERE student_id=? AND state='in_progress'",
                              (student_id,))
        return self._to_model(r) if r else None

    def for_student(self, student_id: str, states: set[ExerciseState] | None = None) -> list[ExerciseSession]:
        rows = self.db.query("SELECT * FROM exercise_session WHERE student_id=? ORDER BY started_at", (student_id,))
        sessions = [self._to_model(r) for r in rows]
        return [s for s in sessions if states is None or s.state in states]

    def add_attempt(self, conn, row: dict) -> None:
        # Named columns, so adding a column in a later migration does not break this insert.
        conn.execute("INSERT INTO attempt (attempt_id, session_id, attempt_number, final_answer_raw, reasoning_text, "
                     "normalised_answer, verification_status, verification_method, verification_reason, "
                     "scaffold_level, created_at, step_check_json) VALUES (:attempt_id,:session_id,:attempt_number,"
                     ":final_answer_raw,:reasoning_text,:normalised_answer,:verification_status,:verification_method,"
                     ":verification_reason,:scaffold_level,:created_at,:step_check_json)",
                     {"step_check_json": "[]", **row})

    def attempts(self, session_id: str) -> list[sqlite3.Row]:
        return self.db.query("SELECT * FROM attempt WHERE session_id=? ORDER BY attempt_number", (session_id,))

    def add_decision(self, conn, decision_id: str, session_id: str, decision) -> None:
        conn.execute("INSERT INTO scaffold_decision VALUES (?,?,?,?,?,?,?,?)",
                     (decision_id, session_id, int(decision.level), decision.action, decision.reason_code,
                      decision.policy_version, json.dumps(decision.inputs), utc_now()))

    def add_message(self, conn, message_id, session_id, student_id, mode, sender, response_type, content) -> None:
        conn.execute("INSERT INTO tutor_message VALUES (?,?,?,?,?,?,?,?)",
                     (message_id, session_id, student_id, mode, sender, response_type, content, utc_now()))

    def messages(self, session_id: str) -> list[sqlite3.Row]:
        return self.db.query("SELECT * FROM tutor_message WHERE session_id=? ORDER BY created_at, rowid",
                             (session_id,))

    def study_messages(self, student_id: str, limit: int = 20) -> list[sqlite3.Row]:
        rows = self.db.query("SELECT * FROM tutor_message WHERE student_id=? AND mode='study' "
                             "ORDER BY created_at DESC, rowid DESC LIMIT ?", (student_id, limit))
        return list(reversed(rows))

    def add_termination(self, conn, session_id, exit_type, stage: dict, reason) -> None:
        conn.execute("INSERT INTO termination VALUES (?,?,?,?,?,?)",
                     (session_id, exit_type, json.dumps(stage), reason, 1, utc_now()))


class EvidenceRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, conn, e: CompetenceEvidence) -> None:
        conn.execute("INSERT INTO competence_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (e.evidence_id, e.student_id, e.outcome_id, e.item_key, e.task_type,
                      int(e.final_answer_correct), e.reasoning_score, e.reasoning_assessor, e.support.value,
                      int(e.max_scaffold_level), e.attempts, e.source_event_id, e.created_at.isoformat(),
                      int(e.excluded), e.note))

    @staticmethod
    def _to_model(r) -> CompetenceEvidence:
        return CompetenceEvidence(
            evidence_id=r["evidence_id"], student_id=r["student_id"], outcome_id=r["outcome_id"],
            item_key=r["item_key"], task_type=r["task_type"], final_answer_correct=bool(r["final_answer_correct"]),
            reasoning_score=r["reasoning_score"], reasoning_assessor=r["reasoning_assessor"],
            support=SupportCategory(r["support"]), max_scaffold_level=ScaffoldLevel(r["max_scaffold_level"]),
            attempts=r["attempts"], source_event_id=r["source_event_id"], created_at=_dt(r["created_at"]),
            excluded=bool(r["excluded"]), note=r["note"])

    def for_student(self, student_id: str) -> list[CompetenceEvidence]:
        return [self._to_model(r) for r in self.db.query(
            "SELECT * FROM competence_evidence WHERE student_id=? ORDER BY created_at", (student_id,))]

    def get(self, evidence_id: str) -> CompetenceEvidence | None:
        r = self.db.query_one("SELECT * FROM competence_evidence WHERE evidence_id=?", (evidence_id,))
        return self._to_model(r) if r else None

    def all(self) -> list[CompetenceEvidence]:
        return [self._to_model(r) for r in self.db.query("SELECT * FROM competence_evidence ORDER BY created_at")]

    def annotate(self, conn, evidence_id: str, excluded: bool | None, note: str | None) -> None:
        """Lecturer decision after a challenge. The original fields are never overwritten."""
        if excluded is not None:
            conn.execute("UPDATE competence_evidence SET excluded=? WHERE evidence_id=?", (int(excluded), evidence_id))
        if note:
            conn.execute("UPDATE competence_evidence SET note=COALESCE(note || ' | ', '') || ? WHERE evidence_id=?",
                         (note, evidence_id))

    # Possible misconceptions (candidates). Stored in misconception_evidence from migration 001.
    def add_misconception_candidate(self, conn, row_id: str, student_id: str, misconception_id: str,
                                    source: str, confidence: float, attempt_id: str) -> None:
        conn.execute("INSERT INTO misconception_evidence VALUES (?,?,?,?,?,?,?,?,?)",
                     (row_id, student_id, misconception_id, "candidate", source, confidence, None, attempt_id,
                      utc_now()))

    def misconception_counts(self, student_id: str) -> dict[str, int]:
        """How often each possible misconception was seen for this student (rejected ones excluded)."""
        rows = self.db.query("SELECT misconception_id, COUNT(*) AS n FROM misconception_evidence "
                             "WHERE student_id=? AND status != 'rejected' GROUP BY misconception_id", (student_id,))
        return {r["misconception_id"]: r["n"] for r in rows}

    def class_misconceptions(self) -> list[sqlite3.Row]:
        return self.db.query(
            """SELECT me.misconception_id, m.label, COUNT(*) AS times, COUNT(DISTINCT me.student_id) AS students
               FROM misconception_evidence me LEFT JOIN misconception m ON m.misconception_id = me.misconception_id
               WHERE me.status != 'rejected' GROUP BY me.misconception_id ORDER BY times DESC""")

    # Challenges
    def add_challenge(self, conn, c: ProfileChallenge) -> None:
        conn.execute("INSERT INTO profile_challenge VALUES (?,?,?,?,?,?,?,?,?)",
                     (c.challenge_id, c.student_id, c.evidence_id, c.statement, c.status.value, None, None,
                      c.created_at.isoformat(), None))

    def challenges(self, student_id: str | None = None, status: ChallengeStatus | None = None) -> list[ProfileChallenge]:
        sql, params = "SELECT * FROM profile_challenge WHERE 1=1", []
        if student_id:
            sql, params = sql + " AND student_id=?", params + [student_id]
        if status:
            sql, params = sql + " AND status=?", params + [status.value]
        return [ProfileChallenge(challenge_id=r["challenge_id"], student_id=r["student_id"],
                                 evidence_id=r["evidence_id"], statement=r["statement"],
                                 status=ChallengeStatus(r["status"]), reviewer_id=r["reviewer_id"],
                                 decision_reason=r["decision_reason"], created_at=_dt(r["created_at"]),
                                 resolved_at=_dt(r["resolved_at"]))
                for r in self.db.query(sql + " ORDER BY created_at", tuple(params))]

    def resolve_challenge(self, conn, challenge_id, status: ChallengeStatus, reviewer_id, reason) -> None:
        conn.execute("UPDATE profile_challenge SET status=?, reviewer_id=?, decision_reason=?, resolved_at=? "
                     "WHERE challenge_id=?", (status.value, reviewer_id, reason, utc_now(), challenge_id))
