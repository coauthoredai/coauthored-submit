"""Who is making a request: the shared result type of the authenticators."""
from dataclasses import dataclass
from typing import Optional, Protocol

from flask import Request


@dataclass(frozen=True)
class Identity:
    user_id: str           # Clerk user id (`user_...`), or `dev:<email>` under DEV_AUTH
    email: Optional[str]
    display_name: Optional[str]


class Authenticator(Protocol):
    def identify(self, request: Request) -> Optional[Identity]:
        """The request's verified identity, or None if it carries no valid credentials."""
        ...
