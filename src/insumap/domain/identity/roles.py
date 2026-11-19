"""Roles of the system (RBAC). Authorization checks permission codes, not roles."""

from enum import StrEnum


class Role(StrEnum):
    """Role of a user, as seeded in ``iam.roles.code``."""

    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    CLINIC_ADMIN = "CLINIC_ADMIN"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"
    SYSTEM = "SYSTEM"
    """Scheduler and system jobs (``app.role = 'SYSTEM'``). No session carries it."""
