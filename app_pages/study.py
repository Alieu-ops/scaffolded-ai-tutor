"""Study mode: explanations grounded in approved notes, with sources. Locked during an active exercise."""

import streamlit as st

from qmtutor.mathcheck.reasoning_format import format_reasoning
from qmtutor.services.study_service import StudyLocked, StudyService
from qmtutor.ui_support import get_context, require_user

ctx = get_context()
student = require_user()
study = StudyService(ctx)

st.title("Study", anchor=False)
st.caption("Ask about a concept. Explanations come from the approved course notes, which are shown as sources.")

if study.is_locked(student):
    st.warning("Study mode is closed while an exercise is in progress. Save or end the exercise first.",
               icon=":material/lock:")
    st.page_link("app_pages/exercise.py", label="Go to the exercise", icon=":material/arrow_forward:")
    st.stop()

for message in study.history(student):
    with st.chat_message("user" if message["sender"] == "student" else "assistant"):
        # Maths in both student and tutor messages is typeset; the tutor keeps its bold headings.
        st.markdown(format_reasoning(message["content"], keep_markdown=message["sender"] != "student"))

if "study_sources" in st.session_state:
    with st.expander("Sources for the last answer", icon=":material/source:"):
        for passage in st.session_state["study_sources"]:
            st.markdown(f"**{passage.heading}**\n\n{format_reasoning(passage.body, keep_markdown=True)}")
            st.caption(f"From the approved course notes (version {passage.version}).")

if query := st.chat_input("e.g. What is the difference between simple and compound interest?"):
    try:
        with st.spinner("Looking in the course notes..."):
            answer = study.ask(student, query)
        st.session_state["study_sources"] = answer.sources
    except StudyLocked as error:
        st.session_state.pop("study_sources", None)
        st.warning(str(error))
        st.stop()
    st.rerun()
