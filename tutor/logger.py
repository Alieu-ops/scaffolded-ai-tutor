"""
Module 7: interaction logging.

Every event (a chat message, an answer attempt, a hint, an item starting
or ending) becomes one row in an SQLite database file. SQLite is a
database stored in a single file; Python has it built in, so there is
nothing to install. scripts/export_logs.py turns the table into a CSV.

Only participant codes are stored, never names or phone numbers.
"""

import re
import sqlite3
from datetime import datetime, timezone

from tutor.skills import PROJECT_ROOT

# One row per event. `phase` (diagnostic / practice), `model` and `note`
# are extra columns beyond the brief, useful when analysing the data.
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_code      TEXT NOT NULL,
    arm                   TEXT NOT NULL,
    session_id            TEXT NOT NULL,
    phase                 TEXT,
    timestamp             TEXT NOT NULL,
    event_type            TEXT NOT NULL,
    skill                 TEXT,
    item_id               TEXT,
    student_text          TEXT,
    ai_text               TEXT,
    correct               INTEGER,
    response_time_seconds REAL,
    model                 TEXT,
    note                  TEXT
)
"""

EVENT_TYPES = {"message", "answer_attempt", "hint_shown", "item_start", "item_end"}


def valid_participant_code(code, pattern):
    """
    Check a participant code against the pattern in config.yaml
    (e.g. P001). This stops people typing their real name by mistake.
    """
    return re.fullmatch(pattern, code or "") is not None


class Logger:
    def __init__(self, db_path):
        self.db_path = PROJECT_ROOT / db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(CREATE_TABLE)

    def log(self, *, participant_code, arm, session_id, event_type, phase=None,
            skill=None, item_id=None, student_text=None, ai_text=None,
            correct=None, response_time_seconds=None, model=None, note=None):
        """Save one event. Arguments after * must be given by name."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event_type: {event_type}")
        row = {
            "participant_code": participant_code,
            "arm": arm,
            "session_id": session_id,
            "phase": phase,
            # UTC time, so logs from different laptops can be compared.
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event_type": event_type,
            "skill": skill,
            "item_id": item_id,
            "student_text": student_text,
            "ai_text": ai_text,
            "correct": None if correct is None else int(correct),
            "response_time_seconds": (None if response_time_seconds is None
                                      else round(response_time_seconds, 2)),
            "model": model,
            "note": note,   # e.g. "leak_blocked" when the tutor's draft gave the answer
        }
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)   # "?" stops SQL injection
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"INSERT INTO events ({columns}) VALUES ({placeholders})",
                         list(row.values()))
