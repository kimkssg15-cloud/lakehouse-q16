#!/bin/sh
# Инициализация: 1) создать бакеты bronze/silver/gold в MinIO (S3 PUT Bucket с подписью
# AWS SigV4 прямо из curl — отдельный клиент mc не нужен, его образ тоже больше не публикуется);
# 2) принять Terms of Use в Lakekeeper и зарегистрировать 3 warehouse, каждый в своём бакете.
# Скрипт идемпотентный: повторный запуск ничего не ломает.
set -u
LK=http://lakekeeper:8181

S3=http://minio:9000
echo "[init] жду MinIO..."
until [ "$(curl -s -o /dev/null -w '%{http_code}' "$S3/")" != "000" ]; do sleep 2; done
for B in bronze silver gold; do
  # 200 = создан, 409 = уже есть (BucketAlreadyOwnedByYou) — оба варианта ок
  curl -s -o /dev/null -w "[init] bucket $B -> HTTP %{http_code}\n" -X PUT "$S3/$B" \
    --aws-sigv4 "aws:amz:us-east-1:s3" --user "minioadmin:minioadmin" \
    -H "x-amz-content-sha256: UNSIGNED-PAYLOAD"
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -I "$S3/$B" \
    --aws-sigv4 "aws:amz:us-east-1:s3" --user "minioadmin:minioadmin" \
    -H "x-amz-content-sha256: UNSIGNED-PAYLOAD")
  if [ "$CODE" != "200" ]; then
    echo "[init] ВНИМАНИЕ: бакет $B не найден (HTTP $CODE). Создай его вручную: http://localhost:9001 -> Buckets -> Create Bucket,"
    echo "[init]           затем повтори: docker compose up -d"
    exit 1
  fi
done

echo "[init] жду Lakekeeper..."
until curl -sf "$LK/health" >/dev/null; do sleep 2; done
echo "[init] Lakekeeper отвечает"

# 1) Terms of Use (204 = ок; ошибка 'already bootstrapped' = тоже ок)
curl -s -o /dev/null -w "[init] bootstrap -> HTTP %{http_code}\n" \
  -X POST "$LK/management/v1/bootstrap" \
  -H "Content-Type: application/json" \
  -d '{"accept-terms-of-use": true}'

# 2) три warehouse
for WH in bronze silver gold; do
  BODY=$(cat <<EOF
{
  "warehouse-name": "$WH",
  "project-id": "00000000-0000-0000-0000-000000000000",
  "storage-profile": {
    "type": "s3",
    "bucket": "$WH",
    "key-prefix": "",
    "endpoint": "http://minio:9000",
    "region": "us-east-1",
    "path-style-access": true,
    "flavor": "s3-compat",
    "sts-enabled": false
  },
  "storage-credential": {
    "type": "s3",
    "credential-type": "access-key",
    "access-key-id": "minioadmin",
    "secret-access-key": "minioadmin"
  }
}
EOF
)
  curl -s -o /dev/null -w "[init] warehouse $WH -> HTTP %{http_code}\n" \
    -X POST "$LK/management/v1/warehouse" \
    -H "Content-Type: application/json" -d "$BODY"
done

# 3) проверка: все три warehouse должны быть в списке
LIST=$(curl -s "$LK/management/v1/warehouse")
for WH in bronze silver gold; do
  echo "$LIST" | grep -q "\"$WH\"" || { echo "[init] ВНИМАНИЕ: warehouse $WH не найден в списке, проверь UI http://localhost:8181/ui"; echo "$LIST"; }
done
echo "[init] готово: warehouse bronze, silver, gold активны"
