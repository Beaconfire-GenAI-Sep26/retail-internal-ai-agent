\set ON_ERROR_STOP on
BEGIN;

-- All probes disappear on rollback, including after a failing psql session.
SET LOCAL ROLE db_migrator;
CREATE TABLE domain.__scrum13_probe (id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY, value text);
CREATE TABLE eval.__scrum13_probe (value text);
INSERT INTO eval.__scrum13_probe VALUES ('expected outcome');
RESET ROLE;

SET LOCAL ROLE auth_svc;
CREATE TABLE auth.__scrum13_probe (value text);
RESET ROLE;
SET LOCAL ROLE agent_svc;
CREATE TABLE agent.__scrum13_probe (value text);
RESET ROLE;

DO $$
DECLARE
    identity_name text;
    schema_name text;
BEGIN
    FOREACH identity_name IN ARRAY ARRAY['auth_svc', 'agent_svc', 'domain_svc', 'eval_runner'] LOOP
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = identity_name
                   AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
            RAISE EXCEPTION 'Excessive role attributes for %', identity_name;
        END IF;
        IF has_database_privilege(identity_name, current_database(), 'CREATE') THEN
            RAISE EXCEPTION '% can create arbitrary schemas', identity_name;
        END IF;

        EXECUTE format('SET LOCAL ROLE %I', identity_name);
        FOREACH schema_name IN ARRAY ARRAY['auth', 'agent', 'domain', 'eval'] LOOP
            IF (identity_name, schema_name) IN (('auth_svc', 'auth'), ('agent_svc', 'agent'),
                                               ('domain_svc', 'domain'), ('eval_runner', 'eval')) THEN
                EXECUTE format('SELECT * FROM %I.__scrum13_probe', schema_name);
            ELSE
                BEGIN
                    EXECUTE format('SELECT * FROM %I.__scrum13_probe', schema_name);
                    RAISE EXCEPTION '% can read forbidden schema %', identity_name, schema_name;
                EXCEPTION WHEN insufficient_privilege THEN
                    NULL;
                END;
            END IF;
        END LOOP;

        IF identity_name = 'eval_runner' THEN
            BEGIN
                INSERT INTO eval.__scrum13_probe VALUES ('unauthorized write');
                RAISE EXCEPTION 'Evaluation identity can write answers';
            EXCEPTION WHEN insufficient_privilege THEN
                NULL;
            END;
        ELSE
            schema_name := replace(identity_name, '_svc', '');
            EXECUTE format('INSERT INTO %I.__scrum13_probe (value) VALUES (%L)', schema_name, 'runtime write');
            EXECUTE format('UPDATE %I.__scrum13_probe SET value = %L', schema_name, 'updated');
            EXECUTE format('DELETE FROM %I.__scrum13_probe', schema_name);
        END IF;
        RESET ROLE;
    END LOOP;
END
$$;

ROLLBACK;
\echo 'SCRUM-13 database permission checks passed'
