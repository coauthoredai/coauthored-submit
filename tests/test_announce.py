"""Announce: rows and files exactly per CONTRACT.md, identifiers, versions, idempotence."""
import json
from datetime import date, datetime

import pytest
from arxiv.db.models import Document, DocumentCategory, License, Metadata, Updates, t_arXiv_in_category
from arxiv.files.key_patterns import current_pdf_path, previous_pdf_path
from arxiv.identifier import Identifier
from sqlalchemy import func, select

from submit.announce import run as announce_run
from submit.announce.run import announce_pending
from submit.models import Contributor, ModerationLog, Submission
from submit.screening.transitions import apply_transition
from submit.submissions import service
from submit.submissions.schema import WithdrawalIn
from tests.helpers import author_dicts, checked_pdf, make_account, pdf_bytes, submission_in

SUBMITTED_AT = datetime(2026, 11, 14, 9, 30)  # unix 1794648600
NOV = datetime(2026, 11, 16, 20, 0)              # unix 1794859200
CC_BY = "http://creativecommons.org/licenses/by/4.0/"


@pytest.fixture
def people(session):
    return make_account(session), make_account(session, "mod@example.org", "Mo", moderator=True)


def accepted(session, store, people, tag="v1", replaces=None, at=SUBMITTED_AT, **overrides):
    author, mod = people
    sub = service.create_submission(session, store, author, submission_in(**overrides),
                                    checked_pdf(tag), at, 100, replaces=replaces)
    apply_transition(session, sub, "accept", "moderator", at, actor_id=mod.id)
    session.commit()
    return sub


def run(session, store, now, mail=None):
    sent = []
    result = announce_pending(session, store, now, send=sent.append,
                              abs_url=lambda pid: f"https://coauthored.test/abs/{pid}")
    session.expire_all()
    return result, sent


def read(store, key):
    return store.obj(key).open("rb").read()


def test_new_paper_rows_and_files_exactly_per_contract(session, store, people):
    sub = accepted(session, store, people)
    result, sent = run(session, store, NOV)
    assert result.announced == [(sub.id, "2611.00001", 1)] and result.failed == []
    pid = "2611.00001"

    doc = session.scalars(select(Document)).one()
    assert (doc.paper_id, doc.title, doc.authors, doc.submitter_email, doc.submitter_id,
            doc.dated, doc.primary_subject_class, doc.created) == (
        pid, "On cooperative games between humans and machines", "Ada Lovelace, Claude",
        "ada@example.org", None, 1794648600,
        "cs.GT", NOV)

    meta = session.scalars(select(Metadata)).one()
    assert meta.document_id == doc.document_id and meta.paper_id == pid and meta.version == 1
    assert (meta.created, meta.updated, meta.published_at, meta.modtime) == (
        SUBMITTED_AT, NOV, NOV, 1794859200)
    assert (meta.submitter_id, meta.submitter_name, meta.submitter_email) == (
        None, "Ada Lovelace", "ada@example.org")
    assert (meta.source_size, meta.source_format, meta.source_flags) == (len(pdf_bytes("v1")), "pdf", "")
    assert (meta.title, meta.authors, meta.abs_categories, meta.comments, meta.license) == (
        doc.title, "Ada Lovelace, Claude", "cs.GT math.CO", "10 pages", CC_BY)
    assert meta.abstract.startswith("We study cooperative games")
    assert (meta.is_current, meta.is_withdrawn) == (1, 0)
    assert (meta.doi, meta.journal_ref, meta.report_num, meta.msc_class, meta.acm_class,
            meta.proxy) == (None,) * 6

    cats = session.execute(select(DocumentCategory.category, DocumentCategory.is_primary)
                           .order_by(DocumentCategory.is_primary.desc())).all()
    assert cats == [("cs.GT", 1), ("math.CO", 0)]
    in_cat = session.execute(select(t_arXiv_in_category.c.document_id, t_arXiv_in_category.c.archive,
                                    t_arXiv_in_category.c.subject_class,
                                    t_arXiv_in_category.c.is_primary)
                             .order_by(t_arXiv_in_category.c.is_primary.desc())).all()
    assert in_cat == [(doc.document_id, "cs", "GT", 1), (doc.document_id, "math", "CO", 0)]
    ups = session.execute(select(Updates.document_id, Updates.version, Updates.date, Updates.action,
                                 Updates.archive, Updates.category).order_by(Updates.category)).all()
    assert ups == [(doc.document_id, 1, date(2026, 11, 16), "new", "cs", "cs.GT"),
                   (doc.document_id, 1, date(2026, 11, 16), "new", "math", "math.CO")]

    contributors = session.scalars(select(Contributor).order_by(Contributor.position)).all()
    assert [(c.paper_id, c.version, c.position, c.display_name, c.kind, c.orcid, c.ai_system,
             c.ai_version, c.ai_provider, c.is_responsible) for c in contributors] == [
        (pid, 1, 1, "Ada Lovelace", "human", "0000-0002-1825-0097", None, None, None, True),
        (pid, 1, 2, "Claude", "ai", None, "Claude", "Opus 5.5 (claude-opus-5-5)", "Anthropic", False)]
    assert all(c.contribution for c in contributors)

    assert current_pdf_path(Identifier(pid)) == "ftp/arxiv/papers/2611/2611.00001.pdf"
    assert read(store, "ftp/arxiv/papers/2611/2611.00001.pdf") == pdf_bytes("v1")
    assert read(store, sub.pdf_key) == pdf_bytes("v1")  # staging is kept
    assert sub.pdf_key.startswith(f"staging/{sub.id}/")
    assert not store.exists("orig/arxiv/papers/2611/2611.00001v1.pdf")

    s = session.get(Submission, sub.id)
    assert (s.status, s.paper_id, s.version, s.announced_at) == ("announced", pid, 1, NOV)
    assert [r.action for r in session.scalars(select(ModerationLog).order_by(ModerationLog.id))] == [
        "accept", "claim", "publish"]
    assert [m.subject for m in sent] == ["Announced: coauthored:2611.00001v1"]
    assert "https://coauthored.test/abs/2611.00001" in sent[0].body


def test_seeds_and_reasons_json(session, store, people):
    assert not store.exists("reasons.json")
    accepted(session, store, people)
    run(session, store, NOV)
    assert json.loads(read(store, "reasons.json")) == {}
    licences = set(session.scalars(select(License.name)))
    assert {CC_BY, "http://creativecommons.org/licenses/by-sa/4.0/",
            "http://creativecommons.org/publicdomain/zero/1.0/",
            "https://aicoauthored.dev/licenses/nonexclusive-distrib/1.0/"} <= licences
    assert "http://arxiv.org/licenses/nonexclusive-distrib/1.0/" not in licences


def test_reasons_json_never_overwritten(app, store):
    store.put_if_absent("reasons.json", b'{"2611.00001v1": "suppressed"}', "application/json")
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    assert "already present" in result.output
    assert json.loads(read(store, "reasons.json")) == {"2611.00001v1": "suppressed"}


def test_init_db_writes_reasons_json_when_missing(app, store):
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    assert json.loads(read(store, "reasons.json")) == {}


def test_identifiers_count_per_month_across_a_boundary(session, store, people):
    a = accepted(session, store, people, tag="a")
    b = accepted(session, store, people, tag="b")
    result, _ = run(session, store, datetime(2026, 11, 30, 23, 59))
    assert [r[1] for r in result.announced] == ["2611.00001", "2611.00002"]
    c = accepted(session, store, people, tag="c")
    result, _ = run(session, store, datetime(2026, 12, 1, 0, 1))
    assert result.announced == [(c.id, "2612.00001", 1)]
    d = accepted(session, store, people, tag="d")
    result, _ = run(session, store, datetime(2026, 12, 2, 20, 0))
    assert result.announced == [(d.id, "2612.00002", 1)]
    assert read(store, "ftp/arxiv/papers/2612/2612.00001.pdf") == pdf_bytes("c")
    assert read(store, "ftp/arxiv/papers/2611/2611.00002.pdf") == pdf_bytes("b")
    dated = dict(session.execute(select(Document.paper_id, Updates.date).join(
        Updates, Updates.document_id == Document.document_id)).all())
    assert dated["2611.00002"] == date(2026, 11, 30) and dated["2612.00001"] == date(2026, 12, 1)
    assert {a.id, b.id} == {r for r, in session.execute(select(Submission.id).where(
        Submission.paper_id.like("2611.%")))}


def test_numbering_skips_existing_documents(session, store, people):
    session.add(Document(paper_id="2611.00007", title="Imported", submitter_email="x@example.org",
                         dated=0))
    session.commit()
    accepted(session, store, people)
    result, _ = run(session, store, NOV)
    assert result.announced[0][1] == "2611.00008"


def test_replacement_moves_the_old_pdf_and_adds_a_version(session, store, people):
    first = accepted(session, store, people, tag="v1")
    run(session, store, NOV)
    pid = "2611.00001"
    human, ai = author_dicts()
    repl = accepted(session, store, people, tag="v2", replaces=pid, at=datetime(2026, 11, 20, 8, 0),
                    title="On cooperative games (revised)", primary_category="cs.GT",
                    cross_lists=["cs.AI"], authors=[human, ai, dict(ai, display_name="Gemini",
                                                                    ai_system="Gemini",
                                                                    ai_provider="Google")])
    when = datetime(2026, 12, 3, 20, 0)
    result, sent = run(session, store, when)
    assert result.announced == [(repl.id, pid, 2)]

    # Files: v1 moved to orig/ (under the paper's own YYMM), v2 at ftp/.
    assert previous_pdf_path(Identifier(f"{pid}v1")) == "orig/arxiv/papers/2611/2611.00001v1.pdf"
    assert read(store, "orig/arxiv/papers/2611/2611.00001v1.pdf") == pdf_bytes("v1")
    assert read(store, "ftp/arxiv/papers/2611/2611.00001.pdf") == pdf_bytes("v2")

    doc = session.scalars(select(Document)).one()  # still one document row
    assert doc.title == "On cooperative games (revised)"
    assert doc.authors == "Ada Lovelace, Claude, Gemini"
    assert doc.dated == 1794648600  # first version's submission time
    metas = session.scalars(select(Metadata).order_by(Metadata.version)).all()
    assert [(m.version, m.is_current) for m in metas] == [(1, 0), (2, 1)]
    assert metas[1].created == datetime(2026, 11, 20, 8, 0)
    assert metas[1].abs_categories == "cs.GT cs.AI"
    assert metas[1].source_size == len(pdf_bytes("v2"))
    assert sorted(session.execute(select(DocumentCategory.category, DocumentCategory.is_primary)).all()) == [
        ("cs.AI", 0), ("cs.GT", 1)]
    assert sorted(session.execute(select(t_arXiv_in_category.c.archive,
                                         t_arXiv_in_category.c.subject_class)).all()) == [
        ("cs", "AI"), ("cs", "GT")]
    ups = sorted(session.execute(select(Updates.version, Updates.action, Updates.category,
                                        Updates.date)).all())
    assert ups == [(1, "new", "cs.GT", date(2026, 11, 16)), (1, "new", "math.CO", date(2026, 11, 16)),
                   (2, "replace", "cs.AI", date(2026, 12, 3)), (2, "replace", "cs.GT", date(2026, 12, 3))]
    v2 = session.scalars(select(Contributor.display_name).where(Contributor.version == 2)
                         .order_by(Contributor.position)).all()
    assert v2 == ["Ada Lovelace", "Claude", "Gemini"]
    assert session.scalar(select(func.count()).select_from(Contributor).where(Contributor.version == 1)) == 2
    assert sent[0].subject == "Announced: coauthored:2611.00001v2"
    assert session.get(Submission, first.id).version == 1


def test_withdrawal_adds_a_version_without_pdf(session, store, people):
    author, mod = people
    accepted(session, store, people, tag="v1")
    run(session, store, NOV)
    pid = "2611.00001"
    w = service.create_withdrawal(session, author, pid, WithdrawalIn(reason="A fatal error in Lemma 2.",
                                                                     authorized=True), NOV, 100)
    apply_transition(session, w, "accept", "moderator", NOV, actor_id=mod.id)
    session.commit()
    result, _ = run(session, store, datetime(2026, 11, 17, 20, 0))
    assert result.announced == [(w.id, pid, 2)]
    metas = session.scalars(select(Metadata).order_by(Metadata.version)).all()
    v2 = metas[1]
    assert [(m.version, m.is_current, m.is_withdrawn) for m in metas] == [(1, 0, 0), (2, 1, 1)]
    assert (v2.source_size, v2.source_format) == (0, "withdrawn")
    assert "A fatal error in Lemma 2." in v2.comments and "withdrawn" in v2.comments
    assert (v2.title, v2.authors, v2.abs_categories, v2.license) == (
        metas[0].title, metas[0].authors, metas[0].abs_categories, metas[0].license)
    assert not store.exists("ftp/arxiv/papers/2611/2611.00001.pdf")
    assert read(store, "orig/arxiv/papers/2611/2611.00001v1.pdf") == pdf_bytes("v1")
    assert session.scalar(select(func.count()).select_from(Contributor).where(Contributor.version == 2)) == 2
    assert session.scalars(select(Updates.action).where(Updates.version == 2)).all() == ["replace", "replace"]


def test_rerun_is_idempotent(session, store, people):
    accepted(session, store, people)
    run(session, store, NOV)
    counts = lambda: [session.scalar(select(func.count()).select_from(t)) for t in  # noqa: E731
                      (Document, Metadata, DocumentCategory, t_arXiv_in_category, Updates, Contributor)]
    before = counts()
    result, sent = run(session, store, NOV)
    assert result.announced == [] and result.failed == [] and sent == []
    assert counts() == before


def test_crash_between_files_and_commit_is_resumed_with_the_same_identity(session, store, people, monkeypatch):
    accepted(session, store, people, tag="v1")
    run(session, store, NOV)
    pid = "2611.00001"
    repl = accepted(session, store, people, tag="v2", replaces=pid)

    real = announce_run.write_rows
    monkeypatch.setattr(announce_run, "write_rows", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("database went away")))
    result, sent = run(session, store, datetime(2026, 11, 30, 23, 59))
    assert result.announced == [] and result.failed[0][0] == repl.id and sent == []
    s = session.get(Submission, repl.id)
    assert (s.status, s.version, s.announced_at) == ("announcing", 2, datetime(2026, 11, 30, 23, 59))
    # Nothing half-published: v1 is still current in the database and at ftp/.
    assert session.scalars(select(Metadata.version)).all() == [1]
    assert read(store, "ftp/arxiv/papers/2611/2611.00001.pdf") == pdf_bytes("v1")
    assert read(store, "orig/arxiv/papers/2611/2611.00001v1.pdf") == pdf_bytes("v1")

    monkeypatch.setattr(announce_run, "write_rows", real)
    result, sent = run(session, store, datetime(2026, 12, 1, 20, 0))  # resumed next day
    assert result.announced == [(repl.id, pid, 2)]
    m2 = session.scalars(select(Metadata).where(Metadata.version == 2)).one()
    assert m2.published_at == datetime(2026, 11, 30, 23, 59)  # the claimed time, kept
    assert read(store, "ftp/arxiv/papers/2611/2611.00001.pdf") == pdf_bytes("v2")
    assert read(store, "orig/arxiv/papers/2611/2611.00001v1.pdf") == pdf_bytes("v1")


def test_crash_after_claim_keeps_the_month_of_the_claim(session, store, people, monkeypatch):
    sub = accepted(session, store, people)
    monkeypatch.setattr(announce_run.files, "publish", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    result, _ = run(session, store, datetime(2026, 11, 30, 23, 59))
    assert result.failed and session.get(Submission, sub.id).status == "announcing"
    assert session.scalars(select(Document)).all() == []
    monkeypatch.undo()
    other = accepted(session, store, people, tag="b")
    result, _ = run(session, store, datetime(2026, 12, 1, 0, 5))
    assert result.announced == [(sub.id, "2611.00001", 1), (other.id, "2612.00001", 1)]
    assert read(store, "ftp/arxiv/papers/2611/2611.00001.pdf") == pdf_bytes("v1")


def test_one_bad_paper_does_not_stop_the_rest(session, store, people):
    bad = accepted(session, store, people, tag="bad")
    store.delete(bad.pdf_key)
    good = accepted(session, store, people, tag="good")
    result, _ = run(session, store, NOV)
    assert [f[0] for f in result.failed] == [bad.id]
    assert result.announced == [(good.id, "2611.00002", 1)]
    assert session.get(Submission, bad.id).status == "announcing"  # left for an operator
