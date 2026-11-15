"""Engine and sessions.

The app owns its engine (from CLASSIC_DB_URI) and uses arxiv-base's models with ordinary
SQLAlchemy sessions bound to it; arxiv-base's global `arxiv.db.Session` is not used.
Each request gets one session (`get_session`), closed at teardown.
"""
from pathlib import Path
from typing import Any

from flask import Flask, current_app, g
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


def make_engine(uri: str) -> Engine:
    if uri.startswith("sqlite"):
        url = make_url(uri)
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(uri)

        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        return engine
    return create_engine(uri, pool_pre_ping=True, pool_recycle=600,
                         isolation_level="READ COMMITTED")


def init_app(app: Flask, engine: Engine | None = None) -> None:
    engine = engine or make_engine(app.config["CLASSIC_DB_URI"])
    app.extensions["db_engine"] = engine
    app.extensions["db_sessionmaker"] = sessionmaker(bind=engine, autoflush=False,
                                                     expire_on_commit=False)

    @app.teardown_appcontext
    def _close(_exc: BaseException | None) -> None:
        session = g.pop("db_session", None)
        if session is not None:
            session.close()


def new_session(app: Flask | None = None) -> Session:
    app = app or current_app
    return app.extensions["db_sessionmaker"]()


def get_session() -> Session:
    """The request's session."""
    if "db_session" not in g:
        g.db_session = new_session()
    return g.db_session


def engine(app: Flask | None = None) -> Engine:
    return (app or current_app).extensions["db_engine"]
