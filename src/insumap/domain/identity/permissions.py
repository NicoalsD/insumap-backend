"""Permission codes of the catalog in ``docs/Actores-y-permisos.md``, section 3.2.

The role to permission matrix lives only in the database
(``iam.role_permissions``). A code the database grants but this enum does not
know grants nothing (deny by default).
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class PermissionCode(StrEnum):
    """One member per permission of ``iam.permissions``."""

    CLINICS_MANAGE = "clinics.manage"
    CLINIC_ADMINS_MANAGE = "clinic_admins.manage"
    CLINICS_READ = "clinics.read"
    SITES_MANAGE = "sites.manage"
    USERS_MANAGE = "users.manage"
    USERS_READ = "users.read"
    PATIENTS_IMPORT = "patients.import"
    IMPORT_BATCHES_READ = "import_batches.read"
    PATIENTS_READ_ROSTER = "patients.read_roster"
    PATIENTS_MANAGE_STATUS = "patients.manage_status"
    CREDENTIALS_ISSUE = "credentials.issue"
    CREDENTIALS_REVOKE = "credentials.revoke"
    CARE_TEAM_ASSIGN = "care_team.assign"
    CARE_TEAM_READ = "care_team.read"
    PATIENTS_READ_ASSIGNED = "patients.read_assigned"
    PATIENTS_READ_OWN = "patients.read_own"
    GLUCOSE_WRITE_OWN = "glucose.write_own"
    GLUCOSE_READ_OWN = "glucose.read_own"
    RECORDS_WRITE_OWN = "records.write_own"
    RECORDS_READ_OWN = "records.read_own"
    RECORDS_CORRECT_OWN = "records.correct_own"
    LABS_WRITE_OWN = "labs.write_own"
    LABS_WRITE_ASSIGNED = "labs.write_assigned"
    PROTOCOL_TEMPLATES_MANAGE = "protocol_templates.manage"
    PROTOCOL_TEMPLATES_READ = "protocol_templates.read"
    TREATMENT_PLANS_MANAGE = "treatment_plans.manage"
    TREATMENT_PLANS_READ_OWN = "treatment_plans.read_own"
    TARGET_PROFILES_MANAGE = "target_profiles.manage"
    TARGET_PROFILES_ASSIGN = "target_profiles.assign"
    REMINDERS_MANAGE_ASSIGNED = "reminders.manage_assigned"
    REMINDERS_MANAGE_OWN = "reminders.manage_own"
    METRICS_READ_ASSIGNED = "metrics.read_assigned"
    METRICS_READ_OWN = "metrics.read_own"
    ALERT_RULES_MANAGE = "alert_rules.manage"
    ALERT_RULES_READ = "alert_rules.read"
    ALERTS_READ_ASSIGNED = "alerts.read_assigned"
    ALERTS_READ_OWN = "alerts.read_own"
    ALERTS_ACKNOWLEDGE = "alerts.acknowledge"
    ALERTS_ACKNOWLEDGE_OWN = "alerts.acknowledge_own"
    ALERTS_RESOLVE = "alerts.resolve"
    ALERTS_READ_SUMMARY = "alerts.read_summary"
    NOTIFICATIONS_READ_OWN = "notifications.read_own"
    NOTIFICATION_PREFERENCES_MANAGE_OWN = "notification_preferences.manage_own"
    AI_FORECASTS_READ_ASSIGNED = "ai.forecasts.read_assigned"
    AI_FORECASTS_READ_OWN = "ai.forecasts.read_own"
    AI_RISK_READ_ASSIGNED = "ai.risk.read_assigned"
    AI_DROPOUT_RISK_READ = "ai.dropout_risk.read"
    RECOMMENDATIONS_READ_ASSIGNED = "recommendations.read_assigned"
    RECOMMENDATIONS_DECIDE = "recommendations.decide"
    CLINICAL_SUMMARIES_GENERATE = "clinical_summaries.generate"
    ASSISTANT_USE = "assistant.use"
    AI_EVALUATIONS_READ = "ai_evaluations.read"
    DASHBOARD_READ_ASSIGNED = "dashboard.read_assigned"
    CLINICAL_NOTES_MANAGE = "clinical_notes.manage"
    REPORTS_GENERATE_ASSIGNED = "reports.generate_assigned"
    REPORTS_GENERATE_OWN = "reports.generate_own"
    CLINIC_KPIS_READ = "clinic_kpis.read"
    REPORTS_GENERATE_CLINIC = "reports.generate_clinic"
    MESSAGES_USE_ASSIGNED = "messages.use_assigned"
    MESSAGES_USE_OWN = "messages.use_own"
    FOLLOW_UPS_MANAGE = "follow_ups.manage"
    FOLLOW_UPS_READ_OWN = "follow_ups.read_own"
    AUDIT_READ = "audit.read"
    AUDIT_READ_PLATFORM = "audit.read_platform"
    CONSENTS_MANAGE_OWN = "consents.manage_own"
    CONSENTS_READ_STATUS = "consents.read_status"
    PRIVACY_REQUESTS_CREATE_OWN = "privacy_requests.create_own"
    PRIVACY_REQUESTS_MANAGE = "privacy_requests.manage"
    DEMO_DATA_MANAGE = "demo_data.manage"

    @classmethod
    def known(cls, codes: Iterable[str]) -> frozenset[PermissionCode]:
        """Keep the codes this enum knows and drop the rest (deny by default)."""
        values = {member.value: member for member in cls}
        return frozenset(values[code] for code in codes if code in values)
