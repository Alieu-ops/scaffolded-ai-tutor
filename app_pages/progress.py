"""
My progress: per-outcome evidence the student can inspect and challenge.
No single ability score is shown; support used and uncertainty are always visible.
Wording comes from qmtutor/labels.py.
"""

import pandas as pd
import streamlit as st

from qmtutor import labels as L
from qmtutor.services.profile_service import ProfileService
from qmtutor.ui_support import flash, get_context, require_user, show_flash

ctx = get_context()
student = require_user()
profiles = ProfileService(ctx)
outcomes = {o.outcome_id: o.description for o in ctx.content.outcomes()}


def short_question(item_key: str) -> str:
    item_id, _, version = item_key.partition("@")
    item = ctx.content.get_item(item_id, version)
    if item is None:
        return item_id
    return item.stem if len(item.stem) <= 70 else item.stem[:67].rsplit(" ", 1)[0] + "..."


def result_text(record) -> str:
    if record.final_answer_correct:
        return "Correct"
    note = record.note or ""
    if note.startswith("terminated"):
        return "Ended without the answer"
    if note.startswith("referred"):
        return "Asked for human help"
    return "Not correct"


def note_text(record) -> str:
    """Notes for the student: workings flag and lecturer decisions, in plain words."""
    parts = []
    for piece in (record.note or "").split(" | "):
        if piece.startswith("final answer correct, but"):
            parts.append("Answer correct, but there were errors in your workings")
        elif piece.startswith("removed by lecturer:"):
            parts.append("Removed by your lecturer: " + piece.split(":", 1)[1].strip())
        elif piece.startswith("lecturer note:"):
            parts.append("Lecturer's note: " + piece.split(":", 1)[1].strip())
    return "; ".join(parts)


HOW_SURE = {"high": "Not very sure yet: very little evidence so far.",
            "moderate": "Fairly sure, based on a few practice tasks (not a test)."}

st.title("My progress", anchor=False)
st.caption("This shows what you have done so far, to guide your practice. It is not a grade.")
show_flash()

profile = profiles.profile(student, student.user_id)
if not profile:
    st.info("Nothing here yet. Finish an exercise to see your progress.")

challengeable = {}
for summary, records in profile:
    with st.container(border=True):
        st.subheader(outcomes.get(summary.outcome_id, summary.outcome_id), anchor=False)
        st.markdown(f"**{summary.label}.** {summary.explanation}")
        st.caption(HOW_SURE.get(summary.uncertainty.split(":")[0], summary.uncertainty))
        st.dataframe(pd.DataFrame([{
            "Date": L.when(r.created_at),
            "Question": short_question(r.item_key) + (" (unfamiliar problem)" if r.task_type == "transfer" else ""),
            "Result": result_text(r),
            "Help used": L.label(L.SUPPORT, r.support.value),
            "Answers tried": r.attempts,
            "Counts towards progress": "No (removed after review)" if r.excluded else "Yes",
            "Notes": note_text(r),
        } for r in records]), hide_index=True)
        for r in records:
            challengeable[r.evidence_id] = f"{L.when(r.created_at)} · {short_question(r.item_key)} · {result_text(r)}"

if challengeable:
    with st.expander("Think something here is wrong? Tell your lecturer", icon=":material/flag:"):
        with st.form("challenge", clear_on_submit=True):
            evidence_id = st.selectbox("Which record?", list(challengeable), format_func=challengeable.get)
            statement = st.text_area("What is wrong or missing?")
            if st.form_submit_button("Send to my lecturer"):
                try:
                    profiles.submit_challenge(student, evidence_id, statement)
                    flash("success", "Sent. Your lecturer will review it and reply here.")
                except ValueError as error:
                    flash("warning", str(error))
                st.rerun()

challenges = profiles.my_challenges(student)
if challenges:
    st.subheader("What I asked my lecturer to check", anchor=False)
    st.dataframe(pd.DataFrame([{"Sent": L.when(c.created_at), "What I said": c.statement,
                                "Status": L.label(L.CHALLENGE_STATUS, c.status.value),
                                "Lecturer's reply": c.decision_reason or ""} for c in challenges]), hide_index=True)
