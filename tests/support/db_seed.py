"""Fictitious identity rows for integration tests and the local Swagger demo.

Rows are inserted with a superuser connection (it bypasses RLS), the way the
importer and the simulator will create them later. Names are fictitious, emails
use the reserved ``example.test`` domain and documents are deliberately invalid.

Run ``uv run python -m tests.support.db_seed`` with ``DATABASE_URL_MIGRATOR``
(superuser) and the API secrets in the environment to seed a migrated local
database; it prints the demo credentials. Never point it at a shared database.
"""

import hashlib
import os
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

from insumap.application.identity.ports import CodePurpose
from insumap.domain.identity.codes import ActivationCode
from insumap.infrastructure.security.code_hasher import HmacCodeHasher
from insumap.infrastructure.security.keys import KeyRing
from insumap.infrastructure.security.password_hasher import (
    Argon2PasswordHasher,
    PasswordHashingConfig,
)
from insumap.shared.config import Settings

DEMO_CLINIC_NAME = "Clínica Demo Insumap"
DEMO_TAX_ID = "900000000-1"
DEMO_TIMEZONE = "America/Bogota"
PATIENT_EMAIL = "paciente.demo@example.test"
DOCTOR_EMAIL = "medica.demo@example.test"
ADMIN_EMAIL = "admin.demo@example.test"
DEMO_PASSWORD = "contrasena-demo-larga"
INVITED_BIRTH_DATE = date(1975, 6, 15)
ACTIVATION_CODE = "7K3F-9QXM-2D8H-WV4T"
NOTICE_VERSION = "2026-11-01"
NOTICE_TEXT = "Aviso de privacidad de la clínica demo (datos simulados)."
INVITATION_DAYS = 7


@dataclass(frozen=True, slots=True)
class DemoWorld:
    """Ids of the seeded rows."""

    clinic_id: UUID
    patient_user_id: UUID
    doctor_user_id: UUID
    admin_user_id: UUID
    invited_user_id: UUID
    notice_id: UUID


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _one(conn: psycopg.Connection, sql: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    value = row[0]
    assert isinstance(value, UUID)
    return value


def _user(
    conn: psycopg.Connection, email: str | None, password_hash: str | None, status: str
) -> UUID:
    return _one(
        conn,
        "INSERT INTO iam.users (email, email_normalized, password_hash, status)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (email, email, password_hash, status),
    )


def _membership(
    conn: psycopg.Connection, user_id: UUID, clinic_id: UUID, role_code: str
) -> None:
    conn.execute(
        "INSERT INTO iam.memberships (user_id, clinic_id, role_id)"
        " SELECT %s, %s, id FROM iam.roles WHERE code = %s",
        (user_id, clinic_id, role_code),
    )


def _patient(
    conn: psycopg.Connection,
    clinic_id: UUID,
    user_id: UUID,
    mrn: str,
    full_name: str,
    birth_date: date,
) -> UUID:
    return _one(
        conn,
        "INSERT INTO clinic.patients (clinic_id, user_id, mrn, full_name,"
        " birth_date, document_type, document_hash, document_hash_key_id,"
        " document_ciphertext, document_key_id, document_last4)"
        " VALUES (%s, %s, %s, %s, %s, 'CC', %s, %s, %s, %s, '0000') RETURNING id",
        (
            clinic_id,
            user_id,
            mrn,
            full_name,
            birth_date,
            _digest(f"{clinic_id}{mrn}"),
            "0" * 16,
            b"invalid-document",
            "0" * 16,
        ),
    )


def seed_demo_world(conn: psycopg.Connection, settings: Settings) -> DemoWorld:
    """Insert a demo clinic, three active accounts and one pending invitation."""
    hasher = Argon2PasswordHasher(
        PasswordHashingConfig(
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
            max_concurrency=settings.password_hash_max_concurrency,
        )
    )
    codes = HmacCodeHasher(
        KeyRing(
            current=settings.code_hmac_key, previous=settings.code_hmac_key_previous
        )
    )
    password_hash = hasher.hash(DEMO_PASSWORD)
    clinic_id = _one(
        conn,
        "INSERT INTO clinic.clinics (name, tax_id, timezone, is_demo)"
        " VALUES (%s, %s, %s, true) RETURNING id",
        (DEMO_CLINIC_NAME, DEMO_TAX_ID, DEMO_TIMEZONE),
    )
    admin = _user(conn, ADMIN_EMAIL, password_hash, "ACTIVE")
    doctor = _user(conn, DOCTOR_EMAIL, password_hash, "ACTIVE")
    patient_user = _user(conn, PATIENT_EMAIL, password_hash, "ACTIVE")
    invited = _user(conn, None, None, "INVITED")
    _membership(conn, admin, clinic_id, "CLINIC_ADMIN")
    _membership(conn, doctor, clinic_id, "DOCTOR")
    _membership(conn, patient_user, clinic_id, "PATIENT")
    _membership(conn, invited, clinic_id, "PATIENT")
    for user_id, name in ((admin, "Laura Admin Demo"), (doctor, "Marta Médica Demo")):
        conn.execute(
            "INSERT INTO clinic.staff_profiles (user_id, clinic_id, full_name)"
            " VALUES (%s, %s, %s)",
            (user_id, clinic_id, name),
        )
    notice_id = _one(
        conn,
        "INSERT INTO clinic.privacy_notice_versions (clinic_id, version, content,"
        " content_sha256, effective_from, is_current, published_by)"
        " VALUES (%s, %s, %s, %s, now(), true, %s) RETURNING id",
        (clinic_id, NOTICE_VERSION, NOTICE_TEXT, _digest(NOTICE_TEXT), admin),
    )
    active_patient = _patient(
        conn,
        clinic_id,
        patient_user,
        "DEMO-0001",
        "Pedro Paciente Demo",
        date(1968, 3, 2),
    )
    conn.execute(
        "INSERT INTO clinic.patient_consents (clinic_id, patient_id,"
        " privacy_notice_version_id, scope, action, recorded_by)"
        " VALUES (%s, %s, %s, 'SENSITIVE_DATA_PROCESSING', 'ACCEPTED', %s)",
        (clinic_id, active_patient, notice_id, patient_user),
    )
    invited_patient = _patient(
        conn, clinic_id, invited, "DEMO-0002", "Ana Invitada Demo", INVITED_BIRTH_DATE
    )
    code = ActivationCode.parse(ACTIVATION_CODE)
    assert code is not None
    keyed = codes.hash_for_storage(CodePurpose.ACTIVATION, code.value)
    conn.execute(
        "INSERT INTO iam.credential_invitations (clinic_id, user_id, patient_id,"
        " purpose, channel, code_hash, code_key_id, expires_at, issued_by)"
        " VALUES (%s, %s, %s, 'PATIENT_ACTIVATION', 'PRINT', %s, %s,"
        " now() + make_interval(days => %s), %s)",
        (
            clinic_id,
            invited,
            invited_patient,
            keyed.value,
            keyed.key_id,
            INVITATION_DAYS,
            admin,
        ),
    )
    return DemoWorld(
        clinic_id=clinic_id,
        patient_user_id=patient_user,
        doctor_user_id=doctor,
        admin_user_id=admin,
        invited_user_id=invited,
        notice_id=notice_id,
    )


def main() -> None:
    """Seed the database of ``DATABASE_URL_MIGRATOR`` and print the credentials."""
    url = os.environ["DATABASE_URL_MIGRATOR"]
    with psycopg.connect(url) as conn:
        seed_demo_world(conn, Settings())
    print(
        f"Clínica demo sembrada. Contraseña de las tres cuentas: {DEMO_PASSWORD}\n"
        f"  PATIENT       {PATIENT_EMAIL}\n"
        f"  DOCTOR        {DOCTOR_EMAIL} (pide enrolar MFA)\n"
        f"  CLINIC_ADMIN  {ADMIN_EMAIL} (pide enrolar MFA)\n"
        f"  Activación: código {ACTIVATION_CODE}, nacimiento {INVITED_BIRTH_DATE}"
    )


if __name__ == "__main__":
    main()
