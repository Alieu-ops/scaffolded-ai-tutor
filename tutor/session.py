"""
Module 5: tutor logic.

A TutorSession holds everything about ONE student's session:
the diagnostic, their skill profile, the current practice item, the
conversation with the AI, and timers for response times. It also logs
every event. Both the web interface (app.py) and the terminal version
(tutor/cli.py) use this class, so they behave identically.

What differs between the three study arms:
    scaffolded   - practises the WEAKEST skill; AI gives hints only;
                   code double-checks that the AI never reveals the answer
    unrestricted - items in random order; AI with a neutral prompt
    control      - items in random order; no AI, answer checking only
"""

import random
import time
import uuid

from tutor.answers import check_answer, copies_solution, reveals_answer
from tutor.diagnostic import mastery_profile, new_counts, record, select_diagnostic_items
from tutor.logger import Logger
from tutor.prompts import load_prompts, system_prompt
from tutor.skills import load_items, load_skills

ARMS = ("scaffolded", "unrestricted", "control")


class TutorSession:
    def __init__(self, config, participant_code, llm=None, retriever=None):
        self.config = config
        self.arm = config["arm"]
        if self.arm not in ARMS:
            raise ValueError(f"arm must be one of {ARMS}, not '{self.arm}'")
        if self.arm != "control" and llm is None:
            raise ValueError("The AI arms need an llm (see tutor/llm.py)")

        self.participant_code = participant_code
        self.session_id = uuid.uuid4().hex[:12]
        self.skills = load_skills(config)
        self.items = load_items(config)
        self.prompts = load_prompts(config)
        self.llm = llm if self.arm != "control" else None
        self.retriever = retriever if self.arm == "scaffolded" else None
        self.logger = Logger(config["logging"]["db_file"])
        self.model_name = self._model_name()

        # Correct / attempted counts per skill -> mastery profile.
        self.counts = new_counts(self.skills)
        self.diagnostic_items = select_diagnostic_items(
            self.items, config["diagnostic"]["items_per_skill"])

        # Practice state.
        self.done_item_ids = set(self.diagnostic_items["item_id"])
        self.items_practised = 0
        self.item = None            # current practice item (a pandas row)
        self.history = []           # chat messages for the current item
        self.attempts = 0           # answer attempts on the current item
        self.last_shown = time.time()  # when the student last saw something new
        # Random order for the non-adaptive arms; seeded so it can be replayed.
        self.rng = random.Random(self.session_id)

    # -
    # Helpers
    # -
    def _model_name(self):
        if self.arm == "control":
            return None
        s = self.config["llm"]
        return s["anthropic_model"] if s["provider"] == "anthropic" else f"ollama:{s['ollama_model']}"

    def _seconds_since_last_shown(self):
        """Response time: seconds since the student last saw new content."""
        now = time.time()
        elapsed = now - self.last_shown
        self.last_shown = now
        return elapsed

    def _log(self, event_type, phase="practice", item=None, **fields):
        item = self.item if item is None else item
        self.logger.log(
            participant_code=self.participant_code, arm=self.arm,
            session_id=self.session_id, phase=phase, event_type=event_type,
            skill=None if item is None else item["skill"],
            item_id=None if item is None else item["item_id"],
            model=self.model_name, **fields)

    @property
    def profile(self):
        """Mastery per skill, 0 to 1 (proportion correct so far)."""
        return mastery_profile(self.counts)

    # -
    # Diagnostic
    # -
    def submit_diagnostic_answer(self, item, answer_text):
        """Score one diagnostic answer, update the profile, log it."""
        correct = check_answer(answer_text, item["answer"])
        record(self.counts, item["skill"], correct)
        self._log("answer_attempt", phase="diagnostic", item=item,
                  student_text=answer_text, correct=correct,
                  response_time_seconds=self._seconds_since_last_shown())
        return correct

    # -
    # Choosing the next practice item
    # -
    def weakest_skill(self, available):
        """Lowest mastery among skills that still have unused items."""
        profile = self.profile
        skill_order = list(self.skills)
        candidates = [s for s in skill_order if s in available]
        # Untested skills (None) count as 0; ties go to the earlier skill.
        return min(candidates, key=lambda s: (profile[s] or 0, skill_order.index(s)))

    @staticmethod
    def target_difficulty(mastery):
        """Weak students start with easy items: 0-0.4 -> 1, 0.4-0.7 -> 2, above -> 3."""
        mastery = mastery or 0
        return 1 if mastery < 0.4 else 2 if mastery < 0.7 else 3

    def next_item(self):
        """
        Pick and start the next practice item. Returns None when the
        session is over (enough items done, or none left).
        """
        if self.items_practised >= self.config["practice"]["items_per_session"]:
            return None
        remaining = self.items[~self.items["item_id"].isin(self.done_item_ids)]
        if remaining.empty:
            return None

        if self.arm == "scaffolded":
            # Adaptive: weakest skill, difficulty closest to the target.
            skill = self.weakest_skill(set(remaining["skill"]))
            pool = remaining[remaining["skill"] == skill]
            target = self.target_difficulty(self.profile[skill])
            gap = (pool["difficulty"] - target).abs()
            item = pool.loc[gap.sort_values(kind="stable").index[0]]
        else:
            # Not adaptive: random item.
            item = remaining.iloc[self.rng.randrange(len(remaining))]

        self.item = item
        self.history = []
        self.attempts = 0
        self.done_item_ids.add(item["item_id"])
        self.last_shown = time.time()
        self._log("item_start")
        return item

    # -
    # Talking to the AI tutor
    # -
    def _syllabus_notes(self, query):
        if self.retriever is None:
            return []
        k = self.config["retrieval"]["passages_per_reply"]
        return self.retriever.search(query, skill=self.item["skill"], k=k)

    def _ai_reply(self, student_text):
        """
        Ask the model for a reply. In the scaffolded arm, check the reply
        for the final answer or copied worked-solution steps (see _leaks);
        if it leaks, ask again, then fall back to a safe generic hint.
        Returns (reply, note).
        """
        notes = self._syllabus_notes(f"{self.item['question']} {student_text}")
        system = system_prompt(self.arm, self.prompts, self.item, self.profile,
                               self.skills, notes)
        messages = self.history + [{"role": "user", "content": student_text}]
        reply = self.llm.chat(system, messages)

        if self.arm != "scaffolded":
            return reply, None

        note = None
        for _ in range(self.config["practice"]["max_leak_retries"]):
            if not self._leaks(reply, messages):
                return reply, note
            note = "leak_blocked_retry"   # a draft leaked; ask again
            reply = self.llm.chat(system + "\n" + self.prompts["leak_retry_note"], messages)
        if not self._leaks(reply, messages):
            return reply, note
        return self.prompts["safe_fallback"].strip(), "leak_blocked_fallback"

    def _leaks(self, reply, messages):
        """
        True if a reply gives the answer away: either it states the final
        answer, or it copies part of the hidden worked solution (middle steps).
        Numbers the student has typed themselves do not count as copied.
        """
        student_texts = " ".join(m["content"] for m in messages if m["role"] == "user")
        known = f"{self.item['question']} {student_texts}"
        return (reveals_answer(reply, self.item["answer"], self.item["question"])
                or copies_solution(reply, self.item["worked_solution"], known))

    def ask_tutor(self, student_text, event_type="message"):
        """Send the student's message to the AI and return its reply."""
        if self.llm is None:
            raise RuntimeError("The control arm has no AI tutor")
        response_time = self._seconds_since_last_shown()
        reply, note = self._ai_reply(student_text)
        self.history += [{"role": "user", "content": student_text},
                         {"role": "assistant", "content": reply}]
        self._log(event_type, student_text=student_text, ai_text=reply,
                  response_time_seconds=response_time, note=note)
        self.last_shown = time.time()  # the student now sees the reply
        return reply

    def request_hint(self):
        """The "Give me a hint" button (scaffolded arm only)."""
        if self.arm != "scaffolded":
            raise RuntimeError("Hints are only available in the scaffolded arm")
        return self.ask_tutor(self.prompts["hint_request"], event_type="hint_shown")

    # -
    # Answering and moving on
    # -
    def submit_answer(self, answer_text):
        """
        Check a practice answer. Only the FIRST attempt on each item
        updates the skill profile, so repeated guessing does not distort it.
        Returns True if correct.
        """
        correct = check_answer(answer_text, self.item["answer"])
        self.attempts += 1
        if self.attempts == 1:
            record(self.counts, self.item["skill"], correct)
        self._log("answer_attempt", student_text=answer_text, correct=correct,
                  response_time_seconds=self._seconds_since_last_shown())
        if correct:
            self._finish_item(correct=True)
        return correct

    def skip_item(self):
        """Give up on the current item. Counts as incorrect if never attempted."""
        if self.attempts == 0:
            record(self.counts, self.item["skill"], False)
        self._finish_item(correct=False, note="skipped")

    def _finish_item(self, correct, note=None):
        self._log("item_end", correct=correct, note=note)
        self.items_practised += 1
        self.item = None
