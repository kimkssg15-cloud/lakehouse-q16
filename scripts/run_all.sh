#!/usr/bin/env bash
# Полный прогон лабораторной (macOS / Linux). Запускать из корня репозитория: ./scripts/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d
echo "Жду, пока Trino станет healthy..."
until [ "$(docker inspect -f '{{.State.Health.Status}}' trino 2>/dev/null)" = "healthy" ]; do sleep 3; done
docker ps
docker exec trino trino --execute "SHOW CATALOGS"
docker compose run --rm runner python runner/lakehouse.py all
docker compose --profile bi up -d superset
echo "Готово: REPORT.md обновлён, Superset поднимается на http://localhost:8088 (admin/admin)"
