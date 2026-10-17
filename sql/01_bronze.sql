-- =====================================================================
-- BRONZE — сырые данные «как пришли» из источника (генератор TPC-H в Trino).
-- Правила слоя:
--   * все колонки источника сохраняем без изменений (можно пересчитать Silver в любой момент);
--   * добавляем только 2 технические колонки: _ingested_at (когда загрузили), _source (откуда);
--   * слой append-only: новые выгрузки дописываются INSERT-ом, старые не перезаписываются;
--   * формат PARQUET + ZSTD, партиционирование по дню загрузки day(_ingested_at).
-- Масштаб: tpch.sf10 (раннер подставляет SF из .env, если он другой).
-- Нужны только 3 таблицы TPC-H, которые использует запрос Q16: part, partsupp, supplier.
-- =====================================================================
SET SESSION bronze.compression_codec = 'ZSTD';

DROP TABLE IF EXISTS bronze.lakehouse.part;
CREATE TABLE bronze.lakehouse.part
WITH (format = 'PARQUET', partitioning = ARRAY['day(_ingested_at)'])
AS
SELECT p.*,
       CAST(current_timestamp AS timestamp(6)) AS _ingested_at,
       'tpch.sf10.part'                        AS _source
FROM tpch.sf10.part p;

DROP TABLE IF EXISTS bronze.lakehouse.supplier;
CREATE TABLE bronze.lakehouse.supplier
WITH (format = 'PARQUET', partitioning = ARRAY['day(_ingested_at)'])
AS
SELECT s.*,
       CAST(current_timestamp AS timestamp(6)) AS _ingested_at,
       'tpch.sf10.supplier'                    AS _source
FROM tpch.sf10.supplier s;

DROP TABLE IF EXISTS bronze.lakehouse.partsupp;
CREATE TABLE bronze.lakehouse.partsupp
WITH (format = 'PARQUET', partitioning = ARRAY['day(_ingested_at)'])
AS
SELECT ps.*,
       CAST(current_timestamp AS timestamp(6)) AS _ingested_at,
       'tpch.sf10.partsupp'                    AS _source
FROM tpch.sf10.partsupp ps;
