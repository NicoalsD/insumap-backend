"""Errors of the notification settings: a ``422`` with the field that is wrong."""

from __future__ import annotations

from typing import final

from insumap.shared.errors import ErrorCode, InsumapError


@final
class InvalidNotificationSettingError(InsumapError):
    """A setting does not follow its rule; ``detail`` names the field and the rule."""

    def __init__(self, field: str, rule: str) -> None:
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            detail={"errors": [{"field": field, "type": rule}]},
        )


@final
class PushEndpointRejectedError(InsumapError):
    """A Web Push endpoint is not an allowed push service (Seguridad.md 13.4)."""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [{"field": "body.endpoint", "type": "endpoint_rejected"}]
            },
        )
