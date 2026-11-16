"""Flask CLI commands: init-db, set-moderator, set-banned, announce."""
from datetime import datetime, timezone
from typing import Optional

import click
from flask import Flask, current_app
from sqlalchemy import func, select

from . import mailer
from .announce.run import announce_pending
from .db import engine, new_session
from .models import Account
from .seed import create_schema, seed_reference_rows
from .storage import ensure_reasons_json


def _set_flag(email: str, flag: str, on: bool) -> None:
    with new_session() as session:
        accounts = session.scalars(select(Account).where(
            func.lower(Account.email) == email.strip().lower())).all()
        if not accounts:
            raise click.ClickException(f"No account with email {email}. They must sign in once first.")
        for account in accounts:
            setattr(account, flag, on)
        session.commit()
        click.echo(f"{flag}={'on' if on else 'off'} for {len(accounts)} account(s) with email {email}")


def register(app: Flask) -> None:
    @app.cli.command("send-test-email")
    @click.argument("to")
    def send_test_email(to: str) -> None:
        """Send a test message through the configured mailer (checks SMTP settings)."""
        current_app.extensions["mailer"].send(mailer.Message(
            to=to, subject="Coauthored test email",
            body="This is a test message from Coauthored's submission service. "
                 "If you can read it, outgoing email works.\n"))
        click.echo(f"sent a test email to {to} via {current_app.config['MAILER']}")

    @app.cli.command("grant-reader")
    @click.argument("user")
    def grant_reader(user: str) -> None:
        """Create (or update) a read-only MySQL user for coauthored-browse. Its password is
        read from the READER_DB_PASSWORD environment variable, never from the command line."""
        import os
        import re as _re
        from sqlalchemy import text
        password = os.environ.get("READER_DB_PASSWORD", "")
        if not password:
            raise click.ClickException("Set READER_DB_PASSWORD.")
        if not _re.fullmatch(r"[A-Za-z0-9_]{1,32}", user):
            raise click.ClickException("User names are letters, digits and _ only.")
        eng = engine()
        if eng.dialect.name != "mysql":
            raise click.ClickException("grant-reader is for MySQL.")
        db = eng.url.database
        with eng.begin() as conn:
            conn.execute(text(f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY :pw"), {"pw": password})
            conn.execute(text(f"ALTER USER '{user}'@'%' IDENTIFIED BY :pw"), {"pw": password})
            conn.execute(text(f"GRANT SELECT ON `{db}`.* TO '{user}'@'%'"))
        click.echo(f"read-only user {user} can SELECT on {db}")

    @app.cli.command("load-classic-schema")
    def load_classic_schema() -> None:
        """Load arxiv-base's classic schema (utf8mb4) into an EMPTY MySQL database."""
        from .classic_schema import load
        try:
            n = load(engine())
        except RuntimeError as ex:
            raise click.ClickException(str(ex))
        click.echo(f"classic schema loaded ({n} statements)")

    @app.cli.command("init-db")
    def init_db() -> None:
        """Create the coauthored tables (and the classic tables on SQLite), seed reference
        rows, and write reasons.json ({}) to the store root if it is missing."""
        missing = create_schema(engine())
        if missing:
            raise click.ClickException(
                "Classic tables missing: " + ", ".join(missing) + ". On MySQL load arxiv-base's "
                "arxiv/db/arxiv_db_schema.sql first (scripts/load_classic_schema.sh).")
        with new_session() as session:
            added = seed_reference_rows(session, current_app.config["LICENSE_HOST"])
            session.commit()
        created = ensure_reasons_json(current_app.extensions["store"])
        click.echo(f"Schema ready; {added} reference rows added; reasons.json "
                   f"{'created' if created else 'already present'}.")

    @app.cli.command("set-moderator")
    @click.argument("email")
    @click.option("--on/--off", "on", default=True, help="Grant or remove moderator rights.")
    def set_moderator(email: str, on: bool) -> None:
        """Grant (--on) or remove (--off) moderator rights."""
        _set_flag(email, "is_moderator", on)

    @app.cli.command("set-banned")
    @click.argument("email")
    @click.option("--on/--off", "on", default=True, help="Ban or unban the account.")
    def set_banned(email: str, on: bool) -> None:
        """Ban (--on) or unban (--off) an account from submitting."""
        _set_flag(email, "is_banned", on)

    @app.cli.command("announce")
    @click.option("--now", "now_text", default=None,
                  help="Announce time, ISO 8601 UTC (default: the current time).")
    def announce(now_text: Optional[str]) -> None:
        """Publish every accepted submission (run daily by Cloud Scheduler)."""
        now = (datetime.fromisoformat(now_text) if now_text else datetime.now(timezone.utc))
        if now.tzinfo is not None:
            now = now.astimezone(timezone.utc).replace(tzinfo=None)
        base = current_app.config["BROWSE_BASE_URL"].rstrip("/")
        with new_session() as session:
            result = announce_pending(
                session, current_app.extensions["store"], now,
                license_host=current_app.config["LICENSE_HOST"],
                send=lambda m: mailer.send(m), abs_url=lambda pid: f"{base}/abs/{pid}")
        for sub_id, paper_id, version in result.announced:
            click.echo(f"announced submission {sub_id} as coauthored:{paper_id}v{version}")
        for sub_id, error in result.failed:
            click.echo(f"FAILED submission {sub_id}: {error}", err=True)
        click.echo(f"{len(result.announced)} announced, {len(result.failed)} failed")
        if result.failed:
            raise SystemExit(1)
