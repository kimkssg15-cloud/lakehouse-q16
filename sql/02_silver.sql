-- =====================================================================
-- SILVER — очищенные, нормализованные и обогащённые данные.
--   Очистка:      NULL-ключи отбрасываем; дубликаты по ключу убираем (берём последнюю загрузку);
--                 отбрасываем невалидные значения (p_size вне 1..50, отрицательный остаток,
--                 нулевая/отрицательная цена) и «сирот» partsupp без детали/поставщика.
--   Нормализация: trim/upper строк; деньги double -> decimal(12,2) (точная арифметика);
--                 p_type 'MEDIUM POLISHED BRASS' раскладываем на 3 атрибута.
--   Обогащение:   s_has_complaints — флаг «на поставщика жаловались» (вместо тяжёлого s_comment),
--                 ps_stock_value = остаток * цена поставки.
--   Убираем:      свободный текст (p_name, p_comment, ps_comment, s_comment) и контакты
--                 поставщика (s_address, s_phone) — в аналитике не нужны, а весят больше всего.
-- Формат PARQUET + ZSTD, без партиционирования (обоснование в REPORT.md, раздел 4).
-- =====================================================================
SET SESSION silver.compression_codec = 'ZSTD';

DROP TABLE IF EXISTS silver.lakehouse.part;
CREATE TABLE silver.lakehouse.part
WITH (format = 'PARQUET')
AS
WITH dedup AS (
    SELECT p_partkey, p_mfgr, p_brand, p_type, p_size, p_container, p_retailprice, _ingested_at,
           row_number() OVER (PARTITION BY p_partkey ORDER BY _ingested_at DESC) AS rn
    FROM bronze.lakehouse.part
    WHERE p_partkey IS NOT NULL
)
SELECT
    p_partkey,
    trim(p_mfgr)                                   AS p_mfgr,
    trim(p_brand)                                  AS p_brand,
    upper(trim(p_type))                            AS p_type,
    split_part(upper(trim(p_type)), ' ', 1)        AS p_type_class,   -- STANDARD / SMALL / MEDIUM / LARGE / ECONOMY / PROMO
    split_part(upper(trim(p_type)), ' ', 2)        AS p_type_finish,  -- ANODIZED / BURNISHED / PLATED / POLISHED / BRUSHED
    split_part(upper(trim(p_type)), ' ', 3)        AS p_material,     -- TIN / NICKEL / BRASS / STEEL / COPPER
    CAST(p_size AS integer)                        AS p_size,
    upper(trim(p_container))                       AS p_container,
    CAST(p_retailprice AS decimal(12, 2))          AS p_retailprice,
    _ingested_at                                   AS _bronze_ingested_at
FROM dedup
WHERE rn = 1
  AND p_brand IS NOT NULL
  AND p_type IS NOT NULL
  AND p_size BETWEEN 1 AND 50;

DROP TABLE IF EXISTS silver.lakehouse.supplier;
CREATE TABLE silver.lakehouse.supplier
WITH (format = 'PARQUET')
AS
WITH dedup AS (
    SELECT s_suppkey, s_name, s_nationkey, s_acctbal, s_comment, _ingested_at,
           row_number() OVER (PARTITION BY s_suppkey ORDER BY _ingested_at DESC) AS rn
    FROM bronze.lakehouse.supplier
    WHERE s_suppkey IS NOT NULL
)
SELECT
    s_suppkey,
    trim(s_name)                                            AS s_name,
    s_nationkey,
    CAST(s_acctbal AS decimal(12, 2))                       AS s_acctbal,
    coalesce(s_comment LIKE '%Customer%Complaints%', false) AS s_has_complaints,
    _ingested_at                                            AS _bronze_ingested_at
FROM dedup
WHERE rn = 1;

DROP TABLE IF EXISTS silver.lakehouse.partsupp;
CREATE TABLE silver.lakehouse.partsupp
WITH (format = 'PARQUET')
AS
WITH dedup AS (
    SELECT ps_partkey, ps_suppkey, ps_availqty, ps_supplycost, _ingested_at,
           row_number() OVER (PARTITION BY ps_partkey, ps_suppkey ORDER BY _ingested_at DESC) AS rn
    FROM bronze.lakehouse.partsupp
    WHERE ps_partkey IS NOT NULL AND ps_suppkey IS NOT NULL
)
SELECT
    d.ps_partkey,
    d.ps_suppkey,
    CAST(d.ps_availqty AS integer)                          AS ps_availqty,
    CAST(d.ps_supplycost AS decimal(12, 2))                 AS ps_supplycost,
    CAST(d.ps_availqty * d.ps_supplycost AS decimal(18, 2)) AS ps_stock_value,
    d._ingested_at                                          AS _bronze_ingested_at
FROM dedup d
WHERE d.rn = 1
  AND d.ps_availqty >= 0
  AND d.ps_supplycost > 0
  AND EXISTS (SELECT 1 FROM silver.lakehouse.part p     WHERE p.p_partkey = d.ps_partkey)
  AND EXISTS (SELECT 1 FROM silver.lakehouse.supplier s WHERE s.s_suppkey = d.ps_suppkey);
