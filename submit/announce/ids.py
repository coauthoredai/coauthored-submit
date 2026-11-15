"""Identifier and version assignment.

New papers get `YYMM.NNNNN`: YYMM from the announce time in UTC, NNNNN counting from
00001 each month. Numbers already used by published papers (arXiv_documents) and numbers
reserved by claimed-but-unfinished announces (coauthored_submissions) are both skipped.
"""
from datetime import datetime

from arxiv.db.models import Document, Metadata
from arxiv.identifier import Identifier
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Submission

MAX_NUMBER = 99999


def yymm(when: datetime) -> str:
    return when.strftime("%y%m")


def next_paper_id(session: Session, when: datetime) -> str:
    prefix = yymm(when)
    pattern = f"{prefix}.%"
    used = [
        session.scalar(select(func.max(Document.paper_id)).where(Document.paper_id.like(pattern))),
        session.scalar(select(func.max(Submission.paper_id)).where(Submission.paper_id.like(pattern))),
    ]
    # Fixed-width numbers, so the string maximum is the numeric maximum.
    last = max((int(pid.split(".")[1]) for pid in used if pid), default=0)
    if last >= MAX_NUMBER:
        raise RuntimeError(f"identifier space for {prefix} is exhausted")
    paper_id = f"{prefix}.{last + 1:05d}"
    Identifier(paper_id)  # validates the form
    return paper_id


def next_version(session: Session, paper_id: str) -> int:
    published = session.scalar(select(func.max(Metadata.version)).where(Metadata.paper_id == paper_id))
    reserved = session.scalar(select(func.max(Submission.version)).where(Submission.paper_id == paper_id))
    if not published:
        raise RuntimeError(f"{paper_id} has no published version to replace")
    return max(published, reserved or 0) + 1
