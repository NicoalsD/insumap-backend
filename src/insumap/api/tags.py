"""Swagger tags of the API, in Spanish."""

from enum import StrEnum


class ApiTag(StrEnum):
    """Name of each Swagger tag, as shown to the reader."""

    HEALTH = "Salud"
    META = "Metadatos"
    AUTH = "Autenticación"
    PUBLIC = "Público"
    CLINICS = "Clínicas"
    USERS = "Usuarios y membresías"
    PATIENTS = "Pacientes"
    IMPORTS = "Importación y credenciales"
    CARE_TEAM = "Equipo de atención"
    RECORDS = "Registros del paciente"
    TREATMENT = "Plan de tratamiento"
    METRICS = "Métricas glucémicas"
    ALERTS = "Alertas"
    NOTIFICATIONS = "Notificaciones"
    AI = "Recomendaciones IA"
    DASHBOARD = "Dashboard médico"
    REPORTS = "Reportes"
    MESSAGING = "Mensajería"
    AUDIT = "Auditoría"
    CONSENT = "Consentimiento y privacidad"
