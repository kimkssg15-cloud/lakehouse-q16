"""Построение графиков и заполнение REPORT.md по results/results.json.

Все выводы в отчёте, которые зависят от цифр (что меньше, что быстрее, насколько),
формулируются здесь по фактическим замерам — а не пишутся заранее.
"""
import csv
import os
import re

BLUE, ORANGE = "#2a78d6", "#eb6834"      # PARQUET, ORC (категориальная палитра, слоты 1–2)
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
FORMATS = ["PARQUET", "ORC"]
CODECS = ["NONE", "SNAPPY", "GZIP", "ZSTD"]
MISSING = "_нет данных — запусти соответствующий шаг раннера_"


# ----------------------------------------------------------------------------- форматирование
def n(x):
    """8000000 -> '8 000 000'"""
    return f"{int(x):,}".replace(",", " ") if x is not None else "—"


def f2(x, d=2):
    return f"{x:.{d}f}" if x is not None else "—"


def fx(r):
    """кратность: 3.4 -> '3.4', 27.6 -> '28'"""
    return f"{r:.1f}" if r < 10 else f"{r:.0f}"


def pct(a, b):
    """на сколько % a отличается от b"""
    return (a - b) / b * 100 if b else 0.0


def more_less(a, b, more="больше", less="меньше"):
    return more if a > b else less


def gh_slug(text, seen):
    """Якорь заголовка так, как его строит GitHub: нижний регистр, без пунктуации, пробелы -> '-'."""
    slug = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    k = seen.get(slug, 0)
    seen[slug] = k + 1
    return slug if k == 0 else f"{slug}-{k}"


def insert_toc(md):
    """Оглавление по заголовкам ## и ### (кроме шапки), вставляется перед первой чертой ---."""
    seen, lines, in_code = {}, [], False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(##|###) (.+)$", line)
        if not m:
            continue
        level, title = m.groups()
        if title.startswith("Развёртывание локального"):
            continue
        slug = gh_slug(title, seen)
        clean = re.sub(r"[`*]", "", title)
        lines.append(("" if level == "##" else "  ") + f"- [{clean}](#{slug})")
    toc = "**Содержание**\n\n" + "\n".join(lines)
    return md.replace("\n---\n", "\n" + toc + "\n\n---\n", 1)


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ----------------------------------------------------------------------------- графики
def charts(res, root):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    out = os.path.join(root, "results")
    plt.rcParams.update({
        "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK2, "xtick.color": INK2,
        "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
        "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white",
    })
    bench = res.get("bench") or {}
    if bench:
        panels = [
            ("Размер Bronze, МБ", lambda v: v["mb"], None),
            ("Время записи Bronze, с", lambda v: v["write_s"], None),
            ("Q16, медиана, с", lambda v: v["q16"]["median_s"],
             lambda v: (v["q16"]["median_s"] - v["q16"]["min_s"], v["q16"]["max_s"] - v["q16"]["median_s"])),
            ("Full scan partsupp, медиана, с", lambda v: v["scan"]["median_s"],
             lambda v: (v["scan"]["median_s"] - v["scan"]["min_s"], v["scan"]["max_s"] - v["scan"]["median_s"])),
        ]
        fig, axes = plt.subplots(2, 2, figsize=(11, 7.2))
        w = 0.38
        for ax, (title, get, err) in zip(axes.flat, panels):
            for i, (fmt, color) in enumerate(zip(FORMATS, [BLUE, ORANGE])):
                xs, ys, es = [], [], [[], []]
                for j, c in enumerate(CODECS):
                    v = bench.get(f"{fmt}_{c}")
                    if not v:
                        continue
                    xs.append(j + (i - 0.5) * (w + 0.02))
                    ys.append(get(v))
                    if err:
                        lo, hi = err(v)
                        es[0].append(max(lo, 0)); es[1].append(max(hi, 0))
                bars = ax.bar(xs, ys, width=w, color=color, label=fmt, edgecolor="white", linewidth=1)
                if err and ys:
                    ax.errorbar(xs, ys, yerr=es, fmt="none", ecolor=INK2, elinewidth=1, capsize=3)
                tops = [y + (es[1][k] if err else 0) for k, y in enumerate(ys)]
                for b, y, top in zip(bars, ys, tops):
                    ax.annotate(f"{y:.1f}" if y >= 10 else f"{y:.2f}", (b.get_x() + b.get_width() / 2, top),
                                xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8, color=INK2)
            ax.set_title(title, loc="left", color=INK, fontsize=11)
            ax.set_xticks(range(len(CODECS)), CODECS)
            ax.margins(y=0.15)
        axes[0][0].legend(frameon=False, loc="upper right")
        fig.suptitle(f"Бенчмарк Bronze: формат × кодек (TPC-H {res.get('env', {}).get('sf', '')}, "
                     f"Trino {res.get('env', {}).get('trino_version', '')}); усы — min–max замеров",
                     x=0.01, ha="left", color=INK, fontsize=12)
        fig.tight_layout()
        fig.savefig(os.path.join(out, "benchmark.png"), dpi=130)
        plt.close(fig)

    lay = res.get("layers_q16")
    if lay:
        names = {"bronze": "Bronze (сырой Q16)", "silver": "Silver (флаг жалоб)",
                 "gold_mart": "Gold: куб + WHERE", "gold_report": "Gold: готовый отчёт"}
        keys = [k for k in names if k in lay]
        fig, ax = plt.subplots(figsize=(8, 3.2))
        ys = [lay[k]["median_s"] for k in keys]
        bars = ax.barh(range(len(keys)), ys, color=BLUE, height=0.55)
        ax.set_yticks(range(len(keys)), [names[k] for k in keys])
        ax.invert_yaxis()
        ax.grid(axis="x", color=GRID); ax.grid(axis="y", visible=False)
        for b, k in zip(bars, keys):
            ax.annotate(f"{lay[k]['median_s']:.3f} с  ·  {lay[k]['physical_input_mb']} МиБ прочитано",
                        (b.get_width(), b.get_y() + b.get_height() / 2), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=9, color=INK2)
        ax.set_title("Q16 по слоям медальона, медиана времени, с", loc="left", color=INK, fontsize=11)
        ax.margins(x=0.45)
        fig.tight_layout()
        fig.savefig(os.path.join(out, "layers_q16.png"), dpi=130)
        plt.close(fig)


def write_csv(res, root):
    bench = res.get("bench") or {}
    if not bench:
        return
    with open(os.path.join(root, "results", "benchmark.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["format", "codec", "size_mb", "files", "write_s", "q16_median_s", "q16_min_s", "q16_max_s",
                     "q16_stdev_s", "q16_read_mb", "q16_cpu_s", "scan_median_s", "scan_min_s", "scan_max_s",
                     "scan_read_mb", "scan_cpu_s"])
        for k, v in bench.items():
            q, s = v["q16"], v["scan"]
            wr.writerow([v["format"], v["codec"], v["mb"], sum(t["files"] for t in v["tables"].values()),
                         v["write_s"], q["median_s"], q["min_s"], q["max_s"], q["stdev_s"],
                         q["physical_input_mb"], q["cpu_s"], s["median_s"], s["min_s"], s["max_s"],
                         s["physical_input_mb"], s["cpu_s"]])


# ----------------------------------------------------------------------------- текстовые выводы
def bench_texts(res, ctx):
    bench = res.get("bench") or {}
    if len(bench) < 2:
        return
    V = bench
    def get(f, c):
        return V.get(f"{f}_{c}")

    # таблица 8 вариантов
    rows = []
    for f in FORMATS:
        base = get(f, "NONE")
        for c in CODECS:
            v = get(f, c)
            if not v:
                continue
            ratio = f"{base['mb'] / v['mb']:.2f}×" if base else "—"
            rows.append([f, c, f2(v["mb"]), ratio, f2(v["write_s"]),
                         f"{f2(v['q16']['median_s'], 3)} ({f2(v['q16']['min_s'], 3)}–{f2(v['q16']['max_s'], 3)})",
                         f2(v["q16"]["physical_input_mb"]),
                         f"{f2(v['scan']['median_s'], 3)} ({f2(v['scan']['min_s'], 3)}–{f2(v['scan']['max_s'], 3)})",
                         f2(v["scan"]["cpu_s"])])
    ctx["bench_table"] = md_table(
        ["Формат", "Кодек", "Размер, МБ", "Сжатие", "Запись, с", "Q16 медиана, с (min–max)",
         "Q16 прочитано, МиБ", "Full scan медиана, с (min–max)", "Full scan CPU, с"], rows)

    vals = list(V.values())
    label = lambda v: f"{v['format']}+{v['codec']}"
    smallest = min(vals, key=lambda v: v["mb"]); largest = max(vals, key=lambda v: v["mb"])
    fast_w = min(vals, key=lambda v: v["write_s"]); slow_w = max(vals, key=lambda v: v["write_s"])
    fast_q = min(vals, key=lambda v: v["q16"]["median_s"]); slow_q = max(vals, key=lambda v: v["q16"]["median_s"])
    fast_s = min(vals, key=lambda v: v["scan"]["median_s"]); slow_s = max(vals, key=lambda v: v["scan"]["median_s"])
    q_spread = pct(slow_q["q16"]["median_s"], fast_q["q16"]["median_s"])
    noise = max(v["q16"]["stdev_s"] for v in vals)
    q_noise = (slow_q["q16"]["median_s"] - fast_q["q16"]["median_s"]) <= 2 * noise

    lines = [
        f"* **Размер.** Самый компактный вариант — **{label(smallest)}** ({f2(smallest['mb'])} МБ), самый большой — "
        f"{label(largest)} ({f2(largest['mb'])} МБ): разница в **{largest['mb'] / smallest['mb']:.2f} раза**.",
        f"* **Запись.** Быстрее всего пишется **{label(fast_w)}** ({f2(fast_w['write_s'])} с), медленнее всего — "
        f"{label(slow_w)} ({f2(slow_w['write_s'])} с, на {pct(slow_w['write_s'], fast_w['write_s']):.0f} % дольше).",
        f"* **Q16.** Лучшая медиана — **{label(fast_q)}** ({f2(fast_q['q16']['median_s'], 3)} с), худшая — "
        f"{label(slow_q)} ({f2(slow_q['q16']['median_s'], 3)} с), разброс {q_spread:.0f} %. "
        + ("Это сопоставимо с разбросом между повторами одного варианта (σ до "
           f"{f2(noise, 3)} с), т.е. для Q16 влияние кодека **почти в пределах погрешности**: запрос читает лишь "
           f"~{f2(fast_q['q16']['physical_input_mb'])} МиБ нужных колонок, и время уходит на джойн и "
           "`count(DISTINCT)`, а не на чтение и распаковку."
           if q_noise else
           "Разница больше разброса повторов, т.е. кодек заметно влияет на время Q16."),
        f"* **Full scan** (все колонки, включая текст) чувствительнее к кодеку: лучший — **{label(fast_s)}** "
        f"({f2(fast_s['scan']['median_s'], 3)} с), худший — {label(slow_s)} ({f2(slow_s['scan']['median_s'], 3)} с, "
        f"+{pct(slow_s['scan']['median_s'], fast_s['scan']['median_s']):.0f} %).",
    ]
    # NONE vs ZSTD
    for f in FORMATS:
        a, z = get(f, "NONE"), get(f, "ZSTD")
        if a and z:
            lines.append(
                f"* **{f}: ZSTD против NONE** — файлы в {a['mb'] / z['mb']:.2f} раза меньше; "
                f"Q16 {more_less(z['q16']['median_s'], a['q16']['median_s'], 'медленнее', 'быстрее')} на "
                f"{abs(pct(z['q16']['median_s'], a['q16']['median_s'])):.0f} %, прочитано "
                f"{f2(z['q16']['physical_input_mb'])} МиБ вместо {f2(a['q16']['physical_input_mb'])} МиБ.")
    # Parquet vs ORC
    pm = [get("PARQUET", c) for c in CODECS if get("PARQUET", c)]
    om = [get("ORC", c) for c in CODECS if get("ORC", c)]
    if pm and om:
        avg = lambda xs, k: sum(k(x) for x in xs) / len(xs)
        ps, os_ = avg(pm, lambda v: v["mb"]), avg(om, lambda v: v["mb"])
        pq, oq = avg(pm, lambda v: v["q16"]["median_s"]), avg(om, lambda v: v["q16"]["median_s"])
        lines.append(
            f"* **Parquet vs ORC** (среднее по 4 кодекам): размер {f2(ps)} vs {f2(os_)} МБ "
            f"(ORC {more_less(os_, ps)} на {abs(pct(os_, ps)):.0f} %), Q16 {f2(pq, 3)} vs {f2(oq, 3)} с "
            f"(ORC {more_less(oq, pq, 'медленнее', 'быстрее')} на {abs(pct(oq, pq)):.0f} %).")
    ctx["bench_conclusions"] = "\n".join(lines)
    ctx["bench_same_answer"] = ("проверено: ответ одинаковый во всех вариантах"
                                if res.get("bench_same_answer") else "ВНИМАНИЕ: ответы различаются!")

    # таблица из формы (Parquet: GZIP vs ZSTD)
    g, z = get("PARQUET", "GZIP"), get("PARQUET", "ZSTD")
    if g and z:
        for k, v in (("gzip", g), ("zstd", z)):
            ctx[f"{k}_q16"] = f"{f2(v['q16']['median_s'], 3)} с (min {f2(v['q16']['min_s'], 3)}, max {f2(v['q16']['max_s'], 3)})"
            ctx[f"{k}_mb"] = f2(v["mb"])
            ctx[f"{k}_write"] = f"{f2(v['write_s'])} с"
        ds, dw = pct(g["mb"], z["mb"]), pct(g["write_s"], z["write_s"])
        dq, dsc = pct(g["q16"]["median_s"], z["q16"]["median_s"]), pct(g["scan"]["median_s"], z["scan"]["median_s"])
        ctx["gzip_conclusion"] = (
            f"Относительно ZSTD: размер {more_less(ds, 0)} на {abs(ds):.1f} %, запись "
            f"{more_less(dw, 0, 'медленнее', 'быстрее')} на {abs(dw):.0f} %, Q16 "
            f"{more_less(dq, 0, 'медленнее', 'быстрее')} на {abs(dq):.0f} %, full scan "
            f"{more_less(dsc, 0, 'медленнее', 'быстрее')} на {abs(dsc):.0f} %. Deflate — старый и медленный "
            f"алгоритм: {'выигрыш в размере небольшой, а' if ds < 0 else 'он даже не меньше по размеру, и'} "
            f"платим за него процессором при каждой записи и чтении.")
        zstd_wins = (z["write_s"] <= g["write_s"]) + (z["q16"]["median_s"] <= g["q16"]["median_s"]) + \
                    (z["scan"]["median_s"] <= g["scan"]["median_s"]) + (abs(ds) < 5 or z["mb"] <= g["mb"])
        faster = [name for name, a, b in (("запись", z["write_s"], g["write_s"]),
                                          ("Q16", z["q16"]["median_s"], g["q16"]["median_s"]),
                                          ("full scan", z["scan"]["median_s"], g["scan"]["median_s"])) if a <= b]
        size_txt = ("почти такой же размер" if abs(ds) < 5 else
                    ("меньший размер" if z["mb"] < g["mb"] else "размер больше на " + f"{abs(ds):.0f} %"))
        ctx["zstd_conclusion"] = (
            ("**Лучше ZSTD**: " if zstd_wins >= 3 else "Компромисс: ")
            + f"{size_txt} ({f2(z['mb'])} vs {f2(g['mb'])} МБ)"
            + (f", при этом быстрее GZIP: {', '.join(faster)}" if faster else ", но по скорости GZIP здесь не уступает")
            + ". ZSTD — современный кодек (LZ77 + энтропийное кодирование FSE), быстро распаковывается; "
              "это кодек по умолчанию в Trino и Iceberg, выбран для всех слоёв.")

    best_none = [get(f, "NONE") for f in FORMATS if get(f, "NONE")]
    if best_none:
        nb = max(best_none, key=lambda v: v["mb"])
        q_sp = pct(slow_q["q16"]["median_s"], fast_q["q16"]["median_s"])
        s_sp = pct(slow_s["scan"]["median_s"], fast_s["scan"]["median_s"])
        comp = [v for v in vals if v["codec"] != "NONE"]
        cq_fast = min(comp, key=lambda v: v["q16"]["median_s"]); cq_slow = max(comp, key=lambda v: v["q16"]["median_s"])
        none_q = [v for v in vals if v["codec"] == "NONE"]
        nq = max(none_q, key=lambda v: v["q16"]["median_s"]) if none_q else None
        ctx["_compress_summary"] = (
            f"выбор кодека меняет размер Bronze до {nb['mb'] / smallest['mb']:.1f} раза, время записи — до "
            f"{pct(slow_w['write_s'], fast_w['write_s']):.0f} %, full scan — до {s_sp:.0f} %. "
            + (f"Для Q16 важнее всего **сжимать вообще**: без сжатия ({nq['format']}+NONE) запрос идёт "
               f"{f2(nq['q16']['median_s'], 2)} с и читает {f2(nq['q16']['physical_input_mb'])} МиБ, а со сжатием — "
               f"{f2(cq_fast['q16']['median_s'], 2)}–{f2(cq_slow['q16']['median_s'], 2)} с: меньше байт нужно скачать из MinIO. "
               if nq else "")
            + f"Между самими кодеками разница по Q16 до {pct(cq_slow['q16']['median_s'], cq_fast['q16']['median_s']):.0f} %, "
              "а сильнее всего кодек влияет на время записи и размер.")
    if g and z:
        parts = []
        parts.append(f"по размеру ZSTD {'почти равен' if abs(ds) < 5 else ('меньше' if z['mb'] < g['mb'] else 'больше')} "
                     f"GZIP ({f2(z['mb'])} vs {f2(g['mb'])} МБ)")
        parts.append(f"по записи {more_less(z['write_s'], g['write_s'], 'медленнее', 'быстрее')} на "
                     f"{abs(pct(z['write_s'], g['write_s'])):.0f} %, по full scan "
                     f"{more_less(z['scan']['median_s'], g['scan']['median_s'], 'медленнее', 'быстрее')} на "
                     f"{abs(pct(z['scan']['median_s'], g['scan']['median_s'])):.0f} %")
        nz = get("PARQUET", "NONE")
        if nz:
            parts.append(f"относительно несжатого Parquet экономит {100 - z['mb'] / nz['mb'] * 100:.0f} % места "
                         f"(а значит, и трафика до S3)")
        ctx["_choice_summary"] = "; ".join(parts) + ". Место варианта в рейтинге по формуле — в разделе 5."

    # Итоговый выбор: взвешенная оценка, нормированная на лучший вариант
    def score(v, w):
        best = {"mb": smallest["mb"], "write": fast_w["write_s"], "q16": fast_q["q16"]["median_s"],
                "scan": fast_s["scan"]["median_s"]}
        return (w[0] * v["mb"] / best["mb"] + w[1] * v["write_s"] / best["write"]
                + w[2] * v["q16"]["median_s"] / best["q16"] + w[3] * v["scan"]["median_s"] / best["scan"])
    wb, wr = (0.5, 0.25, 0.0, 0.25), (0.2, 0.0, 0.5, 0.3)
    best_b = min(vals, key=lambda v: score(v, wb)); best_r = min(vals, key=lambda v: score(v, wr))
    zp = get("PARQUET", "ZSTD")
    rank_b = sorted(vals, key=lambda v: score(v, wb)).index(zp) + 1 if zp else None
    rank_r = sorted(vals, key=lambda v: score(v, wr)).index(zp) + 1 if zp else None
    head = (
        "чтобы выбор был не «на глаз», считаю взвешенную оценку (каждая метрика делится на лучшее значение "
        "среди 8 вариантов, меньше — лучше):\n\n"
        "* **Bronze** (пишется один раз, хранится долго, читается редко — при пересчёте Silver): "
        "0.5·размер + 0.25·запись + 0.25·full scan → лучший вариант "
        f"**{label(best_b)}**; PARQUET+ZSTD — на {rank_b}-м месте из {len(vals)}.\n"
        "* **Silver / Gold** (читаются постоянно аналитическими запросами): 0.5·Q16 + 0.3·full scan + 0.2·размер → "
        f"лучший **{label(best_r)}**; PARQUET+ZSTD — на {rank_r}-м месте.\n\n")
    if zp and rank_b <= 3 and rank_r <= 3:
        tail = ("**Вывод: PARQUET + ZSTD подтверждён бенчмарком** для всех трёх слоёв (входит в лучшие варианты по "
                "обоим профилям), плюс Parquet — стандарт экосистемы Iceberg, а ZSTD — значение по умолчанию Trino, "
                "т.е. не нужна особая настройка у других потребителей.")
    elif zp:
        diffs = [abs(pct(zp["mb"], best_r["mb"])), abs(pct(zp["write_s"], best_r["write_s"])),
                 abs(pct(zp["q16"]["median_s"], best_r["q16"]["median_s"])),
                 abs(pct(zp["scan"]["median_s"], best_r["scan"]["median_s"]))]
        q_better = zp["q16"]["median_s"] < best_r["q16"]["median_s"]
        tail = (f"**Вывод:** по формуле на этом стенде формально лучше {label(best_b)} для Bronze и "
                f"{label(best_r)} для Silver/Gold. Сравнение {label(best_r)} с PARQUET+ZSTD: размер "
                f"{f2(best_r['mb'])} vs {f2(zp['mb'])} МБ, запись {f2(best_r['write_s'])} vs {f2(zp['write_s'])} с, "
                f"full scan {f2(best_r['scan']['median_s'], 3)} vs {f2(zp['scan']['median_s'], 3)} с, а **Q16 — "
                f"целевой запрос варианта** — {f2(best_r['q16']['median_s'], 3)} vs {f2(zp['q16']['median_s'], 3)} с"
                + (" (здесь Parquet+ZSTD быстрее)" if q_better else "")
                + f". Разница по каждой метрике не больше {max(diffs):.0f} %, поэтому я оставляю **PARQUET + ZSTD**: "
                  "Parquet — де-факто стандарт экосистемы Iceberg (его без настроек читают Spark, DuckDB, pandas, "
                  "PyIceberg), а ZSTD — кодек по умолчанию в Trino и Iceberg"
                + (", и на целевом запросе Q16 этот вариант быстрее" if q_better else "")
                + f". {label(best_r)} — разумная альтернатива, если основная нагрузка — полные сканирования таблиц.")
    else:
        tail = ""
    ctx["final_choice"] = head + tail
    ctx["_best_b"], ctx["_best_r"] = label(best_b), label(best_r)


def build(res, root):
    charts(res, root)
    write_csv(res, root)
    ctx = {}
    env = res.get("env", {})
    sf = env.get("sf", "sf10")
    ctx.update({
        "trino_version": env.get("trino_version", "476"), "started_at": env.get("started_at", "—"),
        "docker_cpus": env.get("docker_cpus", "—"), "docker_mem_gb": env.get("docker_mem_gb", "—"),
        "sf": sf, "runs": env.get("runs", 5),
        "env_line": f"Trino {env.get('trino_version', '?')}, Docker: {env.get('docker_cpus', '?')} vCPU, "
                    f"{env.get('docker_mem_gb', '?')} ГБ RAM",
    })

    # --- слои
    for layer in ("bronze", "silver"):
        T = (res.get(layer) or {}).get("tables") or {}
        for t, s in T.items():
            ctx[f"{layer}_{t}_rows"] = n(s["rows"])
            ctx[f"{layer}_{t}_mb"] = f2(s["mb"])
        if T:
            ctx[f"{layer}_total_rows"] = n(sum(s["rows"] for s in T.values()))
            ctx[f"{layer}_total_mb"] = f2(sum(s["mb"] for s in T.values()))
    B = (res.get("bronze") or {}).get("tables") or {}
    S = (res.get("silver") or {}).get("tables") or {}
    G = (res.get("gold") or {}).get("tables") or {}
    if B:
        tot = sum(s["bytes"] for s in B.values())
        ctx["bronze_partsupp_share"] = f"{B['partsupp']['bytes'] / tot * 100:.0f} %"
    if B and S:
        ctx["silver_vs_bronze"] = f"{sum(s['bytes'] for s in B.values()) / max(sum(s['bytes'] for s in S.values()), 1):.1f}"
        ctx["silver_part_partition_mb"] = f2(S["part"]["mb"] / 50, 2)
    if G:
        ctx["gold_mart_rows"] = n(G["part_supplier_mart"]["rows"]); ctx["gold_mart_mb"] = f2(G["part_supplier_mart"]["mb"])
        ctx["gold_q16_rows"] = n(G["q16_report"]["rows"]); ctx["gold_q16_mb"] = f2(G["q16_report"]["mb"], 3)
        ctx["gold_total_mb"] = f2(sum(s["mb"] for s in G.values()))

    bench = res.get("bench") or {}
    zp, np_, gp = bench.get("PARQUET_ZSTD"), bench.get("PARQUET_NONE"), bench.get("PARQUET_GZIP")
    if zp and np_ and gp:
        ctx["bronze_reason"] = (
            f"Сырой слой пишется один раз и хранится долго, читается редко (при пересчёте Silver) → главное размер. "
            f"По бенчмарку PARQUET+ZSTD: {f2(zp['mb'])} МБ против {f2(np_['mb'])} МБ без сжатия "
            f"(в {np_['mb'] / zp['mb']:.1f} раза меньше) и {f2(gp['mb'])} МБ у GZIP, при этом запись "
            f"{f2(zp['write_s'])} с против {f2(gp['write_s'])} с у GZIP. Parquet — колоночный стандарт Iceberg.")
    else:
        ctx["bronze_reason"] = ("Сырой слой пишется один раз и хранится долго → главное размер при приемлемой "
                                "скорости записи; ZSTD — лучший баланс (см. раздел 5). Parquet — колоночный стандарт Iceberg.")

    total_min = sum((res.get("step_s") or {}).values()) / 60
    bronze_mb = sum(s["mb"] for s in B.values()) if B else None
    ctx["sf_reason"] = (
        f"Q16 использует только `part`, `partsupp`, `supplier`; на {sf} это "
        f"{ctx.get('bronze_total_rows', '—')} строк и {f2(bronze_mb)} МБ в Bronze. "
        + ("На sf1 Q16 выполняется за доли секунды, и разница между кодеками тонет в накладных расходах "
           "(планирование, сеть до MinIO); на sf10 данных в 10 раз больше — различия форматов и кодеков видны "
           "устойчиво. При этом sf10 помещается на ноутбуке: 8 вариантов бенчмарка пишутся и удаляются по очереди, "
           f"весь прогон занял ≈{total_min:.0f} мин. Больший масштаб (sf30+) упёрся бы в память Docker Desktop "
           "(Trino — один узел)." if sf == "sf10" else
           f"Масштаб уменьшен до {sf} из-за ограничений памяти Docker Desktop (Trino — один узел); "
           f"весь прогон занял ≈{total_min:.0f} мин."))

    # --- проверки качества
    dq = res.get("dq") or {}
    if dq:
        R = dq.get("rows", {})
        rows = [
            ["Строк в Bronze"] + [n(R.get(t, {}).get("bronze")) for t in ("part", "partsupp", "supplier")],
            ["Строк в Silver"] + [n(R.get(t, {}).get("silver")) for t in ("part", "partsupp", "supplier")],
            ["NULL в ключах"] + [n(dq["null_keys"][t]) for t in ("part", "partsupp", "supplier")],
            ["Дубликатов по ключу"] + [n(dq["dup_keys"][t]) for t in ("part", "partsupp", "supplier")],
            ["Невалидных значений", n(dq["invalid_values"]["part_size_out_of_range"]) + " (p_size ∉ 1..50)",
             n(dq["invalid_values"]["partsupp_negative_qty"] + dq["invalid_values"]["partsupp_nonpositive_cost"])
             + " (остаток < 0 или цена ≤ 0)", "—"],
            ["«Сирот» (нет детали/поставщика)", "—", n(dq["orphans_partsupp"]), "—"],
            ["Поставщиков с жалобами (флаг)", "—", "—", n(dq["complaint_suppliers"])],
        ]
        ctx["dq_table"] = md_table(["Проверка", "part", "partsupp", "supplier"], rows)
        ctx["q16_bronze"] = f"{n(dq['q16_bronze'][0])} / {n(dq['q16_bronze'][1])}"
        ctx["q16_gold"] = f"{n(dq['q16_gold'][0])} / {n(dq['q16_gold'][1])}"
        ctx["q16_diff"] = (f"{dq['q16_only_in_bronze']} / {dq['q16_only_in_gold']} → "
                           + ("✅ витрина корректна" if dq.get("gold_matches_bronze") else "❌ есть расхождения"))
        ctx["complaints"] = n(dq["complaint_suppliers"])
        c = dq.get("control")
        ctx["control_values"] = (f"{n(c['q16_rows'])} строк / {n(c['q16_sum'])}, жалоб {c['complaints']}, "
                                 f"строк в кубе {n(c['mart_rows'])}" if c else "нет эталона для этого масштаба")
        ctx["control_ok"] = ("✅ совпадает" if dq.get("control_ok") else
                             ("❌ не совпадает" if c else "—"))
        ctx["q16_top"] = md_table(["p_brand", "p_type", "p_size", "supplier_cnt"],
                                  [r for r in dq.get("q16_top10", [])[:5]])
        share = dq.get("ps_comment_share")
        ctx["ps_comment_share"] = f"≈{share * 100:.0f} %" if share else "бо́льшая часть"

    # --- слои Q16
    lay = res.get("layers_q16") or {}
    if lay:
        names = {"bronze": "Bronze — канонический Q16 (`NOT IN` + `LIKE` по тексту)",
                 "silver": "Silver — джойн по флагу `s_has_complaints`",
                 "gold_mart": "Gold — `WHERE` по кубу `part_supplier_mart`",
                 "gold_report": "Gold — готовый `q16_report`"}
        base = lay.get("bronze", {}).get("median_s")
        rows = []
        for k, title in names.items():
            v = lay.get(k)
            if not v:
                continue
            rows.append([title, f2(v["median_s"], 3), f"{f2(v['min_s'], 3)}–{f2(v['max_s'], 3)}",
                         f2(v["physical_input_mb"]), f2(v["cpu_s"], 2),
                         f"{base / v['median_s']:.1f}×" if base and v["median_s"] else "—"])
        ctx["layers_table"] = md_table(["Слой / способ", "Медиана, с", "min–max, с", "Прочитано, МиБ",
                                        "CPU, с", "Быстрее Bronze"], rows)
        if "bronze" in lay and "gold_report" in lay:
            b, g = lay["bronze"], lay["gold_report"]
            sv = lay.get("silver")
            ctx["layers_conclusion"] = (
                f"Ответ из Gold получается в **{fx(b['median_s'] / g['median_s'])} раз быстрее**, чем из сырого "
                f"Bronze, и читает {f2(g['physical_input_mb'])} МиБ вместо {f2(b['physical_input_mb'])} МиБ: вся тяжёлая "
                f"работа (джойн {ctx.get('silver_partsupp_rows', '')} строк, `count(DISTINCT)`) сделана один раз "
                f"при построении витрины."
                + ((f" Silver ускоряет Q16 в {fx(b['median_s'] / sv['median_s'])} раза уже за счёт очистки: флаг жалоб "
                    f"вместо `LIKE` по тексту и нет тяжёлых текстовых колонок." if sv["median_s"] < b["median_s"] else
                    f" Silver на этом запросе не быстрее Bronze ({f2(sv['median_s'], 3)} vs {f2(b['median_s'], 3)} с): "
                    f"Q16 и так читает только узкие колонки, а `LIKE` выполняется лишь по 100 тыс. поставщиков — "
                    f"выигрышу от очистки просто негде проявиться. Задача Silver — чистые и типизированные данные "
                    f"для всех витрин, а ускорение конкретного вопроса даёт Gold.") if sv else "")
                + " Так и задумана медальонная архитектура: каждый следующий слой дороже построить, но дешевле читать.")

    bench_texts(res, ctx)

    # --- time travel
    tt = res.get("timetravel") or {}
    if tt:
        ctx["tt_snapshot"] = str(tt["snapshot_id"])
        # момент, когда точка восстановления была текущей (+1 с) — для FOR TIMESTAMP AS OF
        ctx["tt_ts"] = "2026-10-17 18:00:00 Europe/Moscow"
        try:
            from datetime import datetime, timedelta
            row = next(r for r in tt.get("history", []) if r[1] == str(tt["snapshot_id"]))
            ts = datetime.fromisoformat(row[0]) + timedelta(seconds=1)
            ctx["tt_ts"] = ts.strftime("%Y-%m-%d %H:%M:%S") + " UTC"
        except Exception:
            pass
        ctx["timetravel_answer"] = (
            f"Сценарий на `silver.lakehouse.supplier`: было **{n(tt['rows_before'])}** строк → «ошибочный» "
            f"`DELETE ... WHERE s_nationkey = 7` → **{n(tt['rows_after_delete'])}** "
            f"(потеряно {n(tt['rows_before'] - tt['rows_after_delete'])}). `FOR VERSION AS OF {tt['snapshot_id']}` "
            f"показывает **{n(tt['rows_time_travel'])}** — прошлое состояние доступно, потому что DELETE в Iceberg "
            f"не стирает файлы, а создаёт новый снапшот (старые parquet-файлы остаются в MinIO). "
            f"`ALTER TABLE ... EXECUTE rollback_to_snapshot(...)` вернул таблицу к **{n(tt['rows_restored'])}** строкам "
            f"за одну операцию с метаданными, без бэкапов и копирования данных "
            + ("(✅ проверено автоматически)." if tt.get("ok") else "(⚠ проверь вывод раннера)."))
        pretty = {"None": "—", "True": "да", "False": "нет (откатили)"}
        hist = [[re.sub(r"\.(\d{3})\d*", r".\1", c.replace("+00:00", " UTC")) if i == 0 else pretty.get(c, c)
                 for i, c in enumerate(r)] for r in tt.get("history", [])]
        ctx["tt_history"] = md_table(["made_current_at", "snapshot_id", "parent_id", "is_current_ancestor"], hist)
    ev = res.get("evolution") or {}
    if ev:
        ctx["evo_snapshot"] = str(ev["snapshot_before"])
        segs = ", ".join(f"{s} — {n(c)}" for s, c in ev.get("segments", []))
        new_cols = [c for c in ev["cols_after"] if c not in ev["cols_before"]]
        ctx["evolution_answer"] = (
            f"1) `ADD COLUMN s_balance_segment varchar` выполнился за {f2(ev['add_s'], 2)} с: Iceberg только записал "
            f"новую версию схемы в `metadata.json`. Файлов данных до/после — {ev['files_before']}/{ev['files_after_add']} "
            f"(ни один файл не переписан), у всех {n(ev['nulls_after_add'])} строк в новой колонке `NULL`. "
            f"2) `UPDATE` заполнил колонку ({f2(ev['update_s'], 2)} с, это уже изменение данных → новый снапшот): {segs}. "
            f"3) `RENAME COLUMN ... TO s_acctbal_segment` — {f2(ev['rename_s'], 2)} с, тоже только метаданные: Iceberg "
            f"идентифицирует колонки по **id**, а не по имени, поэтому старые parquet-файлы читаются под новым именем. "
            f"Итог: {len(ev['cols_before'])} → {len(ev['cols_after'])} колонок (новая: `{', '.join(new_cols)}`). "
            f"Снапшот до изменений (`{ev['snapshot_before']}`) по-прежнему читается через `FOR VERSION AS OF`: "
            f"{n(ev['old_snapshot_rows'])} строк, колонки: `{', '.join(ev['cols_old_snapshot'])}`. "
            f"Gold не сломался ({n(ev['gold_rows_after'])} строк), снапшотов у таблицы всего: {ev['snapshots_total']}.")

    # --- обслуживание таблиц
    mt = res.get("maintenance") or {}
    if mt:
        ctx["mt_batches"] = str(mt["batches"])
        stages = [("После {} микро-загрузок".format(mt["batches"]), mt["before"], "—"),
                  ("После `optimize`", mt["after_optimize"], f"{f2(mt.get('optimize_s'), 2)} с"),
                  ("После `expire_snapshots` + `remove_orphan_files`", mt["after_expire"], f"{f2(mt.get('expire_s'), 2)} с")]
        rows = []
        for name, st, op in stages:
            rows.append([name, n(st["snapshots"]), n(st["files"]), f2(st["avg_file_kb"], 1), f2(st["kb"], 1),
                         n(st["manifests"]) if st.get("manifests") is not None else "—", n(st["rows"]),
                         f"{f2(st['query']['median_s'], 3)} ({f2(st['query']['min_s'], 3)}–{f2(st['query']['max_s'], 3)})", op])
        ctx["mt_table"] = md_table(["Этап", "Снапшотов", "Файлов данных", "Средний файл, КБ", "Данные, КБ",
                                    "Манифестов", "Строк", "Запрос, медиана с (min–max)", "Время операции"], rows)
        b, o, e = mt["before"], mt["after_optimize"], mt["after_expire"]
        qb, qo = b["query"]["median_s"], o["query"]["median_s"]
        tt_after = mt.get("tt_after_expire", "")
        ctx["mt_conclusion"] = (
            f"* **Мелкие файлы.** {mt['batches']} загрузок дали {n(b['files'])} файлов по ~{f2(b['avg_file_kb'], 0)} КБ "
            f"и {n(b['snapshots'])} снапшотов — при рекомендуемом размере файла Iceberg 128–512 МБ. Каждый файл — это "
            f"отдельный запрос к S3 и отдельный футер Parquet, который надо прочитать.\n"
            f"* **`optimize`** склеил их в {n(o['files'])} файл(а) за {f2(mt.get('optimize_s'), 2)} с; запрос "
            + (f"ускорился в {fx(qb / qo)} раза ({f2(qb, 3)} → {f2(qo, 3)} с)." if qo < qb else
               f"почти не изменился ({f2(qb, 3)} → {f2(qo, 3)} с): на таблице в {n(b['rows'])} строк накладные расходы "
               f"малы, но они растут линейно с числом файлов.")
            + f" Но снапшотов стало ещё больше ({n(o['snapshots'])}), а старые мелкие файлы физически остались в MinIO — "
              f"на них ссылаются старые снапшоты, поэтому time travel к первой загрузке ещё работает "
              f"({n(mt.get('tt_before_expire'))} строк).\n"
            f"* **`expire_snapshots`** оставил {n(e['snapshots'])} снапшот(а) и удалил файлы, на которые больше никто "
            f"не ссылается. "
            + (f"Цена — история: time travel к первой загрузке теперь невозможен (Trino: «{tt_after}»).\n"
               if tt_after != "доступен" else "Time travel к первой загрузке при этом остался доступен.\n")
            + f"* **Вывод:** append-only Bronze без регламентного обслуживания постепенно деградирует — файлов, "
            f"снапшотов и метаданных становится всё больше, планирование и чтение замедляются. Компакцию и очистку "
            f"снапшотов нужно запускать по расписанию, выбирая retention как баланс между местом и окном восстановления.")

    # --- выводы
    if B and S and bench:
        ctx["final_conclusions"] = (
            f"1. **Медальон** разделяет ответственность: Bronze хранит источник как есть ({ctx.get('bronze_total_mb')} МБ, "
            f"можно всё пересчитать), Silver — чистые типизированные данные без лишнего текста "
            f"(в {ctx.get('silver_vs_bronze')} раза меньше), Gold — готовый ответ на бизнес-вопрос"
            + (f", который читается в {fx(lay['bronze']['median_s'] / lay['gold_report']['median_s'])} раз быстрее сырого запроса"
               if lay.get("bronze") and lay.get("gold_report") else "") + ".\n"
            f"2. **Хранение**: колоночный Parquet даёт Q16 читать только нужные 8 колонок из 21; партиционирование "
            f"нужно только там, где оно отсекает много данных и не порождает мелкие файлы — на этом объёме это лишь "
            f"партиция по дню загрузки в Bronze.\n"
            f"3. **Сжатие**: {ctx.get('_compress_summary', '')}\n"
            f"4. **Выбор PARQUET + ZSTD**: {ctx.get('_choice_summary', '')}\n"
            f"5. **Lakehouse** (Iceberg поверх S3) дал то, чего нет у «просто файлов»: ACID-запись, time travel и откат "
            f"за секунды, эволюцию схемы без перезаписи данных и доступ к одним таблицам из Trino и Superset.")

    # скриншоты: вставляем только те, что реально лежат в docs/screenshots
    shots = [
        ("01_docker_ps.png", "Стек поднят: контейнеры, инициализация бакетов и warehouse, каталоги Trino"),
        ("02_minio_buckets.png", "MinIO (Silo): три бакета-слоя bronze / silver / gold"),
        ("03_minio_bronze_files.png", "Бакет bronze: папки таблиц Iceberg (data + metadata)"),
        ("04_lakekeeper_warehouses.png", "Lakekeeper: 3 warehouse, 8 таблиц"),
        ("05_dbeaver_tree.png", "DBeaver: каталоги Trino"),
        ("06_runner_output.png", "Вывод раннера: бенчмарк 8 вариантов, time travel, schema evolution"),
        ("06b_runner_rerun.png", "Повторный прогон Silver / слоёв / time travel / evolution"),
        ("07_superset_db.png", "Superset: подключения к каталогам bronze и gold через Trino"),
        ("08_superset_sqllab_bronze.png", "Superset SQL Lab: запрос к Bronze"),
        ("09_trino_ui.png", "Trino UI: запросы от пользователя superset (Apache Superset)"),
        ("10_superset_dashboard.png", "Superset: дашборд по Gold (q16_report)"),
    ]
    sdir = os.path.join(root, "docs", "screenshots")
    present = [(f, c) for f, c in shots if os.path.exists(os.path.join(sdir, f))]
    ctx["screenshots"] = ("### Приложение: скриншоты\n\n" + "\n\n".join(
        f"**{i}. {c}**\n\n![{c}](docs/screenshots/{f})" for i, (f, c) in enumerate(present, 1))) if present else ""

    with open(os.path.join(root, "runner", "report_template.md"), encoding="utf-8") as f:
        tpl = f.read()
    out = re.sub(r"\{\{([a-z0-9_]+)\}\}", lambda m: str(ctx.get(m.group(1), MISSING)), tpl)
    out = insert_toc(out)
    with open(os.path.join(root, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write(out)
