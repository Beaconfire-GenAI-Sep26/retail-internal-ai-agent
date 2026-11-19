#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 \
  --set db="$POSTGRES_DB" --set auth_password="$AUTH_DB_PASSWORD" \
  --set domain_password="$DOMAIN_DB_PASSWORD" --set agent_password="$AGENT_DB_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE auth_svc LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'auth_svc') \gexec
SELECT 'CREATE ROLE domain_svc LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'domain_svc') \gexec
SELECT 'CREATE ROLE agent_svc LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_svc') \gexec
SELECT format('ALTER ROLE auth_svc PASSWORD %L', :'auth_password') \gexec
SELECT format('ALTER ROLE domain_svc PASSWORD %L', :'domain_password') \gexec
SELECT format('ALTER ROLE agent_svc PASSWORD %L', :'agent_password') \gexec
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO auth_svc, domain_svc, agent_svc;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION auth_svc;
CREATE SCHEMA IF NOT EXISTS domain AUTHORIZATION domain_svc;
CREATE SCHEMA IF NOT EXISTS agent AUTHORIZATION agent_svc;
CREATE SCHEMA IF NOT EXISTS eval;
REVOKE ALL ON SCHEMA auth, domain, agent, eval FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA auth TO auth_svc;
GRANT USAGE, CREATE ON SCHEMA domain TO domain_svc;
GRANT USAGE, CREATE ON SCHEMA agent TO agent_svc;
GRANT ALL ON ALL TABLES IN SCHEMA auth TO auth_svc;
GRANT ALL ON ALL TABLES IN SCHEMA domain TO domain_svc;
GRANT ALL ON ALL TABLES IN SCHEMA agent TO agent_svc;
GRANT ALL ON ALL SEQUENCES IN SCHEMA auth TO auth_svc;
GRANT ALL ON ALL SEQUENCES IN SCHEMA domain TO domain_svc;
GRANT ALL ON ALL SEQUENCES IN SCHEMA agent TO agent_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT ALL ON TABLES TO auth_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA domain GRANT ALL ON TABLES TO domain_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT ALL ON TABLES TO agent_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth GRANT ALL ON SEQUENCES TO auth_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA domain GRANT ALL ON SEQUENCES TO domain_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA agent GRANT ALL ON SEQUENCES TO agent_svc;
REVOKE ALL ON SCHEMA domain, agent, eval FROM auth_svc;
REVOKE ALL ON SCHEMA auth, agent, eval FROM domain_svc;
REVOKE ALL ON SCHEMA auth, domain, eval FROM agent_svc;
SQL
