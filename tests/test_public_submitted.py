"""The public "Submitted" list: unscreened papers, separate and clearly marked."""
from submit.screening.service import CHECKLIST
from tests.helpers import as_user, form_fields, latest_submission, make_account, pdf_bytes, post_form


def _submit(client, session, email="ada@example.org", title="An unscreened paper"):
    as_user(client, email)
    assert post_form(client, "/submit", form_fields(title=title), pdf=pdf_bytes(title)).status_code == 302
    return latest_submission(session)


def test_submitted_paper_is_listed_publicly_and_marked(client, session):
    sub = _submit(client, session)
    as_user(client, None)  # anonymous visitor
    page = client.get("/submitted")
    assert page.status_code == 200 and page.headers["X-Robots-Tag"] == "noindex"
    text = page.get_data(as_text=True)
    assert "An unscreened paper" in text and "not yet screened" in text
    assert "ada@example.org" not in text
    detail = client.get(f"/submitted/{sub.id}").get_data(as_text=True)
    assert "Submitted, not yet screened" in detail and "Drafted the proofs in section 3." in detail
    assert "ada@example.org" not in detail
    pdf = client.get(f"/submitted/{sub.id}/pdf")
    assert pdf.status_code == 200 and pdf.data == pdf_bytes("An unscreened paper")


def test_hold_hides_and_announce_redirects(app, client, session):
    make_account(session, "mod@example.org", "Mo", moderator=True)
    held = _submit(client, session, title="Held paper")
    kept = _submit(client, session, title="Kept paper")
    as_user(client, "mod@example.org")
    assert post_form(client, f"/moderation/{held.id}", {"action": "hold", "reason": "Checking"}).status_code == 302
    as_user(client, None)
    listing = client.get("/submitted").get_data(as_text=True)
    assert "Held paper" not in listing and "Kept paper" in listing
    assert client.get(f"/submitted/{held.id}").status_code == 404
    assert client.get(f"/submitted/{held.id}/pdf").status_code == 404

    as_user(client, "mod@example.org")
    checks = {f"check_{k}": "on" for k in CHECKLIST}
    assert post_form(client, f"/moderation/{kept.id}", {"action": "accept", **checks}).status_code == 302
    as_user(client, None)
    assert "Accepted." in client.get(f"/submitted/{kept.id}").get_data(as_text=True)
    assert app.test_cli_runner().invoke(args=["announce", "--now", "2026-11-16T20:00:00Z"]).exit_code == 0
    resp = client.get(f"/submitted/{kept.id}")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/abs/2611.00001v1")
    assert "Kept paper" not in client.get("/submitted").get_data(as_text=True)


def test_moderators_still_cannot_screen_their_own_submission(client, session):
    make_account(session, "solo@example.org", "Solo", moderator=True)
    sub = _submit(client, session, email="solo@example.org", title="Own paper")
    checks = {f"check_{k}": "on" for k in CHECKLIST}
    resp = post_form(client, f"/moderation/{sub.id}", {"action": "accept", "reason": "x", **checks},
                     token_from=f"/moderation/{sub.id}")
    assert resp.status_code == 403
