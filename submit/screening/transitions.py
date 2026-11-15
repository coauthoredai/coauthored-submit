"""Applying a transition: the guarded status update plus its moderation-log row.

Both happen in the caller's transaction; the caller commits. The UPDATE carries
`WHERE status = :from`, so if another request changed the submission first, no row
matches and StaleTransition is raised instead of overwriting their decision.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from ..models import ModerationLog, Submission
from .state import Role, next_status


class StaleTransition(RuntimeError):
    """The submission's status changed since it was read."""


def apply_transition(session: Session, submission: Submission, action: str, role: Role,
                     now: datetime, actor_id: Optional[int] = None,
                     reason: Optional[str] = None) -> str:
    from_status = submission.status
    to_status = next_status(from_status, action, role, reason)
    result = session.execute(
        update(Submission)
        .where(Submission.id == submission.id, Submission.status == from_status)
        .values(status=to_status, updated_at=now)
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise StaleTransition(f"submission {submission.id} is no longer {from_status}")
    session.add(ModerationLog(
        submission_id=submission.id, from_status=from_status, to_status=to_status,
        action=action, moderator_account_id=actor_id if role == "moderator" else None,
        reason=(reason or None), created_at=now))
    session.flush()
    # Keep the in-memory object in step without reloading it.
    set_committed_value(submission, "status", to_status)
    set_committed_value(submission, "updated_at", now)
    return to_status
