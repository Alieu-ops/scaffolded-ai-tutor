"""
Research services: study assignment, assessment results, pseudonymised export.

Assignment: block randomisation with a fixed seed, so the allocation is
reproducible and balanced across the three arms; the method and who ran it are
recorded. Students never see or change their arm through the app.

Export: replaces operational user ids with research ids from the separate
research_participant_link table, drops raw chat text and free-text answers by
default, keeps item / policy / model versions, and writes a data dictionary.
Creating an export is itself logged.

Primary outcomes (transfer and retention scores) are stored in
assessment_result, separately from practice logs, so process data cannot be
mistaken for learning outcomes.
"""

from __future__ import annotations

import csv
import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from qmtutor.domain.models import Role, StudyArm, UserAccount
from qmtutor.services.auth import require_role
from qmtutor.services.context import AppContext
from qmtutor.storage.db import utc_now
from qmtutor.storage.events import log_event

RESEARCH = {Role.RESEARCHER}
ARMS = [StudyArm.SCAFFOLDED, StudyArm.UNRESTRICTED, StudyArm.EXISTING_SUPPORT]

EXPORT_DICTIONARY = {
    "events.csv": {
        "research_id": "Pseudonymous participant id (not the login id).",
        "occurred_at_utc": "Event time, UTC ISO 8601.",
        "event_type": "Event name from the taxonomy in qmtutor/storage/events.py.",
        "arm": "Assigned study condition.",
        "correlation_id": "Exercise session id linking events of one exercise.",
        "item_key": "Item id and version used.",
        "policy_version": "Scaffold policy version in force.",
        "model": "LLM provider and model, if used.",
        "prompt_version": "Prompt template version, if used.",
        "payload_json": "Minimal structured details; raw chat text is never included.",
    },
    "evidence.csv": {
        "research_id": "Pseudonymous participant id.",
        "outcome_id": "Learning outcome.", "item_key": "Item id and version.",
        "task_type": "practice or transfer.", "final_answer_correct": "1/0, deterministic verifier.",
        "reasoning_score": "Provisional LLM rubric total 0-6 (not validated), or blank.",
        "support": "independent / low_support / high_support.", "max_scaffold_level": "0-7.",
        "attempts": "Counted answer attempts.", "excluded": "1 if removed after a lecturer-reviewed challenge.",
    },
    "assessments.csv": {
        "research_id": "Pseudonymous participant id.",
        "assessment": "paper_transfer / digital_near_transfer / delayed_retention.",
        "final_answer_score": "Score as entered.", "reasoning_score": "Score as entered.",
        "scheduled_for": "Planned date for delayed assessment.", "recorded_at": "UTC time recorded.",
    },
}


class ResearchService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def assignments(self, user: UserAccount) -> list[dict]:
        require_role(user, RESEARCH | {Role.ADMINISTRATOR})
        return [dict(r) for r in self.ctx.db.query(
            "SELECT u.user_id, l.research_id, s.arm, s.method, s.assigned_at FROM user_account u "
            "LEFT JOIN research_participant_link l ON l.user_id = u.user_id "
            "LEFT JOIN study_assignment s ON s.user_id = u.user_id WHERE u.role = 'student' ORDER BY u.user_id")]

    def pseudonymous_assignments(self, user: UserAccount) -> list[dict]:
        """
        What a researcher may see: research id, group and method only. The login id is
        deliberately left out; the link between the two stays inside the service.
        """
        return [{k: r[k] for k in ("research_id", "arm", "method", "assigned_at")} for r in self.assignments(user)]

    def record_assessment_by_research_id(self, user: UserAccount, research_id: str, assessment: str,
                                         final_answer_score: float | None, reasoning_score: float | None) -> None:
        """Enter a paper-test score labelled with a research id (no names on the answer sheet)."""
        require_role(user, RESEARCH | {Role.LECTURER})
        row = self.ctx.db.query_one("SELECT user_id FROM research_participant_link WHERE research_id = ?",
                                    (research_id,))
        if row is None:
            raise ValueError("Unknown research id.")
        self.record_assessment(user, row["user_id"], assessment, final_answer_score, reasoning_score)

    def assign_unassigned(self, researcher: UserAccount, seed: int) -> dict[str, str]:
        """Block-randomise every unassigned student across the three arms (blocks of 3)."""
        require_role(researcher, RESEARCH)
        unassigned = [r["user_id"] for r in self.assignments(researcher) if r["arm"] is None]
        rng = random.Random(seed)
        result = {}
        with self.ctx.db.transaction() as conn:
            for start in range(0, len(unassigned), 3):
                block = ARMS.copy()
                rng.shuffle(block)
                for user_id, arm in zip(unassigned[start:start + 3], block):
                    self.ctx.users.assign_arm(conn, user_id, arm, f"block_randomisation_seed_{seed}",
                                              researcher.user_id)
                    log_event(conn, "study_assigned", actor_id=researcher.user_id, subject_id=user_id,
                              payload={"arm": arm.value, "method": "block_randomisation", "seed": seed})
                    result[user_id] = arm.value
        return result

    def record_assessment(self, user: UserAccount, student_id: str, assessment: str,
                          final_answer_score: float | None, reasoning_score: float | None,
                          scheduled_for: str | None = None) -> None:
        """Enter a supervised (no-AI) assessment score, e.g. from a paper test."""
        require_role(user, RESEARCH | {Role.LECTURER})
        if assessment not in ("paper_transfer", "digital_near_transfer", "delayed_retention"):
            raise ValueError("Unknown assessment type.")
        with self.ctx.db.transaction() as conn:
            conn.execute("INSERT INTO assessment_result VALUES (?,?,?,?,?,?,?,?)",
                         (uuid.uuid4().hex, student_id, assessment, final_answer_score, reasoning_score,
                          user.user_id, scheduled_for, utc_now()))
            log_event(conn, "assessment_result_recorded", actor_id=user.user_id, subject_id=student_id,
                      payload={"assessment": assessment})

    def export(self, researcher: UserAccount, out_dir: Path, purpose: str) -> Path:
        """Write a pseudonymised export folder and return its path."""
        require_role(researcher, RESEARCH)
        if not purpose.strip():
            raise ValueError("State the purpose of the export.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder = Path(out_dir) / f"export_{stamp}"
        folder.mkdir(parents=True, exist_ok=False)
        link = {r["user_id"]: r["research_id"] for r in self.ctx.db.query("SELECT * FROM research_participant_link")}
        arms = {r["user_id"]: r["arm"] for r in self.ctx.db.query("SELECT user_id, arm FROM study_assignment")}

        def rid(user_id):
            return link.get(user_id, "UNLINKED")

        events = self.ctx.db.query("SELECT * FROM event WHERE subject_id IN (SELECT user_id FROM user_account "
                                   "WHERE role='student') ORDER BY occurred_at_utc")
        self._write(folder / "events.csv", EXPORT_DICTIONARY["events.csv"],
                    [{"research_id": rid(e["subject_id"]), "occurred_at_utc": e["occurred_at_utc"],
                      "event_type": e["event_type"], "arm": arms.get(e["subject_id"]),
                      "correlation_id": e["correlation_id"], "item_key": e["item_key"],
                      "policy_version": e["policy_version"], "model": e["model"],
                      "prompt_version": e["prompt_version"], "payload_json": e["payload_json"]} for e in events])
        evidence = self.ctx.evidence.all()
        self._write(folder / "evidence.csv", EXPORT_DICTIONARY["evidence.csv"],
                    [{"research_id": rid(e.student_id), "outcome_id": e.outcome_id, "item_key": e.item_key,
                      "task_type": e.task_type, "final_answer_correct": int(e.final_answer_correct),
                      "reasoning_score": e.reasoning_score, "support": e.support.value,
                      "max_scaffold_level": int(e.max_scaffold_level), "attempts": e.attempts,
                      "excluded": int(e.excluded)} for e in evidence])
        results = self.ctx.db.query("SELECT * FROM assessment_result ORDER BY recorded_at")
        self._write(folder / "assessments.csv", EXPORT_DICTIONARY["assessments.csv"],
                    [{"research_id": rid(r["student_id"]), "assessment": r["assessment"],
                      "final_answer_score": r["final_answer_score"], "reasoning_score": r["reasoning_score"],
                      "scheduled_for": r["scheduled_for"], "recorded_at": r["recorded_at"]} for r in results])
        manifest = {"created_by": researcher.user_id, "created_at_utc": utc_now(), "purpose": purpose.strip(),
                    "schema_version": "1.0", "contains_raw_text": False,
                    "note": "Synthetic prototype data. Research ids only; operational ids excluded.",
                    "data_dictionary": EXPORT_DICTIONARY}
        (folder / "manifest_and_data_dictionary.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with self.ctx.db.transaction() as conn:
            log_event(conn, "research_export_created", actor_id=researcher.user_id,
                      payload={"folder": folder.name, "purpose": purpose.strip(), "rows_events": len(events)})
        return folder

    @staticmethod
    def _write(path: Path, dictionary: dict, rows: list[dict]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(dictionary))
            writer.writeheader()
            writer.writerows(rows)

    def health(self, user: UserAccount) -> dict:
        """Basic system health: database, model server, counts. No personal data."""
        require_role(user, RESEARCH | {Role.ADMINISTRATOR, Role.LECTURER})
        info = {"database": "ok", "provider": self.ctx.model_label}
        counts = self.ctx.db.query("SELECT event_type, COUNT(*) AS n FROM event GROUP BY event_type")
        info["event_counts"] = {r["event_type"]: r["n"] for r in counts}
        info["provider_failures"] = info["event_counts"].get("provider_failure", 0)
        info["leaks_blocked"] = info["event_counts"].get("leak_blocked", 0)
        try:
            import requests
            if self.ctx.provider.name == "ollama":
                requests.get(self.ctx.settings["llm"]["ollama_url"] + "/api/version", timeout=3).raise_for_status()
            info["model_server"] = "reachable" if self.ctx.provider.name == "ollama" else "not checked"
        except Exception:
            info["model_server"] = "NOT reachable"
        return info
