"""
Module 2: diagnostic test.

Version 1 (this file): pick a few items per skill, and estimate mastery
of each skill as the PROPORTION CORRECT (a number from 0 to 1).
Version 2 (later): Bayesian Knowledge Tracing with pyBKT.

Run the test in the terminal:
    python -m tutor.diagnostic
"""

import time
import uuid

from tutor.answers import check_answer
from tutor.logger import Logger, valid_participant_code
from tutor.skills import load_config, load_items, load_skills


def select_diagnostic_items(items, per_skill):
    """
    Choose `per_skill` items for each broad skill, easiest first, with
    different sub-skills where possible. Returns a DataFrame.
    The choice is fixed (not random) so every participant sees the same test.
    """
    chosen = []
    for skill, group in items.groupby("skill", sort=False):
        group = group.sort_values(["difficulty", "item_id"])
        # First pass: one item from each sub-skill; second pass: fill up.
        firsts = group.drop_duplicates("subskill")
        picks = list(firsts.index[:per_skill])
        for idx in group.index:
            if len(picks) >= per_skill:
                break
            if idx not in picks:
                picks.append(idx)
        chosen.extend(picks)
    return items.loc[chosen]


def new_counts(skills):
    """Correct / attempted counters for each skill, all starting at 0."""
    return {s: {"correct": 0, "attempted": 0} for s in skills}


def record(counts, skill, correct):
    """Add one scored answer to the counters."""
    counts[skill]["attempted"] += 1
    counts[skill]["correct"] += int(correct)


def mastery_profile(counts):
    """
    Proportion correct per skill, e.g. {"algebraic_processes": 0.5, ...}.
    None means the skill has not been tested yet.
    """
    return {
        s: (round(c["correct"] / c["attempted"], 2) if c["attempted"] else None)
        for s, c in counts.items()
    }


def run_in_terminal():
    """Give the diagnostic test in the terminal and log every answer."""
    config = load_config()
    skills = load_skills(config)
    items = load_items(config)
    logger = Logger(config["logging"]["db_file"])

    code = input("Participant code (e.g. P001): ").strip().upper()
    while not valid_participant_code(code, config["participant_code_pattern"]):
        code = input("Invalid code. Use the format P001: ").strip().upper()

    session_id = uuid.uuid4().hex[:12]
    test = select_diagnostic_items(items, config["diagnostic"]["items_per_skill"])
    counts = new_counts(skills)

    print(f"\nDiagnostic test: {len(test)} questions. Type your answer and press Enter.\n")
    for number, (_, item) in enumerate(test.iterrows(), start=1):
        print(f"Q{number}. {item['question']}")
        started = time.time()
        answer = input("   Your answer: ")
        correct = check_answer(answer, item["answer"])
        record(counts, item["skill"], correct)
        logger.log(participant_code=code, arm=config["arm"], session_id=session_id,
                   phase="diagnostic", event_type="answer_attempt",
                   skill=item["skill"], item_id=item["item_id"],
                   student_text=answer, correct=correct,
                   response_time_seconds=time.time() - started)

    print("\nYour skill profile (proportion correct):")
    for skill, value in mastery_profile(counts).items():
        bar = "#" * round((value or 0) * 10)
        print(f"  {skills[skill]['label']:<30} {value:.2f}  {bar}")


if __name__ == "__main__":
    run_in_terminal()
