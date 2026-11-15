"""Submitter pages: submit, replace, withdraw, edit after a change request, my account."""
from typing import Any, Optional

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template,
                   request, url_for)
from pydantic import ValidationError
from sqlalchemy import select

from .. import mailer, notify
from ..auth import account_required, current_account
from ..auth.guard import utcnow
from ..db import get_session
from ..licenses import offered_licenses
from ..models import ModerationLog, Submission
from ..screening.state import LABELS, TransitionError, allowed_actions
from ..screening.transitions import StaleTransition
from ..storage import Store
from ..taxonomy import category_label, grouped_options
from . import service
from .forms import (DECLARATIONS, blank_values, field_errors, form_values_from, read_submission,
                    validate_submission)
from .pdf import CheckedPdf, PdfError, check_pdf
from .schema import WithdrawalIn

bp = Blueprint("submissions", __name__)


def store() -> Store:
    return current_app.extensions["store"]


def schema_context() -> dict[str, Any]:
    return {"license_host": current_app.config["LICENSE_HOST"],
            "max_cross_lists": current_app.config["MAX_CROSS_LISTS"]}


def _pdf(required: bool) -> tuple[Optional[CheckedPdf], Optional[str]]:
    upload = request.files.get("pdf")
    if upload is None or not upload.filename:
        return None, ("Choose a PDF file to upload." if required else None)
    try:
        return check_pdf(upload.stream, current_app.config["PDF_MAX_BYTES"]), None
    except PdfError as exc:
        return None, str(exc)


def render_form(mode: str, values: dict[str, Any], errors: dict[str, str], status: int = 200,
                **extra: Any) -> tuple[str, int]:
    authors = values["authors"] or blank_values()["authors"]
    rows = len(authors) + (1 if len(authors) < 3 else 0)
    return render_template(
        "submissions/form.html", mode=mode, values=values, errors=errors, authors=authors,
        rows=rows, category_groups=grouped_options(), licenses=offered_licenses(
            current_app.config["LICENSE_HOST"]), declarations=DECLARATIONS,
        max_pdf_mb=current_app.config["PDF_MAX_BYTES"] // (1024 * 1024),
        max_cross=current_app.config["MAX_CROSS_LISTS"], **extra), status


def _add_author_row(mode: str, **extra: Any) -> tuple[str, int]:
    values = read_submission(request.form)
    values["authors"].append({"display_name": "", "kind": "human", "contribution": "",
                              "orcid": "", "ai_system": "", "ai_version": "", "ai_provider": "",
                              "is_responsible": False, "is_submitter": False})
    flash("Added an author row. If you had chosen a PDF, choose it again before submitting.")
    return render_form(mode, values, {}, focus_row=len(values["authors"]), **extra)


def _own(sub_id: int) -> Submission:
    sub = get_session().get(Submission, sub_id)
    account = current_account()
    if sub is None or account is None:
        abort(404)
    if sub.account_id != account.id and not account.is_moderator:
        abort(404)
    return sub


def _status_link(sub: Submission) -> str:
    return url_for("submissions.detail", sub_id=sub.id, _external=True)


@bp.route("/")
def home() -> str:
    return render_template("home.html")


@bp.route("/submit", methods=["GET", "POST"])
@account_required
def new() -> Any:
    account = current_account()
    if request.method == "GET":
        return render_form("new", blank_values(account.display_name), {})
    if request.form.get("op") == "add_author":
        return _add_author_row("new")
    return _save("new", replaces=None)


@bp.route("/papers/<paper_id>/replace", methods=["GET", "POST"])
@account_required
def replace(paper_id: str) -> Any:
    session, account = get_session(), current_account()
    try:
        paper = service.owned_paper(session, account, paper_id)  # a withdrawn paper may get a new version
        latest = service.latest_announced(session, paper_id)
    except service.SubmissionRefused:
        abort(404)
    if request.method == "GET":
        return render_form("replace", form_values_from(latest), {}, paper=paper)
    if request.form.get("op") == "add_author":
        return _add_author_row("replace", paper=paper)
    return _save("replace", replaces=paper_id, paper=paper)


def _save(mode: str, replaces: Optional[str], **extra: Any) -> Any:
    session, account = get_session(), current_account()
    model, errors, values = validate_submission(request.form, schema_context())
    pdf, pdf_error = _pdf(required=True)
    if pdf_error:
        errors["pdf"] = pdf_error
    if errors or model is None or pdf is None:
        return render_form(mode, values, errors, 400, **extra)
    try:
        sub = service.create_submission(session, store(), account, model, pdf, utcnow(),
                                        current_app.config["SUBMISSIONS_PER_DAY"],
                                        replaces=replaces)
        session.commit()
    except service.SubmissionRefused as exc:
        session.rollback()
        return render_form(mode, values, {"form": str(exc)}, 429 if "24 hours" in str(exc) else 400,
                           **extra)
    finally:
        pdf.file.close()
    mailer.send(notify.received(sub, _status_link(sub)))
    flash("Thank you. Your submission is in the screening queue.")
    return redirect(url_for("submissions.detail", sub_id=sub.id))


@bp.route("/submissions/<int:sub_id>/edit", methods=["GET", "POST"])
@account_required
def edit(sub_id: int) -> Any:
    sub = _own(sub_id)
    if sub.account_id != current_account().id or "resubmit" not in allowed_actions(sub.status, "submitter") \
            or sub.kind == "withdrawal":
        abort(404)
    if request.method == "GET":
        return render_form("edit", form_values_from(sub), {}, sub=sub)
    if request.form.get("op") == "add_author":
        return _add_author_row("edit", sub=sub)
    session = get_session()
    model, errors, values = validate_submission(request.form, schema_context())
    pdf, pdf_error = _pdf(required=False)
    if pdf_error:
        errors["pdf"] = pdf_error
    if errors or model is None:
        return render_form("edit", values, errors, 400, sub=sub)
    try:
        service.update_and_resubmit(session, store(), sub, model, pdf, utcnow())
        session.commit()
    except (service.SubmissionRefused, StaleTransition) as exc:
        session.rollback()
        return render_form("edit", values, {"form": str(exc)}, 409, sub=sub)
    finally:
        if pdf:
            pdf.file.close()
    flash("Your changes are saved and the submission is back in the screening queue.")
    return redirect(url_for("submissions.detail", sub_id=sub.id))


@bp.route("/papers/<paper_id>/withdraw", methods=["GET", "POST"])
@account_required
def withdraw(paper_id: str) -> Any:
    session, account = get_session(), current_account()
    try:
        paper = service.owned_paper(session, account, paper_id)
    except service.SubmissionRefused:
        abort(404)
    errors: dict[str, str] = {}
    values = {"reason": "", "authorized": False}
    if request.method == "POST":
        values = {"reason": request.form.get("reason", ""),
                  "authorized": request.form.get("authorized") == "on"}
        try:
            data = WithdrawalIn.model_validate(values)
            sub = service.create_withdrawal(session, account, paper_id, data, utcnow(),
                                            current_app.config["SUBMISSIONS_PER_DAY"])
            session.commit()
        except ValidationError as exc:
            errors = field_errors(exc)
        except service.SubmissionRefused as exc:
            session.rollback()
            errors = {"form": str(exc)}
        else:
            mailer.send(notify.received(sub, _status_link(sub)))
            flash("Your withdrawal request is in the screening queue.")
            return redirect(url_for("submissions.detail", sub_id=sub.id))
    return render_template("submissions/withdraw.html", paper=paper, values=values,
                           errors=errors), (400 if errors else 200)


@bp.route("/submissions/<int:sub_id>/cancel", methods=["POST"])
@account_required
def cancel(sub_id: int) -> Response:
    sub = _own(sub_id)
    if sub.account_id != current_account().id:
        abort(404)
    session = get_session()
    try:
        service.cancel(session, sub, utcnow())
        session.commit()
        flash("The submission is cancelled.")
    except (TransitionError, StaleTransition) as exc:
        session.rollback()
        flash(f"Could not cancel: {exc}")
    return redirect(url_for("submissions.detail", sub_id=sub.id))


@bp.route("/submissions/<int:sub_id>")
@account_required
def detail(sub_id: int) -> str:
    sub = _own(sub_id)
    log = get_session().scalars(select(ModerationLog).where(
        ModerationLog.submission_id == sub.id).order_by(ModerationLog.id)).all()
    feedback = next((row for row in reversed(log) if row.reason and row.action in
                     ("reject", "request_changes", "hold")), None)
    return render_template("submissions/detail.html", sub=sub, log=log, feedback=feedback,
                           labels=LABELS, category_label=category_label,
                           actions=allowed_actions(sub.status, "submitter")
                           if sub.account_id == current_account().id else [],
                           browse_base=current_app.config["BROWSE_BASE_URL"])


@bp.route("/submissions/<int:sub_id>/pdf")
@account_required
def pdf(sub_id: int) -> Response:
    sub = _own(sub_id)
    return send_staged_pdf(sub)


def send_staged_pdf(sub: Submission) -> Response:
    if not sub.pdf_key or not store().exists(sub.pdf_key):
        abort(404)
    resp = Response(store().read_chunks(sub.pdf_key), mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'inline; filename="submission-{sub.id}.pdf"'
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.route("/account")
@account_required
def account() -> str:
    session, acct = get_session(), current_account()
    subs = session.scalars(select(Submission).where(Submission.account_id == acct.id)
                           .order_by(Submission.created_at.desc())).all()
    return render_template("submissions/account.html", subs=subs, labels=LABELS,
                           papers=service.owned_papers(session, acct),
                           used=service.submissions_today(session, acct, utcnow()),
                           per_day=current_app.config["SUBMISSIONS_PER_DAY"],
                           browse_base=current_app.config["BROWSE_BASE_URL"])
