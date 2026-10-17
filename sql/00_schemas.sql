-- Схемы (namespace Iceberg) во всех трёх слоях.
-- Имя таблицы в Trino всегда из трёх частей: каталог.схема.таблица
CREATE SCHEMA IF NOT EXISTS bronze.lakehouse;
CREATE SCHEMA IF NOT EXISTS bronze.bench;      -- копии Bronze с разными форматами/кодеками для бенчмарка
CREATE SCHEMA IF NOT EXISTS silver.lakehouse;
CREATE SCHEMA IF NOT EXISTS gold.lakehouse;
