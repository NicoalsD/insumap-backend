"""Protocol templates: versioned prototypes of the content of a treatment plan.

A template is a row of ``care.protocol_templates``. Its content is copied in
depth into a new plan (``clone_for_patient``, P05); the template itself does
not change, so the plans already created keep the version they were built from.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, final
from uuid import UUID

from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.treatment.content import PlanItem, TemplateContent
from insumap.domain.treatment.plan import TreatmentPlan

MACHINE_NAME: Final = "protocol_template"
FALLBACK_CODE: Final = "PROTOCOL"
CODE_PREFIX: Final = "P_"
"""Prefix of a code that would otherwise start with a digit (the DB needs a letter)."""
NON_CODE_CHARACTERS: Final = re.compile(r"[^A-Za-z0-9]+")


class TemplateStatus(StrEnum):
    """A template is ``ACTIVE`` while it can be cloned, then ``RETIRED``."""

    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


def derive_template_code(name: str, *, max_length: int) -> str:
    """The stable code of a template, derived from its name.

    The name is folded to ASCII (accents removed), upper-cased and every run of
    other characters becomes ``_``. The code starts with a letter and fits the
    column; a name with no usable letters gets ``FALLBACK_CODE``.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = NON_CODE_CHARACTERS.sub("_", folded).strip("_").upper()
    if not words:
        words = FALLBACK_CODE
    elif not words[0].isalpha():
        words = f"{CODE_PREFIX}{words}"
    return words[:max_length].rstrip("_")


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ProtocolTemplate:
    """One version of a protocol template.

    Pattern: P05 Prototype (``clone_for_patient``). The version is ``ACTIVE``
    while it is in use; the change to ``RETIRED`` is the only one it admits.
    """

    template_id: UUID
    clinic_id: UUID | None
    code: str
    name: str
    version: int
    status: TemplateStatus
    content: TemplateContent
    created_by: UUID | None
    created_at: datetime
    default_target_profile_id: UUID | None = None

    @property
    def is_active(self) -> bool:
        return self.status is TemplateStatus.ACTIVE

    def clone_for_patient(
        self,
        *,
        plan_id: UUID,
        clinic_id: UUID,
        patient_id: UUID,
        target_profile_id: UUID,
        version: int,
        item_ids: tuple[UUID, ...],
        created_by: UUID,
        at: datetime,
    ) -> TreatmentPlan:
        """P05: a new plan for a patient, in ``DRAFT``, with the content of this one.

        The identifiers arrive as arguments, one per item, so the copy never
        generates them and the template keeps its own.
        """
        self._require_active("clone")
        if len(item_ids) != len(self.content.items):
            raise ValueError("one new identifier per item is required")
        items = tuple(
            PlanItem.of(item_id, spec)
            for spec, item_id in zip(self.content.items, item_ids, strict=True)
        )
        return TreatmentPlan.draft(
            plan_id=plan_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            version=version,
            target_profile_id=target_profile_id,
            created_by=created_by,
            at=at,
            items=items,
            template_id=self.template_id,
            titration_rules=self.content.titration_rules,
        )

    def new_version(
        self,
        *,
        template_id: UUID,
        version: int,
        content: TemplateContent,
        created_by: UUID,
        at: datetime,
    ) -> ProtocolTemplate:
        """The next version of this template, ``ACTIVE``; this one is unchanged."""
        self._require_active("version")
        return ProtocolTemplate(
            template_id=template_id,
            clinic_id=self.clinic_id,
            code=self.code,
            name=self.name,
            version=version,
            status=TemplateStatus.ACTIVE,
            content=content,
            created_by=created_by,
            created_at=at,
            default_target_profile_id=self.default_target_profile_id,
        )

    def retired(self) -> ProtocolTemplate:
        """``ACTIVE`` to ``RETIRED``: it can no longer be cloned or versioned."""
        self._require_active("retire")
        return replace(self, status=TemplateStatus.RETIRED)

    def _require_active(self, action: str) -> None:
        if self.status is not TemplateStatus.ACTIVE:
            raise InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)
