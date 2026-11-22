#!/usr/bin/env bash
set -euo pipefail

# A local PostgreSQL installation can host the same disposable test database.
# The private socket and generated password belong to this one invocation.
if [[ -n "${OMEGA_TEST_POSTGRES_BIN:-}" ]]; then
  pg_bin=$OMEGA_TEST_POSTGRES_BIN
  for program in initdb pg_ctl createdb; do
    [[ -x "$pg_bin/$program" ]] || { echo "Missing PostgreSQL test executable: $pg_bin/$program" >&2; exit 1; }
  done
  umask 077
  pg_root=$(mktemp -d /tmp/omega-order-test.XXXXXXXX)
  cleanup_postgres() {
    if [[ -f "$pg_root/data/postmaster.pid" ]]; then
      "$pg_bin/pg_ctl" -D "$pg_root/data" -m fast -w stop >/dev/null || return 1
    fi
    rm -rf -- "$pg_root"
  }
  trap cleanup_postgres EXIT
  pg_password=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
  printf '%s\n' "$pg_password" > "$pg_root/password"
  "$pg_bin/initdb" -D "$pg_root/data" -U postgres --auth-local=trust --auth-host=scram-sha-256 \
    --pwfile="$pg_root/password" --no-locale --encoding=UTF8 >/dev/null
  for attempt in 1 2 3; do
    pg_port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
    if "$pg_bin/pg_ctl" -D "$pg_root/data" -l "$pg_root/start-$attempt.log" \
      -o "-h 127.0.0.1 -p $pg_port -k $pg_root" -w start >/dev/null; then
      break
    fi
    if [[ $attempt == 3 ]] || ! grep -qi 'address already in use' "$pg_root/start-$attempt.log"; then
      cat "$pg_root/start-$attempt.log" >&2
      exit 1
    fi
  done
  "$pg_bin/createdb" -h "$pg_root" -p "$pg_port" -U postgres digital_orders
  export OMEGA_DIGITAL_ORDER_TEST_DSN="postgres://postgres:$pg_password@127.0.0.1:$pg_port/digital_orders?sslmode=disable"
  export OMEGA_DIGITAL_ORDER_BROWSER=1
  go test -race -count=1 -timeout=120s ./internal/commerce ./projects/posters ./cmd/omega
  exit 0
fi

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
