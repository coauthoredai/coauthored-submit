"""Fixtures: a fresh SQLite database (classic + coauthored tables, seeded) and a temporary
local object store per test, and an app in TESTING + DEV_AUTH mode with a capturing mailer."""
import shutil
from pathlib import Path

import pytest

from submit import create_app
from submit.db import make_engine, new_session
from submit.mailer import CapturingMailer
from submit.seed import create_schema, seed_reference_rows
from submit.storage import LocalStore


@pytest.fixture(scope="session")
def template_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("template") / "template.db"
    engine = make_engine(f"sqlite:///{path}")
    assert create_schema(engine) == []
    from sqlalchemy.orm import Session
    with Session(engine) as session:
        seed_reference_rows(session, "aicoauthored.dev")
        session.commit()
    engine.dispose()
    return path


@pytest.fixture
def db_uri(template_db: Path, tmp_path: Path) -> str:
    path = tmp_path / "test.db"
    shutil.copyfile(template_db, path)
    return f"sqlite:///{path}"


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    return LocalStore(str(tmp_path / "store"))


@pytest.fixture
def mail() -> CapturingMailer:
    return CapturingMailer()


@pytest.fixture
def config(db_uri: str) -> dict:
    return {"TESTING": True, "DEV_AUTH": True, "CLASSIC_DB_URI": db_uri, "MAILER": "capture",
            "BROWSE_BASE_URL": "https://coauthored.test"}


@pytest.fixture
def app(config: dict, store: LocalStore, mail: CapturingMailer):
    # No app context is kept pushed: each test-client request then gets its own, as in
    # production, so per-request state (flask.g) does not leak between requests.
    return create_app(config, store=store, mail=mail)


@pytest.fixture
def session(app):
    s = new_session(app)
    yield s
    s.close()


@pytest.fixture
def client(app):
    return app.test_client()
