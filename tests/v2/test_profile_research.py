"""
Milestone 6/8 tests: challengeable profiles, lecturer decisions, policy
governance, study assignment and the pseudonymised research export.
"""

import csv
import json

import pytest

from qmtutor.domain.models import ChallengeStatus, PolicyConfig, StudyArm
from qmtutor.services.auth import PermissionDenied
from qmtutor.services.exercise_service import ExerciseService
from qmtutor.services.lecturer_service import LecturerService, ReviewError
from qmtutor.services.profile_service import ProfileService
from qmtutor.services.research_service import ResearchService
from tests.v2.conftest import consented


def _complete(ctx, student, item_id, answer):
    service = ExerciseService(ctx)
    session = service.start(student, item_id)
    service.submit_attempt(student, session.session_id, answer, "my working")
    return session


def test_student_sees_own_profile_only(ctx, student):
    _complete(ctx, student, "LIN-001", "7")
    profile = ProfileService(ctx).profile(student, "S001")
    summary, records = profile[0]
    assert summary.outcome_id == "LO-01" and summary.independent_correct == 1 and len(records) == 1
    with pytest.raises(PermissionDenied):
        ProfileService(ctx).profile(student, "S002")
    assert ProfileService(ctx).profile(ctx.users.get("L001"), "S001")      # lecturer may review
    with pytest.raises(PermissionDenied):
        ProfileService(ctx).profile(ctx.users.get("R001"), "S001")         # researcher uses exports instead


def test_challenge_and_removal_keeps_history(ctx, student):
    _complete(ctx, student, "LIN-001", "7")
    evidence_id = ctx.evidence.for_student("S001")[0].evidence_id
    challenge = ProfileService(ctx).submit_challenge(student, evidence_id, "My classmate used my account")
    lecturer = ctx.users.get("L001")
    assert LecturerService(ctx).open_challenges(lecturer)[0].challenge_id == challenge.challenge_id
    LecturerService(ctx).resolve_challenge(lecturer, challenge.challenge_id, ChallengeStatus.REMOVED,
                                           "Confirmed with student")
    record = ctx.evidence.get(evidence_id)
    assert record.excluded and "Confirmed with student" in record.note
    summary, _ = ProfileService(ctx).profile(student, "S001")[0]
    assert summary.total == 0
    assert ctx.db.query_one("SELECT COUNT(*) n FROM audit_event WHERE action='challenge_removed'")["n"] == 1
    with pytest.raises(ReviewError):     # cannot resolve twice
        LecturerService(ctx).resolve_challenge(lecturer, challenge.challenge_id, ChallengeStatus.UPHELD, "x")


def test_cannot_challenge_someone_elses_evidence(ctx, student):
    _complete(ctx, student, "LIN-001", "7")
    evidence_id = ctx.evidence.for_student("S001")[0].evidence_id
    with pytest.raises(PermissionDenied):
        ProfileService(ctx).submit_challenge(consented(ctx, "S004"), evidence_id, "not mine")


def test_llm_policy_suggestion_cannot_self_activate(ctx):
    lecturer, researcher = ctx.users.get("L001"), ctx.users.get("R001")
    service = LecturerService(ctx)
    proposal = PolicyConfig(policy_version="SP-1.1", min_attempts_for_analogue=3)
    service.propose_policy(researcher, proposal, "LLM noticed many analogue requests", source="llm_suggestion")
    assert ctx.policies.active().policy_version == "SP-1.0"          # proposal has no effect
    with pytest.raises(PermissionDenied):
        service.decide_policy(researcher, "SP-1.1", True, "ok", True)
    with pytest.raises(ReviewError):
        service.decide_policy(lecturer, "SP-1.1", True, "ok", regression_tests_confirmed=False)
    service.decide_policy(lecturer, "SP-1.1", True, "Reviewed examples", regression_tests_confirmed=True)
    assert ctx.policies.active().policy_version == "SP-1.1"


def test_students_cannot_change_or_see_assignment_controls(ctx, student):
    with pytest.raises(PermissionDenied):
        ResearchService(ctx).assign_unassigned(student, seed=1)
    with pytest.raises(PermissionDenied):
        ResearchService(ctx).assignments(student)


def test_block_randomisation_is_balanced_and_recorded(ctx):
    arms = [r["arm"] for r in ResearchService(ctx).assignments(ctx.users.get("R001"))]
    assert None not in arms
    assert sorted(arms[3:]) == sorted(a.value for a in StudyArm)        # S004-S006 form one balanced block


def test_export_is_pseudonymised_and_excludes_raw_text(ctx, student, tmp_path, fake):
    service = ExerciseService(ctx)
    session = service.start(student, "LIN-001")
    service.chat(student, session.session_id, "My name is Awa and I live in Serrekunda")
    service.submit_attempt(student, session.session_id, "7", "secret reasoning text")
    ResearchService(ctx).record_assessment(ctx.users.get("R001"), "S001", "paper_transfer", 4, 3)
    folder = ResearchService(ctx).export(ctx.users.get("R001"), tmp_path, purpose="unit test")
    everything = " ".join(p.read_text(encoding="utf-8") for p in folder.iterdir())
    for forbidden in ("S001", "Awa", "Serrekunda", "secret reasoning", "Student S001"):
        assert forbidden not in everything
    with open(folder / "events.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows and all(r["research_id"].startswith("RP-") for r in rows)
    assert {"item_key", "policy_version", "model"} <= set(rows[0])
    manifest = json.loads((folder / "manifest_and_data_dictionary.json").read_text(encoding="utf-8"))
    assert manifest["contains_raw_text"] is False and manifest["purpose"] == "unit test"
    assert ctx.db.query_one("SELECT COUNT(*) n FROM event WHERE event_type='research_export_created'")["n"] == 1


def test_only_researchers_can_export(ctx, tmp_path):
    for user_id in ("S001", "L001", "A001"):
        with pytest.raises(PermissionDenied):
            ResearchService(ctx).export(ctx.users.get(user_id), tmp_path, "x")


def test_class_patterns_are_aggregated(ctx, student):
    _complete(ctx, student, "LIN-001", "7")
    rows = LecturerService(ctx).class_patterns(ctx.users.get("L001"))
    row = next(r for r in rows if r["item"].startswith("LIN-001@"))
    assert row["completed"] == 1 and "student_id" not in row
