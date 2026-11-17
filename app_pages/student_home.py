"""Student home: what is in progress, what to do next, and the proactive-hint setting."""

import streamlit as st

from qmtutor.domain.models import StudyArm
from qmtutor.services.exercise_service import ExerciseService
from qmtutor.ui_support import get_context, require_user, show_flash

ctx = get_context()
student = require_user()
service = ExerciseService(ctx)

st.title("Home", anchor=False)
show_flash()

if not ctx.users.has_consent(student.user_id):
    st.info("Please read the study notice on the Sign in page before you start.")
    st.stop()

active = service.active_session(student)
if active:
    item = service.item_for(active)
    with st.container(border=True):
        st.markdown(f"**Exercise in progress:** {item.stem}")
        st.page_link("app_pages/exercise.py", label="Continue the exercise", icon=":material/arrow_forward:")

saved = service.saved_sessions(student)
if saved:
    st.caption(f"You have {len(saved)} saved exercise(s). Resume them on the Exercise page.")

arm = ctx.users.arm_for(student.user_id)

# Adaptive practice (scaffolded group): where to focus, and what is already going well.
def focus_text(label: str) -> str:
    """'No evidence yet' read oddly next to a mix-up seen in a saved (unfinished) exercise."""
    return "no finished exercises yet" if label.startswith("No evidence") else label.lower()


topics, recommendations = service.focus(student)
if topics:
    with st.container(border=True):
        st.subheader("Your focus", anchor=False)
        st.caption("Based on your answers so far. It changes as you practise.")
        for topic in topics:
            if topic.priority >= 2.0:
                st.markdown(f":orange[:material/flag:] **{topic.description}**: {focus_text(topic.label)}.")
                for mix_up in topic.possible_misconceptions:
                    st.caption(f"Possible mix-up seen in your answers: {mix_up.lower()}.")
            else:
                st.markdown(f":green[:material/check_circle:] **{topic.description}**: {focus_text(topic.label)}.")
        if recommendations:
            st.page_link("app_pages/exercise.py", label="See the exercises recommended for you",
                         icon=":material/arrow_forward:")
with st.container(border=True):
    st.subheader("What you can do", anchor=False)
    st.markdown("- **Study**: ask about a concept and see the course notes it comes from.\n"
                "- **Exercise**: practise a question. "
                + ("You can ask for hints, but the tutor will not give the answer."
                   if arm == StudyArm.SCAFFOLDED else
                   "You can use the AI assistant." if arm == StudyArm.UNRESTRICTED else
                   "Check your answer as often as you like.")
                + "\n- **Independent check**: try unfamiliar problems with no help, to see what you can do on your own.\n"
                  "- **My progress**: see the evidence behind your profile and challenge anything that looks wrong.")

if arm == StudyArm.SCAFFOLDED:
    with st.container(border=True):
        st.subheader("Proactive hints", anchor=False)
        st.caption("When this is on, the tutor shows the next hint automatically after a wrong answer. "
                   "It never shows the answer. It is off unless you turn it on.")
        current = ctx.users.proactive_hints_on(student.user_id)
        choice = st.toggle("Show hints automatically after a wrong answer", value=current)
        if choice != current:
            service.set_proactive_hints(student, choice)
            st.rerun()
