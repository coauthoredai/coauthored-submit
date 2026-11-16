"""The signed-in account, and the decorators that guard routes.

On first sight of a verified identity a `coauthored_accounts` row is created.
`login_required` sends anonymous visitors to sign in; `account_required` also refuses
banned accounts; `moderator_required` refuses everyone who is not an unbanned moderator.
"""
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, cast

from flask import abort, current_app, g, make_response, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import get_session
from ..models import Account
from .identity import Authenticator

F = TypeVar("F", bound=Callable[..., Any])


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def authenticator() -> Authenticator:
    return current_app.extensions["authenticator"]


def current_account() -> Optional[Account]:
    if "account" in g:
        return g.account
    g.account = None
    identity = authenticator().identify(request)
    if identity is None:
        return None
    session = get_session()
    account = session.scalar(select(Account).where(Account.clerk_user_id == identity.user_id))
    if account is None:
        email, name = identity.email, identity.display_name
        if not email:
            email, fetched_name = authenticator().fetch_profile(identity.user_id)  # type: ignore[attr-defined]
            name = name or fetched_name
        if not email:
            abort(403, "Your account has no email address we can read. See the help pages.")
        account = Account(clerk_user_id=identity.user_id, email=email,
                          display_name=(name or email.split("@")[0])[:255],
                          is_moderator=False, is_banned=False, created_at=utcnow())
        session.add(account)
        try:
            session.commit()
        except IntegrityError:  # created by a concurrent request
            session.rollback()
            account = session.scalar(select(Account).where(Account.clerk_user_id == identity.user_id))
    elif identity.email and identity.email != account.email:
        account.email = identity.email
        session.commit()
    g.account = account
    return account


def login_required(fn: F) -> F:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_account() is None:
            if request.method == "GET":
                sign_in = url_for("auth.sign_in", next=request.full_path.rstrip("?"))
                if current_app.config["DEV_AUTH"]:
                    return redirect(sign_in)
                return establishing_session(sign_in)
            abort(401)
        return fn(*args, **kwargs)
    return cast(F, wrapper)


def establishing_session(sign_in: str) -> Any:
    """With Clerk, a page with no valid __session cookie may still belong to someone who is
    signed in: Clerk's browser script sets and refreshes that cookie (tokens last about a
    minute), and it only runs on a page. Redirecting straight to Clerk would loop, since
    Clerk sends a signed-in visitor straight back. So render a page that loads Clerk's
    script: it refreshes the cookie and reloads if there is a session, and goes to sign-in
    if there is none (static/js/clerk-establish.js)."""
    resp = make_response(render_template("auth/establishing.html", sign_in_url=sign_in))
    resp.headers["Cache-Control"] = "no-store"
    return resp


def account_required(fn: F) -> F:
    @login_required
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_account().is_banned:  # type: ignore[union-attr]
            abort(403, "This account may not submit.")
        return fn(*args, **kwargs)
    return cast(F, wrapper)


def require_moderator() -> Account:
    """Abort unless the request comes from an unbanned moderator; returns the account."""
    account = current_account()
    if account is None:
        abort(401)
    if not account.is_moderator or account.is_banned:
        abort(403, "Moderators only.")
    return account


def moderator_required(fn: F) -> F:
    @login_required
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        require_moderator()
        return fn(*args, **kwargs)
    return cast(F, wrapper)
