"""Outgoing mail: SMTP in production, the log in development, a capturing fake in tests.

Mail is sent after the database commit, and a failure to send is logged, never raised:
a decision is not undone because an email bounced.
"""
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Mapping, Protocol

from flask import Flask, current_app

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, message: Message) -> None: ...


class LogMailer:
    def send(self, message: Message) -> None:
        log.info("mail to=%s subject=%r\n%s", message.to, message.subject, message.body)


class CapturingMailer:
    def __init__(self) -> None:
        self.outbox: list[Message] = []

    def send(self, message: Message) -> None:
        self.outbox.append(message)


class SmtpMailer:
    def __init__(self, conf: Mapping[str, Any]):
        self.host = conf["SMTP_HOST"]
        self.port = int(conf["SMTP_PORT"])
        self.username = conf.get("SMTP_USERNAME") or ""
        self.password = conf.get("SMTP_PASSWORD") or ""
        self.starttls = bool(conf.get("SMTP_STARTTLS", True))
        self.sender = conf["MAIL_FROM"]

    def send(self, message: Message) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg.set_content(message.body)
        cls = smtplib.SMTP_SSL if self.port == 465 else smtplib.SMTP
        with cls(self.host, self.port, timeout=20) as smtp:
            if self.starttls and cls is smtplib.SMTP:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)


def make_mailer(conf: Mapping[str, Any]) -> Mailer:
    kind = conf.get("MAILER", "log")
    if kind == "smtp":
        return SmtpMailer(conf)
    if kind == "capture":
        return CapturingMailer()
    return LogMailer()


def init_app(app: Flask, mailer: Mailer | None = None) -> None:
    app.extensions["mailer"] = mailer or make_mailer(app.config)


def send(message: Message, app: Flask | None = None) -> bool:
    mailer: Mailer = (app or current_app).extensions["mailer"]
    try:
        mailer.send(message)
        return True
    except Exception:  # noqa: BLE001 - mail must never break a committed decision
        log.exception("could not send mail to %s", message.to)
        return False
