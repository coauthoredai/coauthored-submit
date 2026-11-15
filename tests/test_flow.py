"""End to end through the Flask test client: submit -> screen -> announce."""
from arxiv.db.models import Metadata
from sqlalchemy import select

from submit.models import Account, Contributor, Submission
from submit.screening.service import CHECKLIST
from tests.helpers import as_user, form_fields, latest_submission, make_account, pdf_bytes, post_form

CHECKS = {f"check_{k}": "on" for k in CHECKLIST}


def accept_as_moderator(client, sub_id):
    as_user(client, "mod@example.org")
    resp = post_form(client, f"/moderation/{sub_id}", {"action": "accept", **CHECKS})
    assert resp.status_code == 302, resp.get_data(as_text=True)


def test_submit_accept_announce(app, client, session, store, mail):
    make_account(session, "mod@example.org", "Mo", moderator=True)
    as_user(client, "ada@example.org")
    page = client.get("/submit")
    assert page.status_code == 200 and b"New submission" in page.data
    resp = post_form(client, "/submit", form_fields(), pdf=pdf_bytes("flow"))
    assert resp.status_code == 302, resp.get_data(as_text=True)
    sub = latest_submission(session)
    assert resp.headers["Location"].endswith(f"/submissions/{sub.id}")
    assert (sub.status, sub.kind, sub.account.email) == ("submitted", "new", "ada@example.org")
    assert [c.display_name for c in sub.contributors] == ["Ada Lovelace", "Claude"]  # blank row 3 skipped
    assert store.obj(sub.pdf_key).open("rb").read() == pdf_bytes("flow")
    assert client.get(f"/submissions/{sub.id}").status_code == 200
    assert client.get("/account").status_code == 200

    accept_as_moderator(client, sub.id)
    result = app.test_cli_runner().invoke(args=["announce", "--now", "2026-11-16T20:00:00Z"])
    assert result.exit_code == 0, result.output
    assert "coauthored:2611.00001v1" in result.output

    session.expire_all()
    sub = session.get(Submission, sub.id)
    assert (sub.status, sub.paper_id, sub.version) == ("announced", "2611.00001", 1)
    meta = session.scalars(select(Metadata)).one()
    assert (meta.paper_id, meta.is_current, meta.abs_categories) == ("2611.00001", 1, "cs.GT math.CO")
    assert session.scalars(select(Contributor.kind).order_by(Contributor.position)).all() == ["human", "ai"]
    assert store.obj("ftp/arxiv/papers/2611/2611.00001.pdf").open("rb").read() == pdf_bytes("flow")
    assert [m.subject.split(":")[0] for m in mail.outbox] == ["Received", "Accepted", "Announced"]
    assert "https://coauthored.test/abs/2611.00001" in mail.outbox[-1].body

    # The submitter can now replace it through the web form, starting from v1's details.
    as_user(client, "ada@example.org")
    form = client.get("/papers/2611.00001/replace")
    assert form.status_code == 200 and b"Ada Lovelace" in form.data
    resp = post_form(client, "/papers/2611.00001/replace",
                     form_fields(title="Revised title", comments="v2: fixed a typo"), pdf=pdf_bytes("v2"))
    assert resp.status_code == 302, resp.get_data(as_text=True)
    repl = latest_submission(session)
    assert (repl.kind, repl.paper_id, repl.version) == ("replacement", "2611.00001", None)
    accept_as_moderator(client, repl.id)
    assert app.test_cli_runner().invoke(args=["announce", "--now", "2026-11-17T20:00:00"]).exit_code == 0
    session.expire_all()
    assert [(m.version, m.is_current) for m in session.scalars(
        select(Metadata).order_by(Metadata.version))] == [(1, 0), (2, 1)]
    assert store.obj("orig/arxiv/papers/2611/2611.00001v1.pdf").open("rb").read() == pdf_bytes("flow")

    # Someone else cannot replace or withdraw it.
    as_user(client, "eve@example.org")
    assert client.get("/papers/2611.00001/replace").status_code == 404
    assert client.get("/papers/2611.00001/withdraw").status_code == 404


def test_changes_requested_then_edit_and_resubmit(client, session, mail):
    make_account(session, "mod@example.org", "Mo", moderator=True)
    as_user(client, "ada@example.org")
    post_form(client, "/submit", form_fields(), pdf=pdf_bytes())
    sub = latest_submission(session)
    assert client.get(f"/submissions/{sub.id}/edit").status_code == 404  # not editable yet

    as_user(client, "mod@example.org")
    resp = post_form(client, f"/moderation/{sub.id}", {"action": "request_changes",
                                                    "reason": "State the model version precisely."})
    assert resp.status_code == 302
    assert mail.outbox[-1].subject.startswith("Changes requested")
    assert "State the model version precisely." in mail.outbox[-1].body

    as_user(client, "ada@example.org")
    detail = client.get(f"/submissions/{sub.id}").get_data(as_text=True)
    assert "State the model version precisely." in detail
    edit = client.get(f"/submissions/{sub.id}/edit")
    assert edit.status_code == 200
    resp = post_form(client, f"/submissions/{sub.id}/edit",
                     form_fields(**{"author-2-ai_version": "Opus 5.5 (claude-opus-5-5), 2026-11"}))
    assert resp.status_code == 302, resp.get_data(as_text=True)  # no new PDF: the old one is kept
    session.expire_all()
    sub = session.get(Submission, sub.id)
    assert sub.status == "submitted" and sub.pdf_key
    assert sub.contributors[1].ai_version == "Opus 5.5 (claude-opus-5-5), 2026-11"


def test_form_errors_are_shown_and_tied_to_fields(client, session):
    as_user(client, "ada@example.org")
    fields = form_fields(**{"author-1-kind": "ai", "author-1-is_responsible": None, "submitter": None,
                            "author-1-ai_system": "X", "author-1-ai_version": "1",
                            "author-1-ai_provider": "Y"})
    resp = post_form(client, "/submit", fields, pdf=pdf_bytes())
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert "AI-only author lists are not accepted" in html
    assert 'role="alert"' in html and 'aria-describedby="authors-hint authors-error"' in html
    assert session.scalars(select(Submission)).all() == []

    resp = post_form(client, "/submit", form_fields(title=""), pdf=b"<html>not a pdf</html>")
    html = resp.get_data(as_text=True)
    assert 'id="title-error"' in html and 'aria-invalid="true"' in html
    assert "not a PDF" in html


def test_pdf_size_limit(config, store, mail):
    from submit import create_app
    app = create_app({**config, "PDF_MAX_BYTES": 1024}, store=store, mail=mail)
    client = app.test_client()
    as_user(client, "ada@example.org")
    resp = post_form(client, "/submit", form_fields(), pdf=b"%PDF-1.4\n" + b"0" * 4096)
    assert resp.status_code == 400 and "larger than" in resp.get_data(as_text=True)


def test_rate_limit(client, session):
    as_user(client, "ada@example.org")
    for _ in range(5):
        assert post_form(client, "/submit", form_fields(), pdf=pdf_bytes()).status_code == 302
    resp = post_form(client, "/submit", form_fields(), pdf=pdf_bytes())
    assert resp.status_code == 429 and "24 hours" in resp.get_data(as_text=True)
    assert len(session.scalars(select(Submission)).all()) == 5


def test_add_author_row_keeps_input(client):
    as_user(client, "ada@example.org")
    resp = post_form(client, "/submit", form_fields(op="add_author"))
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'value="Ada Lovelace"' in html and 'id="author-3-display_name"' in html


def test_cancel_and_privacy_of_submissions(client, session):
    as_user(client, "ada@example.org")
    post_form(client, "/submit", form_fields(), pdf=pdf_bytes())
    sub = latest_submission(session)
    as_user(client, "eve@example.org")
    assert client.get(f"/submissions/{sub.id}").status_code == 404
    assert client.get(f"/submissions/{sub.id}/pdf").status_code == 404
    as_user(client, "ada@example.org")
    assert client.get(f"/submissions/{sub.id}/pdf").data == pdf_bytes()
    resp = post_form(client, f"/submissions/{sub.id}/cancel", {}, token_from=f"/submissions/{sub.id}")
    assert resp.status_code == 302
    session.expire_all()
    assert session.get(Submission, sub.id).status == "cancelled"


def test_account_created_on_first_sight(client, session):
    as_user(client, "New.Person@Example.org")
    assert client.get("/account").status_code == 200
    account = session.scalars(select(Account)).one()
    assert account.email == "new.person@example.org" and account.clerk_user_id.startswith("dev:")


def test_paths_browse_links_to_exist(client, session):
    """Browse's header links to these paths on the submit host."""
    for path in ("/submit", "/sign-in", "/sign-up", "/sign-out", "/account", "/moderation"):
        assert client.get(path).status_code in (200, 302), path
    as_user(client, "ada@example.org")
    assert client.get("/submit").status_code == 200
    assert client.get("/account").status_code == 200
    assert client.get("/sign-in").status_code == 200  # DEV_AUTH: the local sign-in form


def test_withdrawal_through_the_web(app, client, session, store):
    make_account(session, "mod@example.org", "Mo", moderator=True)
    as_user(client, "ada@example.org")
    post_form(client, "/submit", form_fields(), pdf=pdf_bytes())
    accept_as_moderator(client, latest_submission(session).id)
    app.test_cli_runner().invoke(args=["announce", "--now", "2026-11-16T20:00:00"])
    as_user(client, "ada@example.org")
    account = client.get("/account").get_data(as_text=True)
    assert 'href="https://coauthored.test/abs/2611.00001"' in account
    resp = post_form(client, "/papers/2611.00001/withdraw", {"reason": ""})
    assert resp.status_code == 400 and 'id="reason-error"' in resp.get_data(as_text=True)
    resp = post_form(client, "/papers/2611.00001/withdraw",
                     {"reason": "Superseded by a corrected paper.", "authorized": "on"})
    assert resp.status_code == 302
    w = latest_submission(session)
    assert (w.kind, w.paper_id, w.pdf_key) == ("withdrawal", "2611.00001", None)
    accept_as_moderator(client, w.id)
    app.test_cli_runner().invoke(args=["announce", "--now", "2026-11-17T20:00:00"])
    session.expire_all()
    v2 = session.scalars(select(Metadata).where(Metadata.version == 2)).one()
    assert v2.is_withdrawn == 1 and v2.is_current == 1
    assert not store.exists("ftp/arxiv/papers/2611/2611.00001.pdf")
