#!/usr/bin/env bash
set -euo pipefail
# A fresh database and loopback port keep concurrent hooks and buyer rehearsals isolated.
container=$(docker run --rm --detach --publish 127.0.0.1::5432 \
  -e POSTGRES_PASSWORD=local-order-test -e POSTGRES_DB=digital_orders postgres:16)
trap 'docker stop "$container" >/dev/null' EXIT
port=$(docker port "$container" 5432/tcp)
export OMEGA_DIGITAL_ORDER_TEST_DSN="postgres://postgres:local-order-test@${port}/digital_orders?sslmode=disable"
export OMEGA_DIGITAL_ORDER_BROWSER=1
for _ in {1..40}; do
  if docker exec "$container" pg_isready -h 127.0.0.1 -U postgres -d digital_orders >/dev/null; then
    go test -race -count=1 -timeout=120s ./internal/commerce ./projects/posters ./cmd/omega
    exit 0
  fi
  sleep 0.5
done
echo 'The local order test database did not become ready.' >&2
exit 1
