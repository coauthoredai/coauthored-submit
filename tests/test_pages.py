"""Rendered pages: accessible structure and honest branding."""
import re

from tests.helpers import as_user, form_fields, latest_submission, make_account, pdf_bytes, post_form


def labels_match_inputs(html: str) -> None:
    ids = set(re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', html))
    fors = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    assert fors <= ids, fors - ids
    visible = {i for i in ids if not i.startswith("csrf")}
    assert visible <= fors, visible - fors  # every field has a label


def test_form_page_is_labelled_and_branded(client):
    as_user(client, "ada@example.org")
    html = client.get("/submit").get_data(as_text=True)
    labels_match_inputs(html)
    assert "#12454d" not in html  # colours come from the stylesheet
    assert "arXiv:" not in html
    assert "not affiliated with or endorsed by arXiv" in " ".join(html.split())


def test_moderation_detail_links_the_pdf(client, session):
    make_account(session, "mod@example.org", "Mo", moderator=True)
    as_user(client, "ada@example.org")
    post_form(client, "/submit", form_fields(), pdf=pdf_bytes())
    sub = latest_submission(session)
    as_user(client, "mod@example.org")
    html = client.get(f"/moderation/{sub.id}").get_data(as_text=True)
    assert f'href="/moderation/{sub.id}/pdf"' in html
    labels_match_inputs(html)
    resp = client.get(f"/moderation/{sub.id}/pdf")
    assert resp.mimetype == "application/pdf" and "Content-Security-Policy" not in resp.headers
    assert client.get("/moderation").headers["Content-Security-Policy"].startswith("default-src 'self'")
