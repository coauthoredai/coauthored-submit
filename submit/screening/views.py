"""Moderator pages. Every route here requires an unbanned moderator (checked before each
request and again in each view), and `service.decide` checks again before any change."""
from typing import Any

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from pydantic import ValidationError
from sqlalchemy import select

from .. import mailer, notify
from ..auth import moderator_required
from ..auth.guard import current_account, require_moderator, utcnow
from ..db import get_session
from ..models import ModerationLog, Submission
from ..submissions.schema import ReasonIn
from ..submissions.views import send_staged_pdf
from ..taxonomy import category_label
from .service import CHECKLIST, NotAllowed, decide
from .state import (ACCEPTED, ANNOUNCING, CHANGES_REQUESTED, LABELS, ON_HOLD, SUBMITTED,
                    TransitionError, allowed_actions)
from .transitions import StaleTransition

bp = Blueprint("screening", __name__, url_prefix="/moderation")

ACTION_LABELS = {"accept": "Accept", "reject": "Reject", "request_changes": "Request changes",
                 "hold": "Put on hold"}


@bp.before_request
def _moderators_only() -> Any:
    if current_account() is None:
        if request.method == "GET":
            return redirect(url_for("auth.sign_in", next=request.full_path.rstrip("?")))
        abort(401)
    require_moderator()
    return None


def _get(sub_id: int) -> Submission:
    sub = get_session().get(Submission, sub_id)
    if sub is None:
        abort(404)
    return sub


@bp.route("")
@moderator_required
def queue() -> str:
    session = get_session()

    def of(*statuses: str) -> list[Submission]:
        return list(session.scalars(select(Submission).where(Submission.status.in_(statuses))
                                    .order_by(Submission.created_at)))
    return render_template("screening/queue.html", labels=LABELS,
                           sections=[("Awaiting screening", of(SUBMITTED)),
                                     ("On hold", of(ON_HOLD)),
                                     ("Accepted, awaiting announcement", of(ACCEPTED, ANNOUNCING)),
                                     ("Changes requested", of(CHANGES_REQUESTED))])


def _render_detail(sub: Submission, errors: dict[str, str], values: dict[str, Any],
                   status: int = 200) -> tuple[str, int]:
    log = get_session().scalars(select(ModerationLog).where(
        ModerationLog.submission_id == sub.id).order_by(ModerationLog.id)).all()
    return render_template(
        "screening/detail.html", sub=sub, log=log, labels=LABELS, checklist=CHECKLIST,
        actions=[(a, ACTION_LABELS[a]) for a in allowed_actions(sub.status, "moderator")],
        errors=errors, values=values, category_label=category_label,
        own=sub.account_id == current_account().id), status


@bp.route("/<int:sub_id>", methods=["GET"])
@moderator_required
def detail(sub_id: int) -> tuple[str, int]:
    return _render_detail(_get(sub_id), {}, {"action": "", "reason": "", "checked": set()})


@bp.route("/<int:sub_id>", methods=["POST"])
@moderator_required
def act(sub_id: int) -> Any:
    session, sub, moderator = get_session(), _get(sub_id), require_moderator()
    checked = {k for k in CHECKLIST if request.form.get(f"check_{k}") == "on"}
    values = {"action": request.form.get("action", ""), "reason": request.form.get("reason", ""),
              "checked": checked}
    try:
        data = ReasonIn.model_validate({"action": values["action"], "reason": values["reason"]})
        decide(session, moderator, sub, data.action, data.reason, checked, utcnow())
        session.commit()
    except ValidationError:
        return _render_detail(sub, {"action": "Choose an action."}, values, 400)
    except NotAllowed as exc:
        session.rollback()
        abort(403, str(exc))
    except TransitionError as exc:
        session.rollback()
        key = "reason" if "reason" in str(exc) else ("checklist" if "checklist" in str(exc) else "action")
        return _render_detail(sub, {key: str(exc)}, values, 400)
    except StaleTransition:
        session.rollback()
        session.expire_all()
        return _render_detail(_get(sub_id), {"form": "Another moderator changed this submission "
                                             "first. Review its new status below."}, values, 409)
    link = url_for("submissions.detail", sub_id=sub.id, _external=True)
    message = notify.decision(sub, data.action, data.reason, link)
    if message:
        mailer.send(message)
    flash(f"Submission {sub.id}: {LABELS[sub.status].lower()}.")
    return redirect(url_for("screening.queue"))


@bp.route("/<int:sub_id>/pdf")
@moderator_required
def pdf(sub_id: int) -> Any:
    return send_staged_pdf(_get(sub_id))
