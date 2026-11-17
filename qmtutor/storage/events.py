"""
Structured event log (the "event envelope" from 05_DATA_MODEL_PRIVACY_AND_LOGGING.md).

Each event records WHO did WHAT, WHEN, under WHICH item, policy, model and
prompt versions, with only the minimum payload needed. Events are written in
the same database transaction as the state change they describe, so the log
and the data can never disagree.

The idempotency key makes a repeated delivery harmless (useful later for
offline sync): inserting the same key twice is ignored, not duplicated.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

from qmtutor import APP_VERSION
from qmtutor.storage.db import utc_now

SCHEMA_VERSION = "1.0"

EVENT_TYPES = {
    "user_signed_in", "consent_recorded", "study_assigned",
    "study_query_submitted", "study_response_shown", "study_blocked_active_exercise",
    "exercise_started", "attempt_submitted", "math_verification_completed",
    "reasoning_assessment_completed", "hint_requested", "proactive_hint_setting_changed",
    "scaffold_decision_made", "tutor_feedback_shown", "leak_blocked", "reply_above_level_blocked",
    "exercise_saved", "exercise_resumed", "exercise_terminated", "exercise_completed",
    "exercise_referred", "misconception_candidate_created", "misconception_validated",
    "profile_viewed", "profile_challenge_submitted", "profile_challenge_resolved",
    "item_imported", "item_reviewed", "item_published", "item_retired",
    "policy_change_proposed", "policy_version_approved", "policy_change_rejected",
    "provider_failure", "research_export_created", "assessment_result_recorded",
}


def log_event(conn: sqlite3.Connection, event_type: str, *, actor_id: str | None = None,
              subject_id: str | None = None, correlation_id: str | None = None,
              item_key: str | None = None, policy_version: str | None = None,
              model: str | None = None, prompt_version: str | None = None,
              payload: dict | None = None, idempotency_key: str | None = None) -> str:
    """Insert one event using the caller's connection/transaction. Returns the event id."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    event_id = uuid.uuid4().hex
    conn.execute(
        """INSERT OR IGNORE INTO event (event_id, occurred_at_utc, actor_id, subject_id, correlation_id,
               event_type, schema_version, item_key, policy_version, model, prompt_version,
               app_version, payload_json, idempotency_key)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id, utc_now(), actor_id, subject_id, correlation_id, event_type, SCHEMA_VERSION,
         item_key, policy_version, model, prompt_version, APP_VERSION,
         json.dumps(payload or {}, default=str), idempotency_key or event_id))
    return event_id
