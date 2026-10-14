"""AgentTrust 对照实验入口。

在项目根目录执行：

    .\\.venv\\Scripts\\python.exe run_experiment.py

它会做三件事：
  1. 让三种调度策略在完全相同的条件下比赛（默认 5 次独立试验 × 100 轮）
  2. 在屏幕上打印对比表格
  3. 把原始数据保存到 results/ 目录（CSV + JSON）

自定义参数：

    .\\.venv\\Scripts\\python.exe run_experiment.py --trials 10 --rounds 200 --seed 7
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# 让脚本能 import 到 app 包（无论从哪个目录调用）
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.experiment import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_REQUIRED_CAPABILITIES,
    DEFAULT_ROUNDS,
    DEFAULT_SEED,
    DEFAULT_TRIALS,
    STRATEGY_LABELS,
    ExperimentConfig,
    format_summary_table,
    run_experiment,
    save_all,
)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AgentTrust 调度策略对照实验",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python run_experiment.py                      # 默认 5 次试验 × 100 轮\n"
            "  python run_experiment.py --trials 1           # 快速跑一次看看\n"
            "  python run_experiment.py --rounds 200         # 加倍轮数，结论更稳\n"
        ),
    )
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                        help=f"每次试验跑多少轮（默认 {DEFAULT_ROUNDS}）")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS,
                        help=f"重复多少次独立试验（默认 {DEFAULT_TRIALS}）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"随机种子，决定实验可复现性（默认 {DEFAULT_SEED}）")
    parser.add_argument("--capability", action="append", dest="capabilities",
                        help="任务需求能力，可重复指定。默认只要求 research")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help=f"结果输出目录（默认 {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--quiet", action="store_true",
                        help="只保存文件，不打印表格")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    config = ExperimentConfig(
        rounds=args.rounds,
        seed=args.seed,
        trials=args.trials,
        required_capabilities=args.capabilities or list(DEFAULT_REQUIRED_CAPABILITIES),
    )

    print(f"开始实验：{config.trials} 次试验 × {config.rounds} 轮 × 3 种策略 ...")
    print()

    result = run_experiment(config)

    if not args.quiet:
        print(format_summary_table(result))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"exp_{stamp}_seed{config.seed}"
    outputs = save_all(result, Path(args.output_dir), run_name)

    print("结果已保存：")
    for label, path in outputs.items():
        print(f"  {label:<9} {path}")
    print()
    print("提示：")
    print("  - *_rounds.csv   逐轮原始数据（参赛要求的原始实验记录）")
    print("  - *_summary.csv  每个策略一行的汇总指标，可直接画对比图")
    print("  - *_meta.json    实验参数、智能体设定和已知局限")
    print()
    print(f"复现本实验：python run_experiment.py --trials {config.trials} "
          f"--rounds {config.rounds} --seed {config.seed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
