"""
Terminal version of a full session: diagnostic, then practice with the
tutor. Useful for quick testing without the web interface.

    python -m tutor.cli

During practice, type:
    a <your answer>   submit an answer, e.g.  a x = 5
    hint              ask for a hint (scaffolded arm)
    skip              move to the next question
    quit              end the session
    anything else     is sent to the AI as a chat message (AI arms)
"""

import sys

from tutor.llm import LLMError, make_llm
from tutor.logger import valid_participant_code
from tutor.session import TutorSession
from tutor.skills import load_config


def make_retriever(config):
    """Load the syllabus search (RAG) if enabled and built; else None."""
    if config["arm"] != "scaffolded" or not config["retrieval"]["enabled"]:
        return None
    try:
        from tutor.retrieval import Retriever
        return Retriever(config)
    except Exception as e:  # missing libraries or index not built yet
        print(f"(Syllabus notes not available: {e})")
        return None


def main():
    # Let the Windows terminal print maths symbols (e.g. pi) from the AI.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = load_config()
    code = input("Participant code (e.g. P001): ").strip().upper()
    while not valid_participant_code(code, config["participant_code_pattern"]):
        code = input("Invalid code. Use the format P001: ").strip().upper()

    llm = make_llm(config) if config["arm"] != "control" else None
    session = TutorSession(config, code, llm=llm, retriever=make_retriever(config))
    print(f"\nArm: {session.arm}   Session: {session.session_id}")

    # Diagnostic
    print(f"\nPART 1: Diagnostic test ({len(session.diagnostic_items)} questions)\n")
    for n, (_, item) in enumerate(session.diagnostic_items.iterrows(), start=1):
        print(f"Q{n}. {item['question']}")
        session.submit_diagnostic_answer(item, input("   Your answer: "))

    print("\nYour skill profile:")
    for skill, value in session.profile.items():
        print(f"  {session.skills[skill]['label']:<30} {value:.2f}")

    # Practice
    print("\nPART 2: Practice. Commands: 'a <answer>', 'hint', 'skip', 'quit'.")
    while (item := session.next_item()) is not None:
        print(f"\n[{session.skills[item['skill']]['label']}] {item['question']}")
        while session.item is not None:
            text = input("> ").strip()
            if not text:
                continue
            if text.lower() == "quit":
                return print("Session ended.")
            if text.lower() == "skip":
                session.skip_item()
            elif text.lower().startswith("a "):
                if session.submit_answer(text[2:]):
                    print("Correct! Well done.")
                else:
                    print("Not quite. Try again" + (", or ask the tutor." if llm else "."))
            elif llm is None:
                print("Type 'a <answer>' to check an answer, or 'skip'.")
            else:
                try:
                    reply = (session.request_hint() if text.lower() == "hint"
                             and session.arm == "scaffolded" else session.ask_tutor(text))
                    print(f"Tutor: {reply}")
                except LLMError as e:
                    print(f"(Problem: {e})")

    print("\nSession complete. Final skill profile:")
    for skill, value in session.profile.items():
        print(f"  {session.skills[skill]['label']:<30} {value:.2f}")


if __name__ == "__main__":
    main()
