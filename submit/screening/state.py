"""The submission state machine: one pure function, `next_status`.

    submitted --accept--> accepted --claim--> announcing --publish--> announced
    submitted --hold--> on_hold          (accept / reject / request_changes from on_hold)
    submitted --request_changes--> changes_requested --resubmit--> submitted
    submitted|on_hold|changes_requested|accepted --reject--> rejected
    submitted|on_hold|changes_requested|accepted --cancel (submitter)--> cancelled
    accepted --hold / request_changes--> (a moderator can pull a paper back before announce)

`claim` and `publish` belong to the announce job. Once claimed (`announcing`) a submission
can only be published: announce may already have written its files.
"""
from dataclasses import dataclass
from typing import Literal, Optional

Role = Literal["moderator", "submitter", "system"]

SUBMITTED = "submitted"
ON_HOLD = "on_hold"
CHANGES_REQUESTED = "changes_requested"
ACCEPTED = "accepted"
REJECTED = "rejected"
CANCELLED = "cancelled"
ANNOUNCING = "announcing"
ANNOUNCED = "announced"

STATUSES = (SUBMITTED, ON_HOLD, CHANGES_REQUESTED, ACCEPTED, REJECTED, CANCELLED,
            ANNOUNCING, ANNOUNCED)
TERMINAL = frozenset({REJECTED, CANCELLED, ANNOUNCED})
PENDING = frozenset(STATUSES) - TERMINAL

LABELS = {
    SUBMITTED: "Submitted, awaiting screening",
    ON_HOLD: "On hold",
    CHANGES_REQUESTED: "Changes requested",
    ACCEPTED: "Accepted, awaiting announcement",
    REJECTED: "Rejected",
    CANCELLED: "Cancelled",
    ANNOUNCING: "Being announced",
    ANNOUNCED: "Announced",
}


@dataclass(frozen=True)
class Rule:
    role: Role
    sources: frozenset[str]
    target: str
    reason_required: bool = False


RULES: dict[str, Rule] = {
    "accept": Rule("moderator", frozenset({SUBMITTED, ON_HOLD}), ACCEPTED),
    "reject": Rule("moderator", frozenset({SUBMITTED, ON_HOLD, CHANGES_REQUESTED, ACCEPTED}),
                   REJECTED, reason_required=True),
    "request_changes": Rule("moderator", frozenset({SUBMITTED, ON_HOLD, ACCEPTED}),
                            CHANGES_REQUESTED, reason_required=True),
    "hold": Rule("moderator", frozenset({SUBMITTED, ACCEPTED}), ON_HOLD),
    "resubmit": Rule("submitter", frozenset({CHANGES_REQUESTED}), SUBMITTED),
    "cancel": Rule("submitter", frozenset({SUBMITTED, ON_HOLD, CHANGES_REQUESTED, ACCEPTED}),
                   CANCELLED),
    "claim": Rule("system", frozenset({ACCEPTED}), ANNOUNCING),
    "publish": Rule("system", frozenset({ANNOUNCING}), ANNOUNCED),
}

MODERATOR_ACTIONS = tuple(a for a, r in RULES.items() if r.role == "moderator")


class TransitionError(ValueError):
    """The action is not allowed from this status, for this role, or without a reason."""


def next_status(current: str, action: str, role: Role, reason: Optional[str] = None) -> str:
    """The status after `action`, or TransitionError. No side effects."""
    rule = RULES.get(action)
    if rule is None:
        raise TransitionError(f"Unknown action {action!r}.")
    if rule.role != role:
        raise TransitionError(f"{action} is not a {role} action.")
    if current not in rule.sources:
        raise TransitionError(f"Cannot {action.replace('_', ' ')} a submission that is "
                              f"{LABELS.get(current, current).lower()}.")
    if rule.reason_required and not (reason and reason.strip()):
        raise TransitionError(f"A reason is required to {action.replace('_', ' ')}.")
    return rule.target


def allowed_actions(current: str, role: Role) -> list[str]:
    return [a for a, r in RULES.items() if r.role == role and current in r.sources]
