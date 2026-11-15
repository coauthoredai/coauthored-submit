"""The database rows written at announce, exactly as CONTRACT.md lists them.

Classic tables via arxiv-base's models: arXiv_documents (once per paper), arXiv_metadata
(one row per version), arXiv_document_category and arXiv_in_category (the latest version's
categories), arXiv_updates (one row per version and category); plus
coauthored_contributors (the author list of this version). The caller commits.
"""
import calendar
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from arxiv.db.models import Document, DocumentCategory, Metadata, Updates, t_arXiv_in_category
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from ..models import Contributor, Submission
from ..taxonomy import split_category

WITHDRAWN_COMMENT = "This paper has been withdrawn by its submitter. Reason: {reason}"


def unix(when: datetime) -> int:
    """Unix time of a naive UTC datetime."""
    return calendar.timegm(when.utctimetuple())


def authors_string(names: list[str]) -> str:
    return ", ".join(names)


@dataclass(frozen=True)
class VersionData:
    """What goes into one version's rows; for a withdrawal, copied from the previous version."""
    title: str
    abstract: str
    comments: Optional[str]
    categories: list[str]       # primary first
    license: str
    contributors: list[dict]
    source_size: int
    source_format: str
    is_withdrawn: int


def version_data(session: Session, sub: Submission, prev: Optional[Metadata]) -> VersionData:
    if sub.kind != "withdrawal":
        return VersionData(
            title=sub.title, abstract=sub.abstract, comments=sub.comments or None,
            categories=sub.categories, license=sub.license,
            contributors=[_contributor_dict(c) for c in sub.contributors],
            source_size=sub.pdf_size or 0, source_format="pdf", is_withdrawn=0)
    assert prev is not None, "a withdrawal needs a published version"
    rows = session.scalars(select(Contributor).where(
        Contributor.paper_id == prev.paper_id, Contributor.version == prev.version)
        .order_by(Contributor.position)).all()
    return VersionData(
        title=prev.title or sub.title, abstract=prev.abstract or sub.abstract,
        comments=WITHDRAWN_COMMENT.format(reason=sub.withdrawal_reason),
        categories=(prev.abs_categories or sub.primary_category).split(), license=prev.license
        or sub.license, contributors=[_contributor_dict(c) for c in rows]
        or [_contributor_dict(c) for c in sub.contributors],
        source_size=0, source_format="withdrawn", is_withdrawn=1)


def _contributor_dict(c: object) -> dict:
    keys = ("position", "display_name", "kind", "orcid", "ai_system", "ai_version",
            "ai_provider", "contribution", "is_responsible")
    return {k: getattr(c, k) for k in keys}


def write_rows(session: Session, sub: Submission, data: VersionData, when: datetime) -> Document:
    paper_id, version = sub.paper_id, sub.version
    assert paper_id and version
    authors = authors_string([c["display_name"] for c in data.contributors])
    primary = data.categories[0]
    submitter_name = (sub.account.display_name or sub.account.email)[:64]
    submitter_email = sub.account.email[:64]

    if version == 1:
        doc = Document(paper_id=paper_id, title=data.title, authors=authors,
                       submitter_email=submitter_email, submitter_id=None,
                       dated=unix(sub.created_at), primary_subject_class=primary, created=when)
        session.add(doc)
        session.flush()
    else:
        doc = session.scalars(select(Document).where(Document.paper_id == paper_id)).one()
        if not data.is_withdrawn:
            doc.title, doc.authors, doc.primary_subject_class = data.title, authors, primary
        session.execute(update(Metadata).where(Metadata.document_id == doc.document_id)
                        .values(is_current=0))

    session.add(Metadata(
        document_id=doc.document_id, paper_id=paper_id, version=version,
        created=sub.created_at, updated=when, submitter_id=None,
        submitter_name=submitter_name, submitter_email=submitter_email,
        source_size=data.source_size, source_format=data.source_format, source_flags="",
        title=data.title, authors=authors, abs_categories=" ".join(data.categories),
        comments=data.comments, license=data.license, abstract=data.abstract,
        is_current=1, is_withdrawn=data.is_withdrawn, modtime=unix(when), published_at=when,
        doi=None, journal_ref=None, report_num=None, msc_class=None, acm_class=None, proxy=None))

    session.execute(delete(DocumentCategory).where(DocumentCategory.document_id == doc.document_id))
    session.execute(delete(t_arXiv_in_category).where(
        t_arXiv_in_category.c.document_id == doc.document_id))
    action = "new" if version == 1 else "replace"
    for i, cat in enumerate(data.categories):
        archive, subject = split_category(cat)
        is_primary = int(i == 0)
        session.add(DocumentCategory(document_id=doc.document_id, category=cat,
                                     is_primary=is_primary))
        session.execute(insert(t_arXiv_in_category).values(
            document_id=doc.document_id, archive=archive, subject_class=subject,
            is_primary=is_primary))
        key = {"document_id": doc.document_id, "date": when.date(), "action": action,
               "category": cat}
        existing = session.get(Updates, (doc.document_id, when.date(), action, cat))
        if existing is None:
            session.add(Updates(version=version, archive=archive, **key))
        else:  # a second version of this paper announced on the same day
            existing.version = version

    session.execute(delete(Contributor).where(Contributor.paper_id == paper_id,
                                              Contributor.version == version))
    for c in data.contributors:
        session.add(Contributor(paper_id=paper_id, version=version, **c))
    session.flush()
    return doc
