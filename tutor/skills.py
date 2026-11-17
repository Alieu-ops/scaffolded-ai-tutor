"""
Module 1: skill map and item bank.

This file only LOADS and CHECKS data. The skills and questions themselves
live in data/skills.yaml and data/items.csv, so a different level or
subject can be used later by pointing config.yaml at different files.

Run it on its own to see a summary:
    python -m tutor.skills
"""

from pathlib import Path

import pandas as pd
import yaml

# The project folder is the parent of the tutor/ folder.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Columns every item must have (from the brief), plus `status` (draft/reviewed).
REQUIRED_ITEM_COLUMNS = [
    "item_id", "skill", "subskill", "difficulty",
    "question", "answer", "worked_solution", "status",
]


def load_config(path="config.yaml"):
    """Read config.yaml and return it as a Python dictionary."""
    with open(PROJECT_ROOT / path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_skills(config):
    """Read the skill map (a dictionary: skill id -> label and sub-skills)."""
    with open(PROJECT_ROOT / config["data"]["skills_file"], encoding="utf-8") as f:
        return yaml.safe_load(f)["skills"]


def load_items(config):
    """Read the item bank into a pandas DataFrame (one row per question)."""
    # dtype=str keeps answers like "3/8" or "060" exactly as written.
    items = pd.read_csv(PROJECT_ROOT / config["data"]["items_file"], dtype=str)
    items["difficulty"] = items["difficulty"].astype(int)
    return items


def check_items(items, skills):
    """
    Check the item bank against the skill map.
    Returns a list of problems (an empty list means everything is fine).
    """
    problems = []

    missing = [c for c in REQUIRED_ITEM_COLUMNS if c not in items.columns]
    if missing:
        return [f"items.csv is missing columns: {missing}"]

    if items["item_id"].duplicated().any():
        dupes = items.loc[items["item_id"].duplicated(), "item_id"].tolist()
        problems.append(f"Duplicate item_id values: {dupes}")

    for _, row in items.iterrows():
        if row["skill"] not in skills:
            problems.append(f"{row['item_id']}: unknown skill '{row['skill']}'")
        elif row["subskill"] not in skills[row["skill"]]["subskills"]:
            problems.append(f"{row['item_id']}: unknown subskill '{row['subskill']}'")
        if row["difficulty"] not in (1, 2, 3):
            problems.append(f"{row['item_id']}: difficulty must be 1, 2 or 3")

    return problems


def empty_profile(skills):
    """
    A starting skill profile for a new student: mastery unknown (None)
    for every broad skill. The diagnostic test (Module 2) fills it in
    with numbers between 0 and 1.
    """
    return {skill_id: None for skill_id in skills}


if __name__ == "__main__":
    # Quick summary when you run: python -m tutor.skills
    config = load_config()
    skills = load_skills(config)
    items = load_items(config)

    print(f"Level: {config['level']}   Subject: {config['subject']}   Arm: {config['arm']}")
    print(f"{len(skills)} skills, {len(items)} items\n")

    # Count of items for each skill and difficulty (like a cross-tab in R).
    print(pd.crosstab(items["skill"], items["difficulty"], margins=True), "\n")

    n_draft = (items["status"] == "draft").sum()
    print(f"Items still marked draft (need your review): {n_draft}")

    problems = check_items(items, skills)
    if problems:
        print("\nPROBLEMS FOUND:")
        for p in problems:
            print("  -", p)
    else:
        print("All items match the skill map. OK")

    print("\nEmpty profile for a new student:", empty_profile(skills))
