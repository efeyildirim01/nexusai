"""Test harness: every test runs against a real PostgreSQL 16.

- CI sets NEXUS_TEST_ADMIN_URL to the docker-compose Postgres (superuser connection).
- Locally, without Docker, the `pgserver` package starts an embedded Postgres 16.

The superuser connection is only used to create roles and a throwaway database. Migrations
run as `nexus_owner`; the API under test connects as `nexus_app`, exactly as in production,
so the Row-Level Security policies are really in force during the tests.
"""

import os
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.main import create_app

API_DIR = Path(__file__).resolve().parents[1]
INIT_DIR = API_DIR.parent / "db" / "init"
TEST_DB = "nexusai_test"


@dataclass(frozen=True)
class DatabaseUrls:
    admin: str  # superuser, test setup only
    owner: str  # nexus_owner: migrations, test fixtures that must bypass RLS
    app: str  # nexus_app: what the API uses
    readonly: str  # nexus_readonly: what AI-generated SQL runs as


def _with_credentials(url: str, user: str, password: str, database: str) -> str:
    parsed = make_url(url).set(
        drivername="postgresql+psycopg", username=user, password=password, database=database
    )
    return parsed.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def admin_url() -> Iterator[str]:
    url = os.environ.get("NEXUS_TEST_ADMIN_URL")
    if url:
        yield url
        return
    try:
        import pgserver
    except ImportError:  # pragma: no cover - depends on the developer's machine
        pytest.exit(
            "No database: set NEXUS_TEST_ADMIN_URL or `pip install -e .[local]` for pgserver",
            returncode=2,
        )
    with tempfile.TemporaryDirectory(prefix="nexusai-pg-", ignore_cleanup_errors=True) as data_dir:
        server = pgserver.get_server(data_dir, cleanup_mode="stop")  # type: ignore[attr-defined]
        yield server.get_uri()


@pytest.fixture(scope="session")
def db_urls(admin_url: str) -> DatabaseUrls:
    admin_dsn = make_url(admin_url).set(drivername="postgresql")
    with psycopg.connect(admin_dsn.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute((INIT_DIR / "01-roles.sql").read_text(encoding="utf-8"))
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}" OWNER nexus_owner')
    # Same per-database hardening as docker-compose, minus psql's \connect line.
    harden = "\n".join(
        line
        for line in (INIT_DIR / "03-harden.sql").read_text(encoding="utf-8").splitlines()
        if not line.startswith("\\")
    )
    test_dsn = admin_dsn.set(database=TEST_DB).render_as_string(hide_password=False)
    with psycopg.connect(test_dsn, autocommit=True) as conn:
        conn.execute(harden)

    urls = DatabaseUrls(
        admin=admin_url,
        owner=_with_credentials(admin_url, "nexus_owner", "nexus_owner_dev", TEST_DB),
        app=_with_credentials(admin_url, "nexus_app", "nexus_app_dev", TEST_DB),
        readonly=_with_credentials(admin_url, "nexus_readonly", "nexus_readonly_dev", TEST_DB),
    )

    config = Config(str(API_DIR / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", urls.owner.replace("%", "%%"))
    command.upgrade(config, "head")
    return urls


@pytest.fixture(scope="session")
def owner_engine(db_urls: DatabaseUrls) -> Iterator[Engine]:
    engine = create_engine(db_urls.owner)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(db_urls: DatabaseUrls) -> Iterator[Engine]:
    """Raw engine connected as the runtime role, for tests that issue SQL directly."""
    engine = create_engine(db_urls.app)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_database(request: pytest.FixtureRequest) -> Iterator[None]:
    if "db_urls" not in request.fixturenames:
        yield
        return
    owner_engine: Engine = request.getfixturevalue("owner_engine")
    yield
    with owner_engine.begin() as conn:
        conn.execute(text("TRUNCATE tenants CASCADE"))


@pytest.fixture
def settings(db_urls: DatabaseUrls) -> Settings:
    return Settings(
        database_url=db_urls.app,
        readonly_database_url=db_urls.readonly,
        jwt_secret="test-secret-" + "x" * 40,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


def unique_slug(prefix: str = "acme") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
