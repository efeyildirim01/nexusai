-- Database roles. Run once by a superuser (docker-compose runs it automatically;
-- the test suite runs it against its own throwaway server).
--
--   nexus_owner  owns the schema and runs migrations. The API never connects as it.
--   nexus_app    what the API connects as. It is NOT the table owner, NOT a superuser
--                and has NO BYPASSRLS, so PostgreSQL Row-Level Security applies to it.
--
-- The passwords below are for local development only. Real environments provision
-- these roles with secrets from their secret store.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_owner') THEN
        CREATE ROLE nexus_owner LOGIN PASSWORD 'nexus_owner_dev'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexus_app') THEN
        CREATE ROLE nexus_app LOGIN PASSWORD 'nexus_app_dev'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;
