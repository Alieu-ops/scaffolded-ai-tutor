"""
Seed a database with SYNTHETIC demo data: accounts, content, the first scaffold
policy, and study assignments. Used by the app on first start, by
scripts/seed_demo.py and by the tests.

The demo approval of items and notes is recorded under the synthetic lecturer
L001 with an explicit reason, so the audit trail never pretends a real
lecturer reviewed the content.

Run:  python -m qmtutor.seed                    (creates data_v2/qmtutor.db if empty)
      python -m qmtutor.seed --reset            (deletes and recreates it)
      python -m qmtutor.seed --update-content   (imports new exercise versions from content/
                                                 and gives them the synthetic demo approval)
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from qmtutor.content.importer import import_content
from qmtutor.domain.models import ContentStatus, PolicyConfig, Role, StudyArm, UserAccount
from qmtutor.services.context import PROJECT_ROOT, AppContext, build_context, load_settings
from qmtutor.services.lecturer_service import LecturerService
from qmtutor.services.research_service import ResearchService
from qmtutor.storage.events import log_event

DEMO_APPROVAL_REASON = "SYNTHETIC DEMO APPROVAL - not a real lecturer review; draft content for prototype testing only."

DEMO_USERS = [
    ("S001", "Student S001 (demo: scaffolded tutor)", Role.STUDENT),
    ("S002", "Student S002 (demo: unrestricted AI)", Role.STUDENT),
    ("S003", "Student S003 (demo: existing support, no AI)", Role.STUDENT),
    ("S004", "Student S004", Role.STUDENT),
    ("S005", "Student S005", Role.STUDENT),
    ("S006", "Student S006", Role.STUDENT),
    ("L001", "Lecturer L001 (synthetic)", Role.LECTURER),
    ("R001", "Researcher R001 (synthetic)", Role.RESEARCHER),
    ("A001", "Administrator A001 (synthetic)", Role.ADMINISTRATOR),
]
DEMO_ARMS = {"S001": StudyArm.SCAFFOLDED, "S002": StudyArm.UNRESTRICTED, "S003": StudyArm.EXISTING_SUPPORT}


def is_seeded(ctx: AppContext) -> bool:
    return ctx.db.query_one("SELECT COUNT(*) AS n FROM user_account")["n"] > 0


def seed(ctx: AppContext, approve_content: bool = True) -> None:
    """Populate an empty database. Safe to call only once per database."""
    if is_seeded(ctx):
        return
    with ctx.db.transaction() as conn:
        for index, (user_id, name, role) in enumerate(DEMO_USERS, start=1):
            ctx.users.add(conn, UserAccount(user_id=user_id, display_name=name, role=role))
            if role == Role.STUDENT:
                # Research ids are deliberately unrelated to login ids.
                ctx.users.set_research_id(conn, user_id, f"RP-{(index * 7919) % 10000:04d}")
        policy = PolicyConfig.model_validate(
            yaml.safe_load((PROJECT_ROOT / ctx.settings["policy_file"]).read_text(encoding="utf-8")))
        ctx.policies.add(conn, policy, "active", "human", "Initial policy from 04_SCAFFOLDING_POLICY.md (for review)",
                         "system", approved_by="system")
        for user_id, arm in DEMO_ARMS.items():
            ctx.users.assign_arm(conn, user_id, arm, "manual_demo_assignment", "system")
            log_event(conn, "study_assigned", actor_id="system", subject_id=user_id,
                      payload={"arm": arm.value, "method": "manual_demo_assignment"})

    report = import_content(ctx.db, PROJECT_ROOT / ctx.settings["content_dir"])
    if not report.ok:
        raise RuntimeError(f"Content validation failed: {report.problems}")

    researcher = ctx.users.get("R001")
    ResearchService(ctx).assign_unassigned(researcher, seed=20261003)

    if approve_content:
        lecturer = ctx.users.get("L001")
        service = LecturerService(ctx)
        # Analogues first, so practice items can link to approved worked examples.
        for item in sorted(ctx.content.items(ContentStatus.DRAFT), key=lambda i: not i.is_analogue):
            service.decide_item(lecturer, item.item_id, item.item_version, "approved", DEMO_APPROVAL_REASON)
        for note in service.notes(lecturer):
            service.decide_note(lecturer, note["note_id"], True, DEMO_APPROVAL_REASON)


def update_content(ctx: AppContext) -> list[str]:
    """Import new item versions into an existing database and approve them (synthetic demo approval)."""
    report = import_content(ctx.db, PROJECT_ROOT / ctx.settings["content_dir"])
    if not report.ok:
        raise RuntimeError(f"Content validation failed: {report.problems}")
    lecturer = ctx.users.get("L001")
    service = LecturerService(ctx)
    for item in sorted(ctx.content.items(ContentStatus.DRAFT), key=lambda i: not i.is_analogue):
        service.decide_item(lecturer, item.item_id, item.item_version, "approved", DEMO_APPROVAL_REASON)
    return report.imported


def main(argv: list[str]) -> None:
    settings = load_settings()
    path = PROJECT_ROOT / settings["database"]
    if "--reset" in argv and path.exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
    ctx = build_context(settings)
    if "--update-content" in argv and is_seeded(ctx):
        imported = update_content(ctx)
        print("New versions imported and approved: " + (", ".join(imported) or "none"))
        return
    already = is_seeded(ctx)
    seed(ctx)
    print("Database already seeded." if already else f"Seeded synthetic demo data in {path}")
    for row in ResearchService(ctx).assignments(ctx.users.get("R001")):
        print(f"  {row['user_id']}  research_id={row['research_id']}  arm={row['arm']}")


if __name__ == "__main__":
    main(sys.argv[1:])
