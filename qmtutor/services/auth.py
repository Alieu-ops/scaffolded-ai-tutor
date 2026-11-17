"""
Roles and permissions, checked in the service layer.

Hiding a page in the menu is a convenience, not security: every service
function that reads or changes protected data calls require_role() (and,
for student data, require_self_or_staff()) itself. So even a crafted request
that reached a service directly would be refused.

Prototype sign-in: a user picks one of the seeded SYNTHETIC accounts. There
are no passwords because there is no real data. A real deployment must
replace this with the institution's sign-in (e.g. OIDC via st.login).
"""

from __future__ import annotations

import uuid

from qmtutor.domain.models import Role, UserAccount
from qmtutor.services.context import AppContext
from qmtutor.storage.db import utc_now
from qmtutor.storage.events import log_event

STAFF_ROLES = {Role.LECTURER, Role.RESEARCHER, Role.ADMINISTRATOR}


class PermissionDenied(Exception):
    """The acting user's role does not allow this action."""


def require_role(user: UserAccount, allowed: set[Role]) -> None:
    if not user.active or user.role not in allowed:
        raise PermissionDenied(f"{user.role.value} accounts cannot perform this action.")


def require_self_or_staff(user: UserAccount, student_id: str, staff: set[Role] | None = None) -> None:
    """A student may only see their own records; listed staff roles may see others."""
    if user.role == Role.STUDENT and user.user_id == student_id:
        return
    require_role(user, staff or {Role.LECTURER})


def sign_in(ctx: AppContext, user_id: str) -> UserAccount:
    """Look up the account server-side; the role comes from the database, never from the client."""
    user = ctx.users.get(user_id)
    if user is None or not user.active:
        raise PermissionDenied("Unknown or inactive account.")
    with ctx.db.transaction() as conn:
        log_event(conn, "user_signed_in", actor_id=user.user_id, payload={"role": user.role.value})
    return user


def record_consent(ctx: AppContext, user: UserAccount, acknowledged: bool) -> None:
    """Record the study-notice decision (placeholder notice until ethics approval)."""
    version = ctx.settings["consent_notice_version"]
    with ctx.db.transaction() as conn:
        conn.execute("INSERT INTO consent_record VALUES (?,?,?,?,?,?)",
                     (uuid.uuid4().hex, user.user_id, version, "acknowledged" if acknowledged else "declined",
                      "prototype_synthetic_data", utc_now()))
        log_event(conn, "consent_recorded", actor_id=user.user_id, subject_id=user.user_id,
                  payload={"notice_version": version, "acknowledged": acknowledged})
