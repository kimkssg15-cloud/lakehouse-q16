-- =====================================================================
-- ОБСЛУЖИВАНИЕ ТАБЛИЦ ICEBERG: проблема мелких файлов (ручная версия для DBeaver).
-- Раннер делает то же самое автоматически: python runner/lakehouse.py maintenance
--
-- Bronze — append-only: при частых загрузках каждая порция = отдельный коммит,
-- новый снапшот и новый маленький файл. Со временем таблица превращается в тысячи
-- мелких файлов и снапшотов -> медленнее планирование и чтение, растут метаданные.
-- Лечится регламентным обслуживанием: optimize (компакция) + expire_snapshots.
-- =====================================================================

-- 0. Демо-таблица с той же схемой, что bronze.supplier, но пустая
DROP TABLE IF EXISTS bronze.lakehouse.maint_demo;
CREATE TABLE bronze.lakehouse.maint_demo WITH (format = 'PARQUET') AS
SELECT * FROM bronze.lakehouse.supplier WITH NO DATA;

-- 1. 30 «микро-загрузок» (в раннере — циклом, здесь пример двух первых)
INSERT INTO bronze.lakehouse.maint_demo SELECT * FROM bronze.lakehouse.supplier WHERE s_suppkey % 30 = 0;
INSERT INTO bronze.lakehouse.maint_demo SELECT * FROM bronze.lakehouse.supplier WHERE s_suppkey % 30 = 1;
-- ... и так далее до s_suppkey % 30 = 29

-- Состояние: снапшоты, живые файлы данных, манифесты
SELECT count(*) AS snapshots FROM bronze.lakehouse."maint_demo$snapshots";
SELECT count(*) AS files, sum(file_size_in_bytes) / 1024 AS kb FROM bronze.lakehouse."maint_demo$files";
SELECT count(*) AS manifests FROM bronze.lakehouse."maint_demo$manifests";

-- 2. Компакция: склеивает мелкие файлы (порог по умолчанию — файлы < 100 МБ)
ALTER TABLE bronze.lakehouse.maint_demo EXECUTE optimize;
-- старые мелкие файлы ещё лежат в MinIO: на них ссылаются старые снапшоты (time travel ещё работает)

-- 3. Удаление старых снапшотов и их файлов.
--    По умолчанию Trino не даёт удалить снапшоты моложе 7 дней — для демонстрации снимаем ограничение
--    в сессии. В реальной системе retention оставляют 7+ дней, чтобы сохранить окно time travel.
SET SESSION bronze.expire_snapshots_min_retention = '0s';
SET SESSION bronze.remove_orphan_files_min_retention = '0s';
ALTER TABLE bronze.lakehouse.maint_demo EXECUTE expire_snapshots(retention_threshold => '0s');
ALTER TABLE bronze.lakehouse.maint_demo EXECUTE remove_orphan_files(retention_threshold => '0s');

-- После expire остался 1 снапшот, time travel к первым загрузкам больше невозможен
SELECT count(*) AS snapshots FROM bronze.lakehouse."maint_demo$snapshots";
SELECT count(*) AS files FROM bronze.lakehouse."maint_demo$files";

-- Рекомендуемый регламент для Bronze с частыми загрузками:
--   ежедневно:   ALTER TABLE ... EXECUTE optimize   (можно ограничить WHERE по партиции — только свежие дни загрузки)
--   ежедневно:   ALTER TABLE ... EXECUTE expire_snapshots(retention_threshold => '7d')
--   еженедельно: ALTER TABLE ... EXECUTE remove_orphan_files(retention_threshold => '7d')
