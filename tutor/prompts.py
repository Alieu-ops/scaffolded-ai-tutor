"""
Builds the system prompt for each study arm from the templates in
data/prompts/<level>.yaml. The wording lives in the YAML file; this code
only fills in the blanks.
"""

import yaml

from tutor.skills import PROJECT_ROOT


def load_prompts(config):
    path = PROJECT_ROOT / config["data"]["prompts_file"]
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def format_profile(profile, skills):
    """{"algebraic_processes": 0.5} -> "- Algebraic processes: 0.50" lines."""
    lines = []
    for skill_id, value in profile.items():
        shown = "not tested" if value is None else f"{value:.2f}"
        lines.append(f"- {skills[skill_id]['label']}: {shown}")
    return "\n".join(lines)


def system_prompt(arm, prompts, item, profile, skills, syllabus_notes):
    """Return the system prompt for this arm and practice item."""
    if arm == "unrestricted":
        # Neutral prompt: no skill profile, no hidden answer, no rules.
        return prompts["unrestricted"].format(question=item["question"])

    if arm == "scaffolded":
        skill = skills[item["skill"]]
        return prompts["scaffolded"].format(
            question=item["question"],
            answer=item["answer"],
            worked_solution=item["worked_solution"],
            profile=format_profile(profile, skills),
            skill_label=skill["label"],
            subskill_label=skill["subskills"][item["subskill"]],
            syllabus_notes="\n\n".join(syllabus_notes) if syllabus_notes else "(none)",
        )

    raise ValueError(f"Arm '{arm}' does not use the AI tutor")
