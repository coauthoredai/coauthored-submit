"""DEV_AUTH: trust a fixed header (or a cookie set by the dev sign-in form).

Only for tests and local development. `submit.config.check_config` refuses to start the
app with DEV_AUTH unless TESTING is set or FLASK_ENV=development, and this class checks
again when it is built, so it cannot be switched on in production by accident.
"""
from typing import Any, Mapping, Optional

from flask import Request

from ..config import is_dev_or_test
from .identity import Identity

HEADER = "X-Dev-User-Email"
NAME_HEADER = "X-Dev-User-Name"
COOKIE = "dev_user_email"


class DevAuthenticator:
    def __init__(self, conf: Mapping[str, Any]):
        if not is_dev_or_test(conf):
            raise RuntimeError("DevAuthenticator refused: not a test or development config")

    def identify(self, request: Request) -> Optional[Identity]:
        email = (request.headers.get(HEADER) or request.cookies.get(COOKIE) or "").strip().lower()
        if not email or "@" not in email:
            return None
        name = request.headers.get(NAME_HEADER) or email.split("@")[0]
        return Identity(user_id=f"dev:{email}", email=email, display_name=name)

    def fetch_profile(self, user_id: str) -> tuple[Optional[str], Optional[str]]:
        return None, None
