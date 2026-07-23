#!/usr/bin/env bash
# Enable Ask Co-Pilot module + seed local demo data (idempotent).
# Requires development-easy stack with healthy mysql + openemr.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/docker/development-easy"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
SCRIPT_DIR="$REPO_ROOT/scripts/copilot"
MYSQL_SERVICE="${COPILOT_MYSQL_SERVICE:-mysql}"
OPENEMR_SERVICE="${COPILOT_OPENEMR_SERVICE:-openemr}"

ENABLE_ONLY=0
SEED_ONLY=0

usage() {
  cat <<'EOF'
Usage: scripts/copilot/setup-local-demo.sh [options]

  --enable-only   Register/enable Ask Co-Pilot module (default: also seed demo data)
  --seed-only     Re-seed demo appointments + missing-RxNorm (skip module SQL)
  -h, --help      Show this help

Runs idempotent SQL against the development-easy MariaDB container.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable-only)
      ENABLE_ONLY=1
      shift
      ;;
    --seed-only)
      SEED_ONLY=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$ENABLE_ONLY" -eq 1 && "$SEED_ONLY" -eq 1 ]]; then
  echo "error: choose at most one of --enable-only or --seed-only" >&2
  exit 1
fi

die() {
  echo "error: $*" >&2
  exit 1
}

[[ -f "$COMPOSE_FILE" ]] || die "missing compose file: $COMPOSE_FILE"
command -v docker >/dev/null 2>&1 || die "docker not found"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

mysql_exec() {
  local sql_file="$1"
  compose exec -T "$MYSQL_SERVICE" \
    mariadb -uopenemr -popenemr openemr <"$sql_file"
}

service_healthy() {
  local service="$1" status
  status="$(
    compose ps --status running --format '{{.Service}} {{.Health}}' 2>/dev/null \
      | awk -v svc="$service" '$1 == svc { print $2; exit }'
  )"
  [[ "$status" == "healthy" ]]
}

wait_for_mysql() {
  local waited=0
  local max_wait="${COPILOT_SETUP_MYSQL_WAIT_SEC:-120}"
  while ! service_healthy "$MYSQL_SERVICE"; do
    if (( waited >= max_wait )); then
      die "mysql not healthy after ${max_wait}s — start stack first"
    fi
    sleep 2
    waited=$((waited + 2))
  done
}

run_enable() {
  echo "Enabling Ask Co-Pilot module..."
  mysql_exec "$SCRIPT_DIR/enable-module.sql"
}

run_seed() {
  echo "Seeding local demo appointments + missing-RxNorm Lisinopril..."
  mysql_exec "$SCRIPT_DIR/seed-local-demo.sql"
}

main() {
  wait_for_mysql

  if [[ "$SEED_ONLY" -eq 1 ]]; then
    run_seed
  elif [[ "$ENABLE_ONLY" -eq 1 ]]; then
    run_enable
  else
    run_enable
    run_seed
  fi

  if service_healthy "$OPENEMR_SERVICE"; then
    echo "Co-Pilot local setup complete (openemr healthy)."
  else
    echo "Co-Pilot local setup SQL applied (openemr not yet healthy — tab may appear after boot)."
  fi
}

main "$@"
