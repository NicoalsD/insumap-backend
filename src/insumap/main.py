"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(
    title="Insumap API",
    description=(
        "API REST de Insumap, plataforma de monitoreo de pacientes con diabetes "
        "para clínicas. Proyecto académico: no es un dispositivo médico."
    ),
    version="0.1.0",
)
