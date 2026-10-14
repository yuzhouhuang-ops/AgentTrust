"""探索性脚本 2：检验 UCB 的真正价值是不是"稳健性"而非"更高成功率"。

背景：第一次对照发现 UCB 的任务成功率（76.60%）**低于**原方案（78.40%），
但平均延迟从 324ms 降到 288ms。

这引出新假设：原方案的高成功率可能只是"这次运气好"（第 2 轮锁定到了合适的智能体）。
如果换成别的随机种子，原方案的成功率会不会大幅波动？
而 UCB 因为会探索，是不是反而更稳定？

本脚本用**多个随机种子**各跑一遍，比较两者的：
  - 成功率的平均值
  - 成功率的**波动范围**（标准差 / 最大最小值）  <- 稳健性
  - 延迟
"""
from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

# 项目根目录（本文件在 调研/ 下，所以往上一层）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.experiment import (  # noqa: E402
    ExperimentConfig,
    RoundRecord,
    aggregate_metrics,
    run_single_trial,
)
from app.scoring import trust_score  # noqa: E402
from app.simulator import TaskSimulator, default_demo_profiles  # noqa: E402
from app.strategies import AgentView  # noqa: E402

from 探索_UCB对照实验 import UCBTrustStrategy  # noqa: E402


def run_ucb_trial(rounds: int, seed: int, explore_weight: float,
                  warmup: int = 5):
    """跑一次 UCB 试验，返回逐轮记录。

    warmup: 前几轮强制各试一遍（UCB 的标准做法：没试过的先试）。
    """
    strategy = UCBTrustStrategy(explore_weight=explore_weight)
    profiles = default_demo_profiles()
    simulator = TaskSimulator(seed=seed)
    by_name = {p.name: p for p in profiles}

    records = []
    for r in range(rounds):
        views = [AgentView.from_profile(p) for p in profiles]
        chosen = strategy.select(views, ["research"])
        outcome = simulator.execute(by_name[chosen.name])
        records.append(
            RoundRecord(
                trial=0, strategy="ucb", round_index=r,
                selected_agent=chosen.name,
                deceptive_selected=by_name[chosen.name].is_deceptive,
                success=outcome.success, latency_ms=outcome.latency_ms,
                trust_at_decision=trust_score(chosen.successes, chosen.failures),
                agent_successes=by_name[chosen.name].successes,
                agent_failures=by_name[chosen.name].failures,
                market_avg_trust=0.0,
            )
        )
    return records


def main() -> None:
    ROUNDS = 100
    TRIALS_PER_SEED = 3
    SEEDS = [1, 7, 42, 99, 123, 500, 2024, 7777]

    print("=" * 84)
    print(f"稳健性对照：{len(SEEDS)} 个不同随机种子，每个种子跑 {TRIALS_PER_SEED} 次试验 × {ROUNDS} 轮")
    print("=" * 84)
    print()

    base_rates, ucb_rates = [], []
    base_lat, ucb_lat = [], []
    base_dep, ucb_dep = [], []

    for seed in SEEDS:
        config = ExperimentConfig(rounds=ROUNDS, seed=seed, trials=TRIALS_PER_SEED,
                                  required_capabilities=["research"])
        seeds = random.Random(seed).sample(range(1, 10**6), TRIALS_PER_SEED)

        recs = []
        for t in range(TRIALS_PER_SEED):
            recs.extend(run_single_trial(config, t, seeds[t]))
        b = aggregate_metrics(recs, config)["trust_aware"]

        urecs = []
        for t in range(TRIALS_PER_SEED):
            urecs.extend(run_ucb_trial(ROUNDS, seed * 1000 + t, explore_weight=0.15))
        u = aggregate_metrics(urecs, config)["ucb"]

        base_rates.append(b.task_success_rate)
        ucb_rates.append(u.task_success_rate)
        base_lat.append(b.avg_latency_ms)
        ucb_lat.append(u.avg_latency_ms)
        base_dep.append(b.deceptive_selection_rate)
        ucb_dep.append(u.deceptive_selection_rate)

        print(f"种子 {seed:>5}:  原方案 {b.task_success_rate:>6.2%} / "
              f"{b.avg_latency_ms:>6.1f}ms   |   "
              f"UCB {u.task_success_rate:>6.2%} / {u.avg_latency_ms:>6.1f}ms")

    print()
    print("=" * 84)
    print(f"{'指标':<26}{'原方案(trust_aware)':>22}{'UCB 探索版':>22}")
    print("-" * 84)

    def row(label, a, b, fmt="{:.2%}"):
        print(f"{label:<26}{fmt.format(a):>22}{fmt.format(b):>22}")

    row("任务成功率 平均", statistics.mean(base_rates), statistics.mean(ucb_rates))
    row("任务成功率 最差", min(base_rates), min(ucb_rates))
    row("任务成功率 最好", max(base_rates), max(ucb_rates))
    row("任务成功率 标准差", statistics.pstdev(base_rates), statistics.pstdev(ucb_rates))
    row("欺骗被选中率 平均", statistics.mean(base_dep), statistics.mean(ucb_dep))
    row("平均延迟", statistics.mean(base_lat), statistics.mean(ucb_lat), "{:.1f}ms")
    print("=" * 84)
    print()
    print("解读要点：")
    print("  - 标准差越小 = 结果越不依赖运气 = 越稳健")
    print("  - 最差值代表'最坏情况下会怎样'，比赛演示时更该关注这个")


if __name__ == "__main__":
    main()
