"""The submission state machine and its guarded, logged application."""
from datetime import datetime

import pytest
from sqlalchemy import select

from submit.db import new_session
from submit.models import ModerationLog, Submission
from submit.screening.state import (ACCEPTED, ANNOUNCED, ANNOUNCING, CANCELLED, CHANGES_REQUESTED,
                                    ON_HOLD, REJECTED, RULES, STATUSES, SUBMITTED, TERMINAL,
                                    TransitionError, allowed_actions, next_status)
from submit.screening.transitions import StaleTransition, apply_transition
from submit.submissions import service
from tests.helpers import checked_pdf, make_account, submission_in

NOW = datetime(2026, 11, 15, 12, 0)

ALLOWED = {
    (SUBMITTED, "accept"): ACCEPTED, (ON_HOLD, "accept"): ACCEPTED,
    (SUBMITTED, "reject"): REJECTED, (ON_HOLD, "reject"): REJECTED,
    (CHANGES_REQUESTED, "reject"): REJECTED, (ACCEPTED, "reject"): REJECTED,
    (SUBMITTED, "request_changes"): CHANGES_REQUESTED, (ON_HOLD, "request_changes"): CHANGES_REQUESTED,
    (ACCEPTED, "request_changes"): CHANGES_REQUESTED,
    (SUBMITTED, "hold"): ON_HOLD, (ACCEPTED, "hold"): ON_HOLD,
    (CHANGES_REQUESTED, "resubmit"): SUBMITTED,
    (SUBMITTED, "cancel"): CANCELLED, (ON_HOLD, "cancel"): CANCELLED,
    (CHANGES_REQUESTED, "cancel"): CANCELLED, (ACCEPTED, "cancel"): CANCELLED,
    (ACCEPTED, "claim"): ANNOUNCING, (ANNOUNCING, "publish"): ANNOUNCED,
}


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("action", list(RULES))
def test_transition_table_is_exactly_as_designed(status, action):
    role = RULES[action].role
    reason = "because"
    if (status, action) in ALLOWED:
        assert next_status(status, action, role, reason) == ALLOWED[(status, action)]
    else:
        with pytest.raises(TransitionError):
            next_status(status, action, role, reason)


@pytest.mark.parametrize("action", ["reject", "request_changes"])
def test_reason_required(action):
    for reason in (None, "", "   "):
        with pytest.raises(TransitionError, match="reason"):
            next_status(SUBMITTED, action, "moderator", reason)


def test_roles_are_enforced():
    with pytest.raises(TransitionError):
        next_status(SUBMITTED, "accept", "submitter")
    with pytest.raises(TransitionError):
        next_status(ACCEPTED, "claim", "moderator")
    with pytest.raises(TransitionError):
        next_status(CHANGES_REQUESTED, "resubmit", "moderator")
    with pytest.raises(TransitionError):
        next_status(SUBMITTED, "nonsense", "moderator")


def test_terminal_and_announcing_states():
    for status in TERMINAL:
        assert all(allowed_actions(status, role) == [] for role in ("moderator", "submitter", "system"))
    assert allowed_actions(ANNOUNCING, "moderator") == []
    assert allowed_actions(ANNOUNCING, "submitter") == []
    assert allowed_actions(ANNOUNCING, "system") == ["publish"]


def _new_submission(session, store):
    account = make_account(session)
    mod = make_account(session, "mod@example.org", "Mo", moderator=True)
    sub = service.create_submission(session, store, account, submission_in(), checked_pdf(), NOW, 5)
    session.commit()
    return sub, mod


def test_apply_transition_writes_the_log_in_the_same_transaction(session, store):
    sub, mod = _new_submission(session, store)
    apply_transition(session, sub, "request_changes", "moderator", NOW, actor_id=mod.id,
                     reason="Add the AI provider")
    session.rollback()  # nothing was committed: neither the status nor the log row
    session.expire_all()
    assert session.get(Submission, sub.id).status == SUBMITTED
    assert session.scalars(select(ModerationLog)).all() == []

    apply_transition(session, sub, "request_changes", "moderator", NOW, actor_id=mod.id,
                     reason="Add the AI provider")
    session.commit()
    row = session.scalars(select(ModerationLog)).one()
    assert (row.submission_id, row.from_status, row.to_status, row.moderator_account_id,
            row.reason, row.action) == (sub.id, SUBMITTED, CHANGES_REQUESTED, mod.id,
                                        "Add the AI provider", "request_changes")


def test_concurrent_decisions_do_not_overwrite_each_other(app, session, store):
    sub, mod = _new_submission(session, store)
    other = new_session(app)
    theirs = other.get(Submission, sub.id)          # both read status=submitted
    apply_transition(session, sub, "accept", "moderator", NOW, actor_id=mod.id)
    session.commit()
    with pytest.raises(StaleTransition):
        apply_transition(other, theirs, "reject", "moderator", NOW, actor_id=mod.id, reason="spam")
    other.rollback()
    other.close()
    session.expire_all()
    assert session.get(Submission, sub.id).status == ACCEPTED
    assert [r.to_status for r in session.scalars(select(ModerationLog))] == [ACCEPTED]
