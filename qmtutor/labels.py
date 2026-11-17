"""
Plain-language labels for everything shown on screen.

The code and database use short machine names ("existing_support", "in_progress",
"min_attempts_for_analogue") because they must never change. People should never
have to read them. Every page translates through this one file, so wording can be
improved in one place without touching the logic or the stored data.
"""

from __future__ import annotations

import json
from datetime import datetime

ROLES = {"student": "Student", "lecturer": "Lecturer", "researcher": "Researcher", "administrator": "Administrator"}

ARMS = {"scaffolded": "Scaffolded tutor", "unrestricted": "Unrestricted AI assistant",
        "existing_support": "Existing support (no AI)"}

CONTENT_STATUS = {"draft": "Draft", "reviewed": "Reviewed", "approved": "Approved (students can see it)",
                  "retired": "Retired", "superseded": "Replaced by a newer version"}

ITEM_DECISIONS = {"reviewed": "Mark as reviewed", "approved": "Approve and publish",
                  "returned": "Return to draft", "retired": "Retire"}
ITEM_DECISIONS_PAST = {"reviewed": "Marked as reviewed", "approved": "Approved and published",
                       "returned": "Returned to draft", "retired": "Retired"}

EXERCISE_STATES = {"in_progress": "In progress", "saved": "Saved", "completed": "Completed",
                   "terminated": "Ended without the answer", "referred": "Asked for human help"}

SUPPORT = {"independent": "No hints", "low_support": "Some hints (levels 1-3)",
           "high_support": "Strong support (levels 4-6)"}

HINT_LEVELS = {0: "No hints yet", 1: "Explain your thinking", 2: "Concept reminder", 3: "Plan hint",
               4: "Next-step hint", 5: "Your correct work so far", 6: "Worked example (different numbers)",
               7: "Stopped or asked for help"}

ANSWER_CHECK = {"correct": "Correct", "incorrect": "Not correct", "unsupported": "Could not be read",
                "empty": "No answer"}

CHALLENGE_STATUS = {"open": "Waiting for the lecturer", "upheld": "Kept as recorded",
                    "amended": "Lecturer added a note", "removed": "Removed from the profile"}
CHALLENGE_DECISIONS = {"upheld": "Keep as recorded", "amended": "Add a note", "removed": "Remove from profile"}

ASSESSMENTS = {"paper_transfer": "Paper test: unfamiliar problems (no AI)",
               "digital_near_transfer": "Digital independent check (no AI)",
               "delayed_retention": "Delayed retention test (no AI)"}

POLICY_STATUS = {"proposed": "Proposed (not in use)", "approved": "Approved", "active": "In use",
                 "retired": "No longer in use", "rejected": "Rejected"}
POLICY_SOURCE = {"human": "A person", "llm_suggestion": "An AI suggestion (needs human review)", "system": "Initial set-up"}

# Each policy setting with a plain explanation, in the order a lecturer would think about them.
POLICY_FIELDS = {
    "policy_version": ("Version", "Name of this set of rules."),
    "max_hint_level": ("Strongest hint allowed", "6 = a worked example with different numbers; the answer is never shown."),
    "min_attempts_for_consolidation": ("Wrong answers before 'your correct work so far'",
                                       "Level 5 restates the student's own correct steps, so it needs some work first."),
    "min_attempts_for_analogue": ("Wrong answers before a worked example", "Part of 'persistent struggle'."),
    "min_hints_before_analogue": ("Hints before a worked example", "Part of 'persistent struggle'."),
    "proactive_hints_default": ("Automatic hints on at the start", "Students can always switch them on or off."),
    "low_support_max_level": ("Highest level that counts as 'some hints'", "Higher levels count as 'strong support'."),
}

RUBRIC = {"method_selection": "Method", "mathematical_steps": "Steps", "conceptual_explanation": "Explanation"}

EVENTS = {
    "user_signed_in": "Signed in", "consent_recorded": "Study notice answered", "study_assigned": "Study group assigned",
    "study_query_submitted": "Study questions asked", "study_response_shown": "Study answers shown",
    "study_blocked_active_exercise": "Study blocked during an exercise", "exercise_started": "Exercises started",
    "attempt_submitted": "Answers handed in", "math_verification_completed": "Answers checked by computer",
    "reasoning_assessment_completed": "Workings scored by AI (provisional)", "hint_requested": "Hints requested",
    "proactive_hint_setting_changed": "Automatic-hint setting changed", "scaffold_decision_made": "Hint decisions",
    "tutor_feedback_shown": "Tutor messages shown", "leak_blocked": "AI replies blocked (would reveal answer)",
    "reply_above_level_blocked": "AI replies blocked (more help than the hint level allows)",
    "misconception_candidate_created": "Possible misconceptions noticed",
    "exercise_saved": "Exercises saved", "exercise_resumed": "Exercises resumed", "exercise_terminated": "Exercises ended",
    "exercise_completed": "Exercises completed", "exercise_referred": "Requests for human help",
    "profile_viewed": "Profiles viewed", "profile_challenge_submitted": "Profile challenges sent",
    "profile_challenge_resolved": "Profile challenges resolved", "item_imported": "Exercises imported",
    "item_reviewed": "Exercise reviews", "item_published": "Exercises published", "item_retired": "Exercises retired",
    "policy_change_proposed": "Policy changes proposed", "policy_version_approved": "Policy versions approved",
    "policy_change_rejected": "Policy changes rejected", "provider_failure": "AI model failures",
    "research_export_created": "Research exports", "assessment_result_recorded": "Assessment results entered",
}


def label(mapping: dict, value, default: str | None = None) -> str:
    """Look up a label; fall back to a tidied version of the machine name, never the raw one."""
    if value is None:
        return default or "-"
    return mapping.get(value, default or humanise(str(value)))


def humanise(name: str) -> str:
    """'in_progress_or_saved' -> 'In progress or saved' (last-resort fallback)."""
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else text


def item_label(item_key: str) -> str:
    """'LIN-001@1.0' -> 'LIN-001 (version 1.0)'."""
    item_id, _, version = str(item_key).partition("@")
    return f"{item_id} (version {version})" if version else item_id


def when(timestamp) -> str:
    """ISO time or datetime -> '3 Oct 2026, 14:55 UTC'."""
    if not timestamp:
        return "-"
    moment = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp))
    return moment.strftime("%d %b %Y, %H:%M UTC").lstrip("0")


def assignment_method(method: str | None) -> str:
    if not method:
        return "Not assigned yet"
    if method.startswith("block_randomisation_seed_"):
        return f"Random, in blocks of 3 (seed {method.rsplit('_', 1)[-1]})"
    return {"manual_demo_assignment": "Set by hand for the demo", "manual_by_researcher": "Set by a researcher"}.get(
        method, humanise(method))


def exit_stage(stage_json: str) -> str:
    """Termination/referral stage -> 'Hint level 4 (Next-step hint), 2 answers, 4 hints'."""
    stage = json.loads(stage_json or "{}")
    level = stage.get("max_level", stage.get("level", 0))
    return (f"Hint level {level} ({HINT_LEVELS.get(level, '')}), {stage.get('attempts', 0)} answer(s), "
            f"{stage.get('hints_shown', 0)} hint(s)")


def rubric_scores(raw: str | None) -> str:
    """'method_selection=1, mathematical_steps=2, steps capped by rule=1' -> 'Method 1/2, Steps 2/2 -> 1/2 ...'."""
    if not raw:
        return "Not scored"
    parts, cap = {}, None
    for piece in raw.split(", "):
        name, _, score = piece.rpartition("=")
        if name == "steps capped by rule":
            cap = score
        else:
            parts[name] = score
    out = []
    for key in ("method_selection", "mathematical_steps", "conceptual_explanation"):
        if key in parts:
            text = f"{RUBRIC[key]} {parts[key]}/2"
            if key == "mathematical_steps" and cap is not None:
                text += f" (lowered to {cap}/2: computer found an error)"
            out.append(text)
    return ", ".join(out)
