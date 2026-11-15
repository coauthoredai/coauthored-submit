"""Moderator authorization on every moderator route and action."""
from datetime import datetime

import pytest
from sqlalchemy import select

from submit.models import Account, ModerationLog, Submission
from submit.screening.service import CHECKLIST, NotAllowed, decide
from submit.submissions import service
from tests.helpers import as_user, checked_pdf, csrf_token, make_account, post_form, submission_in

NOW = datetime(2026, 11, 15, 12, 0)
CHECKS = {f"check_{k}": "on" for k in CHECKLIST}


@pytest.fixture
def sub(session, store):
    author = make_account(session, "ada@example.org")
    make_account(session, "mod@example.org", "Mo", moderator=True)
    make_account(session, "user@example.org", "Uma")
    make_account(session, "exmod@example.org", "Ex", moderator=True, banned=True)
    s = service.create_submission(session, store, author, submission_in(), checked_pdf(), NOW, 5)
    session.commit()
    return s


def routes(sub_id):
    return [("GET", "/moderation"), ("GET", f"/moderation/{sub_id}"), ("POST", f"/moderation/{sub_id}"),
            ("GET", f"/moderation/{sub_id}/pdf")]


@pytest.mark.parametrize("email", ["user@example.org", "ada@example.org", "exmod@example.org"])
def test_non_moderators_are_refused_everywhere(client, sub, email, session):
    as_user(client, email)
    for method, url in routes(sub.id):
        if method == "GET":
            assert client.get(url).status_code == 403, url
        else:
            # With a valid CSRF token, so the refusal comes from the moderator check.
            data = {"action": "accept", "csrf_token": csrf_token(client, "/"), **CHECKS}
            assert client.post(url, data=data).status_code == 403, url
    session.expire_all()
    assert session.get(Submission, sub.id).status == "submitted"
    assert session.scalars(select(ModerationLog)).all() == []


def test_anonymous_cannot_reach_moderation(client, sub):
    for method, url in routes(sub.id):
        resp = client.get(url) if method == "GET" else client.post(url, data={"action": "accept"})
        assert resp.status_code in (302, 400, 401), url
        if method == "GET":
            assert resp.headers["Location"].startswith("/sign-in")


def test_moderator_can_screen(client, sub, session, mail):
    as_user(client, "mod@example.org")
    assert client.get("/moderation").status_code == 200
    page = client.get(f"/moderation/{sub.id}")
    assert page.status_code == 200 and b"Screening checklist" in page.data
    assert client.get(f"/moderation/{sub.id}/pdf").data.startswith(b"%PDF-")

    # Reject needs a reason; accept needs the whole checklist.
    resp = post_form(client, f"/moderation/{sub.id}", {"action": "reject", "reason": ""})
    assert resp.status_code == 400 and b"A reason is required" in resp.data
    resp = post_form(client, f"/moderation/{sub.id}", {"action": "accept", "check_scholarly": "on"})
    assert resp.status_code == 400 and b"Tick every checklist item" in resp.data

    resp = post_form(client, f"/moderation/{sub.id}", {"action": "accept", **CHECKS})
    assert resp.status_code == 302
    session.expire_all()
    assert session.get(Submission, sub.id).status == "accepted"
    log = session.scalars(select(ModerationLog)).one()
    mod = session.scalars(select(Account).where(Account.email == "mod@example.org")).one()
    assert log.moderator_account_id == mod.id and log.to_status == "accepted"
    assert [m.subject for m in mail.outbox] == [f"Accepted: {sub.title}"]
    assert mail.outbox[0].to == "ada@example.org"


def test_moderation_post_without_csrf_token_is_refused(client, sub, session):
    as_user(client, "mod@example.org")
    resp = client.post(f"/moderation/{sub.id}", data={"action": "accept", **CHECKS})
    assert resp.status_code == 400 and b"Form expired" in resp.data
    session.expire_all()
    assert session.get(Submission, sub.id).status == "submitted"


def test_moderators_cannot_screen_their_own_submission(session, store):
    mod = make_account(session, "mod@example.org", moderator=True)
    own = service.create_submission(session, store, mod, submission_in(), checked_pdf(), NOW, 5)
    session.commit()
    with pytest.raises(NotAllowed):
        decide(session, mod, own, "accept", None, set(CHECKLIST), NOW)


def test_decide_checks_moderator_itself(session, sub):
    user = session.scalars(select(Account).where(Account.email == "user@example.org")).one()
    with pytest.raises(NotAllowed):
        decide(session, user, sub, "accept", None, set(CHECKLIST), NOW)


def test_set_moderator_cli(app, session):
    make_account(session, "Grace@Example.org", "Grace")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["set-moderator", "grace@example.org", "--on"])
    assert result.exit_code == 0, result.output
    session.expire_all()
    assert session.scalars(select(Account.is_moderator).where(Account.display_name == "Grace")).one()
    result = runner.invoke(args=["set-moderator", "grace@example.org", "--off"])
    session.expire_all()
    assert not session.scalars(select(Account.is_moderator).where(Account.display_name == "Grace")).one()
    assert runner.invoke(args=["set-moderator", "nobody@example.org"]).exit_code != 0
