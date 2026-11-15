"""Shared test data and HTTP helpers."""
import io
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from submit.models import Account, Submission
from submit.submissions.pdf import CheckedPdf, check_pdf
from submit.submissions.schema import SubmissionIn

CC_BY = "http://creativecommons.org/licenses/by/4.0/"


def pdf_bytes(tag: str = "v1") -> bytes:
    return (b"%PDF-1.4\n% coauthored test " + tag.encode() +
            b"\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n")


def checked_pdf(tag: str = "v1") -> CheckedPdf:
    return check_pdf(io.BytesIO(pdf_bytes(tag)), 50 * 1024 * 1024)


def author_dicts() -> list[dict[str, Any]]:
    return [
        {"kind": "human", "display_name": "Ada Lovelace", "contribution": "Conceived and wrote the paper.",
         "orcid": "0000-0002-1825-0097", "is_responsible": True, "is_submitter": True},
        {"kind": "ai", "display_name": "Claude", "contribution": "Drafted the proofs in section 3.",
         "ai_system": "Claude", "ai_version": "Opus 5.5 (claude-opus-5-5)", "ai_provider": "Anthropic"},
    ]


def submission_dict(**overrides: Any) -> dict[str, Any]:
    data = {
        "title": "On cooperative games between humans and machines",
        "abstract": "We study cooperative games in which some players are AI systems.",
        "comments": "10 pages",
        "primary_category": "cs.GT",
        "cross_lists": ["math.CO"],
        "license": CC_BY,
        "authors": author_dicts(),
        "declarations": {"responsibility": True, "ai_accurate": True, "coauthors_agreed": True,
                         "license_right": True},
    }
    data.update(overrides)
    return data


def submission_in(**overrides: Any) -> SubmissionIn:
    return SubmissionIn.model_validate(submission_dict(**overrides), context={"max_cross_lists": 4})


def make_account(session, email: str = "ada@example.org", name: str = "Ada Lovelace",
                 moderator: bool = False, banned: bool = False) -> Account:
    account = Account(clerk_user_id=f"dev:{email}", email=email, display_name=name,
                      is_moderator=moderator, is_banned=banned, created_at=datetime(2026, 11, 1))
    session.add(account)
    session.commit()
    return account


def form_fields(**overrides: Any) -> dict[str, Any]:
    """The HTML form for a valid submission (one human submitter, one AI author)."""
    fields: dict[str, Any] = {
        "title": "On cooperative games between humans and machines",
        "abstract": "We study cooperative games in which some players are AI systems.",
        "comments": "10 pages",
        "primary_category": "cs.GT",
        "cross_lists": ["math.CO"],
        "license": CC_BY,
        "author_rows": "3",
        "author-1-display_name": "Ada Lovelace", "author-1-kind": "human",
        "author-1-contribution": "Conceived and wrote the paper.",
        "author-1-orcid": "0000-0002-1825-0097", "author-1-is_responsible": "on",
        "submitter": "1",
        "author-2-display_name": "Claude", "author-2-kind": "ai",
        "author-2-contribution": "Drafted the proofs in section 3.",
        "author-2-ai_system": "Claude", "author-2-ai_version": "Opus 5.5 (claude-opus-5-5)",
        "author-2-ai_provider": "Anthropic",
        "author-3-display_name": "", "author-3-kind": "human", "author-3-contribution": "",
        "declare_responsibility": "on", "declare_ai_accurate": "on",
        "declare_coauthors_agreed": "on", "declare_license_right": "on",
        "op": "submit",
    }
    fields.update(overrides)
    return {k: v for k, v in fields.items() if v is not None}


def as_user(client, email: Optional[str]) -> None:
    if email is None:
        client.environ_base.pop("HTTP_X_DEV_USER_EMAIL", None)
    else:
        client.environ_base["HTTP_X_DEV_USER_EMAIL"] = email


def csrf_token(client, url: str) -> str:
    page = client.get(url).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match, f"no CSRF token on {url}"
    return match.group(1)


def post_form(client, url: str, fields: dict[str, Any], pdf: Optional[bytes] = None,
              token_from: Optional[str] = None):
    data = dict(fields)
    data["csrf_token"] = csrf_token(client, token_from or url)
    if pdf is not None:
        data["pdf"] = (io.BytesIO(pdf), "paper.pdf", "application/pdf")
    return client.post(url, data=data, content_type="multipart/form-data")


def latest_submission(session) -> Submission:
    session.expire_all()
    return session.scalars(select(Submission).order_by(Submission.id.desc())).first()
