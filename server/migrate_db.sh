#!/bin/sh

export $(cat .env | grep -v ^# | grep -v ^EMAIL | xargs)

DB_NAME_TMP="${DB_NAME}_tmp"
TODAY=$( date '+%Y-%m-%d' )

cp ${BACKUP_ROOT}/${TODAY}.podcast.postgres-backup.tar.gz .
tar -xzvf ${TODAY}.podcast.postgres-backup.tar.gz podcast.sql

echo "=== backup ${DATABASE_NAME} | from ${TODAY} ===="

echo "==== drop connections ==="
psql -U${DB_USER} -h${DB_HOST} -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname in ('${DATABASE_NAME}', '${DATABASE_NAME_TMP}') AND pid <> pg_backend_pid(); "
echo "==== recreate target DB ===="
psql -U${DB_USER} -h${DB_HOST} -c "drop database if exists ${DB_NAME}"
psql -U${DB_USER} -h${DB_HOST} -c "create database ${DB_NAME}"
alembic upgrade head

echo "==== prepare inserts backup from original backup ===="
psql -U${DB_USER} -h${DB_HOST} -c "drop database if exists ${DB_NAME_TMP}"
psql -U${DB_USER} -h${DB_HOST} -c "create database ${DB_NAME_TMP}"
psql -U${DB_USER} -h${DB_HOST} ${DB_NAME_TMP} < alembic/backup.sql
pg_dump -U${DB_USER} -h${DB_HOST} \
  --data-only --column-inserts --no-owner --no-privileges --exclude-table migrations_history \
  -d ${DB_NAME_TMP} -f alembic/backup_inserts.sql

echo "==== apply inserts backup to target DB ===="
psql -U${DB_USER} -h${DB_HOST} ${DB_NAME} < alembic/backup_inserts.sql

echo "==== clean ===="
psql -U${DB_USER} -h${DB_HOST} -c "drop database if exists ${DB_NAME_TMP}"

echo "==== done ===="
