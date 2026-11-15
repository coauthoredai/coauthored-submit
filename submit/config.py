"""Configuration from environment variables, and the start-up safety checks.

Every setting has an environment variable of the same name (see `.env.example`).
`check_config` refuses unsafe combinations, so a misconfigured production service
fails at start-up instead of running open.
"""
import os
from typing import Any, Mapping

MB = 1024 * 1024
PDF_MAX_BYTES_LIMIT = 50 * MB
"""Policy maximum for an uploaded PDF. PDF_MAX_BYTES may lower it, never raise it."""

DEFAULT_SECRET = "dev-only-not-secret"


class ConfigError(RuntimeError):
    """The configuration is unsafe or incomplete."""


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


DEFAULTS: dict[str, Any] = {
    "SECRET_KEY": DEFAULT_SECRET,
    "FLASK_ENV": "production",
    "TESTING": False,
    "CLASSIC_DB_URI": "sqlite:///instance/coauthored-dev.db",
    # Object store root: a local directory, or gs://bucket for Google Cloud Storage.
    "STORAGE_PREFIX": "./local-store",
    "PDF_MAX_BYTES": PDF_MAX_BYTES_LIMIT,
    "SUBMISSIONS_PER_DAY": 5,
    "MAX_CROSS_LISTS": 4,
    "LICENSE_HOST": "coauthored.pub",
    "BROWSE_BASE_URL": "https://coauthored.pub",
    "HELP_BASE_URL": "https://coauthored.pub",
    "SOURCE_URL": "https://github.com/coauthoredai/coauthored-submit",
    # Auth
    "DEV_AUTH": False,
    "CLERK_JWKS_URL": "",
    "CLERK_ISSUER": "",
    "CLERK_AUTHORIZED_PARTIES": "",
    "CLERK_SECRET_KEY": "",
    "CLERK_PUBLISHABLE_KEY": "",
    "CLERK_FRONTEND_API_URL": "",
    "CLERK_SIGN_IN_URL": "",
    "CLERK_SIGN_UP_URL": "",
    "CLERK_SIGN_OUT_URL": "",
    "CLERK_USER_PROFILE_URL": "",
    "CLERK_API_URL": "https://api.clerk.com/v1",
    # Mail
    "MAILER": "log",  # smtp | log | capture
    "MAIL_FROM": "Coauthored <no-reply@coauthored.pub>",
    "SMTP_HOST": "",
    "SMTP_PORT": 587,
    "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "",
    "SMTP_STARTTLS": True,
    # Cookies
    "SESSION_COOKIE_SECURE": True,
}

_BOOLS = {"TESTING", "DEV_AUTH", "SMTP_STARTTLS", "SESSION_COOKIE_SECURE"}
_INTS = {"PDF_MAX_BYTES", "SUBMISSIONS_PER_DAY", "MAX_CROSS_LISTS", "SMTP_PORT"}
_LISTS = {"CLERK_AUTHORIZED_PARTIES"}


def load_config(environ: Mapping[str, str] | None = None,
                overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Defaults, then the environment, then ``overrides`` (used by tests)."""
    environ = os.environ if environ is None else environ
    conf: dict[str, Any] = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in environ:
            conf[key] = environ[key]
    conf.update(overrides or {})
    for key in _BOOLS:
        conf[key] = _bool(conf[key])
    for key in _INTS:
        conf[key] = int(conf[key])
    for key in _LISTS:
        conf[key] = _list(conf[key])
    if is_dev_or_test(conf):
        # Local http:// development needs non-secure cookies; tests use the test client.
        if "SESSION_COOKIE_SECURE" not in environ and "SESSION_COOKIE_SECURE" not in (overrides or {}):
            conf["SESSION_COOKIE_SECURE"] = False
    conf.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Room for the PDF plus the form fields; larger bodies get a 413 before parsing.
        MAX_CONTENT_LENGTH=conf["PDF_MAX_BYTES"] + MB,
        WTF_CSRF_TIME_LIMIT=None if conf["TESTING"] else 3600 * 8,
    )
    return conf


def is_dev_or_test(conf: Mapping[str, Any]) -> bool:
    return bool(conf.get("TESTING")) or conf.get("FLASK_ENV") == "development"


def check_config(conf: Mapping[str, Any]) -> None:
    """Raise ConfigError for any unsafe setting. Fails closed."""
    dev = is_dev_or_test(conf)
    if conf.get("DEV_AUTH") and not dev:
        raise ConfigError(
            "DEV_AUTH trusts a request header and is refused unless TESTING is set or "
            "FLASK_ENV=development. Configure Clerk for production.")
    if not conf.get("DEV_AUTH"):
        missing = [k for k in ("CLERK_JWKS_URL", "CLERK_ISSUER") if not conf.get(k)]
        if missing:
            raise ConfigError(f"Clerk authentication needs {', '.join(missing)}.")
    if not dev:
        if not conf.get("SECRET_KEY") or conf.get("SECRET_KEY") == DEFAULT_SECRET:
            raise ConfigError("Set SECRET_KEY to a long random value in production.")
        if not conf.get("SESSION_COOKIE_SECURE"):
            raise ConfigError("SESSION_COOKIE_SECURE must be on in production.")
        if conf.get("MAILER") == "capture":
            raise ConfigError("MAILER=capture is for tests only.")
    if conf.get("MAILER") == "smtp" and not conf.get("SMTP_HOST"):
        raise ConfigError("MAILER=smtp needs SMTP_HOST.")
    if conf.get("MAILER") not in {"smtp", "log", "capture"}:
        raise ConfigError("MAILER must be smtp, log or capture.")
    if not 0 < int(conf.get("PDF_MAX_BYTES", 0)) <= PDF_MAX_BYTES_LIMIT:
        raise ConfigError(f"PDF_MAX_BYTES must be between 1 and {PDF_MAX_BYTES_LIMIT}.")
