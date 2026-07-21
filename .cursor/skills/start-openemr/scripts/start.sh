#!/usr/bin/env bash
# Start OpenEMR development-easy stack. Safe to re-run if already up.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/docker/development-easy"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
APP_URL="http://localhost:8300/"
SIDECAR_SERVICE="copilot-sidecar"
OPENEMR_SERVICE="openemr"
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

service_healthy() {
  local service="$1" status
  status="$(
    docker compose -f "$COMPOSE_FILE" ps --status running --format '{{.Service}} {{.Health}}' 2>/dev/null \
      | awk -v svc="$service" '$1 == svc { print $2; exit }'
  )"
  [[ "$status" == "healthy" ]]
}

stack_healthy() {
  service_healthy "$OPENEMR_SERVICE"
}

# The Clinical Co-Pilot sidecar is part of the stack: Ask Co-Pilot fails closed
# ("Something went wrong. Try again.") if the gateway can't reach it.
sidecar_healthy() {
  service_healthy "$SIDECAR_SERVICE"
}

http_ok() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$APP_URL" 2>/dev/null || true)"
  [[ "$code" == "200" || "$code" == "302" ]]
}

start_stack() {
  [[ -f "$COMPOSE_FILE" ]] || die "missing compose file: $COMPOSE_FILE"
  need_cmd curl

  if stack_healthy && http_ok && sidecar_healthy; then
    echo "OpenEMR + Co-Pilot sidecar already running and healthy"
    return 0
  fi

  echo "Starting development-easy stack (incl. Co-Pilot sidecar)..."
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

# Best-effort: report whether the sidecar considers itself ready for live LLM
# turns. Ask Co-Pilot needs OPENROUTER_API_KEY in the sidecar env; without it
# the sidecar is reachable (no "connection refused") but turns still error at
# the route/draft call. Never fails the script.
sidecar_ready_note() {
  local ready
  ready="$(
    docker compose -f "$COMPOSE_FILE" exec -T "$OPENEMR_SERVICE" \
      curl -s --max-time 5 http://copilot-sidecar:8080/ready 2>/dev/null || true
  )"
  if [[ "$ready" == *'"configured":true'* ]]; then
    echo "  Co-Pilot:    sidecar healthy, OpenRouter configured (Ask Co-Pilot ready)"
  else
    echo "  Co-Pilot:    sidecar healthy, but OPENROUTER_API_KEY not set —"
    echo "               live Ask Co-Pilot turns will error until you add it to"
    echo "               $COMPOSE_DIR/.env and re-run, e.g.:"
    echo "                 echo 'OPENROUTER_API_KEY=sk-or-...' >> $COMPOSE_DIR/.env"
  fi
}

print_access() {
  echo
  echo "OpenEMR is up"
  echo "  App:         $APP_URL"
  echo "  App (HTTPS): https://localhost:9300/"
  echo "  Login:       admin / pass"
  echo "  phpMyAdmin:  http://localhost:8310/"
  sidecar_ready_note
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
  if ! sidecar_healthy; then
    die "copilot-sidecar is not healthy — check: docker compose -f $COMPOSE_FILE logs $SIDECAR_SERVICE"
  fi

  print_access
}

main "$@"
