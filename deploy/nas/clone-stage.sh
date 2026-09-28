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
# Preserve interrupted backups for inspection instead of overwriting them.
if [ -e /backup/source-tls.dump ] || [ -e /backup/source-tls.dump.partial ]; then
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
  export PGHOST=db PGPORT=5432 PGDATABASE=trustmap
  export PGUSER=trustmap PGPASSWORD="$TARGET_PASSWORD" PGSSLMODE=disable
  unset PGSSLROOTCERT PGOPTIONS
}
target_db
tables=$(psql -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
if [ "$tables" != 0 ]; then echo 'REFUSED: target database is not empty'; exit 1; fi
source_db
pg_dump --format=custom --no-owner --no-acl --file=/backup/source-tls.dump.partial
mv /backup/source-tls.dump.partial /backup/source-tls.dump
sha256sum /backup/source-tls.dump > /backup/source-tls.dump.sha256
echo 'SOURCE_BACKUP_OK'
target_db
pg_restore --dbname=trustmap --no-owner --no-acl --exit-on-error --single-transaction /backup/source-tls.dump
echo 'NAS_RESTORE_OK'
psql -XAt -v ON_ERROR_STOP=1 -c "SELECT format('SELECT %L, count(*) FROM %I.%I;', tablename, schemaname, tablename) FROM pg_tables WHERE schemaname='public' ORDER BY tablename" > /backup/counts.sql
psql -XAt -v ON_ERROR_STOP=1 -f /backup/counts.sql > /backup/target-counts.txt
source_db
psql -XAt -v ON_ERROR_STOP=1 -f /backup/counts.sql > /backup/source-counts.txt
if cmp -s /backup/target-counts.txt /backup/source-counts.txt; then
  echo 'SOURCE_TARGET_TABLE_COUNTS_MATCH'
else
  echo 'SOURCE_CHANGED_OR_COUNTS_DIFFER: cutover prohibited until reconciled'
  exit 2
fi
cat /backup/target-counts.txt
echo 'STAGING_CLONE_VERIFIED_NOT_PRODUCTION'
