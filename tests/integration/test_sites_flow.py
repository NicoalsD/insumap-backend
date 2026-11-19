"""Sites over PostgreSQL 18: the real grants, RLS and the unique index (RF-15)."""

from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.support.db_seed import ADMIN_EMAIL, DEMO_PASSWORD, DOCTOR_EMAIL, DemoWorld

pytestmark = pytest.mark.integration

SITES = "/api/v1/sites"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(api: TestClient, email: str) -> Any:
    return api.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )


def _staff_headers(api: TestClient, email: str) -> dict[str, str]:
    """Enroll MFA on the first sign in, then sign in with a recovery code."""
    first = _login(api, email)
    assert first.json()["status"] == "MFA_ENROLLMENT_REQUIRED", first.text
    headers = _bearer(first.json()["access_token"])
    started = api.post("/api/v1/auth/mfa/enrollment", headers=headers)
    secret = parse_qs(urlsplit(started.json()["otpauth_uri"]).query)["secret"][0]
    confirmed = api.post(
        "/api/v1/auth/mfa/enrollment/confirm",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert confirmed.status_code == 200, confirmed.text
    second = _login(api, email)
    verified = api.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge_token": second.json()["challenge_token"],
            "code": confirmed.json()["recovery_codes"][0],
        },
    )
    assert verified.status_code == 200, verified.text
    return _bearer(verified.json()["access_token"])


@pytest.fixture
def admin(api: TestClient, demo_world: DemoWorld) -> dict[str, str]:
    del demo_world
    return _staff_headers(api, ADMIN_EMAIL)


def _other_clinic_site(migrated_url: str) -> UUID:
    """A site of a second clinic, inserted as the superuser (outside RLS)."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        clinic = conn.execute(
            "INSERT INTO clinic.clinics (name, tax_id, timezone, is_demo)"
            " VALUES (%s, %s, 'America/Bogota', true) RETURNING id",
            (f"Otra clínica {uuid4().hex[:8]}", uuid4().hex[:12]),
        ).fetchone()
        assert clinic is not None
        site = conn.execute(
            "INSERT INTO clinic.sites (clinic_id, name) VALUES (%s, 'Sede Ajena')"
            " RETURNING id",
            (clinic[0],),
        ).fetchone()
        assert site is not None
        return UUID(str(site[0]))


def test_create_list_and_rename_a_site_of_the_clinic(
    api: TestClient, admin: dict[str, str]
) -> None:
    created = api.post(SITES, headers=admin, json={"name": "  Sede Norte  "})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Sede Norte"
    assert body["simulated"] is True

    listed = api.get(SITES, headers=admin, params={"limit": 10})
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]

    renamed = api.patch(f"{SITES}/{body['id']}", headers=admin, json={"name": "Norte"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {"id": body["id"], "name": "Norte", "simulated": True}


def test_a_name_repeated_in_the_clinic_ignores_case(
    api: TestClient, admin: dict[str, str]
) -> None:
    assert (
        api.post(SITES, headers=admin, json={"name": "Sede Norte"}).status_code == 201
    )

    repeated = api.post(SITES, headers=admin, json={"name": "SEDE norte"})

    assert repeated.status_code == 409, repeated.text
    assert repeated.json()["error"]["code"] == "CONFLICT"


def test_another_clinics_site_is_not_found_and_stays_as_it_was(
    api: TestClient, admin: dict[str, str], migrated_url: str
) -> None:
    foreign = _other_clinic_site(migrated_url)

    patched = api.patch(f"{SITES}/{foreign}", headers=admin, json={"name": "Robada"})
    unknown = api.patch(f"{SITES}/{uuid4()}", headers=admin, json={"name": "Robada"})
    listed = api.get(SITES, headers=admin, params={"limit": 100})

    assert patched.status_code == unknown.status_code == 404
    assert patched.json() == unknown.json()
    assert str(foreign) not in [item["id"] for item in listed.json()["items"]]
    with psycopg.connect(migrated_url) as conn:
        name = conn.execute(
            "SELECT name FROM clinic.sites WHERE id = %s", (foreign,)
        ).fetchone()
    assert name == ("Sede Ajena",)


def test_replacing_a_staff_members_sites_twice(
    api: TestClient, admin: dict[str, str], demo_world: DemoWorld
) -> None:
    north = UUID(api.post(SITES, headers=admin, json={"name": "Norte"}).json()["id"])
    south = UUID(api.post(SITES, headers=admin, json={"name": "Sur"}).json()["id"])
    url = f"/api/v1/users/{demo_world.doctor_user_id}/sites"

    first = api.put(url, headers=admin, json={"site_ids": [str(north), str(north)]})
    second = api.put(url, headers=admin, json={"site_ids": [str(south)]})
    cleared = api.put(url, headers=admin, json={"site_ids": []})

    assert first.status_code == 200, first.text
    assert first.json()["site_ids"] == [str(north)]
    assert second.json()["site_ids"] == [str(south)]
    assert cleared.json()["site_ids"] == []
    assert first.json()["simulated"] is True


def test_staff_sites_refuse_a_site_of_another_clinic(
    api: TestClient,
    admin: dict[str, str],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    foreign = _other_clinic_site(migrated_url)
    url = f"/api/v1/users/{demo_world.doctor_user_id}/sites"

    response = api.put(url, headers=admin, json={"site_ids": [str(foreign)]})
    missing_user = api.put(
        f"/api/v1/users/{uuid4()}/sites", headers=admin, json={"site_ids": []}
    )

    assert response.status_code == 404, response.text
    assert response.json() == missing_user.json()
    with psycopg.connect(migrated_url) as conn:
        links = conn.execute(
            "SELECT count(*) FROM clinic.staff_sites WHERE user_id = %s",
            (demo_world.doctor_user_id,),
        ).fetchone()
    assert links == (0,)


def test_a_doctor_cannot_manage_sites(api: TestClient, demo_world: DemoWorld) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    response = api.post(SITES, headers=doctor, json={"name": "Sede Norte"})

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_each_write_leaves_one_audit_row(
    api: TestClient, admin: dict[str, str], migrated_url: str
) -> None:
    created = api.post(SITES, headers=admin, json={"name": "Sede Norte"}).json()
    api.patch(f"{SITES}/{created['id']}", headers=admin, json={"name": "Norte"})

    with psycopg.connect(migrated_url) as conn:
        rows = conn.execute(
            "SELECT action, entity_type, changed_fields FROM audit.audit_log"
            " WHERE entity_id = %s ORDER BY occurred_at",
            (UUID(created["id"]),),
        ).fetchall()
    assert rows == [
        ("SITE_CREATED", "SITE", ["name"]),
        ("SITE_UPDATED", "SITE", ["name"]),
    ]
