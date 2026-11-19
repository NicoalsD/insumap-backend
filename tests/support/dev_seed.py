"""Semilla de desarrollo: una clínica con pacientes, lecturas y metas.

Se ejecuta una sola vez contra una base migrada, con el superusuario en
``DATABASE_URL_MIGRATOR`` y los secretos de la API en el entorno::

    uv run python -m tests.support.dev_seed

Crea las cuentas de ``db_seed`` (con nombres neutros), el perfil de metas por
defecto, los ajustes globales de la clínica y 12 pacientes asignados a la
médica con 14 días de lecturas CGM cada 15 minutos. Nunca la apuntes a una
base compartida.

Valores clínicos: el perfil usa el consenso internacional de tiempo en rango
(Battelino et al., Diabetes Care 2019;42:1593) y las metas de la ADA. Quedan
pendientes de validación por el equipo clínico.
"""

import math
import os
import random
import uuid
from datetime import UTC, date, datetime, timedelta

import psycopg

from insumap.shared.config import Settings
from tests.support import db_seed

CLINIC_NAME = "Clínica del Valle"
NOTICE_TEXT = (
    "Tratamos tus datos de salud para el seguimiento de tu diabetes por parte "
    "del equipo de tu clínica."
)
DAYS = 14
STEP_MINUTES = 15

# (mrn, nombre, nacimiento, sexo, tipo, IMC, media mg/dL, desviación, picos)
PATIENTS = [
    (
        "VAL-0101",
        "Camila Restrepo Gómez",
        date(1991, 5, 12),
        "FEMALE",
        "T1D",
        23.4,
        142,
        38,
        1.0,
    ),
    (
        "VAL-0102",
        "Andrés Felipe Ochoa",
        date(1984, 9, 3),
        "MALE",
        "T1D",
        26.1,
        188,
        62,
        1.4,
    ),
    (
        "VAL-0103",
        "Luz Marina Cárdenas",
        date(1957, 1, 22),
        "FEMALE",
        "T2D",
        29.8,
        168,
        45,
        1.0,
    ),
    (
        "VAL-0104",
        "Jorge Iván Marín",
        date(1963, 11, 30),
        "MALE",
        "T2D",
        31.2,
        214,
        70,
        1.5,
    ),
    (
        "VAL-0105",
        "Sofía Valencia Ruiz",
        date(2001, 7, 8),
        "FEMALE",
        "T1D",
        21.0,
        122,
        52,
        1.2,
    ),
    (
        "VAL-0106",
        "Héctor Mauricio Peña",
        date(1952, 3, 17),
        "MALE",
        "T2D",
        27.5,
        156,
        34,
        0.8,
    ),
    (
        "VAL-0107",
        "Daniela Orozco Vélez",
        date(1996, 12, 1),
        "FEMALE",
        "T1D",
        24.6,
        176,
        58,
        1.3,
    ),
    (
        "VAL-0108",
        "Ricardo Salcedo Mejía",
        date(1972, 6, 25),
        "MALE",
        "T2D",
        33.9,
        238,
        74,
        1.6,
    ),
    (
        "VAL-0109",
        "Martha Lucía Duque",
        date(1948, 8, 14),
        "FEMALE",
        "T2D",
        25.3,
        148,
        30,
        0.8,
    ),
    (
        "VAL-0110",
        "Tomás Arango Builes",
        date(2009, 2, 19),
        "MALE",
        "T1D",
        19.8,
        164,
        66,
        1.4,
    ),
    (
        "VAL-0111",
        "Natalia Gaviria Toro",
        date(1989, 10, 5),
        "FEMALE",
        "GDM",
        28.2,
        112,
        24,
        0.7,
    ),
    (
        "VAL-0112",
        "Óscar Eduardo Londoño",
        date(1966, 4, 9),
        "MALE",
        "T2D",
        30.4,
        132,
        28,
        0.7,
    ),
]


def _glucose_series(
    rng: random.Random, mean: float, spread: float, peaks: float, start: datetime
) -> list[tuple[datetime, float]]:
    """Curva diaria con picos tras las comidas y ruido; nunca fuera de 40-400."""
    points: list[tuple[datetime, float]] = []
    steps = DAYS * 24 * 60 // STEP_MINUTES
    drift = rng.uniform(-8, 8)
    for index in range(steps):
        at = start + timedelta(minutes=index * STEP_MINUTES)
        hour = (at.hour + at.minute / 60 - 5) % 24  # hora local de Bogotá (UTC-5)
        meals = sum(
            amp * math.exp(-((hour - center) ** 2) / 1.6)
            for center, amp in ((8.0, 0.9), (13.0, 1.0), (19.5, 0.8))
        )
        night = -0.35 if 1 <= hour <= 5 else 0.0
        wobble = rng.gauss(0, 0.28)
        value = mean + spread * (peaks * meals + night + wobble) + drift
        points.append((at, round(min(400.0, max(42.0, value)), 1)))
    return points


def seed_dev(conn: psycopg.Connection, settings: Settings) -> db_seed.DemoWorld:
    """Siembra la clínica, el perfil de metas, los ajustes y los pacientes."""
    db_seed.NOTICE_TEXT = NOTICE_TEXT  # el aviso es inmutable: se siembra ya neutro
    db_seed.DEMO_CLINIC_NAME = CLINIC_NAME
    world = db_seed.seed_demo_world(conn, settings)
    clinic, admin, doctor = world.clinic_id, world.admin_user_id, world.doctor_user_id
    conn.execute("UPDATE clinic.clinics SET is_demo = false WHERE id = %s", (clinic,))
    for user_id, name in ((admin, "Laura Gutiérrez"), (doctor, "Marta Quintero")):
        conn.execute(
            "UPDATE clinic.staff_profiles SET full_name = %s WHERE user_id = %s",
            (name, user_id),
        )
    conn.execute(
        "UPDATE clinic.patients SET full_name = 'Pedro Ramírez', sex = 'MALE',"
        " diabetes_type = 'T2D', bmi = 27.9 WHERE user_id = %s",
        (world.patient_user_id,),
    )
    conn.execute(
        "UPDATE clinic.patients SET full_name = 'Ana Torres', sex = 'FEMALE',"
        " diabetes_type = 'T1D' WHERE user_id = %s",
        (world.invited_user_id,),
    )
    conn.execute(
        "INSERT INTO clinic.clinic_settings (clinic_id,"
        " recommendation_expiry_hours, forecast_refresh_minutes,"
        " dropout_inactivity_days, kpi_min_cell_size)"
        " VALUES (NULL, 24, 15, 7, 5)"
    )
    profile = db_seed._one(
        conn,
        "INSERT INTO care.target_profiles (clinic_id, code, label, population,"
        " version, status, is_default, range_low_mg_dl, range_high_mg_dl,"
        " very_low_mg_dl, very_high_mg_dl, tir_min_pct, tbr_l1_max_pct,"
        " tbr_l2_max_pct, tar_l1_max_pct, tar_l2_max_pct, cv_max_pct,"
        " min_data_sufficiency_pct, min_days, max_gap_minutes,"
        " hypo_episode_min_minutes, min_readings_for_cv,"
        " min_readings_for_cv_smbg, hba1c_goal_pct, fasting_low_mg_dl,"
        " fasting_high_mg_dl, postprandial_max_mg_dl, postprandial_1h_max_mg_dl,"
        " postprandial_2h_max_mg_dl, night_start, night_end, source_reference,"
        " activated_at)"
        " VALUES (NULL, 'ADULT_STANDARD', 'Adulto con diabetes tipo 1 o 2', 'ADULT',"
        " 1, 'ACTIVE', true, 70, 180, 54, 250, 70, 4, 1, 25, 5, 36, 70, 14, 15,"
        " 15, 100, 30, 7.0, 80, 130, 180, 180, 180, '00:00', '06:00',"
        " 'Battelino et al., Diabetes Care 2019;42:1593; ADA Standards of Care',"
        " now()) RETURNING id",
        (),
    )
    rng = random.Random(20261119)  # noqa: S311 - datos de desarrollo, no criptografía
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    start = now - timedelta(days=DAYS)
    start = start.replace(minute=(start.minute // STEP_MINUTES) * STEP_MINUTES)
    people: list[tuple[uuid.UUID, uuid.UUID, tuple[float, float, float]]] = []
    for mrn, name, born, sex, kind, bmi, mean, spread, peaks in PATIENTS:
        user_id, patient_id = db_seed.add_imported_patient(
            conn, clinic, mrn, name, born, None
        )
        conn.execute(
            "UPDATE clinic.patients SET sex = %s, diabetes_type = %s, bmi = %s"
            " WHERE id = %s",
            (sex, kind, bmi, patient_id),
        )
        people.append((user_id, patient_id, (float(mean), float(spread), float(peaks))))
    own = conn.execute(
        "SELECT id FROM clinic.patients WHERE user_id = %s", (world.patient_user_id,)
    ).fetchone()
    assert own is not None
    people.append((world.patient_user_id, own[0], (158.0, 46.0, 1.1)))
    for user_id, patient_id, curve in people:
        level, spread_mg, peak_gain = curve
        conn.execute(
            "INSERT INTO clinic.care_team_assignments (clinic_id, patient_id,"
            " doctor_user_id, is_primary, assigned_by) VALUES (%s, %s, %s, true, %s)",
            (clinic, patient_id, doctor, admin),
        )
        conn.execute(
            "INSERT INTO care.patient_target_assignments (clinic_id, patient_id,"
            " target_profile_id, assigned_by, reason)"
            " VALUES (%s, %s, %s, %s, 'Perfil por defecto de la clínica')",
            (clinic, patient_id, profile, admin),
        )
        rows = [
            (clinic, patient_id, uuid.uuid4(), at, value, "CGM", user_id)
            for at, value in _glucose_series(rng, level, spread_mg, peak_gain, start)
        ]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO monitoring.glucose_readings (clinic_id, patient_id,"
                " client_reading_id, measured_at, value_mg_dl, source, recorded_by)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                rows,
            )
    return world


def main() -> None:
    """Siembra ``DATABASE_URL_MIGRATOR`` y lista las cuentas (sin secretos)."""
    with psycopg.connect(os.environ["DATABASE_URL_MIGRATOR"]) as conn:
        seed_dev(conn, Settings())
    print(
        f"{CLINIC_NAME} sembrada con 13 pacientes y {DAYS} días de lecturas.\n"
        f"  PACIENTE      {db_seed.PATIENT_EMAIL}\n"
        f"  MÉDICA        {db_seed.DOCTOR_EMAIL} (enrola MFA al primer ingreso)\n"
        f"  ADMIN         {db_seed.ADMIN_EMAIL} (enrola MFA al primer ingreso)\n"
        "  Contraseña: DEMO_PASSWORD; código de activación: ACTIVATION_CODE\n"
        "  (constantes de tests/support/db_seed.py)"
    )


if __name__ == "__main__":
    main()
