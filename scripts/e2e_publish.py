"""End-to-end, part 1 (run in coauthored-submit's environment): submit a paper through the
real web flow (DEV_AUTH, test client), accept it as a moderator, and announce it into a
SQLite database and a local object store that coauthored-browse then reads.

usage: python scripts/e2e_publish.py DB_PATH STORE_DIR PAPER.json PAPER.pdf ANNOUNCE_ISO
PAPER.json holds the form fields (see tests/helpers.py:form_fields for the names).
"""
import io
import json
import re
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from submit import create_app
from submit.db import make_engine
from submit.mailer import CapturingMailer
from submit.models import Account
from submit.screening.service import CHECKLIST
from submit.seed import create_schema, seed_reference_rows
from submit.storage import LocalStore


def token(client, url):
    page = client.get(url).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def main(db_path: str, store_dir: str, fields_json: str, pdf_path: str, when: str) -> None:
    uri = f"sqlite:///{Path(db_path).resolve()}"
    engine = make_engine(uri)
    problems = create_schema(engine)
    assert not problems, problems
    with Session(engine) as s:
        seed_reference_rows(s, "aicoauthored.dev")
        s.commit()
    store = LocalStore(store_dir)
    mail = CapturingMailer()
    app = create_app({"TESTING": True, "DEV_AUTH": True, "CLASSIC_DB_URI": uri, "MAILER": "capture",
                      "BROWSE_BASE_URL": "http://localhost:8080"}, store=store, mail=mail)
    fields = json.loads(Path(fields_json).read_text())
    submitter = fields.pop("_submitter_email")
    with Session(engine) as s:
        from datetime import datetime
        s.add(Account(clerk_user_id="dev:moderator@example.org", email="moderator@example.org",
                      display_name="Moderator", is_moderator=True, is_banned=False,
                      created_at=datetime(2026, 11, 1)))
        s.commit()
    client = app.test_client()
    client.environ_base["HTTP_X_DEV_USER_EMAIL"] = submitter
    data = dict(fields, csrf_token=token(client, "/submit"))
    data["pdf"] = (io.BytesIO(Path(pdf_path).read_bytes()), Path(pdf_path).name, "application/pdf")
    resp = client.post("/submit", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302, resp.get_data(as_text=True)[:2000]
    sub_id = resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

    client.environ_base["HTTP_X_DEV_USER_EMAIL"] = "moderator@example.org"
    checks = {f"check_{k}": "on" for k in CHECKLIST}
    url = f"/moderation/{sub_id}"
    resp = client.post(url, data={"action": "accept", "csrf_token": token(client, url), **checks})
    assert resp.status_code == 302, resp.get_data(as_text=True)[:2000]

    result = app.test_cli_runner().invoke(args=["announce", "--now", when])
    assert result.exit_code == 0, result.output
    print(result.output.strip())
    print("mail:", [m.subject for m in mail.outbox])


if __name__ == "__main__":
    main(*sys.argv[1:6])
