BEGIN;

DO $$
BEGIN
    IF current_user IN ('auth_svc', 'agent_svc', 'domain_svc', 'eval_runner', 'db_migrator') THEN
        RAISE EXCEPTION 'Provisioning requires a separate administrator identity';
    END IF;
END
$$;

-- Quote passwords as SQL literals through psql, including punctuation and quotes.
SELECT format('CREATE ROLE %I LOGIN', name)
FROM (VALUES ('auth_svc'), ('agent_svc'), ('domain_svc'),
             ('eval_runner'), ('db_migrator')) AS roles(name)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = name)
\gexec

ALTER ROLE auth_svc NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD :'auth_password';
ALTER ROLE agent_svc NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD :'agent_password';
ALTER ROLE domain_svc NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD :'domain_password';
ALTER ROLE eval_runner NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
SELECT format('ALTER ROLE eval_runner PASSWORD %L', NULLIF(:'eval_password', '')) \gexec
ALTER ROLE db_migrator NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
SELECT format('ALTER ROLE db_migrator PASSWORD %L', NULLIF(:'migration_password', '')) \gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database())
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO auth_svc, agent_svc, domain_svc, eval_runner, db_migrator', current_database())
\gexec
SELECT format('REVOKE CREATE, TEMPORARY ON DATABASE %I FROM auth_svc, agent_svc, domain_svc, eval_runner', current_database())
\gexec
SELECT format('GRANT CREATE ON DATABASE %I TO db_migrator', current_database())
\gexec
REVOKE ALL ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION auth_svc;
CREATE SCHEMA IF NOT EXISTS agent AUTHORIZATION agent_svc;
CREATE SCHEMA IF NOT EXISTS domain AUTHORIZATION db_migrator;
CREATE SCHEMA IF NOT EXISTS eval AUTHORIZATION db_migrator;

-- Existing volumes can contain schemas and tables created by the old admin login.
ALTER SCHEMA auth OWNER TO auth_svc;
ALTER SCHEMA agent OWNER TO agent_svc;
ALTER SCHEMA domain OWNER TO db_migrator;
ALTER SCHEMA eval OWNER TO db_migrator;

SELECT format('ALTER %s %I.%I OWNER TO %I',
              CASE c.relkind WHEN 'S' THEN 'SEQUENCE'
                             WHEN 'v' THEN 'VIEW'
                             WHEN 'm' THEN 'MATERIALIZED VIEW'
                             WHEN 'f' THEN 'FOREIGN TABLE'
                             ELSE 'TABLE' END,
              n.nspname, c.relname, owners.owner_name)
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
JOIN (VALUES ('auth', 'auth_svc'), ('agent', 'agent_svc'),
             ('domain', 'db_migrator'), ('eval', 'db_migrator'))
     AS owners(schema_name, owner_name) ON owners.schema_name = n.nspname
WHERE c.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
  AND pg_get_userbyid(c.relowner) <> owners.owner_name
ORDER BY c.relkind = 'S'
\gexec

REVOKE ALL ON SCHEMA auth, agent, domain, eval FROM PUBLIC, auth_svc, agent_svc, domain_svc, eval_runner;
REVOKE ALL ON ALL TABLES IN SCHEMA auth, agent, domain, eval FROM PUBLIC, auth_svc, agent_svc, domain_svc, eval_runner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA auth, agent, domain, eval FROM PUBLIC, auth_svc, agent_svc, domain_svc, eval_runner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth, agent, domain, eval FROM PUBLIC, auth_svc, agent_svc, domain_svc, eval_runner;

-- Restore each owner's privileges after removing old cross-service grants.
GRANT USAGE, CREATE ON SCHEMA auth TO auth_svc;
GRANT ALL ON ALL TABLES IN SCHEMA auth TO auth_svc;
GRANT ALL ON ALL SEQUENCES IN SCHEMA auth TO auth_svc;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA auth TO auth_svc;
GRANT USAGE, CREATE ON SCHEMA agent TO agent_svc;
GRANT ALL ON ALL TABLES IN SCHEMA agent TO agent_svc;
GRANT ALL ON ALL SEQUENCES IN SCHEMA agent TO agent_svc;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA agent TO agent_svc;
GRANT USAGE ON SCHEMA domain TO domain_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA domain TO domain_svc;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA domain TO domain_svc;
GRANT USAGE ON SCHEMA eval TO eval_runner;
GRANT SELECT ON ALL TABLES IN SCHEMA eval TO eval_runner;

-- Apply the same permissions to tables created by subsequent migrations.
ALTER DEFAULT PRIVILEGES FOR ROLE db_migrator IN SCHEMA domain
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO domain_svc;
ALTER DEFAULT PRIVILEGES FOR ROLE db_migrator IN SCHEMA domain
    GRANT USAGE, SELECT ON SEQUENCES TO domain_svc;
ALTER DEFAULT PRIVILEGES FOR ROLE db_migrator IN SCHEMA eval
    GRANT SELECT ON TABLES TO eval_runner;
ALTER DEFAULT PRIVILEGES FOR ROLE db_migrator IN SCHEMA domain, eval
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

ALTER ROLE auth_svc SET search_path = auth, pg_catalog;
ALTER ROLE agent_svc SET search_path = agent, pg_catalog;
ALTER ROLE domain_svc SET search_path = domain, pg_catalog;
ALTER ROLE eval_runner SET search_path = eval, pg_catalog;

COMMIT;
