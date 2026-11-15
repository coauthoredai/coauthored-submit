"""Optional: init-db, submit, accept and announce against a real MySQL 8.

Skipped unless COAUTHORED_TEST_MYSQL_URI points at a DISPOSABLE database that already has
the classic schema (scripts/load_classic_schema.sh). It writes rows and does not remove them.

    docker compose up -d mysql
    MYSQL="docker compose exec -T mysql mysql" scripts/load_classic_schema.sh -ucoauthored -pcoauthored-dev coauthored
    COAUTHORED_TEST_MYSQL_URI='mysql+pymysql://coauthored:coauthored-dev@127.0.0.1:3307/coauthored?charset=utf8mb4' \\
        uv run pytest tests/test_mysql_integration.py
"""
import os
from datetime import datetime

import pytest
from arxiv.db.models import Metadata, Updates
from sqlalchemy import func, select

from submit import create_app
from submit.announce.run import announce_pending
from submit.db import new_session
from submit.models import Account, Contributor, Submission
from submit.screening.transitions import apply_transition
from submit.seed import create_schema, seed_reference_rows
from submit.submissions import service
from tests.helpers import checked_pdf, submission_in

URI = os.environ.get("COAUTHORED_TEST_MYSQL_URI")
pytestmark = pytest.mark.skipif(not URI, reason="COAUTHORED_TEST_MYSQL_URI not set")


def test_announce_on_mysql(store, mail):
    app = create_app({"TESTING": True, "DEV_AUTH": True, "CLASSIC_DB_URI": URI,
                      "MAILER": "capture"}, store=store, mail=mail)
    from submit.db import engine
    with app.app_context():
        assert create_schema(engine()) == []
    with new_session(app) as session:
        seed_reference_rows(session, "aicoauthored.dev")
        session.commit()
        assert seed_reference_rows(session, "aicoauthored.dev") == 0
        stamp = datetime.now().strftime("%H%M%S%f")
        author = Account(clerk_user_id=f"dev:it{stamp}@example.org", email=f"it{stamp}@example.org",
                         display_name="Zoë Ångström", created_at=datetime(2026, 11, 1))
        mod = Account(clerk_user_id=f"dev:mod{stamp}@example.org", email=f"mod{stamp}@example.org",
                      display_name="Mo", is_moderator=True, created_at=datetime(2026, 11, 1))
        session.add_all([author, mod])
        session.commit()
        title = f"Ψ-games and the Erdős problem ({stamp})"
        sub = service.create_submission(session, store, author, submission_in(title=title),
                                        checked_pdf(stamp), datetime(2026, 11, 14), 100)
        apply_transition(session, sub, "accept", "moderator", datetime(2026, 11, 14), actor_id=mod.id)
        session.commit()
        result = announce_pending(session, store, datetime(2026, 11, 16, 20, 0))
        assert result.failed == [] and [r[0] for r in result.announced] == [sub.id]
        session.expire_all()
        sub = session.get(Submission, sub.id)
        meta = session.scalars(select(Metadata).where(Metadata.paper_id == sub.paper_id)).one()
        assert meta.title == title and meta.submitter_name == "Zoë Ångström"
        assert meta.is_current == 1 and meta.abs_categories == "cs.GT math.CO"
        assert session.scalar(select(func.count()).select_from(Updates).where(
            Updates.document_id == meta.document_id)) == 2
        assert session.scalar(select(func.count()).select_from(Contributor).where(
            Contributor.paper_id == sub.paper_id)) == 2
