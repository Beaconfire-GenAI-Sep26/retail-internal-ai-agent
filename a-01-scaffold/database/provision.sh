#!/bin/sh
set -eu

psql --no-psqlrc --set ON_ERROR_STOP=1 \
    --set auth_password="$AUTH_DB_PASSWORD" \
    --set agent_password="$AGENT_DB_PASSWORD" \
    --set domain_password="$DOMAIN_DB_PASSWORD" \
    --set eval_password="$EVAL_DB_PASSWORD" \
    --set migration_password="$MIGRATION_DB_PASSWORD" \
    --file /setup/provision.sql
