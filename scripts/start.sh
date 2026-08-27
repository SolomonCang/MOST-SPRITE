#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] Missing required command: $1"
    exit 1
  fi
}

require_cmd docker
require_cmd curl

if ! docker info >/dev/null 2>&1; then
  echo "[ERROR] Docker daemon is not running. Please start Docker Desktop first."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[ERROR] Docker Compose is not available. Install Docker Compose v2 or docker-compose."
  exit 1
fi

echo "[INFO] Pulling/building and starting MOST-SPRITE services..."
"${COMPOSE_CMD[@]}" up --build -d

echo "[INFO] Waiting for API health check..."
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:8000/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! curl -fsS "http://localhost:8000/healthz" >/dev/null 2>&1; then
  echo "[WARN] API is not healthy yet. You can inspect logs with: docker compose logs -f api"
else
  echo "[OK] API is healthy."
fi

echo "[DONE] MOST-SPRITE is starting."
echo "       Web UI:    http://localhost:8080"
echo "       API:       http://localhost:8000"
echo "       OpenAPI:   http://localhost:8000/docs"
