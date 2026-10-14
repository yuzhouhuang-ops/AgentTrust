"""生成参赛材料用的架构图（手绘 SVG，零外部依赖）。

【为什么手绘 SVG 而不用 Mermaid】

- Mermaid 渲染需要联网下载 JS 或安装 Node 包，答辩环境下不可靠
- 手绘 SVG 可以精确控制布局与配色，与项目演示页风格统一
- 同时输出 SVG（矢量，放大不糊）和 PNG（可直接插入 Word/PPT）

生成内容：
  架构图-分层.svg/png   —— 四层架构
  架构图-闭环.svg/png   —— 调度反馈闭环
  架构图-抗欺骗.svg/png  —— 抗欺骗机制原理

用法（项目根目录）：
    .\\.venv\\Scripts\\python.exe 参赛材料/生成架构图.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

OUT = pathlib.Path(__file__).resolve().parent / "图表"

# ---------- 配色（与 demo/index.html 一致）----------
BG = "#ffffff"
INK = "#1a1a1a"
MUTED = "#6b7280"
LINE = "#9ca3af"
BLUE = "#1f6feb"
BLUE_BG = "#eaf2ff"
GREEN = "#238636"
GREEN_BG = "#e8f5ec"
RED = "#f85149"
RED_BG = "#fdeceb"
AMBER = "#9e6a03"
AMBER_BG = "#fdf3e3"
GRAY_BG = "#f3f4f6"

FONT = "Microsoft YaHei, PingFang SC, sans-serif"


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text(x, y, s, size=14, fill=INK, weight="400", anchor="middle", opacity=1.0):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}" opacity="{opacity}">{esc(s)}</text>'
    )


def box(x, y, w, h, fill, stroke, rx=8, sw=1.5):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
    )


def arrow(x1, y1, x2, y2, color=LINE, sw=2, dashed=False, marker="arrow"):
    d = ' stroke-dasharray="6 4"' if dashed else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="{sw}"{d} marker-end="url(#{marker})"/>'
    )


def defs() -> str:
    return (
        "<defs>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{LINE}"/></marker>'
        '<marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{BLUE}"/></marker>'
        "</defs>"
    )


# ===========================================================================
# 图 1：四层架构
# ===========================================================================
def layered() -> str:
    W, H = 1000, 620
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="{FONT}">',
         defs(), f'<rect width="{W}" height="{H}" fill="{BG}"/>']

    p.append(text(40, 42, "AgentTrust 系统分层架构", 22, INK, "700", "start"))
    p.append(text(40, 66, "决策层为纯逻辑模块，不依赖网络与存储 —— 一处定义，三处复用",
                  13, MUTED, "400", "start"))

    LX, LW = 40, 920

    # ---- 服务层 ----
    y = 96
    p.append(box(LX, y, LW, 86, BLUE_BG, BLUE, 10))
    p.append(text(LX + 18, y + 26, "服务层", 15, BLUE, "700", "start"))
    p.append(box(LX + 130, y + 14, 300, 58, "#ffffff", BLUE, 7))
    p.append(text(LX + 280, y + 40, "app/main.py", 14, INK, "700"))
    p.append(text(LX + 280, y + 60, "REST 接口：注册 / 发现 / 结果记录", 11.5, MUTED))
    p.append(box(LX + 460, y + 14, 250, 58, "#ffffff", BLUE, 7))
    p.append(text(LX + 585, y + 40, "demo/index.html", 14, INK, "700"))
    p.append(text(LX + 585, y + 60, "可视化演示（单文件零依赖）", 11.5, MUTED))
    p.append(box(LX + 740, y + 14, 160, 58, "#ffffff", BLUE, 7))
    p.append(text(LX + 820, y + 40, "204 个测试", 14, INK, "700"))
    p.append(text(LX + 820, y + 60, "pytest 自动化验证", 11.5, MUTED))

    # ---- 决策层 ----
    y = 216
    p.append(box(LX, y, LW, 116, GREEN_BG, GREEN, 10, 2))
    p.append(text(LX + 18, y + 26, "决策层", 15, GREEN, "700", "start"))
    p.append(text(LX + 18, y + 46, "（核心）", 11, MUTED, "400", "start"))
    p.append(box(LX + 130, y + 16, 340, 84, "#ffffff", GREEN, 7))
    p.append(text(LX + 300, y + 42, "app/scoring.py  —— 评分", 14, INK, "700"))
    p.append(text(LX + 300, y + 64, "可信度 · 能力匹配 · 延迟归一化", 11.5, MUTED))
    p.append(text(LX + 300, y + 84, "综合分 = 0.60×能力 + 0.30×可信度 + 0.10×延迟", 11, GREEN))
    p.append(box(LX + 500, y + 16, 400, 84, "#ffffff", GREEN, 7))
    p.append(text(LX + 700, y + 42, "app/strategies.py  —— 调度策略", 14, INK, "700"))
    p.append(text(LX + 700, y + 64, "随机选择 ｜ 仅能力匹配 ｜ 可信度感知", 11.5, MUTED))
    p.append(text(LX + 700, y + 84, "三种策略用于对照实验", 11, GREEN))

    # ---- 数据层 ----
    y = 366
    p.append(box(LX, y, LW, 74, GRAY_BG, LINE, 10))
    p.append(text(LX + 18, y + 26, "数据层", 15, MUTED, "700", "start"))
    p.append(box(LX + 130, y + 12, 340, 50, "#ffffff", LINE, 7))
    p.append(text(LX + 300, y + 34, "智能体档案", 13.5, INK, "700"))
    p.append(text(LX + 300, y + 52, "能力 / 宣称成功率 / 真实战绩", 11, MUTED))
    p.append(box(LX + 500, y + 12, 400, 50, "#ffffff", LINE, 7))
    p.append(text(LX + 700, y + 34, "任务执行历史", 13.5, INK, "700"))
    p.append(text(LX + 700, y + 52, "每次调度的真实成败与耗时", 11, MUTED))

    # ---- 实验层 ----
    y = 474
    p.append(box(LX, y, LW, 116, AMBER_BG, AMBER, 10))
    p.append(text(LX + 18, y + 26, "实验层", 15, AMBER, "700", "start"))
    p.append(box(LX + 130, y + 16, 230, 84, "#ffffff", AMBER, 7))
    p.append(text(LX + 245, y + 42, "app/simulator.py", 13.5, INK, "700"))
    p.append(text(LX + 245, y + 64, "模拟任务执行", 11.5, MUTED))
    p.append(text(LX + 245, y + 84, "成败由概率产生", 11, AMBER))
    p.append(box(LX + 380, y + 16, 250, 84, "#ffffff", AMBER, 7))
    p.append(text(LX + 505, y + 42, "app/experiment.py", 13.5, INK, "700"))
    p.append(text(LX + 505, y + 64, "对照实验框架", 11.5, MUTED))
    p.append(text(LX + 505, y + 84, "固定种子 · 指标统计", 11, AMBER))
    p.append(box(LX + 650, y + 16, 250, 84, "#ffffff", AMBER, 7))
    p.append(text(LX + 775, y + 42, "results/*.csv", 13.5, INK, "700"))
    p.append(text(LX + 775, y + 64, "原始实验数据", 11.5, MUTED))
    p.append(text(LX + 775, y + 84, "1500 条调度决策记录", 11, AMBER))

    # ---- 层间箭头 ----
    p.append(arrow(LX + 400, 182, LX + 400, 214, LINE, 2))
    p.append(arrow(LX + 500, 332, LX + 500, 364, LINE, 2))
    p.append(arrow(LX + 400, 440, LX + 400, 472, LINE, 2, dashed=True))

    p.append("</svg>")
    return "\n".join(p)


# ===========================================================================
# 图 2：调度反馈闭环
# ===========================================================================
def loop_diagram() -> str:
    W, H = 1000, 560
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="{FONT}">',
         defs(), f'<rect width="{W}" height="{H}" fill="{BG}"/>']

    p.append(text(40, 42, "核心调度闭环", 22, INK, "700", "start"))
    p.append(text(40, 66, "第 5–7 步是整个系统的灵魂：没有真实结果反馈，系统只能采信自我宣称",
                  13, MUTED, "400", "start"))

    steps = [
        ("①", "提交任务", "声明所需能力\n（如 research）", BLUE, BLUE_BG),
        ("②", "取出候选", "所有已注册智能体\n及其历史战绩", BLUE, BLUE_BG),
        ("③", "计算三项分", "能力匹配度\n可信度 · 延迟分", GREEN, GREEN_BG),
        ("④", "策略选出最优", "综合分排序\n返回被选中者", GREEN, GREEN_BG),
        ("⑤", "上报真实结果", "成功/失败\n实际耗时", RED, RED_BG),
        ("⑥", "更新战绩", "成功次数/失败次数\n实测平均延迟", RED, RED_BG),
        ("⑦", "可信度变化", "影响下一轮调度\n系统就此「学习」", AMBER, AMBER_BG),
    ]

    bw, bh = 176, 108
    gap = 14
    cols = 4
    x0, y0 = 40, 108
    positions = []
    for i in range(len(steps)):
        r, c = divmod(i, cols)
        if r == 0:
            x = x0 + c * (bw + gap)
        else:
            x = x0 + (cols - 1 - c) * (bw + gap)
        y = y0 + r * (bh + 60)
        positions.append((x, y))

    for i, ((num, title, desc, color, bgc), (x, y)) in enumerate(zip(steps, positions)):
        p.append(box(x, y, bw, bh, bgc, color, 10, 2))
        p.append(text(x + 24, y + 30, num, 20, color, "700", "start"))
        p.append(text(x + bw / 2 + 8, y + 32, title, 15, INK, "700"))
        for j, line in enumerate(desc.split("\n")):
            p.append(text(x + bw / 2, y + 58 + j * 19, line, 11.5, MUTED))

    # 箭头：第 1 行向右
    for i in range(cols - 1):
        x, y = positions[i]
        p.append(arrow(x + bw, y + bh / 2, x + bw + gap, y + bh / 2, LINE, 2))
    # 折下
    x, y = positions[cols - 1]
    p.append(arrow(x + bw / 2, y + bh, x + bw / 2, y + bh + 60, LINE, 2))
    # 第 2 行向左
    for i in range(cols, len(steps) - 1):
        x, y = positions[i]
        p.append(arrow(x, y + bh / 2, x - gap, y + bh / 2, LINE, 2))

    # 回环箭头
    x, y = positions[len(steps) - 1]
    lx = x + bw / 2
    p.append(f'<path d="M {lx} {y + bh} L {lx} {y + bh + 26} L {x0 + 60} {y + bh + 26} '
             f'L {x0 + 60} {y0 + bh + 34}" fill="none" stroke="{BLUE}" '
             f'stroke-width="2.5" stroke-dasharray="7 5" marker-end="url(#arrow-blue)"/>')
    p.append(text(x0 + 250, y + bh + 46, "回到第 ② 步 —— 自此形成闭环，系统的判断随真实表现持续修正",
                  12.5, BLUE, "700", "start"))

    p.append("</svg>")
    return "\n".join(p)


# ===========================================================================
# 图 3：抗欺骗机制
# ===========================================================================
def anti_deception() -> str:
    W, H = 1000, 520
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="{FONT}">',
         defs(), f'<rect width="{W}" height="{H}" fill="{BG}"/>']

    p.append(text(40, 42, "抗欺骗机制：四道防线", 22, INK, "700", "start"))
    p.append(text(40, 66, "以虚报型智能体 Claimed-Expert（自称 99%，实际 1 胜 7 负）为例",
                  13, MUTED, "400", "start"))

    # 左侧：骗子
    p.append(box(40, 100, 250, 200, RED_BG, RED, 10, 2))
    p.append(text(165, 130, "虚报型智能体", 16, RED, "700"))
    p.append(text(165, 152, "Claimed-Expert", 13, MUTED))

    rows = [("自称成功率", "99%", RED), ("真实成功率", "15%", RED),
            ("延迟", "150ms（最低）", MUTED), ("能力", "3 项（最广）", MUTED)]
    for i, (k, v, c) in enumerate(rows):
        yy = 186 + i * 28
        p.append(text(60, yy, k, 12.5, MUTED, "400", "start"))
        p.append(text(270, yy, v, 12.5, c, "700", "end"))

    # 右侧：系统如何看待
    p.append(box(360, 100, 600, 200, "#ffffff", LINE, 10))
    p.append(text(380, 130, "系统如何处理这些信息", 16, INK, "700", "start"))

    lines = [
        ("❌", "不使用自我宣称值", "可信度函数的参数列表中不含「宣称成功率」—— 结构上无从影响", RED),
        ("✅", "用真实战绩计算可信度", "(1 胜 7 负) → (1+2)÷(1+7+4) = 0.250", GREEN),
        ("✅", "延迟分虽高但权重仅 10%", "延迟分 0.870，贡献 0.087 —— 不足以翻盘", GREEN),
        ("✅", "每次任务后更新战绩", "越骗，可信度越低 —— 反馈闭环自动修正", GREEN),
    ]
    for i, (icon, title, desc, color) in enumerate(lines):
        yy = 162 + i * 34
        p.append(text(385, yy, icon, 14, color))
        p.append(text(412, yy, title, 13, INK, "700", "start"))
        p.append(text(412, yy + 16, desc, 11, MUTED, "400", "start"))
        p.append(f'<line x1="380" y1="{yy + 24}" x2="940" y2="{yy + 24}" '
                 f'stroke="#e5e7eb" stroke-width="1"/>')

    # 底部结论
    p.append(box(40, 320, 920, 172, BLUE_BG, BLUE, 10, 2))
    p.append(text(60, 352, "结果：综合分 0.762，在三个候选中排名最后", 17, BLUE, "700", "start"))

    tbl_y = 378
    heads = ["智能体", "能力×0.60", "可信度×0.30", "延迟×0.10", "综合分"]
    xs = [80, 380, 520, 660, 810]
    for x, h in zip(xs, heads):
        p.append(text(x, tbl_y, h, 12, MUTED, "700", "start"))
    data = [
        ("Reliable-Researcher", "0.600", "0.214", "0.070", "0.884", GREEN),
        ("Fast-Generalist", "0.600", "0.175", "0.085", "0.860", MUTED),
        ("Claimed-Expert（虚报型）", "0.600", "0.075", "0.087", "0.762", RED),
    ]
    for i, (n, a, b, c, t, col) in enumerate(data):
        yy = tbl_y + 24 + i * 22
        p.append(text(xs[0], yy, n, 12, INK if col != RED else RED, "700" if col == RED else "400", "start"))
        for x, v in zip(xs[1:], [a, b, c, t]):
            p.append(text(x, yy, v, 12, col if x == xs[4] else MUTED, "700" if x == xs[4] else "400", "start"))

    p.append(text(60, 478, "注意第一列：三个智能体的能力项均为 0.600 —— "
                           "当能力相同时该项不起区分作用，这正是「仅能力匹配」策略失效的原因。",
                  11.5, MUTED, "400", "start"))

    p.append("</svg>")
    return "\n".join(p)


# ===========================================================================
def render_png(svg_path: pathlib.Path, png_path: pathlib.Path, w: int, h: int) -> bool:
    """用 Edge 无头模式把 SVG 渲染成 PNG。"""
    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge = next((e for e in edge_candidates if pathlib.Path(e).exists()), None)
    if not edge:
        return False
    url = "file:///" + str(svg_path).replace("\\", "/")
    try:
        subprocess.run(
            [edge, "--headless", "--disable-gpu", f"--screenshot={png_path}",
             f"--window-size={w},{h}", "--default-background-color=FFFFFFFF", url],
            check=True, capture_output=True, timeout=90,
        )
        return png_path.exists()
    except Exception as e:
        print(f"    PNG 渲染失败: {e}")
        return False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("架构图-分层", layered(), 1000, 620),
        ("架构图-闭环", loop_diagram(), 1000, 560),
        ("架构图-抗欺骗", anti_deception(), 1000, 520),
    ]
    for name, svg, w, h in jobs:
        sp = OUT / f"{name}.svg"
        sp.write_text(svg, encoding="utf-8")
        pp = OUT / f"{name}.png"
        ok = render_png(sp, pp, w, h)
        size = pp.stat().st_size if pp.exists() else 0
        print(f"  {name}.svg  ({len(svg)} 字符)   PNG: {'已生成 ' + str(size) + ' 字节' if ok else '未生成'}")


if __name__ == "__main__":
    main()
