"""
Milestone 1/3 tests: migrations, transactions, database-level rules, content
import validation and the lecturer approval workflow.
"""

import sqlite3

import pytest

from qmtutor.content.importer import validate_item
from qmtutor.domain.models import ContentStatus, Item
from qmtutor.seed import seed
from qmtutor.services.auth import PermissionDenied
from qmtutor.services.context import build_context
from qmtutor.services.lecturer_service import LecturerService, ReviewError
from qmtutor.storage.db import open_database
from qmtutor.storage.events import log_event


def test_migrations_apply_once_and_are_idempotent(tmp_path):
    db = open_database(tmp_path / "t.db")
    assert db.applied_migrations() == {"001", "002"}
    assert db.migrate() == []                     # second run applies nothing


def test_old_database_upgrades_to_002_without_losing_attempts(tmp_path, monkeypatch):
    """A database created before migration 002 existed keeps its rows and gains the new column."""
    import qmtutor.storage.db as dbmodule
    from qmtutor.storage.db import Database
    only_001 = tmp_path / "only_001"
    only_001.mkdir()
    (only_001 / "001_initial.sql").write_text(
        (dbmodule.MIGRATIONS_DIR / "001_initial.sql").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(dbmodule, "MIGRATIONS_DIR", only_001)
    old = Database(tmp_path / "old.db")
    old.migrate()
    old.connection.execute("PRAGMA foreign_keys = OFF")   # only takes effect outside a transaction
    with old.transaction() as conn:
        conn.execute("INSERT INTO attempt VALUES ('a1','s1',1,'7','my working',NULL,'correct','m','r',0,'now')")
    old.connection.close()

    monkeypatch.undo()                            # back to the real migrations folder (001 + 002)
    upgraded = open_database(tmp_path / "old.db")
    row = upgraded.query_one("SELECT reasoning_text, step_check_json FROM attempt WHERE attempt_id='a1'")
    assert row["reasoning_text"] == "my working" and row["step_check_json"] == "[]"


def test_transaction_rolls_back_on_error(ctx):
    before = ctx.db.query_one("SELECT COUNT(*) n FROM event")["n"]
    with pytest.raises(RuntimeError):
        with ctx.db.transaction() as conn:
            log_event(conn, "profile_viewed", subject_id="S001")
            raise RuntimeError("simulated failure after a write")
    assert ctx.db.query_one("SELECT COUNT(*) n FROM event")["n"] == before


def test_idempotency_key_prevents_duplicate_events(ctx):
    with ctx.db.transaction() as conn:
        log_event(conn, "profile_viewed", subject_id="S001", idempotency_key="sync-123")
        log_event(conn, "profile_viewed", subject_id="S001", idempotency_key="sync-123")
    assert ctx.db.query_one("SELECT COUNT(*) n FROM event WHERE idempotency_key='sync-123'")["n"] == 1


def test_unknown_event_type_rejected(ctx):
    with pytest.raises(ValueError):
        with ctx.db.transaction() as conn:
            log_event(conn, "keystroke_logged")


def test_database_allows_only_one_active_exercise_per_student(ctx):
    insert = ("INSERT INTO exercise_session VALUES (?, 'S001', 'LIN-001', '1.1', 'SP-1.0', 'scaffolded', "
              "'practice', 'in_progress', 0, 0, 0, 0, 'now', 'now')")
    with ctx.db.transaction() as conn:
        conn.execute(insert, ("a",))
    with pytest.raises(sqlite3.IntegrityError):
        with ctx.db.transaction() as conn:
            conn.execute(insert, ("b",))


def test_seed_approves_all_content_with_explicit_synthetic_reason(ctx):
    assert not ctx.content.items(ContentStatus.DRAFT)
    reasons = {r["reason"] for r in ctx.db.query("SELECT reason FROM content_review")}
    assert len(reasons) == 1 and reasons.pop().startswith("SYNTHETIC DEMO APPROVAL")


def test_drafts_are_not_available_to_students(settings, fake):
    context = build_context(settings, db_path=":memory:", provider=fake)
    seed(context, approve_content=False)
    from qmtutor.services.exercise_service import ExerciseService
    assert ExerciseService(context).available_items(context.users.get("S001")) == []


def _item(ctx, item_id):
    return ctx.content.latest_approved(item_id)


def test_validation_catches_wrong_answer_key(ctx):
    item = _item(ctx, "LIN-001")
    broken = item.model_copy(update={"answer_specification": item.answer_specification.model_copy(
        update={"acceptable_forms": ["7", "8"]})})
    problems = validate_item(broken, {"LIN-ANA-001": _item(ctx, "LIN-ANA-001")}, {"LO-01"}, {"MIS-002"})
    assert any("'8' does not verify" in p for p in problems)


def test_validation_catches_analogue_that_leaks_the_answer(ctx):
    item = _item(ctx, "LIN-001")
    leaky = _item(ctx, "LIN-ANA-001").model_copy(update={"worked_solution": ["so the answer is 7 parcels"]})
    problems = validate_item(item, {"LIN-ANA-001": leaky}, {"LO-01"}, {"MIS-002"})
    assert any("possible leak" in p for p in problems)


@pytest.mark.regression
def test_validation_catches_unknown_outcome_and_unparseable_answer(ctx):
    item = _item(ctx, "LIN-001")
    bad = item.model_copy(update={"outcome_id": "LO-99", "answer_specification":
                                  item.answer_specification.model_copy(update={"canonical_expression": "import"})})
    problems = validate_item(bad, {}, {"LO-01"}, {"MIS-002"})
    assert any("unknown outcome" in p for p in problems) and any("does not parse" in p for p in problems)


def test_new_version_supersedes_old_and_history_is_kept(ctx):
    lecturer = ctx.users.get("L001")
    old = _item(ctx, "LIN-002")
    new = old.model_copy(update={"item_version": "1.2", "status": ContentStatus.DRAFT,
                                 "stem": old.stem + " (reworded)"})
    with ctx.db.transaction() as conn:
        ctx.content.add_item_version(conn, new)
    LecturerService(ctx).decide_item(lecturer, "LIN-002", "1.2", "approved", "Clearer wording")
    assert ctx.content.latest_approved("LIN-002").item_version == "1.2"
    assert ctx.content.get_item("LIN-002", "1.1").status == ContentStatus.SUPERSEDED
    with pytest.raises(ReviewError):
        LecturerService(ctx).decide_item(lecturer, "LIN-002", "1.1", "approved", "try to republish")


def test_review_needs_reason_and_lecturer_role(ctx):
    service = LecturerService(ctx)
    with pytest.raises(ReviewError):
        service.decide_item(ctx.users.get("L001"), "LIN-001", "1.0", "retired", "  ")
    with pytest.raises(PermissionDenied):
        service.decide_item(ctx.users.get("S001"), "LIN-001", "1.0", "retired", "student tries")
    with pytest.raises(PermissionDenied):
        service.decide_item(ctx.users.get("R001"), "LIN-001", "1.0", "retired", "researcher tries")


def test_only_approved_notes_are_searchable(ctx):
    lecturer = ctx.users.get("L001")
    assert ctx.retriever.search("compound interest balance")
    service = LecturerService(ctx)
    for note in service.notes(lecturer):
        service.decide_note(lecturer, note["note_id"], False, "withdrawn for revision")
    assert ctx.retriever.search("compound interest balance") == []


def test_retrieval_query_cannot_inject_fts_syntax(ctx):
    for query in ['" OR 1=1 --', "NEAR(", "compound* AND", "'; DROP TABLE knowledge_note; --"]:
        ctx.retriever.search(query)            # must not raise
    assert ctx.db.query_one("SELECT COUNT(*) n FROM knowledge_note")["n"] > 0
