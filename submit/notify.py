"""The emails sent to submitters. Plain text."""
from typing import Optional

from .mailer import Message
from .models import Submission

SIGN_OFF = "\n\n-- \nCoauthored, the open preprint server for papers with AI co-authors.\n"


def _what(sub: Submission) -> str:
    if sub.kind == "replacement":
        return f"your replacement of coauthored:{sub.paper_id}"
    if sub.kind == "withdrawal":
        return f"your withdrawal request for coauthored:{sub.paper_id}"
    return "your submission"


def received(sub: Submission, link: str) -> Message:
    return Message(sub.account.email, f"Received: {sub.title}",
                   f"We received {_what(sub)} \"{sub.title}\" (submission {sub.id}). "
                   f"Moderators will screen it; we will email you when they decide.\n\n"
                   f"Status: {link}{SIGN_OFF}")


def decision(sub: Submission, action: str, reason: Optional[str], link: str) -> Optional[Message]:
    title = sub.title
    if action == "accept":
        body = (f"Moderators accepted {_what(sub)} \"{title}\". It will be announced at the "
                f"next daily announcement, and we will email you its identifier.")
        subject = f"Accepted: {title}"
    elif action == "reject":
        body = f"Moderators did not accept {_what(sub)} \"{title}\".\n\nReason: {reason}"
        subject = f"Not accepted: {title}"
    elif action == "request_changes":
        body = (f"Moderators asked for changes to {_what(sub)} \"{title}\" before it can be "
                f"accepted.\n\nWhat to change: {reason}\n\nEdit and resubmit it here: {link}")
        subject = f"Changes requested: {title}"
    elif action == "hold":
        body = (f"Moderators put {_what(sub)} \"{title}\" on hold for further review."
                + (f"\n\nNote: {reason}" if reason else ""))
        subject = f"On hold: {title}"
    else:
        return None
    return Message(sub.account.email, subject, f"{body}\n\nStatus: {link}{SIGN_OFF}")


def announced(sub: Submission, abs_url: str) -> Message:
    ident = f"coauthored:{sub.paper_id}v{sub.version}"
    if sub.kind == "withdrawal":
        body = f"Your withdrawal of \"{sub.title}\" was announced as {ident}."
    else:
        body = f"\"{sub.title}\" was announced as {ident}."
    return Message(sub.account.email, f"Announced: {ident}",
                   f"{body}\n\nAbstract page: {abs_url}{SIGN_OFF}")
