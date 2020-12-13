#!/bin/sh

export PYTHONPATH=$(pwd)/src
DATABASE_NAME="${DB_NAME}"
DATABASE_NAME_TMP="${DB_NAME}_tmp"

echo "==== drop connections ==="
psql -Upostgres -hlocalhost -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname in ('${DATABASE_NAME}', '${DATABASE_NAME_TMP}') AND pid <> pg_backend_pid(); "
echo "==== recreate target DB ===="
psql -Upostgres -hlocalhost -c "drop database if exists ${DATABASE_NAME}"
psql -Upostgres -hlocalhost -c "create database ${DATABASE_NAME}"
alembic upgrade head

echo "==== prepare inserts backup from original backup ===="
psql -Upostgres -hlocalhost -c "drop database if exists ${DATABASE_NAME_TMP}"
psql -Upostgres -hlocalhost -c "create database ${DATABASE_NAME_TMP}"
psql -Upostgres -hlocalhost ${DATABASE_NAME_TMP} < alembic/backup.sql
pg_dump -Upostgres -hlocalhost \
  --data-only --column-inserts --no-owner --no-privileges --exclude-table migrations_history \
  -d ${DATABASE_NAME_TMP} -f alembic/backup_inserts.sql

echo "==== apply inserts backup to target DB ===="
psql -Upostgres -hlocalhost ${DATABASE_NAME} < alembic/backup_inserts.sql

echo "==== clean ===="
psql -Upostgres -hlocalhost -c "drop database if exists ${DATABASE_NAME_TMP}"

echo "==== done ===="