"""
Lecturer content import and automated validation.

Reads the lecturer asset files in content/ (curriculum map, misconception
library, item YAML, notes) and stores every item as a DRAFT version. Nothing
imported here reaches students until a lecturer approves it in the app
(services/lecturer_service.py). Automated validation only finds structural
and mathematical problems; it does not judge whether the content is good
teaching. That remains a human decision.

Validation checks per item:
    - required fields present and outcome / misconceptions known;
    - the canonical answer parses with the safe parser;
    - every acceptable form verifies as correct (catches typos in the key);
    - the linked analogue exists, is a worked analogue, and does not contain
      the active item's answer (it must not leak the solution);
    - the question stem does not already contain the answer as a new number.
"""

from __future__ import annotations

import csv
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from qmtutor.domain.models import ContentStatus, Item, LearningOutcome, Misconception, VerificationStatus
from qmtutor.mathcheck.safe_parser import MathParseError, parse_answer
from qmtutor.mathcheck.verifier import allowed_variables_for, numbers_in_text, verify_answer
from qmtutor.storage.db import Database
from qmtutor.storage.events import log_event
from qmtutor.storage.repositories import ContentRepository


@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    problems: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def _status(text: str) -> ContentStatus:
    return ContentStatus(str(text or "draft").strip().lower())


def load_outcomes(path: Path) -> list[LearningOutcome]:
    with open(path, encoding="utf-8") as f:
        return [LearningOutcome(outcome_id=r["outcome_id"], course_id=r["course_id"], unit_title=r["unit_title"],
                                description=r["learning_outcome"],
                                prerequisite_ids=[p for p in r["prerequisite_outcome_ids"].split("|") if p],
                                status=_status(r["status"]))
                for r in csv.DictReader(f)]


def load_misconceptions(path: Path) -> list[Misconception]:
    with open(path, encoding="utf-8") as f:
        return [Misconception(misconception_id=r["misconception_id"], concept=r["concept"], label=r["label"],
                              observable_evidence=r["observable_evidence"],
                              approved_feedback=r["approved_feedback"], status=_status(r["status"]))
                for r in csv.DictReader(f)]


def load_item_files(items_dir: Path) -> tuple[list[Item], dict[str, list[str]]]:
    """Parse every items/*.yaml file. Schema errors are reported, not raised."""
    items, problems = [], {}
    for path in sorted(items_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for raw in data.get("items", []):
            raw = {**raw, "status": "draft"}    # imports always start as drafts
            try:
                items.append(Item.model_validate(raw))
            except ValidationError as error:
                problems[f"{raw.get('item_id', '?')} ({path.name})"] = [
                    f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()]
    return items, problems


def validate_item(item: Item, all_items: dict[str, Item], outcome_ids: set[str],
                  misconception_ids: set[str]) -> list[str]:
    """Return a list of problems with one item (empty list = passes automated checks)."""
    problems = []
    if item.outcome_id not in outcome_ids:
        problems.append(f"unknown outcome {item.outcome_id}")
    unknown = set(item.misconception_ids) - misconception_ids
    if unknown:
        problems.append(f"unknown misconception ids {sorted(unknown)}")
    if item.is_analogue:
        if not item.worked_solution:
            problems.append("worked analogue has no worked_solution")
        return problems

    spec = item.answer_specification
    if spec is None:
        return problems + ["missing answer_specification"]
    try:
        correct = parse_answer(spec.canonical_expression, allowed_variables_for(spec), spec.unit_words)
    except MathParseError as error:
        return problems + [f"canonical answer does not parse: {error.message}"]
    for form in spec.acceptable_forms:
        if verify_answer(form, spec).status != VerificationStatus.CORRECT:
            problems.append(f"acceptable form '{form}' does not verify as correct")

    if not item.transfer_flag:
        if item.scaffold_sequence is None:
            problems.append("practice item has no scaffold_sequence")
        elif item.scaffold_sequence.analogous_example_id:
            analogue = all_items.get(item.scaffold_sequence.analogous_example_id)
            if analogue is None:
                problems.append(f"analogue {item.scaffold_sequence.analogous_example_id} not found")
            elif not analogue.is_analogue:
                problems.append("linked analogue is not a worked_analogue item")
            elif correct.expression.is_number and _contains_value(
                    " ".join([analogue.stem, *analogue.worked_solution]), float(correct.expression)):
                problems.append("analogue text contains the active item's answer (possible leak)")

    if correct.expression.is_number:
        answer = float(correct.expression)
        if answer not in (0, 1, 2) and _contains_value(item.stem, answer):
            problems.append("question stem already contains the answer value")

    # Typical wrong answers: the misconception must exist, and the "wrong" answer must really be
    # wrong; otherwise a correct student would be flagged with a misconception.
    for pattern in item.common_wrong_answers:
        if pattern.misconception_id not in misconception_ids:
            problems.append(f"wrong answer {pattern.value}: unknown misconception {pattern.misconception_id}")
        if verify_answer(pattern.value, spec).status == VerificationStatus.CORRECT:
            problems.append(f"wrong answer {pattern.value} is actually marked correct")
        try:
            parse_answer(pattern.value, allowed_variables_for(spec), spec.unit_words)
        except MathParseError:
            problems.append(f"wrong answer {pattern.value} cannot be read")
    return problems


def _contains_value(text: str, value: float) -> bool:
    return any(abs(n - value) < 1e-9 for n in numbers_in_text(text))


def parse_notes(notes_dir: Path) -> list[dict]:
    """Split each notes file into passages at '## ' headings, keeping file-level status and version."""
    notes = []
    for path in sorted(notes_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front, body = {}, text
        if text.startswith("---"):
            _, front_text, body = text.split("---", 2)
            front = yaml.safe_load(front_text) or {}
        for part in re.split(r"^## +", body, flags=re.MULTILINE)[1:]:
            heading, _, content = part.partition("\n")
            slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
            notes.append({"note_id": f"{path.stem}#{slug}", "source": path.name, "heading": heading.strip(),
                          "body": content.strip(), "version": str(front.get("version", "1.0")),
                          "status": _status(front.get("status")).value})
    return notes


def import_content(db: Database, content_dir: Path, actor_id: str = "system") -> ImportReport:
    """Import curriculum, misconceptions, items (as drafts) and notes. Safe to run again."""
    repo = ContentRepository(db)
    report = ImportReport()
    outcomes = load_outcomes(content_dir / "curriculum_map.csv")
    misconceptions = load_misconceptions(content_dir / "misconception_library.csv")
    items, schema_problems = load_item_files(content_dir / "items")
    report.problems.update(schema_problems)

    by_id = {i.item_id: i for i in items}
    outcome_ids = {o.outcome_id for o in outcomes}
    misconception_ids = {m.misconception_id for m in misconceptions}

    with db.transaction() as conn:
        for outcome in outcomes:
            repo.upsert_outcome(conn, outcome)
        for m in misconceptions:
            repo.upsert_misconception(conn, m)
        for item in items:
            problems = validate_item(item, by_id, outcome_ids, misconception_ids)
            if problems:
                report.problems[item.key] = problems
                continue
            if repo.add_item_version(conn, item):
                report.imported.append(item.key)
                log_event(conn, "item_imported", actor_id=actor_id, item_key=item.key,
                          payload={"status": "draft"}, idempotency_key=f"import:{item.key}:{uuid.uuid4().hex[:6]}")
            else:
                report.skipped_existing.append(item.key)

        existing = {r["note_id"]: r["status"] for r in db.query("SELECT note_id, status FROM knowledge_note")}
        notes = parse_notes(content_dir / "notes")
        for note in notes:   # keep a lecturer's approval when re-importing the same note
            if existing.get(note["note_id"]) == ContentStatus.APPROVED.value:
                note["status"] = ContentStatus.APPROVED.value
        repo.replace_notes(conn, notes)
    return report


if __name__ == "__main__":
    # Dry run: validate the content folder without a database.  python -m qmtutor.content.importer
    root = Path(__file__).resolve().parents[2] / "content"
    found, schema = load_item_files(root / "items")
    lookup = {i.item_id: i for i in found}
    outs = {o.outcome_id for o in load_outcomes(root / "curriculum_map.csv")}
    mis = {m.misconception_id for m in load_misconceptions(root / "misconception_library.csv")}
    print(f"{len(found)} items parsed; schema problems: {schema or 'none'}")
    for it in found:
        print(f"  {it.key:<16} {validate_item(it, lookup, outs, mis) or 'OK'}")
