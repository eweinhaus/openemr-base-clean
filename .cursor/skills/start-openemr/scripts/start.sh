#!/usr/bin/env bash
# Start OpenEMR development-easy stack. Safe to re-run if already up.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/docker/development-easy"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
APP_URL="http://localhost:8300/"
MAX_DOCKER_WAIT_SEC=120
POLL_INTERVAL_SEC=2

die() {
  echo "error: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

docker_ready() {
  docker info >/dev/null 2>&1
}

ensure_docker() {
  need_cmd docker
  if docker_ready; then
    echo "Docker daemon: ready"
    return 0
  fi

  echo "Docker daemon not reachable — launching Docker Desktop..."
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open -a Docker || die "could not open Docker Desktop; start it manually, then re-run"
  else
    die "start the Docker daemon, then re-run this script"
  fi

  local waited=0
  while ! docker_ready; do
    if (( waited >= MAX_DOCKER_WAIT_SEC )); then
      die "Docker daemon not ready after ${MAX_DOCKER_WAIT_SEC}s"
    fi
    sleep "$POLL_INTERVAL_SEC"
    waited=$((waited + POLL_INTERVAL_SEC))
    echo "  waiting for Docker... (${waited}s)"
  done
  echo "Docker daemon: ready"
}

stack_healthy() {
  local status
  status="$(
    docker compose -f "$COMPOSE_FILE" ps --status running --format '{{.Service}} {{.Health}}' 2>/dev/null \
      | awk '$1 == "openemr" { print $2; exit }'
  )"
  [[ "$status" == "healthy" ]]
}

http_ok() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$APP_URL" 2>/dev/null || true)"
  [[ "$code" == "200" || "$code" == "302" ]]
}

start_stack() {
  [[ -f "$COMPOSE_FILE" ]] || die "missing compose file: $COMPOSE_FILE"
  need_cmd curl

  if stack_healthy && http_ok; then
    echo "OpenEMR already running and healthy"
    return 0
  fi

  echo "Starting development-easy stack..."
  (
    cd "$COMPOSE_DIR"
    if command -v openemr-cmd >/dev/null 2>&1; then
      # openemr-cmd up does not always wait for healthy; follow with compose wait
      openemr-cmd up
      docker compose up --detach --wait
    else
      docker compose up --detach --wait
    fi
  )
}

print_access() {
  echo
  echo "OpenEMR is up"
  echo "  App:         $APP_URL"
  echo "  App (HTTPS): https://localhost:9300/"
  echo "  Login:       admin / pass"
  echo "  phpMyAdmin:  http://localhost:8310/"
}

main() {
  if [[ "$(pwd)" == *"/openemr-wt-"* ]] || [[ "$REPO_ROOT" == *"/openemr-wt-"* ]]; then
    die "this looks like an openemr-cmd worktree; use: openemr-cmd worktree start <branch> (or worktree up)"
  fi

  ensure_docker
  start_stack

  if ! stack_healthy; then
    die "openemr container is not healthy — check: docker compose -f $COMPOSE_FILE logs openemr"
  fi
  if ! http_ok; then
    die "HTTP check failed for $APP_URL"
  fi

  print_access
}

main "$@"
