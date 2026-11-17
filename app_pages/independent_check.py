"""
Independent check: unfamiliar (transfer) problems with no hints, no chat and
no answer reveal, in every study arm. A locked digital near-transfer task;
the supervised paper assessment is recorded separately by researchers.
"""

import streamlit as st

from qmtutor.services.exercise_service import ExerciseError, ExerciseService
from qmtutor.ui_support import flash, get_context, require_user, show_flash

ctx = get_context()
student = require_user()
service = ExerciseService(ctx)

st.title("Independent check", anchor=False)
st.caption("These problems look different from the practice questions. There are no hints or tutor here. "
           "They show what you can do on your own.")
show_flash()

if service.active_session(student):
    st.info("Finish, save or end your current exercise first.")
    st.page_link("app_pages/exercise.py", label="Go to the exercise", icon=":material/arrow_forward:")
    st.stop()

tried = {s.item_id for s in ctx.exercises.for_student(student.user_id)}
for item in service.available_items(student, task_type="transfer"):
    with st.container(border=True):
        st.markdown(item.stem)
        if item.item_id in tried:
            st.caption("Already attempted.")
            continue
        if st.button("Start", key=f"transfer_{item.item_id}", type="primary"):
            try:
                st.session_state.pop("last_marking", None)
                service.start(student, item.item_id, task_type="transfer")
            except ExerciseError as error:
                flash("warning", str(error))
                st.rerun()
            st.switch_page("app_pages/exercise.py")
