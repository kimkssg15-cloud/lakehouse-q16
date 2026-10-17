# Какие скриншоты снять (и как назвать файлы)

Положи PNG в эту папку с такими именами — на них ссылается REPORT.md.

| Файл | Что на скриншоте |
|---|---|
| `01_docker_ps.png` | вывод `docker ps`: lakehouse-minio, lakehouse-pg, lakekeeper, trino (healthy) |
| `02_minio_buckets.png` | консоль MinIO http://localhost:9001 → Buckets: bronze, silver, gold |
| `03_minio_bronze_files.png` | бакет bronze → папка `partsupp-…/data/_ingested_at_day=…/` с parquet-файлами и `metadata/*.json` |
| `04_lakekeeper_warehouses.png` | Lakekeeper UI http://localhost:8181/ui → 3 warehouse со статусом active |
| `05_dbeaver_tree.png` | DBeaver: подключение к Trino, в дереве каталоги bronze / silver / gold / tpch и таблицы |
| `06_runner_output.png` | конец вывода `docker compose run --rm runner python runner/lakehouse.py all` (строки бенчмарка) |
| `07_superset_db.png` | Superset → Database Connections: подключения bronze и gold, «Connection looks good» |
| `08_superset_sqllab_bronze.png` | Superset SQL Lab: запрос к `bronze.lakehouse.part` и результат |
| `09_trino_ui.png` | Trino UI http://localhost:8080: запросы от пользователя `superset` |
| `10_superset_dashboard.png` | дашборд по `gold.lakehouse.q16_report` |
