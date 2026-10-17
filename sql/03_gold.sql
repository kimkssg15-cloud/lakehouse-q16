-- =====================================================================
-- GOLD — витрины для бизнес-аналитики (вопрос Q16: «сколько поставщиков без жалоб
-- могут поставить детали нужного бренда / типа / размера»).
--
-- 1) part_supplier_mart — полный «куб» по всем (бренд, тип, размер).
--    Все фильтры Q16 стоят на колонках группировки, поэтому из этого куба можно
--    ответить на Q16 с ЛЮБЫМИ параметрами (другой бренд, другие размеры) простым WHERE,
--    без джойнов по 8+ млн строк. Плюс полезные метрики: всего поставщиков, сколько
--    «с жалобами», средняя цена поставки, суммарный остаток.
-- 2) q16_report — готовый ответ на Q16 со стандартными параметрами спецификации TPC-H.
--
-- count(DISTINCT ...) считаем в два шага (сначала уникальные пары «группа × поставщик»,
-- потом считаем пары) — так один хеш-агрегат вместо трёх MarkDistinct, меньше памяти.
-- =====================================================================
SET SESSION gold.compression_codec = 'ZSTD';

DROP TABLE IF EXISTS gold.lakehouse.part_supplier_mart;
CREATE TABLE gold.lakehouse.part_supplier_mart
WITH (format = 'PARQUET')
AS
WITH supplier_in_group AS (
    SELECT p.p_brand,
           p.p_type,
           p.p_size,
           ps.ps_suppkey,
           bool_or(coalesce(s.s_has_complaints, false)) AS has_complaints,
           count(*)                                     AS offer_cnt,
           sum(ps.ps_supplycost)                        AS sum_supplycost,
           sum(ps.ps_availqty)                          AS sum_availqty,
           sum(ps.ps_stock_value)                       AS sum_stock_value
    FROM silver.lakehouse.partsupp ps
    JOIN silver.lakehouse.part p
      ON p.p_partkey = ps.ps_partkey
    LEFT JOIN silver.lakehouse.supplier s
      ON s.s_suppkey = ps.ps_suppkey
    GROUP BY p.p_brand, p.p_type, p.p_size, ps.ps_suppkey
)
SELECT
    p_brand,
    p_type,
    split_part(p_type, ' ', 1)                               AS p_type_class,
    split_part(p_type, ' ', 2)                               AS p_type_finish,
    split_part(p_type, ' ', 3)                               AS p_material,
    p_size,
    count_if(NOT has_complaints)                             AS supplier_cnt,           -- метрика Q16
    count(*)                                                 AS supplier_cnt_total,
    count_if(has_complaints)                                 AS complaint_supplier_cnt,
    sum(offer_cnt)                                           AS offer_cnt,
    CAST(sum(sum_supplycost) / sum(offer_cnt) AS decimal(12, 2)) AS avg_supplycost,
    sum(sum_availqty)                                        AS total_availqty,
    sum(sum_stock_value)                                     AS total_stock_value,
    CAST(current_timestamp AS timestamp(6))                  AS _built_at
FROM supplier_in_group
GROUP BY p_brand, p_type, p_size;

DROP TABLE IF EXISTS gold.lakehouse.q16_report;
CREATE TABLE gold.lakehouse.q16_report
WITH (format = 'PARQUET')
AS
SELECT p_brand, p_type, p_size, supplier_cnt
FROM gold.lakehouse.part_supplier_mart
WHERE p_brand <> 'Brand#45'
  AND p_type NOT LIKE 'MEDIUM POLISHED%'
  AND p_size IN (49, 14, 23, 45, 19, 3, 36, 9)
  AND supplier_cnt > 0;
