"""
Hint rules (the scaffold policy). Researchers and lecturers may PROPOSE a new
version; only a lecturer can approve it, after the technical team confirms the
automated safety tests pass. A proposal marked as an AI suggestion is reviewed
like any other and can never activate itself. Wording comes from qmtutor/labels.py.
"""

import json

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from qmtutor import labels as L
from qmtutor.domain.models import PolicyConfig, Role
from qmtutor.services.lecturer_service import LecturerService, ReviewError
from qmtutor.ui_support import flash, get_context, require_user, show_flash

ctx = get_context()
user = require_user()
service = LecturerService(ctx)
people = {u.user_id: u.display_name for u in ctx.users.list()}


def settings_table(config: dict) -> pd.DataFrame:
    """The policy settings as 'Setting / Value / What it means' rows."""
    rows = []
    for key, (name, meaning) in L.POLICY_FIELDS.items():
        value = config.get(key)
        if isinstance(value, bool):
            value = "Yes" if value else "No"
        rows.append({"Setting": name, "Value": str(value), "What it means": meaning})
    return pd.DataFrame(rows)


st.title("Hint rules", anchor=False)
st.caption("The rules that decide how much help the tutor may give (the 'scaffold policy'). "
           "The AI cannot change them; only a lecturer can approve a new version.")
show_flash()

active = ctx.policies.active()
with st.container(border=True):
    st.subheader(f"In use now: {active.policy_version}", anchor=False)
    st.dataframe(settings_table(active.model_dump(mode="json")), hide_index=True)

rows = service.policies(user)
st.subheader("All versions", anchor=False)
st.dataframe(pd.DataFrame([{
    "Version": r["policy_version"], "Status": L.label(L.POLICY_STATUS, r["status"]),
    "Idea came from": L.label(L.POLICY_SOURCE, r["source"]), "Reason given": r["rationale"],
    "Proposed by": people.get(r["proposed_by"], "Initial set-up" if r["proposed_by"] == "system" else r["proposed_by"]),
    "Approved by": people.get(r["approved_by"], "Initial set-up" if r["approved_by"] == "system" else (r["approved_by"] or "-")),
    "Created": L.when(r["created_at"]),
} for r in rows]), hide_index=True)

with st.expander("Propose a new version", icon=":material/edit:"):
    with st.form("propose"):
        version = st.text_input("Name for the new version", placeholder="e.g. SP-1.1")
        min_attempts = st.number_input(L.POLICY_FIELDS["min_attempts_for_analogue"][0], 0, 10,
                                       active.min_attempts_for_analogue)
        min_hints = st.number_input(L.POLICY_FIELDS["min_hints_before_analogue"][0], 0, 10,
                                    active.min_hints_before_analogue)
        max_level = st.number_input(L.POLICY_FIELDS["max_hint_level"][0], 1, 6, int(active.max_hint_level),
                                    help=L.POLICY_FIELDS["max_hint_level"][1])
        source = st.segmented_control("Where did this idea come from?", ["human", "llm_suggestion"], default="human",
                                      format_func=L.POLICY_SOURCE.get)
        rationale = st.text_area("Reason and evidence for the change")
        if st.form_submit_button("Submit proposal"):
            try:
                if not version.strip() or not rationale.strip():
                    raise ReviewError("Give the new version a name and explain the reason.")
                config = PolicyConfig.model_validate({**active.model_dump(), "policy_version": version.strip(),
                                                      "min_attempts_for_analogue": int(min_attempts),
                                                      "min_hints_before_analogue": int(min_hints),
                                                      "max_hint_level": int(max_level)})
                service.propose_policy(user, config, rationale, source or "human")
                flash("success", "Proposal submitted. Nothing changes until a lecturer approves it.")
            except ReviewError as error:
                flash("warning", str(error))
            except ValidationError:
                flash("warning", "One of the values is not allowed. Please check the numbers.")
            st.rerun()

proposals = [r for r in rows if r["status"] == "proposed"]
if user.role == Role.LECTURER and proposals:
    st.subheader("Proposals waiting for a decision", anchor=False)
    for row in proposals:
        with st.container(border=True):
            st.markdown(f"**{row['policy_version']}**, idea from {L.label(L.POLICY_SOURCE, row['source']).lower()}: "
                        f"{row['rationale']}")
            st.dataframe(settings_table(json.loads(row["config_json"])), hide_index=True)
            with st.form(f"decide_{row['policy_version']}"):
                tested = st.checkbox("The technical team ran the automated safety tests with these rules, "
                                     "and they all passed")
                reason = st.text_input("Reason for your decision")
                approve_col, reject_col = st.columns(2)
                approve = approve_col.form_submit_button("Approve and start using", type="primary")
                reject = reject_col.form_submit_button("Reject")
                if approve or reject:
                    try:
                        service.decide_policy(user, row["policy_version"], approve, reason, tested)
                        flash("success", "Approved: these rules are now in use." if approve else "Proposal rejected.")
                    except ReviewError as error:
                        flash("warning", str(error))
                    st.rerun()
