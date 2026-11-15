"""Sign in, sign up and sign out.

With Clerk these hand over to Clerk's hosted pages (CLERK_SIGN_IN_URL, CLERK_SIGN_UP_URL),
which send the visitor back to `redirect_url`. Under DEV_AUTH, /sign-in is a local form.
"""
from urllib.parse import urlencode

from flask import (Blueprint, current_app, flash, make_response, redirect, render_template,
                   request, url_for)
from flask_wtf import FlaskForm
from werkzeug.wrappers import Response
from wtforms import EmailField
from wtforms.validators import DataRequired, Length

from .dev import COOKIE as DEV_COOKIE

bp = Blueprint("auth", __name__)


def safe_next(target: str | None) -> str:
    """Only same-site paths; anything else goes to the account page."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("submissions.account")


def _hosted(url_key: str, next_path: str) -> Response:
    base = current_app.config.get(url_key)
    if not base:
        return make_response(render_template("auth/unavailable.html"), 503)
    absolute = request.host_url.rstrip("/") + next_path
    sep = "&" if "?" in base else "?"
    return redirect(f"{base}{sep}{urlencode({'redirect_url': absolute})}")


class DevSignInForm(FlaskForm):
    email = EmailField("Email address", validators=[DataRequired(), Length(min=3, max=255)])


@bp.route("/sign-in", methods=["GET", "POST"])
def sign_in() -> Response | str:
    next_path = safe_next(request.args.get("next"))
    if not current_app.config["DEV_AUTH"]:
        return _hosted("CLERK_SIGN_IN_URL", next_path)
    form = DevSignInForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if "@" not in email:
            form.email.errors.append("Enter an email address.")
        else:
            resp = redirect(next_path)
            resp.set_cookie(DEV_COOKIE, email, httponly=True, samesite="Lax",
                            secure=current_app.config["SESSION_COOKIE_SECURE"])
            return resp
    return render_template("auth/dev_sign_in.html", form=form, next_path=next_path)


@bp.route("/sign-up")
def sign_up() -> Response:
    next_path = safe_next(request.args.get("next"))
    if current_app.config["DEV_AUTH"]:
        return redirect(url_for("auth.sign_in", next=next_path))
    return _hosted("CLERK_SIGN_UP_URL", next_path)


@bp.route("/sign-out", methods=["GET", "POST"])
def sign_out() -> Response:
    if current_app.config["DEV_AUTH"]:
        resp = redirect(url_for("submissions.home"))
        resp.delete_cookie(DEV_COOKIE)
        flash("You are signed out.")
        return resp
    if current_app.config.get("CLERK_SIGN_OUT_URL"):
        resp = redirect(current_app.config["CLERK_SIGN_OUT_URL"])
    else:
        # Clerk's browser script ends the Clerk session (see static/js/clerk-session.js).
        resp = make_response(render_template("auth/sign_out.html"))
    resp.delete_cookie("__session")
    return resp
