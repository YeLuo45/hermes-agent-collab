#!/bin/bash
set -e

echo "[entrypoint] Waiting for PostgreSQL at $POSTGRES_HOST:$POSTGRES_PORT..."
until pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER"; do
  echo "[entrypoint] PostgreSQL not ready, retrying in 2s..."
  sleep 2
done
echo "[entrypoint] PostgreSQL is ready."

# Create database if it doesn't exist
if [ -n "$POSTGRES_PASSWORD" ]; then
  echo "[entrypoint] Ensuring database '$POSTGRES_DB' exists..."
  PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c \
    "SELECT 1 FROM pg_database WHERE datname='$POSTGRES_DB'" | grep -q 1 || \
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c \
    "CREATE DATABASE $POSTGRES_DB"
  echo "[entrypoint] Database ready."
fi

echo "[entrypoint] Starting hermes-agent-collab..."
exec "$@"
