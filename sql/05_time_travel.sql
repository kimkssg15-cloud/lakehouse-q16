-- =====================================================================
-- TIME TRAVEL и восстановление из снапшота (ручная версия для DBeaver).
-- Раннер делает то же самое автоматически: python runner/lakehouse.py timetravel
-- Сценарий: «случайно» удалили всех поставщиков из Германии (s_nationkey = 7)
-- и восстанавливаем таблицу откатом на снапшот до удаления.
-- =====================================================================

-- 1. Запоминаем текущий снапшот (это «точка восстановления»)
-- текущий снапшот = последний «предок текущего состояния» в журнале $history
-- (после rollback самый новый снапшот уже не текущий, поэтому фильтр is_current_ancestor)
SELECT snapshot_id, made_current_at
FROM silver.lakehouse."supplier$history"
WHERE is_current_ancestor
ORDER BY made_current_at DESC
LIMIT 1;
-- скопируй snapshot_id из результата, ниже он обозначен как <SNAPSHOT_ID>

SELECT count(*) AS rows_before FROM silver.lakehouse.supplier;

-- 2. «Авария»: ошибочный DELETE
DELETE FROM silver.lakehouse.supplier WHERE s_nationkey = 7;

SELECT count(*) AS rows_after_delete FROM silver.lakehouse.supplier;

-- 3. Time travel: читаем таблицу такой, какой она была до удаления
--    (по id снапшота или по времени)
SELECT count(*) AS rows_in_past
FROM silver.lakehouse.supplier FOR VERSION AS OF <SNAPSHOT_ID>;

-- SELECT count(*) FROM silver.lakehouse.supplier
--   FOR TIMESTAMP AS OF TIMESTAMP '2026-10-13 18:00:00 Europe/Moscow';

-- Что именно потеряли:
SELECT s_suppkey, s_name FROM silver.lakehouse.supplier FOR VERSION AS OF <SNAPSHOT_ID>
EXCEPT
SELECT s_suppkey, s_name FROM silver.lakehouse.supplier
LIMIT 10;

-- 4. Восстановление: откат текущего состояния таблицы на снапшот
ALTER TABLE silver.lakehouse.supplier EXECUTE rollback_to_snapshot(<SNAPSHOT_ID>);

SELECT count(*) AS rows_restored FROM silver.lakehouse.supplier;   -- снова как в п.1

-- 5. История таблицы: видно snapshot с delete и откат
SELECT * FROM silver.lakehouse."supplier$history" ORDER BY made_current_at;

-- Альтернатива откату (если нужно восстановить только часть строк):
-- INSERT INTO silver.lakehouse.supplier
-- SELECT * FROM silver.lakehouse.supplier FOR VERSION AS OF <SNAPSHOT_ID>
-- WHERE s_nationkey = 7;
