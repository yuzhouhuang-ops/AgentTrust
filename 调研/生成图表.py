"""从实验原始数据生成 SVG 图表。

【为什么自己画 SVG，不用 matplotlib】

matplotlib 要装几百 MB 依赖，而本项目的图表很简单（三根柱子）。
直接用 Python 生成 SVG 的好处：
  - 零新依赖
  - SVG 是矢量图，放进报告和 PPT 放大不糊
  - 生成的文件小，能直接提交到 git
  - 数值直接来自 results/*.csv，改了数据重跑就更新

用法（在项目根目录）：
    .\\.venv\\Scripts\\python.exe 调研/生成图表.py
"""
from __future__ import annotations

import csv
import glob
import html
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "docs" / "图表"

# 配色（与 demo/index.html 风格保持一致）
C_STYLE = {
    "background": "#ffffff",
    "text": "#1a1a1a",
    "muted": "#6b7280",
    "grid": "#e5e7eb",
    "axis": "#9ca3af",
}
COLORS = {
    "trust_aware": "#1f6feb",       # 本方案：蓝
    "random": "#9ca3af",            # 随机：灰
    "capability_only": "#f85149",   # 仅能力：红
}
LABELS = {
    "trust_aware": "可信度感知\n（本方案）",
    "random": "随机选择",
    "capability_only": "仅能力匹配",
}
ORDER = ["capability_only", "random", "trust_aware"]   # 左到右


def load_latest_records() -> tuple[pathlib.Path, list[dict]]:
    files = sorted(glob.glob(str(ROOT / "results" / "*_rounds.csv")))
    if not files:
        raise SystemExit("找不到 results/*_rounds.csv，请先运行 run_experiment.py")
    path = pathlib.Path(files[-1])
    with path.open(encoding="utf-8-sig") as f:
        return path, list(csv.DictReader(f))


def summarize(rows: list[dict]) -> dict:
    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "ok": 0, "dep": 0})
    for r in rows:
        a = agg[r["strategy"]]
        a["n"] += 1
        if r["success"] == "True":
            a["ok"] += 1
        if r["deceptive_selected"] == "True":
            a["dep"] += 1
    return {
        k: {
            "success_rate": v["ok"] / v["n"] if v["n"] else 0.0,
            "deceptive_rate": v["dep"] / v["n"] if v["n"] else 0.0,
            "n": v["n"],
        }
        for k, v in agg.items()
    }


# ---------------------------------------------------------------------------
# 图 1：三种策略横向对比（分组柱状图）
# ---------------------------------------------------------------------------
def chart_comparison(stats: dict, out: pathlib.Path) -> None:
    W, H = 860, 480
    ML, MR, MT, MB = 90, 40, 90, 110      # 边距
    plot_w = W - ML - MR
    plot_h = H - MT - MB

    groups = [s for s in ORDER if s in stats]
    n_groups = len(groups)
    group_w = plot_w / max(1, n_groups)
    bar_w = min(76, group_w * 0.30)
    gap = 12

    def y_of(v: float) -> float:
        return MT + plot_h * (1 - v)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Microsoft YaHei, PingFang SC, sans-serif">'
    )
    parts.append(f'<rect width="{W}" height="{H}" fill="{C_STYLE["background"]}"/>')

    # 标题
    parts.append(
        f'<text x="{ML}" y="38" font-size="21" font-weight="700" '
        f'fill="{C_STYLE["text"]}">三种调度策略效果对比</text>'
    )
    parts.append(
        f'<text x="{ML}" y="62" font-size="13" fill="{C_STYLE["muted"]}">'
        f'5 次独立试验 × 100 轮 × 3 种策略 = 1500 次调度决策 ｜ 固定随机种子 42</text>'
    )

    # 网格线 + Y 轴刻度
    for i in range(6):
        v = i / 5
        y = y_of(v)
        parts.append(
            f'<line x1="{ML}" y1="{y:.1f}" x2="{ML + plot_w}" y2="{y:.1f}" '
            f'stroke="{C_STYLE["grid"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{ML - 12}" y="{y + 5:.1f}" font-size="13" text-anchor="end" '
            f'fill="{C_STYLE["muted"]}">{v * 100:.0f}%</text>'
        )

    # 图例
    leg_y = 78
    lx = ML + plot_w - 330
    for i, (key, label) in enumerate([
        ("_success", "任务成功率（越高越好）"),
        ("_deceptive", "欺骗智能体被选中率（越低越好）"),
    ]):
        x = lx + i * 170
        color = "#1f6feb" if key == "_success" else "#f85149"
        parts.append(f'<rect x="{x}" y="{leg_y - 9}" width="12" height="12" fill="{color}" rx="2"/>')
        parts.append(
            f'<text x="{x + 18}" y="{leg_y + 1}" font-size="12" '
            f'fill="{C_STYLE["muted"]}">{html.escape(label)}</text>'
        )

    # 柱子
    for gi, key in enumerate(groups):
        cx = ML + group_w * (gi + 0.5)
        s = stats[key]
        for bi, (val, color) in enumerate([
            (s["success_rate"], "#1f6feb"),
            (s["deceptive_rate"], "#f85149"),
        ]):
            x = cx - bar_w - gap / 2 + bi * (bar_w + gap)
            h = plot_h * val
            y = y_of(val)
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(0, h):.1f}" '
                f'fill="{color}" rx="3"/>'
            )
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{y - 7:.1f}" font-size="14" '
                f'font-weight="700" text-anchor="middle" fill="{color}">{val * 100:.1f}%</text>'
            )

        # 组标签（支持 \n 换行）
        lines = LABELS.get(key, key).split("\n")
        for li, line in enumerate(lines):
            weight = "700" if li == 0 else "400"
            size = 14 if li == 0 else 12
            fill = C_STYLE["text"] if li == 0 else C_STYLE["muted"]
            parts.append(
                f'<text x="{cx:.1f}" y="{MT + plot_h + 26 + li * 18}" font-size="{size}" '
                f'font-weight="{weight}" text-anchor="middle" fill="{fill}">{html.escape(line)}</text>'
            )

    # 坐标轴
    parts.append(
        f'<line x1="{ML}" y1="{MT + plot_h}" x2="{ML + plot_w}" y2="{MT + plot_h}" '
        f'stroke="{C_STYLE["axis"]}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<line x1="{ML}" y1="{MT}" x2="{ML}" y2="{MT + plot_h}" '
        f'stroke="{C_STYLE["axis"]}" stroke-width="1.5"/>'
    )

    # 结论注释
    note_y = H - 30
    parts.append(
        f'<text x="{ML}" y="{note_y}" font-size="13" fill="{C_STYLE["text"]}">'
        f'关键发现：「仅能力匹配」比「随机选择」还差 4 倍 —— '
        f'能力项恒为 1.0 失去区分作用后退化为「只看延迟」，而欺骗智能体延迟最低。</text>'
    )

    parts.append("</svg>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


# ---------------------------------------------------------------------------
# 图 2：欺骗智能体被选中率随轮次的变化（折线图）
# ---------------------------------------------------------------------------
def chart_curve(rows: list[dict], out: pathlib.Path) -> None:
    W, H = 860, 440
    ML, MR, MT, MB = 90, 150, 90, 80
    plot_w = W - ML - MR
    plot_h = H - MT - MB

    # 按轮次统计各策略的"累计被骗率"
    series: dict[str, list[tuple[int, float]]] = {}
    for strat in ORDER:
        sub = sorted(
            [r for r in rows if r["strategy"] == strat],
            key=lambda r: (int(r["trial"]), int(r["round_index"])),
        )
        if not sub:
            continue
        dep = 0
        pts = []
        for i, r in enumerate(sub, start=1):
            if r["deceptive_selected"] == "True":
                dep += 1
            pts.append((i, dep / i))
        series[strat] = pts

    def y_of(v: float) -> float:
        return MT + plot_h * (1 - v)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Microsoft YaHei, PingFang SC, sans-serif">'
    )
    parts.append(f'<rect width="{W}" height="{H}" fill="{C_STYLE["background"]}"/>')
    parts.append(
        f'<text x="{ML}" y="38" font-size="21" font-weight="700" '
        f'fill="{C_STYLE["text"]}">欺骗智能体被选中率（累计）</text>'
    )
    parts.append(
        f'<text x="{ML}" y="62" font-size="13" fill="{C_STYLE["muted"]}">'
        f'横轴为累计决策次数 ｜ 纵轴为累计被骗比例 ｜ 越低越好</text>'
    )

    n_points = max(len(v) for v in series.values())
    for i in range(6):
        v = i / 5
        y = y_of(v)
        parts.append(
            f'<line x1="{ML}" y1="{y:.1f}" x2="{ML + plot_w}" y2="{y:.1f}" '
            f'stroke="{C_STYLE["grid"]}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{ML - 12}" y="{y + 5:.1f}" font-size="13" text-anchor="end" '
            f'fill="{C_STYLE["muted"]}">{v * 100:.0f}%</text>'
        )
    for i in range(6):
        v = i / 5
        x = ML + plot_w * v
        parts.append(
            f'<line x1="{x:.1f}" y1="{MT + plot_h}" x2="{x:.1f}" y2="{MT + plot_h + 5}" '
            f'stroke="{C_STYLE["axis"]}"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{MT + plot_h + 22}" font-size="12" text-anchor="middle" '
            f'fill="{C_STYLE["muted"]}">{int(v * n_points)}</text>'
        )

    # 折线
    for strat, pts in series.items():
        color = COLORS[strat]
        d = " ".join(
            f'{"M" if i == 0 else "L"}{ML + plot_w * (idx / n_points):.1f},{y_of(v):.1f}'
            for i, (idx, v) in enumerate(pts)
        )
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.5"/>')

    # 图例（右侧）
    ly = MT + 10
    for strat in ORDER:
        if strat not in series:
            continue
        color = COLORS[strat]
        final = series[strat][-1][1]
        parts.append(f'<rect x="{ML + plot_w + 20}" y="{ly - 9}" width="12" height="12" fill="{color}" rx="2"/>')
        parts.append(
            f'<text x="{ML + plot_w + 38}" y="{ly + 1}" font-size="12" '
            f'fill="{C_STYLE["text"]}">{html.escape(LABELS[strat].replace(chr(10), ""))}</text>'
        )
        parts.append(
            f'<text x="{ML + plot_w + 38}" y="{ly + 17}" font-size="12" font-weight="700" '
            f'fill="{color}">{final * 100:.1f}%</text>'
        )
        ly += 44

    parts.append(
        f'<line x1="{ML}" y1="{MT + plot_h}" x2="{ML + plot_w}" y2="{MT + plot_h}" '
        f'stroke="{C_STYLE["axis"]}" stroke-width="1.5"/>'
    )
    parts.append(
        f'<line x1="{ML}" y1="{MT}" x2="{ML}" y2="{MT + plot_h}" '
        f'stroke="{C_STYLE["axis"]}" stroke-width="1.5"/>'
    )
    parts.append("</svg>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    path, rows = load_latest_records()
    stats = summarize(rows)

    print(f"数据来源: {path.relative_to(ROOT)}")
    print(f"总记录数: {len(rows)}")
    print()
    print("汇总（用于核对图表数字）:")
    for k in ORDER:
        if k in stats:
            s = stats[k]
            print(f"  {k:<18} 成功率 {s['success_rate']:>7.2%}   被骗率 {s['deceptive_rate']:>7.2%}   n={s['n']}")

    out1 = OUT_DIR / "策略对比.svg"
    out2 = OUT_DIR / "被骗率曲线.svg"
    chart_comparison(stats, out1)
    chart_curve(rows, out2)

    print()
    print("已生成图表:")
    print(f"  {out1.relative_to(ROOT)}")
    print(f"  {out2.relative_to(ROOT)}")
    print()
    print("用法：SVG 可直接插入 Markdown，或拖进 PPT / Word。")


if __name__ == "__main__":
    main()
