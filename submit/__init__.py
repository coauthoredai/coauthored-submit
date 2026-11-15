"""coauthored-submit: accounts, submission, screening and the daily announce for Coauthored."""
from typing import Any, Mapping, Optional

from flask import Flask, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import auth, cli, db, mailer
from .config import check_config, is_dev_or_test, load_config
from .storage import Store, make_store

csrf = CSRFProtect()


def create_app(overrides: Optional[Mapping[str, Any]] = None, *, engine: Optional[Engine] = None,
               store: Optional[Store] = None, mail: Optional[mailer.Mailer] = None,
               authenticator: Optional[auth.Authenticator] = None) -> Flask:
    conf = load_config(overrides=overrides)
    check_config(conf)  # refuses unsafe settings, e.g. DEV_AUTH outside dev/test

    app = Flask(__name__, instance_relative_config=False)
    app.config.update(conf)
    if not is_dev_or_test(conf):
        # Cloud Run terminates TLS and sets X-Forwarded-For/-Proto/-Host.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)  # type: ignore[method-assign]

    csrf.init_app(app)
    db.init_app(app, engine)
    app.extensions["store"] = store or make_store(app.config["STORAGE_PREFIX"])
    mailer.init_app(app, mail)
    auth.init_app(app, authenticator)

    from .screening.views import bp as screening_bp
    from .submissions.views import bp as submissions_bp
    app.register_blueprint(submissions_bp)
    app.register_blueprint(screening_bp)
    cli.register(app)
    _templates(app)
    _errors(app)
    _headers(app)
    return app


def _templates(app: Flask) -> None:
    from .auth.guard import current_account

    @app.context_processor
    def chrome() -> dict[str, Any]:
        c = app.config
        fapi = (c.get("CLERK_FRONTEND_API_URL") or "").rstrip("/")
        clerk_js = (f"{fapi}/npm/@clerk/clerk-js@5/dist/clerk.browser.js"
                    if fapi and c.get("CLERK_PUBLISHABLE_KEY") and not c["DEV_AUTH"] else "")
        return {"account": current_account(), "browse_base": c["BROWSE_BASE_URL"].rstrip("/"),
                "help_base": c["HELP_BASE_URL"].rstrip("/"), "source_url": c["SOURCE_URL"],
                "clerk_js": clerk_js, "clerk_publishable_key": c.get("CLERK_PUBLISHABLE_KEY"),
                "dev_auth": c["DEV_AUTH"]}


def _errors(app: Flask) -> None:
    @app.errorhandler(CSRFError)
    def csrf_error(exc: CSRFError) -> tuple[str, int]:
        return render_template("error.html", code=400, title="Form expired",
                               message="The form expired or was sent from another site. Go back, "
                                       "reload the page and try again."), 400

    @app.errorhandler(413)
    def too_large(exc: HTTPException) -> tuple[str, int]:
        mb = app.config["PDF_MAX_BYTES"] // (1024 * 1024)
        return render_template("error.html", code=413, title="File too large",
                               message=f"The upload is larger than {mb} MB, the most we accept."), 413

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException) -> tuple[str, int]:
        titles = {401: "Sign in needed", 403: "Not allowed", 404: "Not found",
                  405: "Not allowed", 409: "Conflict", 429: "Too many submissions"}
        default = {401: "Sign in to continue.", 404: "There is nothing here."}
        msg = exc.description if exc.description and not exc.description.startswith(
            ("The server", "The requested URL", "You don't have")) else default.get(exc.code or 0, "")
        return render_template("error.html", code=exc.code, title=titles.get(exc.code or 0, exc.name),
                               message=msg), exc.code or 500


def _headers(app: Flask) -> None:
    @app.after_request
    def security_headers(resp: Any) -> Any:
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if not app.config["TESTING"] and not is_dev_or_test(app.config):
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if resp.mimetype == "text/html":
            fapi = (app.config.get("CLERK_FRONTEND_API_URL") or "").rstrip("/")
            extra = f" {fapi}" if fapi else ""
            resp.headers.setdefault(
                "Content-Security-Policy",
                f"default-src 'self'; script-src 'self'{extra} https://challenges.cloudflare.com; "
                f"connect-src 'self'{extra}; img-src 'self' data: https://img.clerk.com; "
                f"style-src 'self' 'unsafe-inline'; frame-src 'self' https://challenges.cloudflare.com; "
                "worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        return resp
