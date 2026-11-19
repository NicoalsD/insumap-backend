"""Catalog of the injection sites: the codes the database and the API share.

``injection_site`` is stored as ``varchar(14)`` with a CHECK over these codes and
``injection_spot`` as a ``smallint`` from 1 to 4. Left and right are the patient's.
"""

from __future__ import annotations

from enum import StrEnum

SPOT_MIN = 1
SPOT_MAX = 4
ALL_SPOTS: tuple[int, ...] = tuple(range(SPOT_MIN, SPOT_MAX + 1))


class SiteGroup(StrEnum):
    """The body zone of a site; the preference of an insulin kind works on zones."""

    ABDOMEN = "ABDOMEN"
    THIGH = "THIGH"
    ARM = "ARM"
    BUTTOCK = "BUTTOCK"


class SiteCode(StrEnum):
    """One of the eight sites. The declaration order is the canonical order."""

    ABDOMEN_RIGHT = "ABDOMEN_RIGHT"
    ABDOMEN_LEFT = "ABDOMEN_LEFT"
    THIGH_RIGHT = "THIGH_RIGHT"
    THIGH_LEFT = "THIGH_LEFT"
    ARM_RIGHT = "ARM_RIGHT"
    ARM_LEFT = "ARM_LEFT"
    BUTTOCK_RIGHT = "BUTTOCK_RIGHT"
    BUTTOCK_LEFT = "BUTTOCK_LEFT"

    @property
    def group(self) -> SiteGroup:
        return SiteGroup(self.value.rsplit("_", 1)[0])

    @property
    def is_left(self) -> bool:
        return self.value.endswith("_LEFT")


SITE_ORDER: tuple[SiteCode, ...] = tuple(SiteCode)


class PregnancyStatus(StrEnum):
    """``clinic.patients.pregnancy_status``."""

    NONE = "NONE"
    PREGNANT = "PREGNANT"
    UNKNOWN = "UNKNOWN"


class SiteState(StrEnum):
    """What the app shows for a site."""

    SUGGESTED = "SUGGESTED"
    ALLOWED = "ALLOWED"
    RECENT = "RECENT"
    AVOID = "AVOID"


class ReasonCode(StrEnum):
    """Why a site is suggested or avoided; the app translates each code."""

    PLAN_RESTRICTED = "PLAN_RESTRICTED"
    LIPOHYPERTROPHY_REPORTED = "LIPOHYPERTROPHY_REPORTED"
    PREGNANCY_AVOID_ABDOMEN_CENTER = "PREGNANCY_AVOID_ABDOMEN_CENTER"
    LEAN_AVOID_LIMBS = "LEAN_AVOID_LIMBS"
    RECENTLY_USED = "RECENTLY_USED"
    FASTEST_ABSORPTION = "FASTEST_ABSORPTION"
    STEADY_ABSORPTION = "STEADY_ABSORPTION"
    ROTATE_NEXT = "ROTATE_NEXT"


class NeedleNote(StrEnum):
    """The needle advice: always 4 mm, with or without the skin pinch."""

    PINCH_OPTIONAL = "NEEDLE_4MM_PINCH_OPTIONAL"
    PINCH_UP = "NEEDLE_4MM_PINCH_UP"
