"""Creating and changing submissions. Callers commit; nothing here sends mail.

Rules enforced here (validation of the content itself is in schema.py):
- at most SUBMISSIONS_PER_DAY submissions (of any kind) per account per rolling 24 hours;
- replacements and withdrawals only for papers this account submitted, and only one
  pending replacement or withdrawal per paper at a time;
- a submission can be edited only while changes are requested.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, Contributor, Submission, SubmissionContributor
from ..screening.state import ANNOUNCED, CHANGES_REQUESTED, PENDING, SUBMITTED
from ..screening.transitions import apply_transition
from ..storage import Store
from .pdf import CheckedPdf, staging_key
from .schema import SubmissionIn, WithdrawalIn


class SubmissionRefused(Exception):
    """The account may not do this (rate limit, ownership, wrong state)."""


@dataclass
class Paper:
    paper_id: str
    version: int
    title: str
    is_withdrawn: bool
    pending: Optional[Submission]


def submissions_today(session: Session, account: Account, now: datetime) -> int:
    return session.scalar(select(func.count(Submission.id)).where(
        Submission.account_id == account.id,
        Submission.created_at > now - timedelta(days=1))) or 0


def check_rate_limit(session: Session, account: Account, now: datetime, per_day: int) -> None:
    if submissions_today(session, account, now) >= per_day:
        raise SubmissionRefused(
            f"You have made {per_day} submissions in the last 24 hours, the most we accept. "
            "Please try again tomorrow.")


def _contributors(data: SubmissionIn) -> list[SubmissionContributor]:
    return [SubmissionContributor(
        position=i, display_name=a.display_name, kind=a.kind, orcid=a.orcid,
        ai_system=a.ai_system, ai_version=a.ai_version, ai_provider=a.ai_provider,
        contribution=a.contribution, is_responsible=a.is_responsible,
        is_submitter=a.is_submitter) for i, a in enumerate(data.authors, start=1)]


def _apply(sub: Submission, data: SubmissionIn) -> None:
    sub.title = data.title  # type: ignore[assignment]
    sub.abstract = data.abstract  # type: ignore[assignment]
    sub.comments = data.comments
    sub.primary_category = data.primary_category  # type: ignore[assignment]
    sub.cross_categories = " ".join(data.cross_lists)
    sub.license = data.license
    sub.contributors = _contributors(data)


def _stage(session: Session, store: Store, sub: Submission, pdf: CheckedPdf) -> None:
    session.flush()  # assigns sub.id
    key = staging_key(sub.id, pdf.sha256)
    store.put(key, pdf.file)
    sub.pdf_key, sub.pdf_sha256, sub.pdf_size = key, pdf.sha256, pdf.size


def create_submission(session: Session, store: Store, account: Account, data: SubmissionIn,
                      pdf: CheckedPdf, now: datetime, per_day: int,
                      replaces: Optional[str] = None) -> Submission:
    """A new paper, or with `replaces` a new version of that paper."""
    check_rate_limit(session, account, now, per_day)
    if replaces:
        paper = owned_paper(session, account, replaces)
        if paper.pending:
            raise SubmissionRefused("This paper already has a replacement or withdrawal pending.")
    sub = Submission(account_id=account.id, kind="replacement" if replaces else "new",
                     status=SUBMITTED, paper_id=replaces, declarations_at=now,
                     created_at=now, updated_at=now)
    _apply(sub, data)
    session.add(sub)
    _stage(session, store, sub, pdf)
    session.flush()
    return sub


def create_withdrawal(session: Session, account: Account, paper_id: str, data: WithdrawalIn,
                      now: datetime, per_day: int) -> Submission:
    check_rate_limit(session, account, now, per_day)
    paper = owned_paper(session, account, paper_id)
    if paper.pending:
        raise SubmissionRefused("This paper already has a replacement or withdrawal pending.")
    if paper.is_withdrawn:
        raise SubmissionRefused("This paper is already withdrawn.")
    latest = latest_announced(session, paper_id)
    sub = Submission(account_id=account.id, kind="withdrawal", status=SUBMITTED,
                     paper_id=paper_id, title=latest.title, abstract=latest.abstract,
                     comments=None, primary_category=latest.primary_category,
                     cross_categories=latest.cross_categories, license=latest.license,
                     withdrawal_reason=data.reason, declarations_at=now, created_at=now,
                     updated_at=now)
    sub.contributors = [SubmissionContributor(
        position=c.position, display_name=c.display_name, kind=c.kind, orcid=c.orcid,
        ai_system=c.ai_system, ai_version=c.ai_version, ai_provider=c.ai_provider,
        contribution=c.contribution, is_responsible=c.is_responsible,
        is_submitter=c.is_submitter) for c in latest.contributors]
    session.add(sub)
    session.flush()
    return sub


def update_and_resubmit(session: Session, store: Store, sub: Submission, data: SubmissionIn,
                        pdf: Optional[CheckedPdf], now: datetime) -> Submission:
    """Edit a submission whose changes were requested, then put it back in the queue."""
    if sub.status != CHANGES_REQUESTED or sub.kind == "withdrawal":
        raise SubmissionRefused("This submission cannot be edited now.")
    _apply(sub, data)
    sub.declarations_at = now
    if pdf is not None:
        _stage(session, store, sub, pdf)
    session.flush()
    apply_transition(session, sub, "resubmit", "submitter", now)
    return sub


def cancel(session: Session, sub: Submission, now: datetime) -> None:
    apply_transition(session, sub, "cancel", "submitter", now)


def latest_announced(session: Session, paper_id: str) -> Submission:
    sub = session.scalar(select(Submission).where(
        Submission.paper_id == paper_id, Submission.status == ANNOUNCED,
        Submission.kind != "withdrawal").order_by(Submission.version.desc()).limit(1))
    if sub is None:
        raise SubmissionRefused("No such paper.")
    return sub


def owned_paper(session: Session, account: Account, paper_id: str) -> Paper:
    for paper in owned_papers(session, account):
        if paper.paper_id == paper_id:
            return paper
    raise SubmissionRefused("You can only replace or withdraw papers you submitted.")


def owned_papers(session: Session, account: Account) -> list[Paper]:
    """Papers first submitted (v1) by this account, with their latest announced version."""
    firsts = session.scalars(select(Submission.paper_id).where(
        Submission.account_id == account.id, Submission.kind == "new",
        Submission.status == ANNOUNCED)).all()
    papers = []
    for paper_id in firsts:
        latest = session.scalar(select(Submission).where(
            Submission.paper_id == paper_id, Submission.status == ANNOUNCED)
            .order_by(Submission.version.desc()).limit(1))
        pending = session.scalar(select(Submission).where(
            Submission.paper_id == paper_id, Submission.status.in_(PENDING)).limit(1))
        papers.append(Paper(paper_id=paper_id, version=latest.version or 1, title=latest.title,
                            is_withdrawn=latest.kind == "withdrawal", pending=pending))
    return sorted(papers, key=lambda p: p.paper_id, reverse=True)


def published_contributors(session: Session, paper_id: str, version: int) -> list[Contributor]:
    return list(session.scalars(select(Contributor).where(
        Contributor.paper_id == paper_id, Contributor.version == version)
        .order_by(Contributor.position)))
