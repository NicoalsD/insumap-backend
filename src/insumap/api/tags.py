"""Swagger tags of the API, in Spanish."""

from enum import StrEnum


class ApiTag(StrEnum):
    """Name of each Swagger tag, as shown to the reader."""

    HEALTH = "Salud"
    META = "Metadatos"
    AUTH = "Autenticación"
    RECORDS = "Registros del paciente"
    METRICS = "Métricas glucémicas"
