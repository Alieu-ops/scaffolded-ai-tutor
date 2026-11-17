"""
Module 6: web interface (Streamlit).

Start it from the project folder with:
    streamlit run app.py
A page opens in the browser at http://localhost:8501
(start_app.bat and run_app.py use port 8502, so this version can run
alongside the senior secondary app).

How Streamlit works: every click re-runs this whole script from the top.
Anything that must survive between clicks is kept in st.session_state
(here: which screen we are on, and the TutorSession object).

Screens: login -> diagnostic -> practice -> end
"""

import streamlit as st

from keyboard import maths_keyboard
from tutor.llm import LLMError, make_llm
from tutor.logger import valid_participant_code
from tutor.mathtext import pretty
from tutor.session import TutorSession
from tutor.skills import load_config

config = load_config()
st.set_page_config(page_title=config["app_title"], page_icon="📐", layout="centered")
state = st.session_state
CHAT_PLACEHOLDER = "Type a message to the tutor"


# Slow things (loading models) are done once and shared, not on every click.
@st.cache_resource(show_spinner="Getting ready...")
def get_llm():
    return make_llm(config) if config["arm"] != "control" else None


@st.cache_resource(show_spinner="Getting ready...")
def get_retriever():
    if config["arm"] != "scaffolded" or not config["retrieval"]["enabled"]:
        return None
    try:
        from tutor.retrieval import Retriever
        return Retriever(config)
    except Exception as e:
        print(f"Syllabus notes not available: {e}")  # shown in the terminal only
        return None


def keyboard_toggle(answer_label, chat=False):
    """Switch to show the on-screen maths keyboard (remembered between screens)."""
    # The on/off choice is kept in state.keyboard_on, because Streamlit forgets
    # a switch's value on screens where the switch is not shown.
    state.keyboard_on = st.toggle("🧮 Maths keyboard (powers, logs, √, π)",
                                  value=state.get("keyboard_on", False),
                                  key=f"keyboard_{answer_label}")
    if state.keyboard_on:
        maths_keyboard(answer_label, CHAT_PLACEHOLDER if chat else None)


def show_profile(session):
    """Skill profile as progress bars."""
    for skill, value in session.profile.items():
        value = value or 0
        st.progress(value, text=f"{session.skills[skill]['label']}: {value:.0%}")


# -
# Screen 1: login with an anonymous participant code
# -
def login_screen():
    st.title(config["app_title"])
    st.write("Enter the participant code you were given. Do not enter your name.")
    with st.form("login"):
        code = st.text_input("Participant code", placeholder="e.g. P001").strip().upper()
        if st.form_submit_button("Start", type="primary"):
            if not valid_participant_code(code, config["participant_code_pattern"]):
                st.error("That code is not valid. It should look like P001.")
            else:
                state.session = TutorSession(config, code, llm=get_llm(),
                                             retriever=get_retriever())
                state.screen = "diagnostic"
                state.q_index = 0
                st.rerun()


# -
# Screen 2: diagnostic test, one question at a time
# -
def diagnostic_screen():
    session = state.session
    items = session.diagnostic_items
    n = state.q_index

    if n >= len(items):
        st.title("Your skill profile")
        # Same wording in every arm, so the arms differ only in the tutor.
        st.write("Here is how you did in each topic.")
        show_profile(session)
        if st.button("Start practice", type="primary"):
            state.screen = "practice"
            session.next_item()
            st.rerun()
        return

    item = items.iloc[n]
    st.title("Part 1: Short test")
    st.caption(f"Question {n + 1} of {len(items)}. Try your best; no help in this part.")
    st.markdown(f"**{pretty(item['question'])}**")
    with st.form(f"diag_{n}", clear_on_submit=True):
        answer = st.text_input("Your answer")
        if st.form_submit_button("Next", type="primary"):
            session.submit_diagnostic_answer(item, answer)
            state.q_index += 1
            st.rerun()
    keyboard_toggle("Your answer")


# -
# Screen 3: practice (with or without the AI tutor, depending on the arm)
# -
def practice_screen():
    session = state.session
    if session.item is None:           # no items left
        state.screen = "end"
        st.rerun()

    item = session.item
    has_ai = session.arm != "control"

    st.title("Part 2: Practice")
    st.caption(f"Question {session.items_practised + 1} of "
               f"{config['practice']['items_per_session']}  ·  "
               f"{session.skills[item['skill']]['label']}")

    if state.get("feedback"):          # message from the previous click
        kind, text = state.pop("feedback")
        getattr(st, kind)(text)

    st.subheader(pretty(item["question"]), anchor=False)

    # Answer box (all arms)
    with st.form("answer", clear_on_submit=True):
        answer = st.text_input("Your final answer")
        col1, col2 = st.columns(2)
        check = col1.form_submit_button("Check answer", type="primary", width="stretch")
        skip = col2.form_submit_button("Skip question", width="stretch")
    if check and answer.strip():
        if session.submit_answer(answer):
            state.feedback = ("success", "Correct! Well done. Here is the next question.")
            session.next_item()
        else:
            tip = " Ask the tutor below if you need help." if has_ai else ""
            state.feedback = ("warning", "Not quite. Try again." + tip)
        st.rerun()
    if skip:
        session.skip_item()
        state.feedback = ("info", "Question skipped.")
        session.next_item()
        st.rerun()

    keyboard_toggle("Your final answer", chat=has_ai)

    if not has_ai:
        return

    # AI chat (scaffolded and unrestricted arms)
    st.divider()
    st.subheader("Tutor" if session.arm == "scaffolded" else "AI assistant")
    for msg in session.history:
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.write(pretty(msg["content"]))

    if session.arm == "scaffolded" and st.button("💡 Give me a hint"):
        call_ai(session.request_hint)
    if text := st.chat_input(CHAT_PLACEHOLDER):
        call_ai(lambda: session.ask_tutor(text))


def call_ai(action):
    """Run an AI call with a spinner; show a clear message if it fails."""
    try:
        with st.spinner("Thinking..."):
            action()
    except LLMError as e:
        st.error(str(e))
        return
    st.rerun()


# -
# Screen 4: end of session
# -
def end_screen():
    st.title("Session complete")
    st.write("Thank you! Your answers have been saved. You can close this page.")
    show_profile(state.session)
    if st.button("Start a new participant"):
        state.clear()
        st.rerun()


SCREENS = {"login": login_screen, "diagnostic": diagnostic_screen,
           "practice": practice_screen, "end": end_screen}
SCREENS[state.get("screen", "login")]()
