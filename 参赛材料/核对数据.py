"""核对参赛材料文档里的数字与原始实验数据是否一致。

这是提交前必做的检查：文档写 78.4%、原始数据是 78.0% —— 这种事一旦被评委发现，
整份材料的可信度就崩了。
"""
from __future__ import annotations

import csv
import glob
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def actual_from_csv() -> dict:
    f = sorted(glob.glob(str(ROOT / "results" / "*_rounds.csv")))[-1]
    rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
    agg = defaultdict(lambda: {"n": 0, "ok": 0, "dep": 0, "early_dep": 0,
                               "early_n": 0, "late_dep": 0, "late_n": 0})
    for r in rows:
        a = agg[r["strategy"]]
        a["n"] += 1
        ok = r["success"] == "True"
        dep = r["deceptive_selected"] == "True"
        if ok:
            a["ok"] += 1
        if dep:
            a["dep"] += 1
        if int(r["round_index"]) < 20:
            a["early_n"] += 1
            if dep:
                a["early_dep"] += 1
        else:
            a["late_n"] += 1
            if dep:
                a["late_dep"] += 1
    out = {}
    for k, v in agg.items():
        out[k] = {
            "success": v["ok"] / v["n"],
            "deceptive": v["dep"] / v["n"],
            "early_deceptive": v["early_dep"] / v["early_n"] if v["early_n"] else 0,
            "late_deceptive": v["late_dep"] / v["late_n"] if v["late_n"] else 0,
            "n": v["n"],
        }
    return out, rows


def main() -> None:
    real, rows = actual_from_csv()

    doc = ROOT / "参赛材料" / "作品技术方案.md"
    text = doc.read_text(encoding="utf-8")

    print("=" * 66)
    print("核对：作品技术方案.md")
    print("=" * 66)
    print(f"数据源: results/*_rounds.csv  ({len(rows)} 条记录)")
    print()

    checks = [
        ("仅能力匹配 任务成功率", "16.20%", real["capability_only"]["success"]),
        ("仅能力匹配 被选中率", "100.00%", real["capability_only"]["deceptive"]),
        ("随机选择 任务成功率", "58.40%", real["random"]["success"]),
        ("随机选择 被选中率", "29.20%", real["random"]["deceptive"]),
        ("可信度感知 任务成功率", "78.40%", real["trust_aware"]["success"]),
        ("可信度感知 被选中率", "1.20%", real["trust_aware"]["deceptive"]),
        ("可信度感知 前20轮被骗率", "6.00%", real["trust_aware"]["early_deceptive"]),
        ("可信度感知 20轮后被骗率", "0.00%", real["trust_aware"]["late_deceptive"]),
    ]

    bad = 0
    for label, stated, actual in checks:
        in_doc = stated in text
        stated_num = float(stated.rstrip("%")) / 100
        matches = abs(stated_num - actual) < 5e-4
        flag = "OK " if (in_doc and matches) else "!! "
        if not (in_doc and matches):
            bad += 1
        print(f"  {flag}{label:<26} 文档={stated:<9} 实际={actual:.4%}  "
              f"{'在文档中' if in_doc else '文档中未找到'}")

    print()
    print(f"  1500 次决策: 文档中{'有' if '1500' in text else '无'} | 实际 {len(rows)} 条")
    if len(rows) != 1500 or "1500" not in text:
        bad += 1

    # 手算表核对
    print()
    print("  手算表（第 5.4 节）核对:")
    from app.scoring import score_breakdown
    expect = {
        "Reliable-Researcher": (8, 2, 430),
        "Fast-Generalist": (5, 3, 180),
        "Claimed-Expert": (1, 7, 150),
    }
    for name, (s, f, lat) in expect.items():
        d = score_breakdown(["research"], ["research"], s, f, lat)
        cap = f"{d['weighted_capability']:.3f}"
        tru = f"{d['weighted_trust']:.3f}"
        ltn = f"{d['weighted_latency']:.3f}"
        tot = f"{d['total']:.3f}"
        ok = all(v in text for v in (cap, tru, ltn, tot))
        if not ok:
            bad += 1
        print(f"    {'OK ' if ok else '!! '}{name:<22} {cap} / {tru} / {ltn} -> {tot}")

    # 图片引用检查
    print()
    print("  图片引用检查:")
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
        link = m.group(1)
        target = doc.parent / link
        ok = target.exists()
        if not ok:
            bad += 1
        print(f"    {'OK ' if ok else '!! '}{link}")

    print()
    print("=" * 66)
    print(f"  结论: {'全部一致' if bad == 0 else f'发现 {bad} 处问题，需修正'}")
    print("=" * 66)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
