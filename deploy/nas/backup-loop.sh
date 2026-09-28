#!/bin/sh
set -eu
umask 077
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
export PGHOST=db PGPORT=5432 PGDATABASE=trustmap_final_20260929 PGUSER=trustmap
export PGPASSWORD="$POSTGRES_PASSWORD" PGCONNECT_TIMEOUT=20
mkdir -p /backup/daily
while :; do
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  target="/backup/daily/trustmap-$stamp.dump"
  if [ -e "$target" ] || [ -e "$target.partial" ]; then echo "BACKUP_NAME_EXISTS" >&2; exit 1; fi
  if pg_dump --format=custom --no-owner --no-acl --file="$target.partial"; then
    mv "$target.partial" "$target"
    sha256sum "$target" > "$target.sha256"
    echo "BACKUP_OK $stamp"
  else
    echo "BACKUP_FAILED $stamp" >&2
    exit 1
  fi
  sleep 86400 &
  wait "$!"
done
