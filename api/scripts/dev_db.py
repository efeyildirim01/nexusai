"""Local development database without Docker.

Starts an embedded PostgreSQL 16 (the `pgserver` package) in api/.devdb, applies the same
role and hardening scripts as docker-compose, runs the migrations, and prints the
environment variables for the API. The server keeps running after this script exits.

    python scripts/dev_db.py            # start (idempotent) and migrate
    python scripts/dev_db.py --env      # also write api/.env
"""

import argparse
import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

API_DIR = Path(__file__).resolve().parents[1]
INIT_DIR = API_DIR.parent / "db" / "init"
DATA_DIR = API_DIR / ".devdb"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", action="store_true", help="write api/.env")
    args = parser.parse_args()

    try:
        import pgserver
    except ImportError:
        sys.exit("pip install -e '.[local]' first, or use docker compose up")

    server = pgserver.get_server(DATA_DIR, cleanup_mode=None)  # type: ignore[attr-defined]
    admin = make_url(server.get_uri()).set(drivername="postgresql")

    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute((INIT_DIR / "01-roles.sql").read_text(encoding="utf-8"))  # type: ignore[arg-type]
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = 'nexusai'").fetchone()
        if not exists:
            conn.execute("CREATE DATABASE nexusai OWNER nexus_owner")
    harden = "\n".join(
        line
        for line in (INIT_DIR / "03-harden.sql").read_text(encoding="utf-8").splitlines()
        if not line.startswith("\\")
    )
    app_db = admin.set(database="nexusai")
    with psycopg.connect(app_db.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute(harden)  # type: ignore[arg-type]

    def url(user: str, password: str) -> str:
        return app_db.set(
            drivername="postgresql+psycopg", username=user, password=password
        ).render_as_string(hide_password=False)

    owner = url("nexus_owner", "nexus_owner_dev")
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", owner.replace("%", "%%"))
    command.upgrade(config, "head")

    env = {
        "NEXUS_DATABASE_URL": url("nexus_app", "nexus_app_dev"),
        "NEXUS_READONLY_DATABASE_URL": url("nexus_readonly", "nexus_readonly_dev"),
        "NEXUS_MIGRATIONS_DATABASE_URL": owner,
    }
    lines = [f"{k}={v}" for k, v in env.items()]
    print("\n".join(lines))
    if args.env:
        target = API_DIR / ".env"
        existing = target.read_text().splitlines() if target.exists() else []
        kept = [line for line in existing if line.split("=", 1)[0] not in env]
        if not any(line.startswith("NEXUS_JWT_SECRET=") for line in kept):
            import secrets

            kept.append(f"NEXUS_JWT_SECRET={secrets.token_urlsafe(48)}")
        target.write_text("\n".join(kept + lines) + "\n")
        print(f"Wrote {target}")


if __name__ == "__main__":
    main()
