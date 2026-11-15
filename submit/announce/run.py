"""The daily announce: publish every accepted submission.

First, idempotent set-up: the licence/category seed rows, and `reasons.json` at the store
root if missing. Then per submission, in submission order:

1. **Claim** (one transaction): assign the identifier (new paper) or next version
   (replacement, withdrawal), record the announce time, and move `accepted` ->
   `announcing`. From here the submission can only be published, and re-runs reuse the
   same identifier, version and time (so a run that crashes at 23:59 on the last day of a
   month and resumes the next day still matches its YYMM).
2. **Files** (files.py): idempotent whole-object writes, before the database commit.
3. **Publish** (one transaction): the classic rows and coauthored_contributors
   (classic.py) plus `announcing` -> `announced` (guarded) and its log row. If this fails,
   the transaction rolls back, ftp/ is restored, and the submission stays `announcing`
   for the next run to finish.
4. Email the submitter (after the commit; failures are only logged).

A crash anywhere leaves either nothing published, or a claimed submission that the next
run completes. Running announce again when nothing is accepted does nothing.
"""
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterator, Optional

from arxiv.db.models import Metadata
from sqlalchemy import case, select, text
from sqlalchemy.orm import Session

from ..mailer import Message
from ..models import Submission
from ..notify import announced
from ..screening.state import ACCEPTED, ANNOUNCED, ANNOUNCING
from ..screening.transitions import apply_transition
from ..seed import seed_reference_rows
from ..storage import Store, ensure_reasons_json
from . import files
from .classic import version_data, write_rows
from .ids import next_paper_id, next_version

log = logging.getLogger(__name__)


@dataclass
class AnnounceResult:
    announced: list[tuple[int, str, int]] = field(default_factory=list)  # (submission, id, v)
    failed: list[tuple[int, str]] = field(default_factory=list)


@contextmanager
def _run_lock(session: Session) -> Iterator[bool]:
    """One announce at a time. MySQL: a named lock; SQLite (tests, dev): no-op."""
    if session.get_bind().dialect.name != "mysql":
        yield True
        return
    conn = session.get_bind().connect()  # type: ignore[union-attr]
    try:
        got = conn.execute(text("SELECT GET_LOCK('coauthored_announce', 0)")).scalar()
        yield bool(got)
        if got:
            conn.execute(text("SELECT RELEASE_LOCK('coauthored_announce')"))
    finally:
        conn.close()


def announce_pending(session: Session, store: Store, now: datetime, *,
                     license_host: str = "coauthored.pub",
                     send: Optional[Callable[[Message], object]] = None,
                     abs_url: Callable[[str], str] = lambda pid: f"/abs/{pid}") -> AnnounceResult:
    """Publish all accepted (and resume all claimed) submissions. `now` is naive UTC."""
    result = AnnounceResult()
    with _run_lock(session) as locked:
        if not locked:
            log.warning("another announce is running; nothing done")
            return result
        seed_reference_rows(session, license_host)
        session.commit()
        ensure_reasons_json(store)
        ids = session.scalars(
            select(Submission.id).where(Submission.status.in_((ACCEPTED, ANNOUNCING)))
            .order_by(case((Submission.status == ANNOUNCING, 0), else_=1), Submission.id)).all()
        for sub_id in ids:
            try:
                sub = announce_one(session, store, sub_id, now)
            except Exception as exc:  # noqa: BLE001 - one bad paper must not stop the rest
                session.rollback()
                log.exception("announce failed for submission %s", sub_id)
                result.failed.append((sub_id, f"{type(exc).__name__}: {exc}"))
                continue
            if sub is None:
                continue
            result.announced.append((sub.id, sub.paper_id, sub.version))  # type: ignore[arg-type]
            if send:
                send(announced(sub, abs_url(sub.paper_id)))  # type: ignore[arg-type]
    return result


def _claim(session: Session, sub: Submission, now: datetime) -> None:
    if sub.kind == "new":
        sub.paper_id, sub.version = next_paper_id(session, now), 1
    else:
        sub.version = next_version(session, sub.paper_id)  # type: ignore[arg-type]
    sub.announced_at = now
    apply_transition(session, sub, "claim", "system", now)
    session.commit()


def announce_one(session: Session, store: Store, sub_id: int, now: datetime) -> Optional[Submission]:
    sub = session.get(Submission, sub_id, populate_existing=True)
    if sub is None or sub.status not in (ACCEPTED, ANNOUNCING):
        return None
    if sub.status == ACCEPTED:
        _claim(session, sub, now)
    when = sub.announced_at
    assert when is not None and sub.paper_id and sub.version

    prev = None
    prev_staged = None
    if sub.version > 1:
        prev = session.scalars(select(Metadata).where(
            Metadata.paper_id == sub.paper_id, Metadata.version == sub.version - 1)).one()
        prev_sub = session.scalars(select(Submission).where(
            Submission.paper_id == sub.paper_id, Submission.version == sub.version - 1,
            Submission.status == ANNOUNCED)).first()
        prev_staged = prev_sub.pdf_key if prev_sub else None
    plan = files.plan(sub.paper_id, sub.version,
                      new_pdf=sub.pdf_key if sub.kind != "withdrawal" else None,
                      prev_had_pdf=bool(prev and not prev.is_withdrawn),
                      prev_staged=prev_staged)
    files.publish(store, plan)
    try:
        write_rows(session, sub, version_data(session, sub, prev), when)
        apply_transition(session, sub, "publish", "system", now)
        session.commit()
    except BaseException:
        session.rollback()
        _undo_unless_committed(session, store, plan, sub.id)
        raise
    return sub


def _undo_unless_committed(session: Session, store: Store, plan: files.FilePlan, sub_id: int) -> None:
    """Restore ftp/ only when the database certainly did not publish this version.

    If the status cannot be read, leave the files: the submission is then still
    `announcing` (and the next run re-publishes it) or it is `announced` (and the files are
    right). Restoring blindly could leave an announced version pointing at the old PDF.
    """
    try:
        status = session.scalar(select(Submission.status).where(Submission.id == sub_id))
        if status == ANNOUNCED:
            return
        files.undo(store, plan)
    except Exception:  # noqa: BLE001
        log.exception("could not check or restore %s after a failed publish", plan.current_key)
