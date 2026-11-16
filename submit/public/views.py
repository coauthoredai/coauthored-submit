"""Public list of submissions awaiting screening, marked "Submitted".

Owner's decision (2026-11-16): submitted papers are visible before a moderator screens them,
listed separately from announced papers and clearly marked as not yet screened. Only
submissions in status `submitted` are shown (new papers and new versions; never withdrawals,
and nothing on hold, sent back, rejected or cancelled), so a moderator removes one from view
by putting it on hold. The pages ask search engines not to index them, and the submitter's
email is never shown. Once a paper is announced, its page redirects to the public record.
"""
from typing import Any

from flask import Blueprint, abort, current_app, redirect, render_template
from sqlalchemy import select

from ..db import get_session
from ..models import Submission
from ..screening.state import ACCEPTED, ANNOUNCED, ANNOUNCING, SUBMITTED
from ..submissions.views import send_staged_pdf
from ..taxonomy import category_label

bp = Blueprint("public", __name__)

LISTED_KINDS = ("new", "replacement")


def _listed(sub_id: int) -> Submission:
    sub = get_session().get(Submission, sub_id)
    if sub is None or sub.kind not in LISTED_KINDS:
        abort(404)
    return sub


@bp.route("/submitted")
def submitted() -> Any:
    subs = get_session().scalars(
        select(Submission).where(Submission.status == SUBMITTED, Submission.kind.in_(LISTED_KINDS))
        .order_by(Submission.created_at.desc())).all()
    resp = current_app.make_response(render_template(
        "public/submitted.html", subs=subs, category_label=category_label))
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@bp.route("/submitted/<int:sub_id>")
def submitted_detail(sub_id: int) -> Any:
    sub = _listed(sub_id)
    if sub.status == ANNOUNCED and sub.paper_id:
        return redirect(f"{current_app.config['BROWSE_BASE_URL']}/abs/{sub.paper_id}v{sub.version}")
    if sub.status not in (SUBMITTED, ACCEPTED, ANNOUNCING):
        abort(404)
    resp = current_app.make_response(render_template(
        "public/submitted_detail.html", sub=sub, category_label=category_label))
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@bp.route("/submitted/<int:sub_id>/pdf")
def submitted_pdf(sub_id: int) -> Any:
    sub = _listed(sub_id)
    if sub.status not in (SUBMITTED, ACCEPTED, ANNOUNCING):
        abort(404)
    resp = send_staged_pdf(sub)
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp
