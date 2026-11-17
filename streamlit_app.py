"""
Entry point of the version 2 web interface (Streamlit multipage navigation).

    streamlit run streamlit_app.py --server.port 8503

Which pages appear depends on the signed-in account's role, read from the
database. Hiding pages is only a convenience: each service re-checks the role,
so a page reached by other means still cannot perform a forbidden action.
"""

import streamlit as st

from qmtutor.domain.models import Role
from qmtutor.ui_support import current_user, get_context

ctx = get_context()
st.set_page_config(page_title=ctx.settings["app_title"], page_icon=":material/calculate:", layout="wide")

user = current_user()
# The same page signs people in and, once signed in, shows their account and "Sign out".
sign_in = st.Page("app_pages/sign_in.py", title="Sign in" if user is None else "My account",
                  icon=":material/login:" if user is None else ":material/account_circle:")

if user is None:
    pages = [sign_in]
elif user.role == Role.STUDENT:
    pages = {"Learn": [st.Page("app_pages/student_home.py", title="Home", icon=":material/home:", default=True),
                       st.Page("app_pages/study.py", title="Study", icon=":material/menu_book:"),
                       st.Page("app_pages/exercise.py", title="Exercise", icon=":material/edit_note:"),
                       st.Page("app_pages/independent_check.py", title="Independent check", icon=":material/quiz:")],
             "Me": [st.Page("app_pages/progress.py", title="My progress", icon=":material/insights:"), sign_in]}
elif user.role == Role.LECTURER:
    pages = {"Teach": [st.Page("app_pages/lecturer_dashboard.py", title="Dashboard", icon=":material/dashboard:",
                               default=True),
                       st.Page("app_pages/lecturer_content.py", title="Content review", icon=":material/fact_check:"),
                       st.Page("app_pages/lecturer_policy.py", title="Hint rules", icon=":material/tune:")],
             "Account": [sign_in]}
elif user.role == Role.RESEARCHER:
    pages = {"Research": [st.Page("app_pages/research.py", title="Research", icon=":material/science:", default=True),
                          st.Page("app_pages/lecturer_policy.py", title="Hint rules", icon=":material/tune:")],
             "Account": [sign_in]}
else:
    pages = {"Admin": [st.Page("app_pages/admin.py", title="System health", icon=":material/monitor_heart:",
                               default=True)], "Account": [sign_in]}

if user:
    st.sidebar.caption(f"Signed in as **{user.display_name}**")
    st.sidebar.caption("Prototype with synthetic data only. Not for real students.")

st.navigation(pages).run()
