"""Prepare a managed PostgreSQL database (Render free tier) for NexusAI.

The hosted equivalent of db/init/*.sql plus the docker-compose `migrate` job, for hosts
that give you an admin user but no superuser, shell or one-off jobs:

  1. creates nexus_owner, nexus_app and nexus_readonly with generated passwords
     (re-running rotates them), with the same attributes as db/init/01-roles.sql;
  2. lets nexus_owner create (and grant) objects in the public schema, which on a local
     stack it gets by owning the database;
  3. applies db/init/03-harden.sql when the admin user is allowed to, and says so when not;
  4. runs `alembic upgrade head` as nexus_owner;
  5. writes the nexus_app / nexus_readonly URLs for the API to .env.render (git-ignored).

Usage (from the repository root, with the API's virtualenv):

  NEXUS_ADMIN_DATABASE_URL='postgresql://nexus_admin:...@dpg-...render.com/nexusai' \
    api/.venv/Scripts/python scripts/provision_render.py

The API URLs use the database's internal hostname (the first label of the external one on
Render); set NEXUS_INTERNAL_DB_HOST to override it.
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".env.render"
SET_CONFIG = "pg_catalog.set_config(text, text, boolean)"

BASE = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
ROLES = {
    "nexus_owner": BASE,
    "nexus_app": BASE + " NOINHERIT",
    "nexus_readonly": BASE + " NOINHERIT CONNECTION LIMIT 20",
}


def url(user: str, password: str, host: str, port: str, dbname: str, sslmode: str) -> str:
    query = f"?sslmode={sslmode}" if sslmode else ""
    return f"postgresql+psycopg://{user}:{quote(password, safe='')}@{host}:{port}/{dbname}{query}"


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]  # keep order with alembic
    admin_url = os.environ.get("NEXUS_ADMIN_DATABASE_URL")
    if not admin_url:
        print("Set NEXUS_ADMIN_DATABASE_URL to the database's external admin URL.", file=sys.stderr)
        return 2
    params = conninfo_to_dict(admin_url)
    host, dbname = str(params["host"]), str(params["dbname"])
    port = str(params.get("port") or 5432)
    sslmode = str(params.get("sslmode") or ("require" if "render.com" in host else ""))
    internal_host = os.environ.get("NEXUS_INTERNAL_DB_HOST") or (
        host.split(".")[0] if host.endswith(".render.com") else host
    )

    passwords = {role: secrets.token_urlsafe(32) for role in ROLES}
    with psycopg.connect(admin_url, autocommit=True) as conn:
        superuser = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        is_superuser = bool(superuser.fetchone()[0])  # type: ignore[index]
        print(f"connected to {host}/{dbname} as {params.get('user')} (superuser: {is_superuser})")

        for role, attributes in ROLES.items():
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            # Only a superuser may restate NOSUPERUSER, so an existing role just gets a new
            # password; its attributes were set when it was created.
            statement = (
                "ALTER ROLE {} PASSWORD {}" if exists else "CREATE ROLE {} LOGIN PASSWORD {} "
            )
            conn.execute(
                sql.SQL(statement + ("" if exists else attributes)).format(
                    sql.Identifier(role), sql.Literal(passwords[role])
                )
            )
            print(f"{'rotated password of' if exists else 'created'} role {role}")

        # Safety nets for the AI query role, as in 01-roles.sql.
        conn.execute("ALTER ROLE nexus_readonly SET default_transaction_read_only = on")
        conn.execute("ALTER ROLE nexus_readonly SET statement_timeout = '5s'")
        conn.execute("ALTER ROLE nexus_readonly SET idle_in_transaction_session_timeout = '10s'")

        # Locally nexus_owner owns the database (and so the public schema). Here the admin
        # user owns both, so give nexus_owner what the migrations need, including the right
        # to grant schema usage to the other two roles.
        conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO nexus_owner WITH GRANT OPTION")

        # 03-harden.sql. A REVOKE without the privilege to do it is only a warning, so check
        # the outcome instead of relying on an error.
        try:
            conn.execute(f"REVOKE EXECUTE ON FUNCTION {SET_CONFIG} FROM PUBLIC")
            conn.execute(f"GRANT EXECUTE ON FUNCTION {SET_CONFIG} TO nexus_owner, nexus_app")
        except psycopg.errors.InsufficientPrivilege:
            pass
        check = conn.execute(
            "SELECT has_function_privilege('nexus_readonly', %s, 'EXECUTE')", (SET_CONFIG,)
        )
        readonly_can_set_config = bool(check.fetchone()[0])  # type: ignore[index]

    print("running migrations as nexus_owner")
    env = os.environ | {
        "NEXUS_MIGRATIONS_DATABASE_URL": url(
            "nexus_owner", passwords["nexus_owner"], host, port, dbname, sslmode
        )
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "api", env=env, check=True
    )

    def api_url(role: str) -> str:
        return url(role, passwords[role], internal_host, port, dbname, sslmode)

    OUTPUT.write_text(
        "# Generated by scripts/provision_render.py. Paste the two URLs into nexusai-api's\n"
        "# environment on Render. Keep this file private; it is git-ignored.\n"
        f"NEXUS_DATABASE_URL={api_url('nexus_app')}\n"
        f"NEXUS_READONLY_DATABASE_URL={api_url('nexus_readonly')}\n"
        "# nexus_owner (migrations only, external host; never give it to the API)\n"
        f"NEXUS_MIGRATIONS_DATABASE_URL={env['NEXUS_MIGRATIONS_DATABASE_URL']}\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.name}")

    if readonly_can_set_config:
        print(
            "WARNING: 03-harden.sql could not be applied (no superuser): nexus_readonly can still"
            " call set_config(). The SQL validator is the only guard for that function here."
        )
    else:
        print("03-harden.sql applied: nexus_readonly cannot call set_config()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
