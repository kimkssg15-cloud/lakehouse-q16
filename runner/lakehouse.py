#!/usr/bin/env python3
"""
Раннер лабораторной: Bronze -> Silver -> Gold, проверки качества, бенчмарк форматов/кодеков,
time travel, schema evolution и автозаполнение REPORT.md реальными цифрами.

Запуск (из корня репозитория):
    docker compose run --rm runner python runner/lakehouse.py all

Отдельные шаги:
    setup | bronze | silver | gold | validate | layers | bench | timetravel | evolution | report

Все результаты складываются в results/results.json (шаги можно перезапускать по одному),
по ним строятся графики results/*.png и файл REPORT.md (из runner/report_template.md).
"""
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone, timedelta

import trino

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_DIR = os.path.join(ROOT, "sql")
RES_DIR = os.path.join(ROOT, "results")
RES_FILE = os.path.join(RES_DIR, "results.json")

HOST = os.environ.get("TRINO_HOST", "localhost")
PORT = int(os.environ.get("TRINO_PORT", "8080"))
SF = os.environ.get("SF", "sf10")
RUNS = int(os.environ.get("BENCH_RUNS", "5"))
KEEP_BENCH = os.environ.get("KEEP_BENCH", "0") == "1"

FORMATS = ["PARQUET", "ORC"]
CODECS = ["NONE", "SNAPPY", "GZIP", "ZSTD"]
TABLES = ["part", "partsupp", "supplier"]
MSK = timezone(timedelta(hours=3))

# Контрольные значения Q16 — посчитаны независимо (DuckDB на данных dbgen-совместимого
# генератора tpchgen-rs). Для sf1 совпадает с эталонным ответом спецификации TPC-H (18 314 строк).
CONTROL = {
    "sf1":  {"q16_rows": 18314, "q16_sum": 118250,  "complaints": 4,  "mart_rows": 123039},
    "sf5":  {"q16_rows": 27724, "q16_sum": 592541,  "complaints": 26, "mart_rows": 186607},
    "sf10": {"q16_rows": 27840, "q16_sum": 1186339, "complaints": 56, "mart_rows": 187495},
}

Q16_PARAMS = """p_brand <> 'Brand#45'
  AND p_type NOT LIKE 'MEDIUM POLISHED%'
  AND p_size IN (49, 14, 23, 45, 19, 3, 36, 9)"""


# ----------------------------------------------------------------------------- helpers
def log(msg):
    print(f"[{datetime.now(MSK):%H:%M:%S}] {msg}", flush=True)


def load_results():
    if os.path.exists(RES_FILE):
        with open(RES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_results(res):
    os.makedirs(RES_DIR, exist_ok=True)
    with open(RES_FILE, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2, default=str)


def connect(session=None):
    return trino.dbapi.connect(
        host=HOST, port=PORT, user="lab", source="lab-runner",
        session_properties=session or {}, request_timeout=3600,
    )


class Trino:
    """Тонкая обёртка: выполнить SQL, дочитать результат, вернуть строки + метрики запроса."""

    def __init__(self, session=None):
        self.conn = connect(session)

    def run(self, sql, quiet=False):
        cur = self.conn.cursor()
        t0 = time.perf_counter()
        cur.execute(sql)
        rows = cur.fetchall()
        wall = time.perf_counter() - t0
        cols = [d[0] for d in (cur.description or [])]
        st = cur.stats or {}
        qid = getattr(cur, "query_id", None) or st.get("queryId")
        m = {
            "query_id": qid,
            "client_s": round(wall, 3),
            "elapsed_s": round(st.get("elapsedTimeMillis", wall * 1000) / 1000, 3),
            "cpu_s": round(st.get("cpuTimeMillis", 0) / 1000, 3),
            "physical_input_mb": round(st.get("physicalInputBytes", 0) / 2**20, 2),
            "processed_rows": st.get("processedRows", 0),
            "peak_memory_mb": round(st.get("peakMemoryBytes", 0) / 2**20, 1),
        }
        # Серверное время из system.runtime.queries (end - created) — как советует методичка
        if qid:
            try:
                c2 = self.conn.cursor()
                c2.execute(
                    "SELECT to_milliseconds(\"end\" - created) FROM system.runtime.queries "
                    f"WHERE query_id = '{qid}'"
                )
                r = c2.fetchall()
                if r and r[0][0] is not None:
                    m["elapsed_s"] = round(r[0][0] / 1000, 3)
            except Exception:
                pass
        if not quiet:
            first = " ".join(sql.split())[:90]
            log(f"  {m['elapsed_s']:>8.2f}s  {first}")
        return rows, cols, m

    def scalar(self, sql):
        rows, _, _ = self.run(sql, quiet=True)
        return rows[0][0] if rows else None


def split_sql(text):
    """Разбить .sql на операторы: убрать комментарии -- (вне строк) и резать по ';'."""
    out, buf, in_str, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        if ch == "'" :
            in_str = not in_str
            buf.append(ch)
        elif not in_str and text.startswith("--", i):
            j = text.find("\n", i)
            i = len(text) if j == -1 else j
            continue
        elif not in_str and ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    stmt = "".join(buf).strip()
    if stmt:
        out.append(stmt)
    return out


def sql_file(name):
    with open(os.path.join(SQL_DIR, name), encoding="utf-8") as f:
        text = f.read()
    if SF != "sf10":
        text = text.replace("tpch.sf10.", f"tpch.{SF}.")
    return split_sql(text)


def run_file(db, name):
    log(f"== {name}")
    timings = []
    for stmt in sql_file(name):
        _, _, m = db.run(stmt)
        head = " ".join(stmt.split())[:120]
        timings.append({"sql": head, **m})
    return timings


def table_stats(db, fq):
    """Строки, число файлов, размер (МиБ) таблицы Iceberg по метатаблице $files."""
    cat, sch, tbl = fq.split(".")
    rows = db.scalar(f"SELECT count(*) FROM {fq}")
    r, _, _ = db.run(
        f'SELECT count(*), coalesce(sum(file_size_in_bytes), 0) FROM {cat}.{sch}."{tbl}$files"',
        quiet=True,
    )
    files, size = r[0]
    _, cols, _ = db.run(f"SELECT * FROM {fq} LIMIT 0", quiet=True)
    return {"rows": rows, "files": files, "bytes": size, "mb": round(size / 2**20, 2), "columns": cols}


def current_snapshot(db, schema, table):
    """id текущего снапшота. После rollback самый новый снапшот уже НЕ текущий, а журнал $history
    не получает новой записи — поэтому берём последнего «предка текущего состояния»."""
    return db.scalar(f'SELECT snapshot_id FROM {schema}."{table}$history" '
                     f'WHERE is_current_ancestor ORDER BY made_current_at DESC LIMIT 1')


def median_run(db, sql, runs=RUNS):
    """1 прогрев + runs замеров; возвращает медиану/мин/макс и метрики медианного прогона."""
    db.run(sql, quiet=True)  # warm-up: JIT, метаданные, соединения к MinIO
    ms, last_rows = [], None
    for _ in range(runs):
        rows, _, m = db.run(sql, quiet=True)
        ms.append(m)
        last_rows = rows
    el = [m["elapsed_s"] for m in ms]
    med = statistics.median(el)
    mid = sorted(ms, key=lambda m: m["elapsed_s"])[len(ms) // 2]
    return {
        "median_s": round(med, 3), "min_s": round(min(el), 3), "max_s": round(max(el), 3),
        "stdev_s": round(statistics.stdev(el), 3) if len(el) > 1 else 0.0,
        "runs": el, "cpu_s": mid["cpu_s"], "physical_input_mb": mid["physical_input_mb"],
        "peak_memory_mb": mid["peak_memory_mb"], "result": last_rows[0] if last_rows else None,
    }


def q16_sql(part, partsupp, supplier):
    return f"""SELECT p_brand, p_type, p_size, count(DISTINCT ps_suppkey) AS supplier_cnt
FROM {partsupp} JOIN {part} ON p_partkey = ps_partkey
WHERE {Q16_PARAMS}
  AND ps_suppkey NOT IN (SELECT s_suppkey FROM {supplier} WHERE s_comment LIKE '%Customer%Complaints%')
GROUP BY p_brand, p_type, p_size"""


def wrap_check(q):
    """Обёртка для замеров: считаем ответ на сервере, клиенту — 1 строка (контрольная сумма)."""
    return f"SELECT count(*), sum(supplier_cnt) FROM ({q})"


# ----------------------------------------------------------------------------- steps
def step_setup(res):
    db = Trino()
    rows, _, _ = db.run("SELECT node_version FROM system.runtime.nodes", quiet=True)
    cats = [r[0] for r in db.run("SHOW CATALOGS", quiet=True)[0]]
    mem_gb = None
    try:
        with open("/proc/meminfo") as f:
            mem_gb = round(int(f.readline().split()[1]) / 2**20, 1)
    except Exception:
        pass
    res["env"] = {
        "trino_version": rows[0][0] if rows else "?", "nodes": len(rows), "catalogs": cats,
        "sf": SF, "runs": RUNS, "docker_cpus": os.cpu_count(), "docker_mem_gb": mem_gb,
        "started_at": datetime.now(MSK).strftime("%Y-%m-%d %H:%M МСК"),
    }
    log(f"Trino {res['env']['trino_version']}, каталоги: {', '.join(cats)}")
    for need in ["bronze", "silver", "gold", "tpch"]:
        if need not in cats:
            sys.exit(f"Нет каталога {need} в Trino — проверь папку catalog/ и docker compose logs trino")
    run_file(db, "00_schemas.sql")


def step_layer(res, layer, sql_name, tables):
    db = Trino()
    t0 = time.perf_counter()
    timings = run_file(db, sql_name)
    total = time.perf_counter() - t0
    stats = {}
    for t in tables:
        fq = f"{layer}.lakehouse.{t}"
        stats[t] = table_stats(db, fq)
        s = stats[t]
        log(f"  {fq}: {s['rows']:,} строк, {s['files']} файлов, {s['mb']} МиБ")
    res[layer] = {"tables": stats, "build_s": round(total, 2), "statements": timings}


def step_validate(res):
    db = Trino()
    dq = {}
    log("== проверки качества данных")
    b, s = "bronze.lakehouse", "silver.lakehouse"
    dq["null_keys"] = {
        "part": db.scalar(f"SELECT count(*) FROM {b}.part WHERE p_partkey IS NULL"),
        "supplier": db.scalar(f"SELECT count(*) FROM {b}.supplier WHERE s_suppkey IS NULL"),
        "partsupp": db.scalar(f"SELECT count(*) FROM {b}.partsupp WHERE ps_partkey IS NULL OR ps_suppkey IS NULL"),
    }
    dq["dup_keys"] = {
        "part": db.scalar(f"SELECT count(*) - count(DISTINCT p_partkey) FROM {b}.part"),
        "supplier": db.scalar(f"SELECT count(*) - count(DISTINCT s_suppkey) FROM {b}.supplier"),
        "partsupp": db.scalar(
            f"SELECT count(*) FROM (SELECT ps_partkey, ps_suppkey FROM {b}.partsupp "
            f"GROUP BY 1, 2 HAVING count(*) > 1)"),
    }
    dq["invalid_values"] = {
        "part_size_out_of_range": db.scalar(f"SELECT count(*) FROM {b}.part WHERE p_size NOT BETWEEN 1 AND 50"),
        "partsupp_negative_qty": db.scalar(f"SELECT count(*) FROM {b}.partsupp WHERE ps_availqty < 0"),
        "partsupp_nonpositive_cost": db.scalar(f"SELECT count(*) FROM {b}.partsupp WHERE ps_supplycost <= 0"),
    }
    dq["orphans_partsupp"] = db.scalar(
        f"SELECT count(*) FROM {b}.partsupp ps LEFT JOIN {b}.part p ON p.p_partkey = ps.ps_partkey "
        f"LEFT JOIN {b}.supplier su ON su.s_suppkey = ps.ps_suppkey "
        f"WHERE p.p_partkey IS NULL OR su.s_suppkey IS NULL")
    try:  # доля текстовой колонки ps_comment (field id 5) в весе файлов partsupp
        dq["ps_comment_share"] = db.scalar(
            f'SELECT CAST(sum(element_at(column_sizes, 5)) AS double) / sum(file_size_in_bytes) '
            f'FROM bronze.lakehouse."partsupp$files"')
    except Exception as e:
        log(f"  (не удалось посчитать долю ps_comment: {e})")
    dq["complaint_suppliers"] = db.scalar(f"SELECT count_if(s_has_complaints) FROM {s}.supplier")
    dq["rows"] = {t: {"bronze": db.scalar(f"SELECT count(*) FROM {b}.{t}"),
                      "silver": db.scalar(f"SELECT count(*) FROM {s}.{t}")} for t in TABLES}

    # Корректность Gold: ответ Q16 по сырому Bronze == ответ из витрины Gold
    raw = q16_sql(f"{b}.part", f"{b}.partsupp", f"{b}.supplier")
    gold = "SELECT p_brand, p_type, p_size, supplier_cnt FROM gold.lakehouse.q16_report"
    dq["q16_bronze"] = list(db.run(wrap_check(raw), quiet=True)[0][0])
    dq["q16_gold"] = list(db.run(wrap_check(gold), quiet=True)[0][0])
    dq["q16_only_in_bronze"] = db.scalar(f"SELECT count(*) FROM ({raw} EXCEPT {gold})")
    dq["q16_only_in_gold"] = db.scalar(f"SELECT count(*) FROM ({gold} EXCEPT {raw})")
    dq["mart_rows"] = db.scalar("SELECT count(*) FROM gold.lakehouse.part_supplier_mart")
    top, cols, _ = db.run(
        "SELECT p_brand, p_type, p_size, supplier_cnt FROM gold.lakehouse.q16_report "
        "ORDER BY supplier_cnt DESC, p_brand, p_type, p_size LIMIT 10", quiet=True)
    dq["q16_top10"] = [list(r) for r in top]

    ctrl = CONTROL.get(SF)
    if ctrl:
        dq["control"] = ctrl
        dq["control_ok"] = (dq["q16_bronze"] == [ctrl["q16_rows"], ctrl["q16_sum"]]
                            and dq["complaint_suppliers"] == ctrl["complaints"]
                            and dq["mart_rows"] == ctrl["mart_rows"])
    ok = dq["q16_only_in_bronze"] == 0 and dq["q16_only_in_gold"] == 0
    dq["gold_matches_bronze"] = ok
    log(f"  Q16 Bronze: {dq['q16_bronze']}  Gold: {dq['q16_gold']}  расхождений: "
        f"{dq['q16_only_in_bronze']}/{dq['q16_only_in_gold']}  контроль: {dq.get('control_ok')}")
    res["dq"] = dq


def step_layers(res):
    """Один и тот же бизнес-вопрос (Q16) по трём слоям — зачем вообще нужен Gold."""
    db = Trino()
    log(f"== Q16 по слоям медальона ({RUNS} замеров + прогрев)")
    b, s = "bronze.lakehouse", "silver.lakehouse"
    queries = {
        "bronze": q16_sql(f"{b}.part", f"{b}.partsupp", f"{b}.supplier"),
        "silver": f"""SELECT p.p_brand, p.p_type, p.p_size, count(DISTINCT ps.ps_suppkey) AS supplier_cnt
FROM {s}.partsupp ps JOIN {s}.part p ON p.p_partkey = ps.ps_partkey
WHERE p.p_brand <> 'Brand#45' AND p.p_type NOT LIKE 'MEDIUM POLISHED%'
  AND p.p_size IN (49, 14, 23, 45, 19, 3, 36, 9)
  AND ps.ps_suppkey NOT IN (SELECT s_suppkey FROM {s}.supplier WHERE s_has_complaints)
GROUP BY p.p_brand, p.p_type, p.p_size""",
        "gold_mart": f"""SELECT p_brand, p_type, p_size, supplier_cnt FROM gold.lakehouse.part_supplier_mart
WHERE {Q16_PARAMS} AND supplier_cnt > 0""",
        "gold_report": "SELECT p_brand, p_type, p_size, supplier_cnt FROM gold.lakehouse.q16_report",
    }
    out = {}
    for k, q in queries.items():
        out[k] = median_run(db, wrap_check(q))
        out[k]["sql"] = q
        log(f"  {k:12s} медиана {out[k]['median_s']:.3f}s  прочитано {out[k]['physical_input_mb']} МиБ  "
            f"результат {out[k]['result']}")
    res["layers_q16"] = out


def step_bench(res):
    log(f"== бенчмарк: {len(FORMATS)} формата x {len(CODECS)} кодека, {RUNS} замеров + прогрев")
    bench = res.get("bench", {})
    src = "bronze.lakehouse"
    for fmt in FORMATS:
        for codec in CODECS:
            key = f"{fmt}_{codec}"
            sfx = key.lower()
            db = Trino(session={"bronze.compression_codec": codec})
            log(f"-- {fmt} + {codec}")
            v = {"format": fmt, "codec": codec, "tables": {}}
            write_total = 0.0
            for t in TABLES:
                fq = f"bronze.bench.{t}_{sfx}"
                db.run(f"DROP TABLE IF EXISTS {fq}", quiet=True)
                _, _, m = db.run(
                    f"CREATE TABLE {fq} WITH (format = '{fmt}') AS SELECT * FROM {src}.{t}", quiet=True)
                st = table_stats(db, fq)
                st.pop("columns", None)
                st["write_s"] = m["elapsed_s"]
                st["write_cpu_s"] = m["cpu_s"]
                v["tables"][t] = st
                write_total += m["elapsed_s"]
            v["write_s"] = round(write_total, 3)
            v["bytes"] = sum(x["bytes"] for x in v["tables"].values())
            v["mb"] = round(v["bytes"] / 2**20, 2)
            names = {t: f"bronze.bench.{t}_{sfx}" for t in TABLES}
            v["q16"] = median_run(db, wrap_check(q16_sql(names["part"], names["partsupp"], names["supplier"])))
            v["scan"] = median_run(db, (
                f"SELECT count(*), sum(length(ps_comment)), "
                f"CAST(sum(ps_availqty * ps_supplycost) AS bigint) FROM {names['partsupp']}"))
            log(f"   размер {v['mb']:>9.2f} МиБ | запись {v['write_s']:>7.2f}s | "
                f"Q16 {v['q16']['median_s']:.3f}s | full-scan {v['scan']['median_s']:.3f}s | "
                f"Q16 прочитал {v['q16']['physical_input_mb']} МиБ")
            if not KEEP_BENCH:
                for fq in names.values():
                    db.run(f"DROP TABLE IF EXISTS {fq}", quiet=True)
            bench[key] = v
            res["bench"] = bench
            save_results(res)  # сохраняем после каждого варианта — можно прервать и продолжить
    # контроль: все варианты дали один и тот же ответ Q16
    answers = {json.dumps(v["q16"]["result"]) for v in bench.values()}
    res["bench_same_answer"] = len(answers) == 1


def step_timetravel(res):
    db = Trino()
    log("== time travel + восстановление из снапшота (silver.lakehouse.supplier)")
    t = "silver.lakehouse.supplier"
    snap = current_snapshot(db, "silver.lakehouse", "supplier")
    before = db.scalar(f"SELECT count(*) FROM {t}")
    db.run(f"DELETE FROM {t} WHERE s_nationkey = 7")
    after = db.scalar(f"SELECT count(*) FROM {t}")
    past = db.scalar(f"SELECT count(*) FROM {t} FOR VERSION AS OF {snap}")
    lost, _, _ = db.run(f"SELECT s_suppkey, s_name FROM {t} FOR VERSION AS OF {snap} WHERE s_nationkey = 7 "
                        f"ORDER BY s_suppkey LIMIT 3", quiet=True)
    db.run(f"ALTER TABLE {t} EXECUTE rollback_to_snapshot({snap})")
    restored = db.scalar(f"SELECT count(*) FROM {t}")
    hist, hcols, _ = db.run(f'SELECT made_current_at, snapshot_id, parent_id, is_current_ancestor '
                            f'FROM silver.lakehouse."supplier$history" ORDER BY made_current_at', quiet=True)
    res["timetravel"] = {
        "snapshot_id": snap, "rows_before": before, "rows_after_delete": after,
        "rows_time_travel": past, "rows_restored": restored, "lost_sample": [list(r) for r in lost],
        "history": [[str(c) for c in r] for r in hist], "ok": before == past == restored and after < before,
    }
    log(f"  до {before:,} -> после DELETE {after:,} -> FOR VERSION AS OF {past:,} -> после отката {restored:,}")


def step_evolution(res):
    db = Trino()
    log("== schema evolution (silver.lakehouse.supplier)")
    t = "silver.lakehouse.supplier"
    db.run(f"ALTER TABLE {t} DROP COLUMN IF EXISTS s_acctbal_segment", quiet=True)
    db.run(f"ALTER TABLE {t} DROP COLUMN IF EXISTS s_balance_segment", quiet=True)
    snap = current_snapshot(db, "silver.lakehouse", "supplier")
    files_before = db.scalar(f'SELECT count(*) FROM silver.lakehouse."supplier$files"')
    _, cols_before, _ = db.run(f"SELECT * FROM {t} LIMIT 0", quiet=True)

    _, _, m_add = db.run(f"ALTER TABLE {t} ADD COLUMN s_balance_segment varchar")
    files_after_add = db.scalar(f'SELECT count(*) FROM silver.lakehouse."supplier$files"')
    nulls = db.scalar(f"SELECT count(*) FROM {t} WHERE s_balance_segment IS NULL")
    _, _, m_upd = db.run(f"""UPDATE {t} SET s_balance_segment = CASE
        WHEN s_acctbal < 0 THEN 'DEBT' WHEN s_acctbal < 5000 THEN 'LOW' ELSE 'HIGH' END""")
    _, _, m_ren = db.run(f"ALTER TABLE {t} RENAME COLUMN s_balance_segment TO s_acctbal_segment")
    _, cols_after, _ = db.run(f"SELECT * FROM {t} LIMIT 0", quiet=True)
    seg, _, _ = db.run(f"SELECT s_acctbal_segment, count(*) FROM {t} GROUP BY 1 ORDER BY 1", quiet=True)
    _, cols_old, _ = db.run(f"SELECT * FROM {t} FOR VERSION AS OF {snap} LIMIT 1", quiet=True)
    old_rows = db.scalar(f"SELECT count(*) FROM {t} FOR VERSION AS OF {snap}")
    gold_ok = db.scalar("SELECT count(*) FROM gold.lakehouse.part_supplier_mart")
    n_snap = db.scalar(f'SELECT count(*) FROM silver.lakehouse."supplier$snapshots"')
    res["evolution"] = {
        "snapshot_before": snap, "cols_before": cols_before, "cols_after": cols_after,
        "cols_old_snapshot": cols_old, "old_snapshot_rows": old_rows,
        "files_before": files_before, "files_after_add": files_after_add,
        "nulls_after_add": nulls, "segments": [list(r) for r in seg],
        "add_s": m_add["elapsed_s"], "update_s": m_upd["elapsed_s"], "rename_s": m_ren["elapsed_s"],
        "gold_rows_after": gold_ok, "snapshots_total": n_snap,
    }
    log(f"  колонки: {len(cols_before)} -> {len(cols_after)}; файлов до/после ADD: "
        f"{files_before}/{files_after_add}; сегменты: {seg}")


# ----------------------------------------------------------------------------- report
def step_report(res):
    import report
    report.build(res, ROOT)
    log("REPORT.md и графики results/*.png обновлены")


STEPS = {
    "setup": step_setup,
    "bronze": lambda r: step_layer(r, "bronze", "01_bronze.sql", TABLES),
    "silver": lambda r: step_layer(r, "silver", "02_silver.sql", TABLES),
    "gold": lambda r: step_layer(r, "gold", "03_gold.sql", ["part_supplier_mart", "q16_report"]),
    "validate": step_validate,
    "layers": step_layers,
    "bench": step_bench,
    "timetravel": step_timetravel,
    "evolution": step_evolution,
    "report": step_report,
}
ALL = ["setup", "bronze", "silver", "gold", "validate", "layers", "bench", "timetravel", "evolution", "report"]


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    steps = ALL if argv[1] == "all" else argv[1:]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    res = load_results()
    for name in steps:
        if name not in STEPS:
            sys.exit(f"неизвестный шаг: {name}; доступны: {', '.join(STEPS)} или all")
        t0 = time.perf_counter()
        STEPS[name](res)
        res.setdefault("step_s", {})[name] = round(time.perf_counter() - t0, 1)
        save_results(res)
    log("готово")


if __name__ == "__main__":
    main(sys.argv)
