#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

KEYS="${DEMO_KEYS_DIR:-$HOME/.keys/chongdae}"
FAN="$KEYS/demo/fan.json"

[ -f "$FAN" ] || { echo "기여자 키페어가 없습니다: $FAN" >&2; exit 1; }

SERVICE_TOKEN=$(grep '^SERVICE_TOKEN=' .env | cut -d= -f2-)

docker compose exec -T api mkdir -p /tmp/demo
docker compose cp demo/run_demo.py api:/tmp/demo/run_demo.py >/dev/null
docker compose cp "$FAN" api:/tmp/demo/fan.json >/dev/null

trap 'docker compose exec -T api rm -rf /tmp/demo >/dev/null 2>&1 || true' EXIT

docker compose exec -T \
  -e DEMO_BASE_URL=http://localhost:8080 \
  -e SERVICE_TOKEN="$SERVICE_TOKEN" \
  -e DEMO_CLUSTER="${DEMO_CLUSTER:-devnet}" \
  api python /tmp/demo/run_demo.py
