#!/bin/sh
set -eu
umask 077
export PGCONNECT_TIMEOUT=20
# Fail before connecting if the private migration configuration is incomplete.
: "${SOURCE_HOST:?SOURCE_HOST is required}"
: "${SOURCE_DATABASE:?SOURCE_DATABASE is required}"
: "${SOURCE_USER:?SOURCE_USER is required}"
: "${SOURCE_PASSWORD:?SOURCE_PASSWORD is required}"
: "${TARGET_PASSWORD:?TARGET_PASSWORD is required}"
if [ "${SOURCE_WRITES_FROZEN:-}" != "yes" ]; then
  echo 'REFUSED: source write freeze must be verified before final backup'
  exit 1
fi
# Preserve interrupted backups for inspection instead of overwriting them.
if [ -e /backup/final-20260929.dump ] || [ -e /backup/final-20260929.dump.partial ]; then
  echo 'REFUSED: backup or interrupted backup already exists'
  exit 1
fi
# Source credentials exist only in the container environment, never in arguments.
source_db() {
  export PGHOST="$SOURCE_HOST" PGPORT=5432 PGDATABASE="$SOURCE_DATABASE"
  export PGUSER="$SOURCE_USER" PGPASSWORD="$SOURCE_PASSWORD"
  export PGSSLMODE=verify-full PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt
  export PGOPTIONS='-c default_transaction_read_only=on'
}
target_db() {
  export PGHOST=db PGPORT=5432 PGDATABASE=trustmap_final_20260929
  export PGUSER=trustmap PGPASSWORD="$TARGET_PASSWORD" PGSSLMODE=disable
  unset PGSSLROOTCERT PGOPTIONS
}
target_db
export PGDATABASE=postgres
exists=$(psql -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_database WHERE datname='trustmap_final_20260929'")
if [ "$exists" != 0 ]; then echo 'REFUSED: final target database already exists'; exit 1; fi
createdb --owner=trustmap trustmap_final_20260929
export PGDATABASE=trustmap_final_20260929
tables=$(psql -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
if [ "$tables" != 0 ]; then echo 'REFUSED: target database is not empty'; exit 1; fi
source_db
pg_dump --format=custom --no-owner --no-acl --file=/backup/final-20260929.dump.partial
mv /backup/final-20260929.dump.partial /backup/final-20260929.dump
sha256sum /backup/final-20260929.dump > /backup/final-20260929.dump.sha256
echo 'SOURCE_BACKUP_OK'
target_db
pg_restore --dbname=trustmap_final_20260929 --no-owner --no-acl --exit-on-error --single-transaction /backup/final-20260929.dump
echo 'NAS_RESTORE_OK'
psql -XAt -v ON_ERROR_STOP=1 > /backup/final-counts.sql <<'SQL'
SELECT format($q$SELECT %L, count(*), md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), '')) FROM %I.%I t;$q$, tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
SQL
psql -XAt -v ON_ERROR_STOP=1 -f /backup/final-counts.sql > /backup/final-target-counts.txt
source_db
psql -XAt -v ON_ERROR_STOP=1 -f /backup/final-counts.sql > /backup/final-source-counts.txt
if cmp -s /backup/final-target-counts.txt /backup/final-source-counts.txt; then
  echo 'SOURCE_TARGET_COUNTS_AND_CONTENT_HASHES_MATCH'
else
  echo 'SOURCE_CHANGED_OR_COUNTS_DIFFER: cutover prohibited until reconciled'
  exit 2
fi
cat /backup/final-target-counts.txt
echo 'FINAL_CLONE_READY_REQUIRES_CUTOVER_VERIFICATION'
