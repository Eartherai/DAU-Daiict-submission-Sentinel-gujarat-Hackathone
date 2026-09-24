#!/bin/sh
# PostgreSQL + PostGIS for Saakshya, in the project, without admin rights.
#
#   tools/db/setup_postgres.sh          install (once), initialise, start
#   tools/db/setup_postgres.sh stop     stop the server
#
# Installs micromamba and conda-forge `postgis` (which brings the PostgreSQL
# it was built against) into var/pg/, initialises a cluster in var/pg/data
# listening on 127.0.0.1 only, creates the `saakshya` database with the
# PostGIS extension, and writes the connection URL to var/pg/url (mode 600).
# Nothing here is committed: var/pg/ is gitignored.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PG="$ROOT/var/pg"
ENV="$PG/env"
DATA="$PG/data"
PORT="${SAAKSHYA_PG_PORT:-5544}"
BIN="$ENV/bin"

if [ "${1:-}" = "stop" ]; then
  "$BIN/pg_ctl" -D "$DATA" stop -m fast
  exit 0
fi

if [ ! -x "$BIN/postgres" ]; then
  mkdir -p "$PG/bin"
  if [ ! -x "$PG/bin/micromamba" ]; then
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64) PLAT=osx-arm64 ;;
      Darwin-x86_64) PLAT=osx-64 ;;
      Linux-aarch64) PLAT=linux-aarch64 ;;
      *) PLAT=linux-64 ;;
    esac
    curl -sSL --fail "https://micro.mamba.pm/api/micromamba/$PLAT/latest" -o "$PG/micromamba.tar.bz2"
    tar -xjf "$PG/micromamba.tar.bz2" -C "$PG" bin/micromamba
  fi
  MAMBA_ROOT_PREFIX="$PG/mamba" "$PG/bin/micromamba" create -y -p "$ENV" -c conda-forge postgis
fi

if [ ! -f "$DATA/PG_VERSION" ]; then
  PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
  umask 077
  printf '%s\n' "$PW" > "$PG/pwfile"
  "$BIN/initdb" -D "$DATA" -U saakshya --pwfile="$PG/pwfile" -A scram-sha-256 -E UTF8 --locale=C >/dev/null
  printf "listen_addresses = '127.0.0.1'\nport = %s\n" "$PORT" >> "$DATA/postgresql.conf"
  printf 'postgresql+psycopg://saakshya:%s@127.0.0.1:%s/saakshya\n' "$PW" "$PORT" > "$PG/url"
  rm -f "$PG/pwfile"
fi

if ! "$BIN/pg_ctl" -D "$DATA" status >/dev/null 2>&1; then
  "$BIN/pg_ctl" -D "$DATA" -l "$PG/server.log" -w start >/dev/null
fi

PGPASSWORD="$(sed -E 's#.*saakshya:([^@]*)@.*#\1#' "$PG/url")"
export PGPASSWORD
if ! "$BIN/psql" -h 127.0.0.1 -p "$PORT" -U saakshya -d postgres -tAc \
     "select 1 from pg_database where datname='saakshya'" | grep -q 1; then
  "$BIN/psql" -h 127.0.0.1 -p "$PORT" -U saakshya -d postgres -qc "create database saakshya"
fi
"$BIN/psql" -h 127.0.0.1 -p "$PORT" -U saakshya -d saakshya -qc "create extension if not exists postgis"
VER="$("$BIN/psql" -h 127.0.0.1 -p "$PORT" -U saakshya -d saakshya -tAc \
      "select split_part(version(), ' ', 2) || ' + PostGIS ' || postgis_lib_version()")"
echo "PostgreSQL $VER on 127.0.0.1:$PORT; URL in var/pg/url"
