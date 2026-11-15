"""Authentication: Clerk in production, DEV_AUTH in tests and local development."""
from flask import Flask

from .clerk import ClerkAuthenticator
from .dev import DevAuthenticator
from .guard import account_required, current_account, login_required, moderator_required
from .identity import Authenticator, Identity

__all__ = ["init_app", "Authenticator", "Identity", "ClerkAuthenticator", "DevAuthenticator",
           "account_required", "current_account", "login_required", "moderator_required"]


def init_app(app: Flask, authenticator: Authenticator | None = None) -> None:
    if authenticator is None:
        if app.config["DEV_AUTH"]:
            authenticator = DevAuthenticator(app.config)
        else:
            authenticator = ClerkAuthenticator(app.config)
    app.extensions["authenticator"] = authenticator
    from .views import bp
    app.register_blueprint(bp)
