"""
Research page: study groups, supervised (no-AI) assessment results, pseudonymised
export and system health. Researchers see research ids only: never names, login
ids or chat text. Wording comes from qmtutor/labels.py.
"""

import pandas as pd
import streamlit as st

from qmtutor import labels as L
from qmtutor.services.context import PROJECT_ROOT
from qmtutor.services.research_service import ResearchService
from qmtutor.ui_support import flash, get_context, require_user, show_flash, show_health

ctx = get_context()
researcher = require_user()
service = ResearchService(ctx)

st.title("Research", anchor=False)
st.caption("You see research IDs only. Names and login IDs are kept separately and never shown here.")
show_flash()

st.subheader("Study groups", anchor=False)
assignments = service.pseudonymous_assignments(researcher)
st.dataframe(pd.DataFrame([{"Research ID": r["research_id"], "Study group": L.label(L.ARMS, r["arm"], "Not assigned yet"),
                            "How assigned": L.assignment_method(r["method"]), "When": L.when(r["assigned_at"])}
                           for r in assignments]), hide_index=True)
if any(r["arm"] is None for r in assignments):
    with st.form("assign"):
        seed = st.number_input("Random seed (recorded, so the allocation can be reproduced)", value=20261003, step=1)
        if st.form_submit_button("Randomly assign students without a group"):
            result = service.assign_unassigned(researcher, int(seed))
            flash("success", f"Assigned {len(result)} student(s) at random, in balanced blocks of three.")
            st.rerun()

st.subheader("Supervised assessment results (no AI)", anchor=False)
st.caption("These are the main learning outcomes: scores from tests taken without any AI help. "
           "Enter them using the research ID written on the answer sheet.")
with st.form("assessment", clear_on_submit=True):
    research_id = st.selectbox("Research ID", [r["research_id"] for r in assignments])
    assessment = st.segmented_control("Assessment", list(L.ASSESSMENTS), default="paper_transfer",
                                      format_func=L.ASSESSMENTS.get)
    final_score = st.number_input("Final-answer score", min_value=0.0, step=0.5)
    reasoning_score = st.number_input("Workings score", min_value=0.0, step=0.5)
    if st.form_submit_button("Save score"):
        service.record_assessment_by_research_id(researcher, research_id, assessment, final_score, reasoning_score)
        flash("success", f"Score saved for {research_id}.")
        st.rerun()

st.subheader("Pseudonymised export", anchor=False)
st.caption("Creates CSV files with research IDs, versions and events, plus a data dictionary. "
           "No names, login IDs, chat messages or written workings are included.")
with st.form("export"):
    purpose = st.text_input("Purpose of this export (recorded)")
    if st.form_submit_button("Create export", icon=":material/download:"):
        try:
            folder = service.export(researcher, PROJECT_ROOT / "exports_v2", purpose)
            flash("success", f"Export saved in the folder {folder.relative_to(PROJECT_ROOT)}.")
        except ValueError as error:
            flash("warning", str(error))
        st.rerun()

st.subheader("System health", anchor=False)
show_health(service.health(researcher))
