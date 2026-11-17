"""
Prompt assembly. Fills the templates in prompts/tutor_prompts_v2.yaml from
the scaffold decision, the approved item fields and retrieved notes.

Safety boundary (enforced by what this module chooses to pass in): the
scaffolded exercise prompt receives the question stem, the level's approved
cue and the student's OWN verified checkpoints. It never receives the answer
specification, the worked solution or unverified checkpoints. A test
(tests/v2/test_llm_contracts.py) asserts this for every item.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from qmtutor.domain.models import Checkpoint, Item, ScaffoldLevel

PROMPTS_FILE = Path(__file__).resolve().parents[2] / "prompts" / "tutor_prompts_v2.yaml"

# Human-readable policy ladder, from content/scaffold_levels.csv.
LEVEL_GUIDANCE = {
    ScaffoldLevel.INDEPENDENT: ("Independent attempt", "clarify the wording of the question only",
                                "any method, step or answer"),
    ScaffoldLevel.SELF_EXPLANATION: ("Self-explanation prompt", "questions that ask what is known, unknown and tried",
                                     "naming the method or the next calculation"),
    ScaffoldLevel.CONCEPTUAL_CUE: ("Conceptual cue", "pointing to the relevant definition or relationship",
                                   "substituting the question's values or deriving the answer"),
    ScaffoldLevel.STRATEGIC_HINT: ("Strategic hint", "the general method or a planning question",
                                   "a full sequence of steps with the question's numbers"),
    ScaffoldLevel.STEP_HINT: ("Step-focused hint", "naming the next decision or operation",
                              "doing the calculation or giving any resulting value"),
    ScaffoldLevel.PARTIAL_CONSOLIDATION: ("Partial consolidation",
                                          "restating ONLY the student's verified work listed below, then asking the next step",
                                          "introducing any new intermediate value"),
}


@lru_cache(maxsize=1)
def load_prompts() -> dict:
    return yaml.safe_load(PROMPTS_FILE.read_text(encoding="utf-8"))


def prompt_version() -> str:
    return load_prompts()["prompt_version"]


def approved_cue(item: Item, level: ScaffoldLevel) -> str:
    """The lecturer-approved text for a level (levels 0-4 use the scaffold sequence)."""
    seq = item.scaffold_sequence
    if seq is None:
        return "Try the first step yourself."
    return {ScaffoldLevel.INDEPENDENT: "Read the question carefully and decide what is being asked.",
            ScaffoldLevel.SELF_EXPLANATION: seq.self_explanation,
            ScaffoldLevel.CONCEPTUAL_CUE: seq.conceptual_cue,
            ScaffoldLevel.STRATEGIC_HINT: seq.strategic_hint}.get(level, seq.step_hint)


def format_notes(passages) -> str:
    if not passages:
        return "(no approved notes found)"
    return "\n".join(f"[{p.note_id}] {p.heading}: {p.body}" for p in passages)


def scaffolded_exercise_prompt(item: Item, level: ScaffoldLevel, verified: list[tuple[Checkpoint, str]],
                               passages, focus_notes: list[str] | None = None) -> str:
    level_for_text = min(level, ScaffoldLevel.PARTIAL_CONSOLIDATION)
    name, allowed, prohibited = LEVEL_GUIDANCE[ScaffoldLevel(level_for_text)]
    consolidation = ""
    if level_for_text == ScaffoldLevel.PARTIAL_CONSOLIDATION:
        lines = [f"- {cp.label}: the student wrote {value}" for cp, value in verified] or ["- (none verified yet)"]
        consolidation = "Student's verified work so far:\n" + "\n".join(lines) + "\n"
    return load_prompts()["scaffolded_exercise"].format(
        stem=item.stem, level=int(level_for_text), level_name=name, allowed=allowed, prohibited=prohibited,
        approved_cue=approved_cue(item, ScaffoldLevel(level_for_text)), consolidation_block=consolidation,
        notes=format_notes(passages), focus_block=_focus_block(focus_notes))


def _focus_block(focus_notes: list[str] | None) -> str:
    """Possible misconceptions this student has shown, with the lecturer's approved way to address them."""
    if not focus_notes:
        return ""
    lines = "\n".join(f"- {note}" for note in focus_notes)
    return ("This student's earlier answers suggest a possible difficulty. If it is relevant, address it "
            "using the lecturer's approach (as a question, not by giving steps):\n" + lines + "\n")


def study_prompt(passages) -> str:
    return load_prompts()["study"].format(notes=format_notes(passages))


def unrestricted_prompt(item: Item) -> str:
    return load_prompts()["unrestricted"].format(stem=item.stem)


def reasoning_prompt(item: Item, workings: str, final_answer: str = "", verdict: str = "",
                     steps=()) -> str:
    """
    Assessor prompt. Unlike the tutoring prompt, this one may include the worked solution:
    the assessment is shown to lecturers only, never to the student.
    """
    step_lines = "\n".join(f"- line {s.line_number}: {s.text} -> {s.status} ({s.detail})" for s in steps) \
        or "- (no equations found)"
    return load_prompts()["reasoning_assessment"].format(
        stem=item.stem, reasoning=workings, final_answer=final_answer or "(none)",
        verdict=verdict or "not checked", step_checks=step_lines,
        worked_solution="; ".join(item.worked_solution) or "(not provided)")
