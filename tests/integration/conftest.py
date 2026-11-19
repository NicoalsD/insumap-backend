"""PostgreSQL 18 with the schema of ``db-schema.lock`` for integration tests.

The database comes from ``INSUMAP_TEST_DATABASE_URL`` (a superuser URL of a
throwaway database, as in CI) or, when it is not set and Docker answers, from a
Testcontainers ``postgres:18-alpine``. Without either, the tests are skipped.

The migrations are applied with the Alembic of ``insumap-database``, found at
``INSUMAP_DATABASE_REPO_PATH`` (default ``../insumap-database``) and checked out
at the tag of ``db-schema.lock``. The API connects as ``insumap_app``: no DDL
and subject to RLS, never as the superuser.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from insumap.container import Container
from insumap.main import create_app
from tests.support.db_seed import DemoWorld, seed_demo_world
from tests.support.settings import make_settings

ROOT = Path(__file__).resolve().parents[2]
DATABASE_REPO_VAR = "INSUMAP_DATABASE_REPO_PATH"
DATABASE_URL_VAR = "INSUMAP_TEST_DATABASE_URL"
POSTGRES_IMAGE = "postgres:18-alpine"
APP_ROLE = "insumap_app"
APP_ROLE_TEST_PASSWORD = "app-test-only"
ORIGIN = "https://app.example.test"
TRUNCATED_SCHEMAS = ("iam", "clinic")
SEEDED_TABLES = ("iam.roles", "iam.permissions", "iam.role_permissions")


def _database_repo() -> Path:
    path = Path(os.environ.get(DATABASE_REPO_VAR, ROOT.parent / "insumap-database"))
    if not (path / "alembic.ini").is_file():
        pytest.skip(f"{DATABASE_REPO_VAR} does not point at insumap-database: {path}")
    return path


def _plain_url(url: str) -> str:
    """psycopg and Alembic take ``postgresql://``; drop a ``+driver`` suffix."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(scheme=parts.scheme.split("+")[0]))


@pytest.fixture(scope="session")
def superuser_url() -> Iterator[str]:
    url = os.environ.get(DATABASE_URL_VAR)
    if url:
        yield _plain_url(url)
        return
    try:
        container = PostgresContainer(POSTGRES_IMAGE, driver=None)
        container.start()
    except Exception as error:
        pytest.skip(f"no {DATABASE_URL_VAR} and Docker is unavailable: {error}")
    try:
        yield _plain_url(container.get_connection_url())
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated_url(superuser_url: str) -> str:
    """Apply the migrations and give ``insumap_app`` a throwaway password."""
    repo = _database_repo()
    subprocess.run(  # noqa: S603 - fixed command, test only
        ["uv", "run", "--project", str(repo), "alembic", "upgrade", "head"],  # noqa: S607
        cwd=repo,
        env={**os.environ, "DATABASE_URL_MIGRATOR": superuser_url},
        check=True,
        capture_output=True,
    )
    with psycopg.connect(superuser_url, autocommit=True) as conn:
        conn.execute(f"ALTER ROLE {APP_ROLE} PASSWORD '{APP_ROLE_TEST_PASSWORD}'")
    return superuser_url


@pytest.fixture
def demo_world(migrated_url: str) -> DemoWorld:
    """Empty the identity tables (keeping the seeded catalogs) and seed again."""
    settings = make_settings()
    with psycopg.connect(migrated_url) as conn:
        tables = conn.execute(
            "SELECT schemaname || '.' || tablename FROM pg_tables"
            " WHERE schemaname = ANY(%s)",
            (list(TRUNCATED_SCHEMAS),),
        ).fetchall()
        names = [row[0] for row in tables if row[0] not in SEEDED_TABLES]
        conn.execute("SET session_replication_role = replica")
        conn.execute(f"TRUNCATE {', '.join(names)}")
        conn.execute("SET session_replication_role = DEFAULT")
        return seed_demo_world(conn, settings)


@pytest.fixture
def app_url(migrated_url: str) -> str:
    parts = urlsplit(migrated_url)
    host = parts.hostname or "localhost"
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{APP_ROLE}:{APP_ROLE_TEST_PASSWORD}@{host}{port}"
    return urlunsplit(parts._replace(netloc=netloc))


@pytest.fixture
def api(app_url: str, demo_world: DemoWorld) -> Iterator[TestClient]:
    """The real app over PostgreSQL: real repositories, Argon2id, JWT and TOTP."""
    settings = make_settings(database_url=app_url, cors_origins=[ORIGIN])
    app = create_app(Container(settings))
    with TestClient(
        app, base_url="https://testserver", raise_server_exceptions=False
    ) as client:
        yield client
