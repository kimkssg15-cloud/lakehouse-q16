-- =====================================================================
-- TPC-H Q16 «Parts/Supplier Relationship» — вариант 4.
-- Сколько поставщиков могут поставить детали с нужными характеристиками
-- (исключая бренд Brand#45, тип MEDIUM POLISHED*, 8 размеров) и при этом
-- НЕ имеют жалоб клиентов (s_comment LIKE '%Customer%Complaints%').
-- Три способа получить один и тот же ответ — по слоям медальона.
-- =====================================================================

-- (а) Канонический Q16 прямо по сырому Bronze (как в спецификации TPC-H)
SELECT p_brand, p_type, p_size, count(DISTINCT ps_suppkey) AS supplier_cnt
FROM bronze.lakehouse.partsupp, bronze.lakehouse.part
WHERE p_partkey = ps_partkey
  AND p_brand <> 'Brand#45'
  AND p_type NOT LIKE 'MEDIUM POLISHED%'
  AND p_size IN (49, 14, 23, 45, 19, 3, 36, 9)
  AND ps_suppkey NOT IN (
        SELECT s_suppkey FROM bronze.lakehouse.supplier
        WHERE s_comment LIKE '%Customer%Complaints%')
GROUP BY p_brand, p_type, p_size
ORDER BY supplier_cnt DESC, p_brand, p_type, p_size;

-- (б) Тот же запрос по Silver: вместо LIKE по тексту комментария — готовый флаг жалоб
SELECT p.p_brand, p.p_type, p.p_size, count(DISTINCT ps.ps_suppkey) AS supplier_cnt
FROM silver.lakehouse.partsupp ps
JOIN silver.lakehouse.part p ON p.p_partkey = ps.ps_partkey
WHERE p.p_brand <> 'Brand#45'
  AND p.p_type NOT LIKE 'MEDIUM POLISHED%'
  AND p.p_size IN (49, 14, 23, 45, 19, 3, 36, 9)
  AND ps.ps_suppkey NOT IN (SELECT s_suppkey FROM silver.lakehouse.supplier WHERE s_has_complaints)
GROUP BY p.p_brand, p.p_type, p.p_size
ORDER BY supplier_cnt DESC, p.p_brand, p.p_type, p.p_size;

-- (в) Из Gold: готовая витрина, ответ за миллисекунды
SELECT p_brand, p_type, p_size, supplier_cnt
FROM gold.lakehouse.q16_report
ORDER BY supplier_cnt DESC, p_brand, p_type, p_size;

-- Проверка корректности: Bronze-ответ и Gold-ответ совпадают (оба запроса должны вернуть 0)
SELECT count(*) AS only_in_bronze FROM (
    SELECT p_brand, p_type, p_size, count(DISTINCT ps_suppkey) AS supplier_cnt
    FROM bronze.lakehouse.partsupp JOIN bronze.lakehouse.part ON p_partkey = ps_partkey
    WHERE p_brand <> 'Brand#45' AND p_type NOT LIKE 'MEDIUM POLISHED%'
      AND p_size IN (49, 14, 23, 45, 19, 3, 36, 9)
      AND ps_suppkey NOT IN (SELECT s_suppkey FROM bronze.lakehouse.supplier
                             WHERE s_comment LIKE '%Customer%Complaints%')
    GROUP BY p_brand, p_type, p_size
    EXCEPT
    SELECT p_brand, p_type, p_size, supplier_cnt FROM gold.lakehouse.q16_report
);
