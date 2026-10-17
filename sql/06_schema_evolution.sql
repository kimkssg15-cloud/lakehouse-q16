-- =====================================================================
-- SCHEMA EVOLUTION на Silver (ручная версия для DBeaver).
-- Раннер делает то же самое автоматически: python runner/lakehouse.py evolution
-- Iceberg хранит колонки по числовому id, а не по имени, поэтому ADD / RENAME —
-- это только новая версия метаданных (metadata.json), parquet-файлы не переписываются.
-- =====================================================================

-- 0. Снапшот ДО изменений схемы — понадобится для time travel
SELECT snapshot_id FROM silver.lakehouse."supplier$history" WHERE is_current_ancestor ORDER BY made_current_at DESC LIMIT 1;

-- 1. Добавили колонку: сегмент поставщика по балансу счёта
ALTER TABLE silver.lakehouse.supplier ADD COLUMN s_balance_segment varchar;

-- старые строки сразу видны с NULL в новой колонке — файлы не переписывались
SELECT s_suppkey, s_acctbal, s_balance_segment FROM silver.lakehouse.supplier LIMIT 3;

-- 2. Заполнили (это уже изменение данных -> новый снапшот)
UPDATE silver.lakehouse.supplier
SET s_balance_segment = CASE
        WHEN s_acctbal < 0    THEN 'DEBT'
        WHEN s_acctbal < 5000 THEN 'LOW'
        ELSE 'HIGH'
    END;

-- 3. Переименовали колонку (только метаданные)
ALTER TABLE silver.lakehouse.supplier RENAME COLUMN s_balance_segment TO s_acctbal_segment;

DESCRIBE silver.lakehouse.supplier;

SELECT s_acctbal_segment, count(*) AS suppliers
FROM silver.lakehouse.supplier
GROUP BY s_acctbal_segment
ORDER BY 1;

-- 4. Старый снапшот по-прежнему читается (time travel через изменение схемы)
-- SELECT * FROM silver.lakehouse.supplier FOR VERSION AS OF <SNAPSHOT_ID> LIMIT 3;

-- 5. Gold продолжает работать: витрина ссылается на колонки по имени, новые колонки ей не мешают
SELECT count(*) FROM gold.lakehouse.part_supplier_mart;

-- История метаданных
SELECT * FROM silver.lakehouse."supplier$history" ORDER BY made_current_at;
