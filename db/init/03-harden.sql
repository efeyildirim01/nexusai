-- Per-database hardening; must run as a superuser inside the application database.
\connect nexusai

-- set_config() can change app.tenant_id (and with it the RLS scope) from inside a SELECT.
-- Only the API's own role may call it; the AI query role cannot, even if a generated query
-- slipped past the SQL validator. (The API sets the tenant for that role with SET LOCAL.)
REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) TO nexus_owner, nexus_app;
