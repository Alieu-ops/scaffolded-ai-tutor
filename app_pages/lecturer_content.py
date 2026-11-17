"""
Content review: preview each exercise exactly as students see it (plus the answer
key and hints, which only lecturers see), then review, approve, return or retire.
Also approve the study notes used in study mode. Wording comes from qmtutor/labels.py.
"""

import pandas as pd
import streamlit as st

from qmtutor import labels as L
from qmtutor.services.lecturer_service import LecturerService, ReviewError
from qmtutor.ui_support import flash, get_context, require_user, show_flash

ctx = get_context()
lecturer = require_user()
service = LecturerService(ctx)
people = {u.user_id: u.display_name for u in ctx.users.list()}

st.title("Content review", anchor=False)
st.caption("Only approved content reaches students. Every decision needs a reason and is recorded.")
show_flash()

items_tab, notes_tab = st.tabs(["Exercises", "Study notes"])

with items_tab:
    items = service.items(lecturer)
    by_id = {i.item_id: i for i in items}
    status_filter = st.pills("Show", list(L.CONTENT_STATUS), selection_mode="multi",
                             default=["draft", "reviewed", "approved"],
                             format_func=lambda s: L.CONTENT_STATUS[s].split(" (")[0])
    for item in items:
        if item.status.value not in status_filter:
            continue
        kind = "Worked example (used as a hint)" if item.is_analogue else (
            f"Independent check: {item.subskill}" if item.transfer_flag else item.subskill)
        with st.expander(f"{L.item_label(item.key)} · {L.label(L.CONTENT_STATUS, item.status.value)} · {kind}"):
            st.markdown("**What the student sees**")
            st.info(item.stem)
            spec = item.answer_specification
            if spec:
                tolerance = ("exact" if not (spec.absolute_tolerance or spec.relative_tolerance)
                             else f"within {spec.absolute_tolerance:g}" if spec.absolute_tolerance
                             else f"within {spec.relative_tolerance:%}")
                st.markdown("**Answer key** (checked by the computer; never sent to the AI)")
                st.markdown(f"- Correct answer: **{spec.canonical_expression}**"
                            + (f" {spec.units}" if spec.units else "")
                            + f"\n- Also accepted: {', '.join(spec.acceptable_forms) or 'none listed'}"
                            + f"\n- Tolerance: {tolerance}\n- Rounding: {spec.rounding_rule}")
            if item.scaffold_sequence:
                seq = item.scaffold_sequence
                analogue = by_id.get(seq.analogous_example_id)
                st.markdown("**Hints, from lightest to strongest**")
                st.markdown(f"1. *{L.HINT_LEVELS[1]}:* {seq.self_explanation}\n"
                            f"2. *{L.HINT_LEVELS[2]}:* {seq.conceptual_cue}\n"
                            f"3. *{L.HINT_LEVELS[3]}:* {seq.strategic_hint}\n"
                            f"4. *{L.HINT_LEVELS[4]}:* {seq.step_hint}\n"
                            f"5. *{L.HINT_LEVELS[5]}:* repeats only steps the student wrote correctly"
                            + (f" ({'; '.join(c.label for c in item.checkpoints)})" if item.checkpoints else "")
                            + f"\n6. *{L.HINT_LEVELS[6]}:* "
                            + (f"\"{analogue.stem}\"" if analogue else "none linked"))
            if item.worked_solution:
                title = "Worked steps shown to the student" if item.is_analogue else \
                    "Model solution (lecturers only; used to stop the AI revealing steps)"
                st.markdown(f"**{title}**\n" + "\n".join(f"- {s}" for s in item.worked_solution))
            history = service.review_history(lecturer, item.item_id)
            if history:
                st.markdown("**Review history**")
                st.dataframe(pd.DataFrame([{"Version": h["item_version"],
                                            "Reviewer": people.get(h["reviewer_id"], h["reviewer_id"]),
                                            "Decision": L.label(L.ITEM_DECISIONS_PAST, h["decision"]),
                                            "Reason": h["reason"], "When": L.when(h["created_at"])}
                                           for h in history]), hide_index=True)
            with st.form(f"review_{item.key}"):
                decision = st.segmented_control("Decision", list(L.ITEM_DECISIONS), format_func=L.ITEM_DECISIONS.get,
                                                key=f"d_{item.key}")
                reason = st.text_input("Reason", key=f"r_{item.key}")
                if st.form_submit_button("Record decision"):
                    if not decision:
                        flash("warning", "Choose a decision first.")
                    else:
                        try:
                            service.decide_item(lecturer, item.item_id, item.item_version, decision, reason)
                            flash("success", f"{L.item_label(item.key)}: {L.ITEM_DECISIONS_PAST[decision].lower()}.")
                        except ReviewError as error:
                            flash("warning", str(error))
                    st.rerun()

with notes_tab:
    st.caption("Study mode explains concepts using only approved notes.")
    for note in service.notes(lecturer):
        status = "Approved" if note["status"] == "approved" else "Not approved"
        with st.expander(f"{note['heading']} · {status}"):
            st.caption(f"From the notes file for this topic, version {note['version']}.")
            st.markdown(note["body"])
            with st.form(f"note_{note['note_id']}"):
                approve = st.toggle("Approved for study mode", value=note["status"] == "approved")
                reason = st.text_input("Reason")
                if st.form_submit_button("Save"):
                    try:
                        service.decide_note(lecturer, note["note_id"], approve, reason)
                        flash("success", f"\"{note['heading']}\" is now {'approved' if approve else 'not approved'}.")
                    except ReviewError as error:
                        flash("warning", str(error))
                    st.rerun()
