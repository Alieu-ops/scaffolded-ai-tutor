"""Administrator: system health and accounts. No academic decisions are made here."""

import pandas as pd
import streamlit as st

from qmtutor import labels as L
from qmtutor.services.research_service import ResearchService
from qmtutor.ui_support import get_context, require_user, show_health

ctx = get_context()
admin = require_user()

st.title("System health", anchor=False)
show_health(ResearchService(ctx).health(admin))

st.subheader("Accounts", anchor=False)
st.caption("Demo accounts with synthetic names. A real deployment would use the university's sign-in.")
st.dataframe(pd.DataFrame([{"Account": u.user_id, "Name": u.display_name, "Role": L.label(L.ROLES, u.role.value),
                            "Active": "Yes" if u.active else "No"} for u in ctx.users.list()]), hide_index=True)
