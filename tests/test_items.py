"""Checks that the item bank and skill map are consistent. Run: pytest"""

from tutor.answers import check_answer, reveals_answer
from tutor.diagnostic import select_diagnostic_items
from tutor.skills import PROJECT_ROOT, check_items, load_config, load_items, load_skills


def test_items_match_skill_map():
    config = load_config()
    problems = check_items(load_items(config), load_skills(config))
    assert problems == [], problems


def test_every_skill_has_items():
    # The diagnostic needs at least 2 items per broad skill.
    config = load_config()
    counts = load_items(config)["skill"].value_counts()
    for skill in load_skills(config):
        assert counts.get(skill, 0) >= 2, f"Too few items for {skill}"


def test_easy_item_left_after_diagnostic():
    # A weak student should start practice on an easy (difficulty 1) item,
    # so each skill needs one left over after the diagnostic uses its items.
    config = load_config()
    items = load_items(config)
    used = select_diagnostic_items(items, config["diagnostic"]["items_per_skill"])
    left = items[~items["item_id"].isin(used["item_id"])]
    for skill in load_skills(config):
        easy = left[(left["skill"] == skill) & (left["difficulty"] == 1)]
        assert len(easy) >= 1, f"No easy practice item left for {skill}"


def test_every_answer_is_accepted_by_checker():
    # The correct answer, typed exactly, must be marked correct.
    items = load_items(load_config())
    for _, item in items.iterrows():
        assert check_answer(item["answer"], item["answer"]), item["item_id"]


def test_notes_do_not_contain_answers():
    # The notes are pasted into the tutor's instructions, so they must not
    # contain any item's answer (e.g. a worked example using the same numbers).
    # Only a skill's own notes are retrieved for its items. Small whole-number
    # answers (10 or less) are skipped: they appear in every formula (x^2, n - 1).
    config = load_config()
    items = load_items(config)
    notes_dir = PROJECT_ROOT / config["data"]["knowledge_dir"]
    for path in notes_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        for _, item in items[items["skill"] == path.stem].iterrows():
            if item["answer"].isdigit() and int(item["answer"]) <= 10:
                continue
            assert not reveals_answer(text, item["answer"], item["question"]), \
                f"{path.name} contains the answer to {item['item_id']}"


def test_leak_of_every_answer_is_detected():
    # If the tutor wrote the answer in a message, the leak check must see it.
    # (Fails when every answer number is already printed in the question.)
    items = load_items(load_config())
    for _, item in items.iterrows():
        message = f"So the answer is {item['answer']}."
        assert reveals_answer(message, item["answer"], item["question"]), item["item_id"]
