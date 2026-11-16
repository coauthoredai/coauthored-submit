"""Authentication: fail-closed configuration, Clerk token verification, account creation."""
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from submit import create_app
from submit.auth.clerk import ClerkAuthenticator
from submit.auth.dev import DevAuthenticator
from submit.config import ConfigError, check_config, load_config
from submit.models import Account
from tests.helpers import as_user, make_account

ISSUER = "https://clerk.coauthored.test"
PARTY = "https://submit.coauthored.test"

PROD = {"FLASK_ENV": "production", "TESTING": False, "SECRET_KEY": "x" * 40,
        "CLERK_JWKS_URL": f"{ISSUER}/.well-known/jwks.json", "CLERK_ISSUER": ISSUER,
        "CLERK_AUTHORIZED_PARTIES": PARTY, "MAILER": "log"}


def test_dev_auth_refused_in_production_config():
    conf = load_config(environ={}, overrides={**PROD, "DEV_AUTH": True})
    with pytest.raises(ConfigError, match="DEV_AUTH"):
        check_config(conf)
    with pytest.raises(ConfigError, match="DEV_AUTH"):
        create_app({**PROD, "DEV_AUTH": True})
    with pytest.raises(RuntimeError):
        DevAuthenticator(conf)


def test_dev_auth_refused_by_default_environment(monkeypatch):
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("DEV_AUTH", "1")
    with pytest.raises(ConfigError, match="DEV_AUTH"):
        check_config(load_config())


def test_dev_auth_allowed_only_in_development_or_testing():
    check_config(load_config(environ={}, overrides={"DEV_AUTH": True, "FLASK_ENV": "development"}))
    check_config(load_config(environ={}, overrides={"DEV_AUTH": True, "TESTING": True}))


def test_production_needs_clerk_and_a_real_secret():
    check_config(load_config(environ={}, overrides=PROD))
    with pytest.raises(ConfigError, match="CLERK_JWKS_URL"):
        check_config(load_config(environ={}, overrides={**PROD, "CLERK_JWKS_URL": ""}))
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        check_config(load_config(environ={}, overrides={**PROD, "SECRET_KEY": "dev-only-not-secret"}))
    with pytest.raises(ConfigError, match="PDF_MAX_BYTES"):
        check_config(load_config(environ={}, overrides={**PROD, "PDF_MAX_BYTES": 60 * 1024 * 1024}))
    assert load_config(environ={}, overrides=PROD)["SESSION_COOKIE_SECURE"] is True


# ---- Clerk session tokens -------------------------------------------------------------

@pytest.fixture(scope="module")
def keys():
    good = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return good, bad


@pytest.fixture
def clerk(keys):
    jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=keys[0].public_key()))
    return ClerkAuthenticator(load_config(environ={}, overrides=PROD), jwk_client=jwks)


def token(key, **claims):
    now = int(time.time())
    body = {"sub": "user_123", "iss": ISSUER, "azp": PARTY, "iat": now, "nbf": now - 1,
            "exp": now + 60, "email": "ada@example.org", "name": "Ada Lovelace", **claims}
    return jwt.encode({k: v for k, v in body.items() if v is not None}, key, algorithm="RS256",
                      headers={"kid": "ins_1"})


def test_valid_clerk_token(clerk, keys):
    claims = clerk.verify(token(keys[0]))
    assert claims["sub"] == "user_123"


@pytest.mark.parametrize("claims", [
    {"iss": "https://evil.example"},
    {"exp": int(time.time()) - 120},
    {"azp": "https://evil.example"},
    {"azp": None},
    {"sub": None},
])
def test_invalid_clerk_tokens_are_rejected(clerk, keys, claims):
    with pytest.raises(jwt.InvalidTokenError):
        clerk.verify(token(keys[0], **claims))


def test_token_signed_by_another_key_is_rejected(clerk, keys):
    with pytest.raises(jwt.InvalidSignatureError):
        clerk.verify(token(keys[1]))


def test_hs256_token_is_rejected(clerk):
    forged = jwt.encode({"sub": "user_1", "iss": ISSUER, "azp": PARTY, "iat": int(time.time()),
                         "exp": int(time.time()) + 60}, "s" * 40, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        clerk.verify(forged)


def test_clerk_app_creates_account_on_first_sight(db_uri, store, mail, clerk, keys):
    app = create_app({**PROD, "CLASSIC_DB_URI": db_uri}, store=store, mail=mail, authenticator=clerk)
    client = app.test_client()
    anon = client.get("/account")  # no token: the session-establishing page, not the account
    assert anon.status_code == 200 and "data-sign-in=" in anon.get_data(as_text=True)
    client.set_cookie("__session", token(keys[0]))
    signed_in = client.get("/account")
    assert signed_in.status_code == 200 and "data-sign-in=" not in signed_in.get_data(as_text=True)
    client.delete_cookie("__session")
    bearer = {"Authorization": f"Bearer {token(keys[0])}"}
    assert client.get("/account", headers=bearer).status_code == 200
    with app.app_context():
        from submit.db import new_session
        with new_session() as s:
            account = s.scalars(select(Account)).one()  # one account, not two
            assert (account.clerk_user_id, account.email, account.display_name) == (
                "user_123", "ada@example.org", "Ada Lovelace")
            assert not account.is_moderator and not account.is_banned
    bad = {"Authorization": f"Bearer {token(keys[1])}"}
    resp = client.get("/account", headers=bad)  # a bad token is no session: establish or sign in
    assert resp.status_code == 200 and "data-sign-in=" in resp.get_data(as_text=True)


def test_sign_in_redirects_to_clerk_hosted_page(db_uri, store, mail, clerk):
    app = create_app({**PROD, "CLASSIC_DB_URI": db_uri,
                      "CLERK_SIGN_IN_URL": "https://accounts.coauthored.test/sign-in"},
                     store=store, mail=mail, authenticator=clerk)
    resp = app.test_client().get("/sign-in?next=/submit", base_url="https://submit.coauthored.test")
    assert resp.status_code == 302
    assert resp.headers["Location"] == ("https://accounts.coauthored.test/sign-in?redirect_url="
                                        "https%3A%2F%2Fsubmit.coauthored.test%2Fsubmit")
    evil = app.test_client().get("/sign-in?next=//evil.example/x", base_url="https://submit.coauthored.test")
    assert "evil.example" not in evil.headers["Location"]


# ---- Guards ---------------------------------------------------------------------------

def test_anonymous_visitors_are_sent_to_sign_in_under_dev_auth(client):
    resp = client.get("/submit")
    assert resp.status_code == 302 and resp.headers["Location"].startswith("/sign-in?next=/submit")
    assert client.post("/submit").status_code in (400, 401)  # CSRF or auth: never accepted


def test_banned_account_cannot_submit(client, session):
    make_account(session, "banned@example.org", banned=True)
    as_user(client, "banned@example.org")
    assert client.get("/submit").status_code == 403


def test_clerk_mode_protected_page_establishes_session_instead_of_looping(db_uri, store, mail, clerk):
    """Without a valid __session cookie, a protected page must not redirect straight to
    Clerk (Clerk would send a signed-in visitor straight back: a redirect loop). It renders
    a page that lets Clerk's script set the cookie, with sign-in as the fallback."""
    app = create_app({**PROD, "CLASSIC_DB_URI": db_uri,
                      "CLERK_PUBLISHABLE_KEY": "pk_test_Y2xlcmsuY29hdXRob3JlZC50ZXN0JA",
                      "CLERK_FRONTEND_API_URL": "https://clerk.coauthored.test",
                      "CLERK_SIGN_IN_URL": "https://accounts.coauthored.test/sign-in"},
                     store=store, mail=mail, authenticator=clerk)
    resp = app.test_client().get("/account", base_url="https://submit.coauthored.test")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    page = resp.get_data(as_text=True)
    assert 'data-sign-in="/sign-in?next=/account"' in page
    assert "clerk-establish.js" in page and 'id="clerk-js"' in page
