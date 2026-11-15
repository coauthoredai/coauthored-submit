"""Clerk session tokens, verified with PyJWT against Clerk's JWKS.

The token comes from the `__session` cookie (set and refreshed by Clerk's browser script)
or an `Authorization: Bearer` header. Checked: RS256 signature by a key in CLERK_JWKS_URL,
`exp`/`nbf`/`iat` (5 s leeway), `iss` == CLERK_ISSUER, and `azp` in
CLERK_AUTHORIZED_PARTIES when that list is set.

Email and name come from the token when the Clerk instance adds them as custom session
claims (`email`, `name`; see README), otherwise from Clerk's Backend API with
CLERK_SECRET_KEY, fetched only when an account is first created.
"""
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Mapping, Optional

import jwt
from flask import Request

from .identity import Identity

log = logging.getLogger(__name__)


class ClerkAuthenticator:
    def __init__(self, conf: Mapping[str, Any], jwk_client: Optional[jwt.PyJWKClient] = None):
        self.issuer = conf["CLERK_ISSUER"]
        self.parties = list(conf.get("CLERK_AUTHORIZED_PARTIES") or [])
        self.secret_key = conf.get("CLERK_SECRET_KEY") or ""
        self.api_url = (conf.get("CLERK_API_URL") or "https://api.clerk.com/v1").rstrip("/")
        self.jwk_client = jwk_client or jwt.PyJWKClient(conf["CLERK_JWKS_URL"], cache_keys=True,
                                                        lifespan=3600, timeout=10)

    @staticmethod
    def token_from(request: Request) -> Optional[str]:
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip() or None
        return request.cookies.get("__session") or None

    def verify(self, token: str) -> dict[str, Any]:
        """Claims of a valid token; raises jwt.InvalidTokenError otherwise."""
        key = self.jwk_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer, leeway=5,
                            options={"require": ["exp", "iat", "iss", "sub"],
                                     "verify_aud": False})
        if self.parties and claims.get("azp") not in self.parties:
            raise jwt.InvalidTokenError("token azp is not an authorized party")
        return claims

    def identify(self, request: Request) -> Optional[Identity]:
        token = self.token_from(request)
        if not token:
            return None
        try:
            claims = self.verify(token)
        except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
            log.info("rejected Clerk token: %s", exc)
            return None
        return Identity(user_id=str(claims["sub"]), email=claims.get("email"),
                        display_name=claims.get("name"))

    def fetch_profile(self, user_id: str) -> tuple[Optional[str], Optional[str]]:
        """(primary email, full name) from Clerk's Backend API, or (None, None)."""
        if not self.secret_key:
            return None, None
        req = urllib.request.Request(f"{self.api_url}/users/{urllib.parse.quote(user_id, safe='')}",
                                     headers={"Authorization": f"Bearer {self.secret_key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - fixed https host
                user = json.load(resp)
        except Exception:  # noqa: BLE001
            log.exception("Clerk Backend API lookup failed for %s", user_id)
            return None, None
        primary = user.get("primary_email_address_id")
        email = next((e.get("email_address") for e in user.get("email_addresses", [])
                      if e.get("id") == primary), None)
        name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or None
        return email, name
