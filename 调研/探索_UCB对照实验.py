"""探索性脚本（非正式代码）：验证 UCB 探索机制能否修复"过早锁定"缺陷。

背景：当前 TrustAwareStrategy 实测存在缺陷 ——
第 2 轮的一次随机成败，会锁定后续 98 轮的选择，算法从不探索。

做法：不改动项目任何文件，在这里临时实现一个带 UCB 探索奖励的策略，
用项目已有的实验框架跑对照，看指标是否改善。

UCB1 参考：John Myles White, "Bandit Algorithms for Website Optimization"
（MIT License）https://github.com/johnmyleswhite/BanditsBook
核心思想：选人时用「历史表现 + 探索奖励」，样本越少奖励越大。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.experiment import (  # noqa: E402
    ExperimentConfig,
    aggregate_metrics,
    run_single_trial,
)
from app.scoring import match_score, trust_score  # noqa: E402
from app.strategies import AgentView  # noqa: E402


class UCBTrustStrategy:
    """可信度感知 + UCB 探索奖励。

    综合分 = 原有的加权分 + 探索奖励

    探索奖励 = sqrt(2 * ln(总决策数) / 该智能体被选中次数)

    效果：
      - 被选中次数越少 -> 奖励越大 -> 有机会被试一试（解决"从不探索"）
      - 被选中次数越多 -> 奖励越小 -> 最终回归"选最好的"
    """

    name = "ucb_trust"

    def __init__(self, explore_weight: float = 0.15) -> None:
        # 探索奖励的缩放系数。1.0 表示完全按标准 UCB1；
        # 这里取小一些，避免探索盖过"能力+可信度"的主要判断。
        self.explore_weight = explore_weight
        # 记录每个智能体被本策略选中过多少次
        self.counts: dict[str, int] = {}
        self.total = 0

    def select(self, agents, required):
        eligible = [a for a in agents if match_score(a.capabilities, required) > 0]
        if not eligible:
            return None

        self.total += 1
        best = None
        best_score = -1.0
        for a in eligible:
            base = (
                0.60 * match_score(a.capabilities, required)
                + 0.30 * trust_score(a.successes, a.failures)
                + 0.10 * (1000 / (1000 + a.latency_ms))
            )
            n = self.counts.get(a.name, 0)
            if n == 0:
                # 从没试过的，给一个很大的奖励，先试一次
                bonus = 1.0
            else:
                bonus = math.sqrt(2 * math.log(self.total) / n)
            score = base + self.explore_weight * bonus
            if score > best_score:
                best_score = score
                best = a

        self.counts[best.name] = self.counts.get(best.name, 0) + 1
        return best


def run_with_custom_strategy(rounds, seed, trials, strategy_factory):
    """用自定义策略跑实验，返回每个策略的汇总指标。"""
    from app.simulator import TaskSimulator, default_demo_profiles

    all_records = []
    for trial in range(trials):
        strategy = strategy_factory()
        profiles = default_demo_profiles()
        simulator = TaskSimulator(seed=seed * 1000 + trial)
        by_name = {p.name: p for p in profiles}
        for r in range(rounds):
            views = [AgentView.from_profile(p) for p in profiles]
            chosen = strategy.select(views, ["research"])
            if chosen is None:
                continue
            outcome = simulator.execute(by_name[chosen.name])
            from app.experiment import RoundRecord

            all_records.append(
                RoundRecord(
                    trial=trial, strategy="ucb_trust", round_index=r,
                    selected_agent=chosen.name,
                    deceptive_selected=by_name[chosen.name].is_deceptive,
                    success=outcome.success, latency_ms=outcome.latency_ms,
                    trust_at_decision=trust_score(chosen.successes, chosen.failures),
                    agent_successes=by_name[chosen.name].successes,
                    agent_failures=by_name[chosen.name].failures,
                    market_avg_trust=0.0,
                )
            )
    return all_records


if __name__ == "__main__":
    ROUNDS, SEED, TRIALS = 100, 42, 5
    config = ExperimentConfig(rounds=ROUNDS, seed=SEED, trials=TRIALS,
                              required_capabilities=["research"])

    print("=" * 78)
    print("对照实验：原方案 vs 加入 UCB 探索奖励")
    print(f"参数：{TRIALS} 次试验 × {ROUNDS} 轮，种子 {SEED}")
    print("=" * 78)
    print()

    # 原方案（项目里的三种策略）
    baseline_records = []
    import random
    seeds = random.Random(SEED).sample(range(1, 10**6), TRIALS)
    for t in range(TRIALS):
        baseline_records.extend(run_single_trial(config, t, seeds[t]))
    baseline = aggregate_metrics(baseline_records, config)

    # 新方案（UCB）
    for ew in (0.05, 0.10, 0.15, 0.25):
        ucb_records = run_with_custom_strategy(
            ROUNDS, SEED, TRIALS, lambda ew=ew: UCBTrustStrategy(explore_weight=ew)
        )
        ucb = aggregate_metrics(ucb_records, config)["ucb_trust"]

        print(f"--- 探索系数 = {ew} ---")
        print(f"  任务成功率      {ucb.task_success_rate:>7.2%}")
        print(f"  欺骗被选中率    {ucb.deceptive_selection_rate:>7.2%}")
        print(f"  平均延迟        {ucb.avg_latency_ms:>7.1f}ms")
        picks = " ｜ ".join(f"{k}={v}" for k, v in sorted(ucb.selections_per_agent.items()))
        print(f"  选择分布        {picks}")
        print()

    print("=" * 78)
    print("对照：项目现有的三种策略")
    print("=" * 78)
    for name in sorted(baseline):
        m = baseline[name]
        picks = " ｜ ".join(f"{k}={v}" for k, v in sorted(m.selections_per_agent.items()))
        print(f"  {name:<16} 成功率 {m.task_success_rate:>7.2%}  "
              f"被骗率 {m.deceptive_selection_rate:>7.2%}  延迟 {m.avg_latency_ms:>6.1f}ms")
        print(f"                  选择分布: {picks}")
