"""Sign in with a synthetic demo account, then acknowledge the study notice."""

import streamlit as st

from qmtutor.services.auth import record_consent, sign_in
from qmtutor.ui_support import current_user, get_context

ctx = get_context()
user = current_user()

st.title("Quantitative Methods tutor", anchor=False)
st.caption("Research prototype. Demo accounts and content are synthetic. Do not enter real names or data.")

if user is None:
    # Students first, so the default choice is never a staff account (found in browser check, 3 Oct 2026).
    order = {"student": 0, "lecturer": 1, "researcher": 2, "administrator": 3}
    accounts = sorted(ctx.users.list(), key=lambda a: (order[a.role.value], a.user_id))
    labels = {a.user_id: f"{a.display_name}" for a in accounts}
    with st.form("sign_in"):
        choice = st.selectbox("Demo account", list(labels), format_func=labels.get)
        if st.form_submit_button("Sign in", type="primary"):
            sign_in(ctx, choice)
            st.session_state.clear()
            st.session_state["user_id"] = choice
            st.rerun()
    st.stop()

st.success(f"Signed in as {user.display_name}.")
if user.role.value == "student" and not ctx.users.has_consent(user.user_id):
    with st.container(border=True):
        st.subheader("Study notice (placeholder)", anchor=False)
        st.markdown(
            "- This tutor gives hints, not answers, during exercises.\n"
            "- Your activity is recorded under a code so researchers can study how the tutor is used.\n"
            "- Researchers see a pseudonymous id, not your name.\n"
            "- You can see your progress evidence and challenge anything you think is wrong.\n\n"
            "*A real notice and consent process need ethics approval before any real student uses this.*")
        if st.button("I have read this notice", type="primary"):
            record_consent(ctx, user, True)
            st.rerun()

if st.button("Sign out", icon=":material/logout:"):
    st.session_state.clear()
    st.rerun()
