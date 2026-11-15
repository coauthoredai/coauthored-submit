"""Moderator decisions. Screening only: is this a genuine, complete scholarly paper that
credits its AI authors per policy? It is not peer review."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Account, Submission
from .state import TransitionError
from .transitions import apply_transition

CHECKLIST = {
    "scholarly": "A real scholarly paper (research, review or technical report), not an advert, "
                 "essay without scholarly content, or placeholder.",
    "complete": "Complete and readable: the PDF opens, and its title, abstract and authors match "
                "the form.",
    "category": "The primary category fits the paper (and the cross-lists are reasonable).",
    "ai_credit": "AI authors are credited per policy: system, version, provider and contribution "
                 "for each, and at least one human author takes responsibility.",
    "clean": "No spam, plagiarism or harmful content.",
}


class NotAllowed(PermissionError):
    pass


def decide(session: Session, moderator: Account, sub: Submission, action: str,
           reason: Optional[str], checked: set[str], now: datetime) -> str:
    """Apply a moderator's decision (caller commits). Returns the new status."""
    if not moderator.is_moderator or moderator.is_banned:
        raise NotAllowed("Moderators only.")
    if sub.account_id == moderator.id:
        raise NotAllowed("Moderators cannot screen their own submissions.")
    if action == "accept" and set(CHECKLIST) - checked:
        raise TransitionError("Tick every checklist item before accepting.")
    return apply_transition(session, sub, action, "moderator", now, actor_id=moderator.id,
                            reason=reason)
