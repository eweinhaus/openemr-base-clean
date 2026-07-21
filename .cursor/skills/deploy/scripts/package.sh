#!/usr/bin/env bash
# Package Clinical Co-Pilot overlay + sidecar for DigitalOcean /opt/openemr deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
SKILL_SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
STAGE="$ROOT/tmp/do-copilot-deploy"
OUT="$ROOT/tmp/do-copilot-deploy.tgz"

rm -rf "$STAGE"
mkdir -p \
  "$STAGE/overlay/interface/ask_copilot" \
  "$STAGE/overlay/interface/modules/custom_modules" \
  "$STAGE/overlay/src" \
  "$STAGE/sidecar"

# PHP / module overlay
cp -R "$ROOT/interface/ask_copilot/." "$STAGE/overlay/interface/ask_copilot/"
cp -R "$ROOT/interface/modules/custom_modules/oe-module-ask-copilot" \
  "$STAGE/overlay/interface/modules/custom_modules/"
cp -R "$ROOT/src/ClinicalCopilot" "$STAGE/overlay/src/"

# Sidecar build context (no venv / tests / caches)
rsync -a \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  --exclude 'tests' \
  --exclude '.DS_Store' \
  --exclude '._*' \
  "$ROOT/sidecar/" "$STAGE/sidecar/"

# DO compose: stock OpenEMR + overlay mounts + single-worker sidecar
cat > "$STAGE/docker-compose.yml" <<'EOF'
services:
  mysql:
    restart: always
    image: mariadb:11.8
    command: ['mariadbd', '--character-set-server=utf8mb4', '--innodb-buffer-pool-size=256M']
    volumes:
      - databasevolume:/var/lib/mysql
    environment:
      MYSQL_ROOT_PASSWORD: root
    healthcheck:
      test: ['CMD', 'healthcheck.sh', '--connect', '--innodb_initialized']
      start_period: 1m
      interval: 30s
      timeout: 5s
      retries: 5
  openemr:
    restart: always
    image: openemr/openemr:latest
    ports:
      - 80:80
      - 443:443
    volumes:
      - logvolume01:/var/log
      - sitevolume:/var/www/localhost/htdocs/openemr/sites
      - ./overlay/interface/ask_copilot:/var/www/localhost/htdocs/openemr/interface/ask_copilot
      - ./overlay/interface/modules/custom_modules/oe-module-ask-copilot:/var/www/localhost/htdocs/openemr/interface/modules/custom_modules/oe-module-ask-copilot
      - ./overlay/src/ClinicalCopilot:/var/www/localhost/htdocs/openemr/src/ClinicalCopilot
    environment:
      MYSQL_HOST: mysql
      MYSQL_ROOT_PASS: root
      MYSQL_USER: openemr
      MYSQL_PASS: openemr
      OE_USER: admin
      OE_PASS: pass
      COPILOT_INTERNAL_SECRET: "${COPILOT_INTERNAL_SECRET:-dev-copilot-secret-change-me}"
      COPILOT_SIDECAR_URL: "${COPILOT_SIDECAR_URL:-http://copilot-sidecar:8080}"
      COPILOT_GATEWAY_TIMEOUT_SECONDS: "${COPILOT_GATEWAY_TIMEOUT_SECONDS:-45}"
    depends_on:
      mysql:
        condition: service_healthy
  copilot-sidecar:
    restart: always
    build:
      context: ./sidecar
      dockerfile: Dockerfile
    environment:
      COPILOT_INTERNAL_SECRET: "${COPILOT_INTERNAL_SECRET:-dev-copilot-secret-change-me}"
      COPILOT_GATEWAY_TOOL_URL: "${COPILOT_GATEWAY_TOOL_URL:-http://openemr/interface/ask_copilot/tool_proxy.php}"
      OPENROUTER_API_KEY: "${OPENROUTER_API_KEY:-}"
      OPENROUTER_BASE_URL: "${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}"
      OPENROUTER_MODEL: "${OPENROUTER_MODEL:-anthropic/claude-haiku-4.5}"
      COPILOT_LLM_TIMEOUT_SECONDS: "${COPILOT_LLM_TIMEOUT_SECONDS:-30}"
      COPILOT_TOOL_TIMEOUT_SECONDS: "${COPILOT_TOOL_TIMEOUT_SECONDS:-10}"
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"]
      start_period: 20s
      interval: 30s
      timeout: 5s
      retries: 3
volumes:
  logvolume01: {}
  sitevolume: {}
  databasevolume: {}
EOF

cat > "$STAGE/.env.example" <<'EOF'
COPILOT_INTERNAL_SECRET=dev-copilot-secret-change-me
COPILOT_SIDECAR_URL=http://copilot-sidecar:8080
COPILOT_GATEWAY_TIMEOUT_SECONDS=45
COPILOT_GATEWAY_TOOL_URL=http://openemr/interface/ask_copilot/tool_proxy.php
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=anthropic/claude-haiku-4.5
EOF

cp "$SKILL_SCRIPTS/enable-module.sql" "$STAGE/enable_ask_copilot.sql"

# Drop AppleDouble if any slipped in
find "$STAGE" -name '._*' -delete
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true

mkdir -p "$ROOT/tmp"
tar -czf "$OUT" -C "$STAGE" .
echo "PACKAGED $OUT"
tar -tzf "$OUT" | head -30
