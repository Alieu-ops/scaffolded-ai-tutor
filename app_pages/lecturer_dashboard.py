"""
Lecturer dashboard: class patterns (aggregated), help requests, profile
challenges to resolve, and one student's evidence when educationally needed.
AI scores are labelled as provisional everywhere. All wording comes from qmtutor/labels.py.
"""

import pandas as pd
import streamlit as st

from qmtutor import labels as L
from qmtutor.domain.models import ChallengeStatus
from qmtutor.services.lecturer_service import LecturerService, ReviewError
from qmtutor.ui_support import flash, get_context, require_user, show_flash

ctx = get_context()
lecturer = require_user()
service = LecturerService(ctx)
names = {s.user_id: s.display_name for s in service.students(lecturer)}

st.title("Dashboard", anchor=False)
show_flash()

st.subheader("Class patterns by exercise", anchor=False)
st.caption("Totals for the whole class, without names. The workings score is the AI's provisional "
           "judgement (0-2) and needs your review before use.")
patterns = service.class_patterns(lecturer)
if patterns:
    st.dataframe(pd.DataFrame([{
        "Exercise": L.item_label(p["item"]), "Students": p["students"], "Completed": p["completed"],
        "Still open": p["in_progress_or_saved"], "Ended without answer": p["terminated"],
        "Asked for help": p["referred"], "Hints shown": p["hints_shown"],
        "Needed strong support": p["reached_high_support"],
        "AI replies blocked (would reveal answer)": p["leaks_blocked"],
        "Average AI workings score (provisional)": p["mean_provisional_reasoning_0_2"],
    } for p in patterns]), hide_index=True)
else:
    st.info("No student activity yet.")

st.subheader("Possible misconceptions in the class", anchor=False)
st.caption("Noticed when a wrong answer matches a typical wrong answer you listed for an exercise. "
           "These are possible, not confirmed: one slip is not a misconception.")
mix_ups = ctx.evidence.class_misconceptions()
if mix_ups:
    st.dataframe(pd.DataFrame([{"Possible misconception": m["label"] or m["misconception_id"],
                                "Times seen": m["times"], "Students": m["students"]} for m in mix_ups]),
                 hide_index=True)
else:
    st.caption("None noticed yet.")

st.subheader("Requests for human help", anchor=False)
referrals = service.referrals(lecturer)
if referrals:
    st.dataframe(pd.DataFrame([{"Student": names.get(r["student_id"], r["student_id"]), "Exercise": r["item_id"],
                                "Where they stopped": L.exit_stage(r["stage_json"]),
                                "Their message": r["reason"] or "", "When": L.when(r["created_at"])}
                               for r in referrals]), hide_index=True)
else:
    st.caption("No requests.")

st.subheader("Profile challenges", anchor=False)
open_challenges = service.open_challenges(lecturer)
if not open_challenges:
    st.caption("No challenges waiting.")
for challenge in open_challenges:
    evidence = ctx.evidence.get(challenge.evidence_id)
    with st.container(border=True):
        st.markdown(f"**{names.get(challenge.student_id, challenge.student_id)}** questions their record for "
                    f"**{L.item_label(evidence.item_key)}**: answer "
                    f"{'correct' if evidence.final_answer_correct else 'not correct'}, "
                    f"{L.label(L.SUPPORT, evidence.support.value).lower()}, {evidence.attempts} answer(s).")
        st.markdown(f"> {challenge.statement}")
        with st.form(f"resolve_{challenge.challenge_id}"):
            decision = st.segmented_control("Decision", list(L.CHALLENGE_DECISIONS), default="upheld",
                                            format_func=L.CHALLENGE_DECISIONS.get,
                                            key=f"decision_{challenge.challenge_id}")
            reason = st.text_input("Reason (the student will see this)")
            if st.form_submit_button("Record decision"):
                try:
                    service.resolve_challenge(lecturer, challenge.challenge_id, ChallengeStatus(decision), reason)
                    flash("success", "Decision recorded. The student can see it on their progress page.")
                except ReviewError as error:
                    flash("warning", str(error))
                st.rerun()

st.subheader("Review one student's work", anchor=False)
chosen = st.selectbox("Student", [None, *names], format_func=lambda s: "Choose a student" if s is None else names[s])
if chosen:
    rows = service.student_evidence_review(lecturer, chosen)
    if rows:
        st.caption("The answer and workings checks are done by the computer and are exact. AI scores and "
                   "comments are provisional. Rows marked in 'Needs your judgement' deserve a closer look.")
        st.dataframe(pd.DataFrame([{
            "Exercise": r["item"], "Answer no.": r["attempt"], "Final answer": r["final_answer"],
            "Answer check": L.label(L.ANSWER_CHECK, r["answer_check"]),
            "Workings check": r["workings_check"],
            "Needs your judgement": "Correct answer but workings have errors" if r["flag"] else "",
            "Hint level reached": f"{r['support_level']} - {L.HINT_LEVELS.get(r['support_level'], '')}",
            "AI rubric scores (provisional)": L.rubric_scores(r["provisional_llm_scores"]),
            "AI comment (provisional)": r["provisional_llm_comment"] or "",
            "Workings as written": r["workings"],
        } for r in rows]), hide_index=True)
    else:
        st.caption("No answers handed in yet.")
