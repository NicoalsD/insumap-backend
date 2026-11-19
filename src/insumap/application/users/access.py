"""Scope rules shared by the staff use cases: the caller's clinic and its staff."""

from __future__ import annotations

from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.domain.identity.errors import PermissionDeniedError


def clinic_of(actor: Actor) -> UUID:
    """The clinic of the caller; a caller without a clinic has no staff to manage."""
    if actor.clinic_id is None:
        raise PermissionDeniedError
    return actor.clinic_id
