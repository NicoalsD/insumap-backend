"""Catalog of user-facing messages (``messages_es.json``)."""

from __future__ import annotations

import json
import re
import string
from collections.abc import Mapping
from importlib.resources import files
from typing import final

SPANISH_MESSAGES_PACKAGE = "insumap.shared.i18n"
SPANISH_MESSAGES_FILE = "messages_es.json"
MESSAGE_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*")


class MissingMessageError(KeyError):
    """Raised when a message key is not in the catalog."""


class MessageRenderError(ValueError):
    """Raised when a message cannot be filled with the given parameters."""


@final
class MessageCatalog:
    """Spanish texts for the user, looked up by English dotted keys.

    Keys come from the code (``glucose.out_of_range``) and texts may contain named
    placeholders (``{value}``) that ``render`` fills. Only plain named placeholders
    are accepted, so a template can never reach attributes or items of a
    parameter. A missing key raises ``MissingMessageError``; tests check that
    every key the code uses exists.
    """

    def __init__(self, messages: Mapping[str, str]) -> None:
        for key, text in messages.items():
            _check_entry(key, text)
        self._messages = dict(messages)

    @classmethod
    def load_spanish(cls) -> MessageCatalog:
        """Load ``messages_es.json``, shipped inside this package."""
        resource = files(SPANISH_MESSAGES_PACKAGE).joinpath(SPANISH_MESSAGES_FILE)
        content = json.loads(resource.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            raise TypeError(f"{SPANISH_MESSAGES_FILE} must hold a JSON object")
        return cls(content)

    def message_keys(self) -> frozenset[str]:
        """Return every key of the catalog."""
        return frozenset(self._messages)

    def __contains__(self, key: object) -> bool:
        return key in self._messages

    def placeholders(self, key: str) -> frozenset[str]:
        """Return the names of the placeholders of a message."""
        return frozenset(_placeholder_names(self._template(key)))

    def render(self, key: str, /, **params: object) -> str:
        """Return the text of ``key`` with its placeholders filled from ``params``."""
        template = self._template(key)
        try:
            return template.format_map(params)
        except KeyError as error:
            raise MessageRenderError(
                f"Message '{key}' needs the parameter {error}"
            ) from error

    def _template(self, key: str) -> str:
        try:
            return self._messages[key]
        except KeyError:
            raise MissingMessageError(key) from None


def _check_entry(key: object, text: object) -> None:
    if not isinstance(key, str) or MESSAGE_KEY_PATTERN.fullmatch(key) is None:
        raise ValueError(f"Invalid message key: {key!r}")
    if not isinstance(text, str):
        raise TypeError(f"Message '{key}' must be a string")
    for name in _placeholder_names(text):
        if not name.isidentifier():
            raise ValueError(f"Message '{key}' has an unsupported placeholder")


def _placeholder_names(template: str) -> list[str]:
    return [
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name is not None
    ]
