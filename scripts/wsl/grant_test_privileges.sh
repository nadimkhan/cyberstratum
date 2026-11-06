#!/usr/bin/env bash
# Grant the application's test role the privileges the schema gate needs.
#
# The schema gate (`tests/api/test_migration_contract.py` and
# `tests/api/test_schema_matches_migrations.py`) applies the real
# migration chain to a throwaway database and compares the result with
# the models. That needs two privileges the application role does not
# have by default:
#
#   * CREATEDB, to create the throwaway database;
#   * ownership of the `public` schema, because the contract test empties
#     the schema before it migrates and the comparison test's database is
#     created from template1.
#
# A cluster initialised by the application's own role already satisfies
# both. A cluster initialised by a different role does not: `public` then
# belongs to the initialising superuser, and the gate fails with
# "must be owner of schema public" or "permission denied to create
# database" — an environment fault that looks like a code fault.
#
# This script fixes that on the project's isolated cluster only. It
# connects as the cluster's own superuser role, which this cluster trusts
# locally, so no sudo and no password are needed. The system PostgreSQL
# on 5432 and the system Redis are never touched.
#
# Usage:  bash scripts/wsl/grant_test_privileges.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}" || exit 1

if [ ! -f ./.env ]; then
  echo "No .env in ${REPO_ROOT}; the connection settings live there." >&2
  exit 1
fi

set -a
# The .env file was written on Windows, so it carries carriage returns.
# Sourcing it as-is would put a CR at the end of every value.
# shellcheck disable=SC1091
source <(tr -d '\r' < ./.env)
set +a

URL="${TEST_DATABASE_URL:-$DATABASE_URL}"
read -r ROLE _ HOST PORT DBNAME <<<"$(python3 -c '
import re, sys
m = re.match(r"postgresql(?:\+\w+)?://([^:]+):([^@]*)@([^:/]+):(\d+)/([^?]+)", sys.argv[1])
print(*(m.groups() if m else ("", "", "", "", "")), sep=" ")
' "${URL}")"

if [ -z "${ROLE}" ] || [ -z "${PORT}" ]; then
  echo "Could not read the database settings from .env." >&2
  exit 1
fi

# The isolated cluster's superuser. It is created by the launcher, which
# initialises the cluster with this role name.
SUPER="cyberstratum"

PSQL=(psql -h "${HOST}" -p "${PORT}" -U "${SUPER}" -v ON_ERROR_STOP=1 -tA)

echo "role=${ROLE} database=${DBNAME} superuser=${SUPER}"

echo "== CREATEDB for the application role =="
"${PSQL[@]}" -d postgres -c "ALTER ROLE \"${ROLE}\" CREATEDB"
"${PSQL[@]}" -d postgres -c \
  "select rolname, rolcreatedb, rolsuper from pg_roles where rolname = '${ROLE}'"

echo "== public schema owner in template1, so new databases inherit it =="
"${PSQL[@]}" -d template1 -c "ALTER SCHEMA public OWNER TO \"${ROLE}\""
"${PSQL[@]}" -d template1 -c \
  "select n.nspname, pg_get_userbyid(n.nspowner) from pg_namespace n where n.nspname = 'public'"

echo "== public schema owner in the test database =="
"${PSQL[@]}" -d "${DBNAME}" -c "ALTER SCHEMA public OWNER TO \"${ROLE}\""
"${PSQL[@]}" -d "${DBNAME}" -c \
  "select n.nspname, pg_get_userbyid(n.nspowner) from pg_namespace n where n.nspname = 'public'"

echo "done"
