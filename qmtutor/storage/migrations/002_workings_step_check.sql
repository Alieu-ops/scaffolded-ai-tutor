-- Migration 002: store the deterministic step check of a student's workings,
-- and a short provisional comment from the LLM assessor.
-- Added 3 Oct 2026 when the reasoning box became a "Workings" box.
-- Existing databases get the new columns with empty values; nothing is lost.

ALTER TABLE attempt ADD COLUMN step_check_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE reasoning_assessment ADD COLUMN comment TEXT;
