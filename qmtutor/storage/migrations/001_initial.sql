-- Migration 001: initial schema for qmtutor (version 2).
-- Applied once by storage/db.py, inside a transaction, and recorded in
-- schema_migrations. Later changes go in 002_*.sql etc.; never edit this file
-- after it has been applied to a database holding real records.
--
-- Privacy design: user_account holds operational identity. Research exports
-- use research_participant_link.research_id instead, and that table is only
-- read by the research export service.

CREATE TABLE user_account (
    user_id       TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('student','lecturer','researcher','administrator')),
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE research_participant_link (
    user_id      TEXT PRIMARY KEY REFERENCES user_account(user_id),
    research_id  TEXT NOT NULL UNIQUE
);

CREATE TABLE consent_record (
    consent_id     TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL REFERENCES user_account(user_id),
    notice_version TEXT NOT NULL,
    decision       TEXT NOT NULL CHECK (decision IN ('acknowledged','declined')),
    scope          TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE study_assignment (
    user_id      TEXT PRIMARY KEY REFERENCES user_account(user_id),
    arm          TEXT NOT NULL CHECK (arm IN ('scaffolded','unrestricted','existing_support')),
    method       TEXT NOT NULL,          -- e.g. 'seeded_block_randomisation', 'manual_by_researcher'
    assigned_by  TEXT NOT NULL,
    assigned_at  TEXT NOT NULL
);

CREATE TABLE user_preference (
    user_id              TEXT PRIMARY KEY REFERENCES user_account(user_id),
    proactive_hints_on   INTEGER NOT NULL DEFAULT 0,   -- off by default (policy rule)
    updated_at           TEXT NOT NULL
);

-- Curriculum -------------------------------------------------------------
CREATE TABLE learning_outcome (
    outcome_id        TEXT PRIMARY KEY,
    course_id         TEXT NOT NULL,
    unit_title        TEXT NOT NULL,
    description       TEXT NOT NULL,
    prerequisite_ids  TEXT NOT NULL DEFAULT '',      -- pipe-separated
    status            TEXT NOT NULL
);

CREATE TABLE misconception (
    misconception_id     TEXT PRIMARY KEY,
    concept              TEXT NOT NULL,
    label                TEXT NOT NULL,
    observable_evidence  TEXT NOT NULL,
    approved_feedback    TEXT NOT NULL,
    status               TEXT NOT NULL
);

-- One row per item VERSION. The full validated item is stored as JSON so the
-- exact version a student saw can always be reconstructed.
CREATE TABLE item_version (
    item_id       TEXT NOT NULL,
    item_version  TEXT NOT NULL,
    outcome_id    TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('draft','reviewed','approved','retired','superseded')),
    is_analogue   INTEGER NOT NULL DEFAULT 0,
    transfer_flag INTEGER NOT NULL DEFAULT 0,
    item_json     TEXT NOT NULL,
    imported_at   TEXT NOT NULL,
    PRIMARY KEY (item_id, item_version)
);

CREATE TABLE content_review (
    review_id     TEXT PRIMARY KEY,
    item_id       TEXT NOT NULL,
    item_version  TEXT NOT NULL,
    reviewer_id   TEXT NOT NULL REFERENCES user_account(user_id),
    decision      TEXT NOT NULL,          -- reviewed / approved / returned / retired
    reason        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (item_id, item_version) REFERENCES item_version(item_id, item_version)
);

CREATE TABLE knowledge_note (
    note_id     TEXT PRIMARY KEY,         -- file stem + heading slug
    source      TEXT NOT NULL,            -- file name
    heading     TEXT NOT NULL,
    body        TEXT NOT NULL,
    version     TEXT NOT NULL,
    status      TEXT NOT NULL
);
-- Lexical search index (SQLite FTS5) over approved notes: the retrieval baseline.
CREATE VIRTUAL TABLE knowledge_fts USING fts5(note_id UNINDEXED, heading, body);

-- Scaffold policy --------------------------------------------------------
CREATE TABLE scaffold_policy_version (
    policy_version  TEXT PRIMARY KEY,
    config_json     TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('proposed','approved','active','retired','rejected')),
    source          TEXT NOT NULL,        -- 'human' or 'llm_suggestion' (suggestions can never self-activate)
    rationale       TEXT NOT NULL,
    proposed_by     TEXT NOT NULL,
    approved_by     TEXT,
    created_at      TEXT NOT NULL,
    decided_at      TEXT
);

-- Learning interaction -------------------------------------------------
CREATE TABLE exercise_session (
    session_id        TEXT PRIMARY KEY,
    student_id        TEXT NOT NULL REFERENCES user_account(user_id),
    item_id           TEXT NOT NULL,
    item_version      TEXT NOT NULL,
    policy_version    TEXT NOT NULL,
    arm               TEXT NOT NULL,
    task_type         TEXT NOT NULL DEFAULT 'practice',   -- practice / transfer
    state             TEXT NOT NULL CHECK (state IN ('in_progress','saved','completed','terminated','referred')),
    current_level     INTEGER NOT NULL DEFAULT 0,
    max_level_reached INTEGER NOT NULL DEFAULT 0,
    attempts          INTEGER NOT NULL DEFAULT 0,
    hints_shown       INTEGER NOT NULL DEFAULT 0,
    started_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (item_id, item_version) REFERENCES item_version(item_id, item_version)
);
-- At most one protected (in-progress) exercise per student, enforced by the database.
CREATE UNIQUE INDEX one_active_exercise ON exercise_session(student_id) WHERE state = 'in_progress';

CREATE TABLE attempt (
    attempt_id          TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES exercise_session(session_id),
    attempt_number      INTEGER NOT NULL,
    final_answer_raw    TEXT NOT NULL,
    reasoning_text      TEXT NOT NULL DEFAULT '',
    normalised_answer   TEXT,
    verification_status TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    verification_reason TEXT NOT NULL,
    scaffold_level      INTEGER NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE reasoning_assessment (
    assessment_id  TEXT PRIMARY KEY,
    attempt_id     TEXT NOT NULL REFERENCES attempt(attempt_id),
    dimension      TEXT NOT NULL,
    score          INTEGER,
    confidence     REAL,
    evidence_span  TEXT,
    assessor_type  TEXT NOT NULL,         -- 'llm_provisional' or 'lecturer'
    assessor_id    TEXT,
    model          TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE scaffold_decision (
    decision_id     TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES exercise_session(session_id),
    level           INTEGER NOT NULL,
    action          TEXT NOT NULL,
    reason_code     TEXT NOT NULL,
    policy_version  TEXT NOT NULL,
    inputs_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE tutor_message (
    message_id      TEXT PRIMARY KEY,
    session_id      TEXT,                 -- NULL for study-mode messages
    student_id      TEXT NOT NULL REFERENCES user_account(user_id),
    mode            TEXT NOT NULL,        -- 'exercise' or 'study'
    sender          TEXT NOT NULL,        -- 'student' or 'tutor'
    response_type   TEXT,                 -- e.g. 'hint_level_2', 'refusal', 'fallback', 'study_explanation'
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE termination (
    session_id   TEXT PRIMARY KEY REFERENCES exercise_session(session_id),
    exit_type    TEXT NOT NULL,           -- 'terminated' or 'referred'
    stage_json   TEXT NOT NULL,           -- level, attempts, hints at exit
    reason       TEXT,
    referral_offered INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

-- Learner evidence -------------------------------------------------------
CREATE TABLE competence_evidence (
    evidence_id         TEXT PRIMARY KEY,
    student_id          TEXT NOT NULL REFERENCES user_account(user_id),
    outcome_id          TEXT NOT NULL,
    item_key            TEXT NOT NULL,
    task_type           TEXT NOT NULL,
    final_answer_correct INTEGER NOT NULL,
    reasoning_score     INTEGER,
    reasoning_assessor  TEXT,
    support             TEXT NOT NULL,
    max_scaffold_level  INTEGER NOT NULL,
    attempts            INTEGER NOT NULL,
    source_event_id     TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    excluded            INTEGER NOT NULL DEFAULT 0,
    note                TEXT
);

CREATE TABLE profile_challenge (
    challenge_id    TEXT PRIMARY KEY,
    student_id      TEXT NOT NULL REFERENCES user_account(user_id),
    evidence_id     TEXT NOT NULL REFERENCES competence_evidence(evidence_id),
    statement       TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('open','upheld','amended','removed')),
    reviewer_id     TEXT,
    decision_reason TEXT,
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);

CREATE TABLE misconception_evidence (
    id                TEXT PRIMARY KEY,
    student_id        TEXT NOT NULL,
    misconception_id  TEXT,              -- NULL for an unnamed candidate pattern
    status            TEXT NOT NULL CHECK (status IN ('candidate','validated','rejected')),
    source            TEXT NOT NULL,
    confidence        REAL,
    reviewer_id       TEXT,
    attempt_id        TEXT,
    created_at        TEXT NOT NULL
);

-- Research and operations -----------------------------------------------
CREATE TABLE assessment_result (
    result_id     TEXT PRIMARY KEY,
    student_id    TEXT NOT NULL REFERENCES user_account(user_id),
    assessment    TEXT NOT NULL,          -- 'paper_transfer', 'digital_near_transfer', 'delayed_retention'
    final_answer_score REAL,
    reasoning_score    REAL,
    marker_id     TEXT,
    scheduled_for TEXT,
    recorded_at   TEXT NOT NULL
);

-- The event envelope (05_DATA_MODEL_PRIVACY_AND_LOGGING.md). One row per event.
CREATE TABLE event (
    event_id         TEXT PRIMARY KEY,
    occurred_at_utc  TEXT NOT NULL,
    actor_id         TEXT,
    subject_id       TEXT,
    correlation_id   TEXT,
    event_type       TEXT NOT NULL,
    schema_version   TEXT NOT NULL,
    item_key         TEXT,
    policy_version   TEXT,
    model            TEXT,
    prompt_version   TEXT,
    app_version      TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE    -- repeated delivery cannot duplicate an event
);
CREATE INDEX event_by_subject ON event(subject_id, occurred_at_utc);

CREATE TABLE audit_event (
    audit_id    TEXT PRIMARY KEY,
    actor_id    TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
