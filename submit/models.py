"""The coauthored_* tables, owned and created by coauthored-submit.

They live in their own SQLAlchemy metadata, separate from arxiv-base's classic schema,
so `flask init-db` can create them without touching the classic tables.
`coauthored_contributors` is the one table coauthored-browse reads (CONTRACT.md);
the others are private to this app.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (Boolean, DateTime, ForeignKey, Index, Integer, MetaData, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"}


class CoauthoredBase(DeclarativeBase):
    metadata = MetaData()


class Account(CoauthoredBase):
    __tablename__ = "coauthored_accounts"
    __table_args__ = MYSQL_OPTS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clerk_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    orcid: Mapped[Optional[str]] = mapped_column(String(19))
    is_moderator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Submission(CoauthoredBase):
    """One submission: a new paper, a replacement (new version) or a withdrawal."""
    __tablename__ = "coauthored_submissions"
    __table_args__ = (
        UniqueConstraint("paper_id", "version", name="uq_submission_paper_version"),
        Index("ix_submission_status", "status"),
        Index("ix_submission_account_created", "account_id", "created_at"),
        MYSQL_OPTS,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("coauthored_accounts.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # new | replacement | withdrawal
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    primary_category: Mapped[str] = mapped_column(String(32), nullable=False)
    cross_categories: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    license: Mapped[str] = mapped_column(String(255), nullable=False)
    pdf_key: Mapped[Optional[str]] = mapped_column(String(255))
    pdf_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    pdf_size: Mapped[Optional[int]] = mapped_column(Integer)
    withdrawal_reason: Mapped[Optional[str]] = mapped_column(Text)
    # Replacements and withdrawals name their paper here from the start; new papers get
    # paper_id and version when announce claims them.
    paper_id: Mapped[Optional[str]] = mapped_column(String(20))
    version: Mapped[Optional[int]] = mapped_column(Integer)
    declarations_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    announced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    account: Mapped[Account] = relationship(Account, lazy="joined")
    contributors: Mapped[list["SubmissionContributor"]] = relationship(
        "SubmissionContributor", order_by="SubmissionContributor.position",
        cascade="all, delete-orphan", lazy="selectin")

    @property
    def categories(self) -> list[str]:
        """Primary first, then cross-lists."""
        return [self.primary_category] + [c for c in self.cross_categories.split() if c]


class SubmissionContributor(CoauthoredBase):
    """The author list as submitted; copied to coauthored_contributors at announce."""
    __tablename__ = "coauthored_submission_contributors"
    __table_args__ = MYSQL_OPTS

    submission_id: Mapped[int] = mapped_column(
        ForeignKey("coauthored_submissions.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    orcid: Mapped[Optional[str]] = mapped_column(String(19))
    ai_system: Mapped[Optional[str]] = mapped_column(String(128))
    ai_version: Mapped[Optional[str]] = mapped_column(String(128))
    ai_provider: Mapped[Optional[str]] = mapped_column(String(128))
    contribution: Mapped[str] = mapped_column(Text, nullable=False)
    is_responsible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_submitter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ModerationLog(CoauthoredBase):
    """One row per status change, written in the same transaction as the change."""
    __tablename__ = "coauthored_moderation_log"
    __table_args__ = (Index("ix_modlog_submission", "submission_id"), MYSQL_OPTS)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("coauthored_submissions.id"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(24), nullable=False)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    # The moderator who acted; NULL for the submitter's own actions and for announce.
    moderator_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("coauthored_accounts.id"))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Contributor(CoauthoredBase):
    """coauthored_contributors: the published author list (CONTRACT.md), read by browse."""
    __tablename__ = "coauthored_contributors"
    __table_args__ = MYSQL_OPTS

    paper_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    orcid: Mapped[Optional[str]] = mapped_column(String(19))
    ai_system: Mapped[Optional[str]] = mapped_column(String(128))
    ai_version: Mapped[Optional[str]] = mapped_column(String(128))
    ai_provider: Mapped[Optional[str]] = mapped_column(String(128))
    contribution: Mapped[str] = mapped_column(Text, nullable=False)
    is_responsible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
