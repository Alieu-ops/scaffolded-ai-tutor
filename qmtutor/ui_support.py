"""
Helpers shared by the Streamlit pages: the cached application context and
the signed-in user.

Session state holds only the signed-in user's id and temporary page state.
Durable records (exercises, attempts, evidence) always come from the database
through the services, so a browser refresh never loses or invents progress.
"""

from __future__ import annotations

import os

import streamlit as st

from qmtutor.domain.models import UserAccount
from qmtutor.seed import is_seeded, seed
from qmtutor.services.context import AppContext, build_context, load_settings


@st.cache_resource(show_spinner="Starting the tutor...")
def get_context() -> AppContext:
    """
    One shared context per server process (database connection, model client, retriever).
    Tests set QMTUTOR_DB and QMTUTOR_PROVIDER=fake to use a temporary database and no real model.
    """
    settings = load_settings()
    if os.environ.get("QMTUTOR_PROVIDER"):
        settings["llm"]["provider"] = os.environ["QMTUTOR_PROVIDER"]
    ctx = build_context(settings, db_path=os.environ.get("QMTUTOR_DB"))
    if not is_seeded(ctx):
        seed(ctx)       # first start: synthetic demo accounts and content
    return ctx


def current_user() -> UserAccount | None:
    """Re-read the account from the database on every run, so role changes take effect."""
    user_id = st.session_state.get("user_id")
    return get_context().users.get(user_id) if user_id else None


def require_user() -> UserAccount:
    user = current_user()
    if user is None:
        st.warning("Please sign in first.")
        st.stop()
    return user


def show_health(info: dict) -> None:
    """System health as readable metrics and an activity table (no raw JSON on screen)."""
    import pandas as pd
    from qmtutor import labels as L

    row = st.container(horizontal=True)
    row.metric("Database", "Working" if info.get("database") == "ok" else "Problem")
    row.metric("AI model server", "Reachable" if info.get("model_server") == "reachable" else
               "Not reachable" if info.get("model_server") == "NOT reachable" else "Not checked")
    row.metric("AI model failures", info.get("provider_failures", 0))
    row.metric("AI replies blocked", info.get("leaks_blocked", 0), help="Replies that would have revealed an answer.")
    provider = str(info.get("provider", ""))
    st.caption(f"AI model in use: {provider.split(':', 1)[-1]} (via {provider.split(':', 1)[0].capitalize()})")
    counts = info.get("event_counts", {})
    if counts:
        st.dataframe(pd.DataFrame([{"Activity": L.label(L.EVENTS, name), "Count": n}
                                   for name, n in sorted(counts.items(), key=lambda kv: -kv[1])]), hide_index=True)


def flash(kind: str, text: str) -> None:
    """Queue a message to show after the next rerun."""
    st.session_state["flash"] = (kind, text)


def show_flash() -> None:
    if message := st.session_state.pop("flash", None):
        getattr(st, message[0])(message[1])
