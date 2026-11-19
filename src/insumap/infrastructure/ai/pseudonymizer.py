"""``subject_ref``: the pseudonym of a patient for the AI (security 18.1)."""

from __future__ import annotations

from typing import final
from uuid import UUID

from insumap.domain.ai.subject_ref import (
    SUBJECT_REF_HEX_CHARS,
    SUBJECT_REF_PREFIX,
    SubjectRef,
)
from insumap.infrastructure.security.subkey_hasher import SubkeyHasher


@final
class HmacPseudonymizer:
    """Deterministic, keyed and not reversible without ``APP_HMAC_KEY``.

    The same patient always gets the same pseudonym, so the AI can correlate its
    own calls, and the pseudonym cannot be computed from the UUID alone.
    """

    def __init__(self, hasher: SubkeyHasher) -> None:  # built with Subkey.SUBJECT_REF
        self._hasher = hasher

    def subject_ref(self, patient_id: UUID) -> SubjectRef:
        digest = self._hasher.hexdigest(str(patient_id))
        return SubjectRef(f"{SUBJECT_REF_PREFIX}{digest[:SUBJECT_REF_HEX_CHARS]}")
