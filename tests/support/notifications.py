"""A notification channel that keeps what it was asked to deliver."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import override

from insumap.application.notifications.notification import (
    NotificationChannel,
    Recipient,
)

TOKEN_IN_LINK = re.compile(r"#token=(\S+)")


@dataclass(frozen=True, slots=True, kw_only=True)
class Delivered:
    recipient: Recipient
    subject: str
    body: str

    def token(self) -> str:
        """The single-use token of the link in the body."""
        match = TOKEN_IN_LINK.search(self.body)
        assert match is not None, self.body
        return match.group(1).rstrip(".")


@dataclass
class InMemoryChannel(NotificationChannel):
    external: bool = True
    delivered: list[Delivered] = field(default_factory=list)
    fail: bool = False

    @property
    @override
    def is_external(self) -> bool:
        return self.external

    @override
    def deliver(self, *, recipient: Recipient, subject: str, body: str) -> None:
        if self.fail:
            raise ConnectionError("smtp is down")
        self.delivered.append(
            Delivered(recipient=recipient, subject=subject, body=body)
        )
