"""实验运行器：让三种调度策略在同一条件下比赛，并统计指标。

【这个文件解决什么问题】

2a 造好了"真实考官"（模拟任务执行器），2b 定好了"三条选人规矩"（三种策略）。
但没有一个东西把它们串起来跑 —— 这个文件就是那根线。

【公平性设计（最重要）】

三种策略必须面对**完全相同的条件**，否则比较没有意义。做法是"配对轮次"：

    第 1 轮：随机策略选一个 → 真实执行 → 记账
            仅能力策略选一个 → 真实执行 → 记账
            可信度策略选一个 → 真实执行 → 记账
    （三个策略都看过这一轮的状态之后，才进入第 2 轮）

也就是说：**每一轮里，三个策略看到的历史战绩是同一份**。
唯一的差别只有"怎么选"。这是标准的对照实验做法。

【为什么每个策略要有一份独立的智能体副本】

如果三个策略共用同一批智能体，先跑的策略会把战绩改掉，
后跑的策略就在一个"已经被改变过的世界"里做决策 —— 不公平。
所以每个策略拿到一整套全新的智能体（同名、同参数、从零开始）。

【冷启动】

智能体默认从"0 胜 0 负"开始，可信度是公式的先验值 0.5。
系统必须靠真实任务积累战绩，才能识别出虚报型智能体。
这种"从零学起"的设定，才能真实反映算法的学习速度和冷启动缺陷。

【可复现性】

种子、轮数、智能体参数全部会写进实验结果文件。
任何人拿到种子和参数，都能复现出完全一样的数字。
"""
from __future__ import annotations

import csv
import json
import random
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.scoring import WEIGHT_CAPABILITY, WEIGHT_LATENCY, WEIGHT_TRUST, trust_score
from app.simulator import AgentProfile, TaskSimulator, default_demo_profiles
from app.strategies import AgentView, build_strategies

# 默认实验参数。改这里就能调整实验规模。
DEFAULT_ROUNDS = 100
DEFAULT_SEED = 42
DEFAULT_TRIALS = 5

# 实验默认使用的任务需求能力（只要求 research 一项）。
#
# 为什么选单项能力？因为在这个演示集里三个智能体都具备 research，
# 能力匹配度会完全相同（都是 1.0），这时能力项起不到区分作用，
# 决策压力就落在了"可信度"和"延迟"上 —— 这正是我们要考验的地方。
#
# 注意：这也意味着本次实验无法体现"能力匹配"这一项的作用，
# 这是本实验的**已知局限**，报告里必须如实说明。
DEFAULT_REQUIRED_CAPABILITIES = ["research"]

# 观察前多少轮内是否选中虚报型智能体（用于体现"冷启动会先被骗"）
EARLY_PHASE_ROUNDS = 20

# 结果输出目录（相对于项目根目录）
DEFAULT_OUTPUT_DIR = "results"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RoundRecord:
    """一轮实验的明细记录，对应实验结果 CSV 的一行。"""

    trial: int
    strategy: str
    round_index: int
    selected_agent: str
    # 被选中的智能体是否属于虚报型（抗欺骗的核心观测指标）
    deceptive_selected: bool
    success: bool
    latency_ms: float
    # 做决策那一刻，被选中智能体的可信度（用于观察"学习过程"）
    trust_at_decision: float
    # 该智能体此时累计的成功/失败次数
    agent_successes: int
    agent_failures: int
    # 此刻在场智能体的平均可信度（用来判断"是否已积累到足够战绩"）
    market_avg_trust: float


@dataclass
class StrategyMetrics:
    """某个策略在一组实验中的汇总指标。"""

    strategy: str
    total_rounds: int
    success_count: int
    failure_count: int
    deceptive_selection_count: int
    # 早期阶段（前 EARLY_PHASE_ROUNDS 轮）选中虚报型的比例
    early_deceptive_selections: int
    early_rounds: int
    # 后期阶段选中虚报型的比例
    late_deceptive_selections: int
    late_rounds: int
    # 全程是否从未选中过虚报型
    never_selected_deceptive: bool
    # 第一次之后再也没有选中虚报型的轮次（None 表示没有纠正过来）
    recovery_round: Optional[int]
    # 弃权轮数：没有任何智能体能胜任该任务的轮次
    abstention_count: int
    avg_latency_ms: float
    latency_std: float
    # 每个智能体被选中的次数
    selections_per_agent: Dict[str, int]
    # 每个智能体被选中时的实测成功率
    success_rate_per_agent: Dict[str, float]
    final_trust_scores: Dict[str, float]

    @property
    def task_success_rate(self) -> float:
        """任务成功率：最重要的成效指标。

        分母是全部轮次。弃权轮（没有智能体能胜任）计为失败 ——
        因为对用户来说任务确实没完成，不能因为"没人接单"就不算数。
        这样不同策略的成功率口径才一致。
        """
        if self.total_rounds == 0:
            return 0.0
        return self.success_count / self.total_rounds

    @property
    def deceptive_selection_rate(self) -> float:
        """欺骗智能体被选中比例：抗欺骗能力的直接体现，越低越好。"""
        if self.total_rounds == 0:
            return 0.0
        return self.deceptive_selection_count / self.total_rounds

    @property
    def early_deceptive_rate(self) -> float:
        if self.early_rounds == 0:
            return 0.0
        return self.early_deceptive_selections / self.early_rounds

    @property
    def late_deceptive_rate(self) -> float:
        if self.late_rounds == 0:
            return 0.0
        return self.late_deceptive_selections / self.late_rounds

    def to_row(self) -> Dict[str, Any]:
        """转成适合写进汇总 CSV 的一行（只放数值和字符串，不放嵌套结构）。"""
        return {
            "strategy": self.strategy,
            "total_rounds": self.total_rounds,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "task_success_rate": round(self.task_success_rate, 6),
            "deceptive_selection_count": self.deceptive_selection_count,
            "deceptive_selection_rate": round(self.deceptive_selection_rate, 6),
            "early_deceptive_rate": round(self.early_deceptive_rate, 6),
            "late_deceptive_rate": round(self.late_deceptive_rate, 6),
            "never_selected_deceptive": self.never_selected_deceptive,
            "recovery_round": "" if self.recovery_round is None else self.recovery_round,
            "abstention_count": self.abstention_count,
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "latency_std": round(self.latency_std, 3),
        }


@dataclass
class ExperimentConfig:
    """一组实验的完整参数。这些参数会被写进结果文件，用于复现。"""

    rounds: int = DEFAULT_ROUNDS
    seed: int = DEFAULT_SEED
    trials: int = DEFAULT_TRIALS
    required_capabilities: List[str] = field(
        default_factory=lambda: list(DEFAULT_REQUIRED_CAPABILITIES)
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rounds_per_trial": self.rounds,
            "seed": self.seed,
            "trials": self.trials,
            "required_capabilities": list(self.required_capabilities),
            "early_phase_rounds": EARLY_PHASE_ROUNDS,
            "scoring_weights": {
                "capability": WEIGHT_CAPABILITY,
                "trust": WEIGHT_TRUST,
                "latency": WEIGHT_LATENCY,
            },
        }


@dataclass
class ExperimentResult:
    """一次完整实验的全部产物。"""

    config: ExperimentConfig
    records: List[RoundRecord]
    metrics: Dict[str, StrategyMetrics]
    # 每个策略在每一轮的成功率曲线（用于画学习曲线图）
    success_curve: Dict[str, List[float]]
    agent_profiles: List[Dict[str, Any]]

    @property
    def total_decisions(self) -> int:
        return len(self.records)


# ---------------------------------------------------------------------------
# 核心实验循环
# ---------------------------------------------------------------------------
def run_single_trial(
    config: ExperimentConfig,
    trial: int,
    strategy_seed: int,
) -> List[RoundRecord]:
    """跑一轮完整的对照实验（rounds 轮 × 三种策略）。

    每个策略拿到一套独立的智能体副本和独立的模拟器，
    保证互不干扰，同时三方看到的历史状态完全同步。
    """
    strategies = build_strategies(seed=strategy_seed)

    # 每个策略一套独立的智能体 + 独立的随机数流。
    # 用 trial 和策略序号组合出不同的种子，保证不同试验之间不完全重复，
    # 但同一个 (config.seed, trial) 永远可复现。
    world: Dict[str, Dict[str, Any]] = {}
    for index, strategy in enumerate(strategies):
        profiles = default_demo_profiles()
        world[strategy.name] = {
            "profiles": profiles,
            "simulator": TaskSimulator(seed=config.seed * 1000 + trial * 10 + index),
            "by_name": {p.name: p for p in profiles},
        }

    records: List[RoundRecord] = []

    for round_index in range(config.rounds):
        for strategy in strategies:
            state = world[strategy.name]
            profiles: List[AgentProfile] = state["profiles"]
            simulator: TaskSimulator = state["simulator"]

            # 快照：策略看到的是"此刻"的历史战绩，决策过程中不会变
            views = [AgentView.from_profile(p) for p in profiles]
            chosen = strategy.select(views, config.required_capabilities)

            if chosen is None:
                # 没有任何智能体能胜任这个任务，本策略本轮弃权。
                # 仍然记一条，避免不同策略的轮数不一致导致统计口径混乱。
                records.append(
                    RoundRecord(
                        trial=trial,
                        strategy=strategy.name,
                        round_index=round_index,
                        selected_agent="<无人胜任>",
                        deceptive_selected=False,
                        success=False,
                        latency_ms=0.0,
                        trust_at_decision=0.0,
                        agent_successes=0,
                        agent_failures=0,
                        market_avg_trust=_avg(
                            trust_score(p.successes, p.failures) for p in profiles
                        ),
                    )
                )
                continue

            # 找到对应的真实档案并执行任务 —— 结果由概率产生
            profile = state["by_name"][chosen.name]
            outcome = simulator.execute(profile)

            records.append(
                RoundRecord(
                    trial=trial,
                    strategy=strategy.name,
                    round_index=round_index,
                    selected_agent=chosen.name,
                    deceptive_selected=profile.is_deceptive,
                    success=outcome.success,
                    latency_ms=outcome.latency_ms,
                    trust_at_decision=trust_score(
                        chosen.successes, chosen.failures
                    ),
                    agent_successes=profile.successes,
                    agent_failures=profile.failures,
                    market_avg_trust=_avg(
                        trust_score(p.successes, p.failures) for p in profiles
                    ),
                )
            )

    return records


def _avg(values) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def run_experiment(
    config: Optional[ExperimentConfig] = None,
    trial_seeds: Optional[Sequence[int]] = None,
) -> ExperimentResult:
    """跑完整实验：trials 次独立试验，每次 rounds 轮，每次覆盖三种策略。

    多次试验是为了避免"某一次运气好"造成误判 —— 这是参赛要求的"重复运行实验"。
    """
    config = config or ExperimentConfig()

    if config.rounds <= 0:
        raise ValueError(f"rounds 必须大于 0，收到 {config.rounds}")
    if config.trials <= 0:
        raise ValueError(f"trials 必须大于 0，收到 {config.trials}")

    if trial_seeds is None:
        # 试验种子从主种子派生，保证整体可复现
        rng = random.Random(config.seed)
        trial_seeds = [rng.randrange(1, 10**6) for _ in range(config.trials)]

    all_records: List[RoundRecord] = []
    for trial, strategy_seed in enumerate(trial_seeds):
        all_records.extend(run_single_trial(config, trial, strategy_seed))

    metrics = aggregate_metrics(all_records, config)
    curves = build_success_curves(all_records, config)

    return ExperimentResult(
        config=config,
        records=all_records,
        metrics=metrics,
        success_curve=curves,
        agent_profiles=[_profile_snapshot(p) for p in default_demo_profiles()],
    )


def _profile_snapshot(profile: AgentProfile) -> Dict[str, Any]:
    """把智能体参数转成可写入文件的字典（不含运行期统计）。"""
    return {
        "name": profile.name,
        "capabilities": list(profile.capabilities),
        "claimed_success_rate": profile.claimed_success_rate,
        "true_success_rate": profile.true_success_rate,
        "latency_ms": profile.latency_ms,
        "is_deceptive": profile.is_deceptive,
        "overclaim_gap": round(profile.overclaim_gap, 6),
        "note": profile.note,
    }


def aggregate_metrics(
    records: Sequence[RoundRecord], config: ExperimentConfig
) -> Dict[str, StrategyMetrics]:
    """把逐轮明细汇总成每个策略的指标。"""
    by_strategy: Dict[str, List[RoundRecord]] = {}
    for r in records:
        by_strategy.setdefault(r.strategy, []).append(r)

    result: Dict[str, StrategyMetrics] = {}
    for name, rows in by_strategy.items():
        total = len(rows)
        successes = sum(1 for r in rows if r.success)
        deceptive_rows = [r for r in rows if r.deceptive_selected]

        early = [r for r in rows if r.round_index < EARLY_PHASE_ROUNDS]
        late = [r for r in rows if r.round_index >= EARLY_PHASE_ROUNDS]

        latencies = [r.latency_ms for r in rows if r.latency_ms > 0]

        # 每轮是否选中虚报型（按轮次排序），用来算"第几轮之后不再上当"
        ordered = sorted(rows, key=lambda r: (r.trial, r.round_index))
        last_deceptive_round: Optional[int] = None
        for r in ordered:
            if r.deceptive_selected:
                last_deceptive_round = max(
                    last_deceptive_round if last_deceptive_round is not None else -1,
                    r.round_index,
                )

        selections = {a: 0 for a in _agent_names(rows)}
        for r in rows:
            # 弃权轮不是"选中了某个智能体"，不能混进选择分布里。
            # 否则会出现一个叫 <无人胜任> 的假智能体，污染统计。
            if r.selected_agent in selections:
                selections[r.selected_agent] += 1

        per_agent_success: Dict[str, List[bool]] = {}
        for r in rows:
            if r.selected_agent not in selections:
                continue
            per_agent_success.setdefault(r.selected_agent, []).append(r.success)

        final_trust: Dict[str, float] = {}
        for r in sorted(rows, key=lambda r: (r.trial, r.round_index)):
            if r.selected_agent in selections:
                final_trust[r.selected_agent] = r.trust_at_decision

        result[name] = StrategyMetrics(
            strategy=name,
            total_rounds=total,
            success_count=successes,
            failure_count=total - successes,
            deceptive_selection_count=len(deceptive_rows),
            early_deceptive_selections=sum(1 for r in early if r.deceptive_selected),
            early_rounds=len(early),
            late_deceptive_selections=sum(1 for r in late if r.deceptive_selected),
            late_rounds=len(late),
            never_selected_deceptive=len(deceptive_rows) == 0,
            recovery_round=(
                None if last_deceptive_round is None else last_deceptive_round + 1
            ),
            abstention_count=sum(
                1 for r in rows if r.selected_agent not in selections
            ),
            avg_latency_ms=_avg(latencies),
            latency_std=(
                statistics.pstdev(latencies) if len(latencies) > 1 else 0.0
            ),
            selections_per_agent=selections,
            success_rate_per_agent={
                agent: (sum(vals) / len(vals) if vals else 0.0)
                for agent, vals in per_agent_success.items()
            },
            final_trust_scores={k: round(v, 6) for k, v in final_trust.items()},
        )
    return result


def _agent_names(rows: Sequence[RoundRecord]) -> List[str]:
    names = {r.selected_agent for r in rows}
    names.discard("<无人胜任>")
    return sorted(names)


def build_success_curves(
    records: Sequence[RoundRecord], config: ExperimentConfig
) -> Dict[str, List[float]]:
    """计算每个策略的"累计成功率曲线"，用于观察学习过程。

    第 k 个数字 = 该策略在前 k+1 轮里的累计成功率。
    """
    grouped: Dict[str, List[RoundRecord]] = {}
    for r in records:
        grouped.setdefault(r.strategy, []).append(r)

    curves: Dict[str, List[float]] = {}
    for name, rows in grouped.items():
        ordered = sorted(rows, key=lambda r: (r.trial, r.round_index))
        curve: List[float] = []
        wins = 0
        for i, r in enumerate(ordered, start=1):
            if r.success:
                wins += 1
            curve.append(wins / i)
        curves[name] = curve
    return curves


# ---------------------------------------------------------------------------
# 结果输出
# ---------------------------------------------------------------------------
def records_to_csv(records: Sequence[RoundRecord], path: Path) -> Path:
    """把逐轮明细写成 CSV（原始数据，参赛要求保存）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(RoundRecord.__dataclass_fields__.keys())
    # utf-8-sig 让 Excel 打开中文不乱码
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))
    return path


def summary_to_csv(result: ExperimentResult, path: Path) -> Path:
    """把汇总指标写成 CSV（一行为一个策略，可直接用于做对比图）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [m.to_row() for m in result.metrics.values()]
    rows.sort(key=lambda r: r["strategy"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def metadata_to_json(result: ExperimentResult, path: Path, extra: Optional[Dict] = None) -> Path:
    """把实验参数和结论性指标写成 JSON，保证实验可复现、可追溯。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": result.config.to_dict(),
        "agent_profiles": result.agent_profiles,
        "metrics_summary": {
            name: {
                "task_success_rate": round(m.task_success_rate, 6),
                "deceptive_selection_rate": round(m.deceptive_selection_rate, 6),
                "early_deceptive_rate": round(m.early_deceptive_rate, 6),
                "late_deceptive_rate": round(m.late_deceptive_rate, 6),
                "never_selected_deceptive": m.never_selected_deceptive,
                "recovery_round": m.recovery_round,
                "avg_latency_ms": round(m.avg_latency_ms, 3),
                "selections_per_agent": m.selections_per_agent,
                "success_rate_per_agent": {
                    k: round(v, 6) for k, v in m.success_rate_per_agent.items()
                },
            }
            for name, m in result.metrics.items()
        },
        "limitations": [
            "智能体的成功率和延迟是人为设定的演示参数，不是真实系统测量值。",
            "实验使用单项能力需求（research），三个智能体能力完全匹配，"
            "因此能力匹配度恒为 1.0，本实验无法体现能力匹配项的作用。",
            "可信度公式为拉普拉斯平滑，属于基础做法，尚未与更复杂算法做对比。",
            "冷启动阶段缺乏历史数据，所有策略都可能先被虚报型智能体误导。",
        ],
    }
    if extra:
        payload.update(extra)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def save_all(
    result: ExperimentResult, output_dir: Path, run_name: str
) -> Dict[str, Path]:
    """一次性保存全部产物，返回文件路径字典。"""
    output_dir = Path(output_dir)
    outputs = {
        "rounds": output_dir / f"{run_name}_rounds.csv",
        "summary": output_dir / f"{run_name}_summary.csv",
        "metadata": output_dir / f"{run_name}_meta.json",
    }
    records_to_csv(result.records, outputs["rounds"])
    summary_to_csv(result, outputs["summary"])
    metadata_to_json(result, outputs["metadata"])
    return outputs


# ---------------------------------------------------------------------------
# 打印
# ---------------------------------------------------------------------------
STRATEGY_LABELS = {
    "random": "随机选择",
    "capability_only": "仅能力匹配",
    "trust_aware": "可信度感知",
}


def format_summary_table(result: ExperimentResult) -> str:
    """把汇总指标排成一张能直接贴进报告的对比表。"""
    lines: List[str] = []
    lines.append("=" * 92)
    lines.append("实验结果汇总")
    lines.append("=" * 92)
    lines.append(
        f"参数：{result.config.trials} 次独立试验 × "
        f"{result.config.rounds} 轮 × {len(result.metrics)} 种策略 "
        f"= 共 {result.total_decisions} 次调度决策"
    )
    lines.append(
        f"任务需求能力：{result.config.required_capabilities} ｜ "
        f"随机种子：{result.config.seed}"
    )
    lines.append("")
    header = (
        f"{'策略':<14}{'任务成功率':>12}{'欺骗被选中率':>14}"
        f"{'前期被骗率':>12}{'后期被骗率':>12}{'平均延迟':>12}"
    )
    lines.append(header)
    lines.append("-" * 92)
    for name in sorted(result.metrics):
        m = result.metrics[name]
        lines.append(
            f"{STRATEGY_LABELS.get(name, name):<14}"
            f"{m.task_success_rate:>11.2%} "
            f"{m.deceptive_selection_rate:>13.2%} "
            f"{m.early_deceptive_rate:>11.2%} "
            f"{m.late_deceptive_rate:>11.2%} "
            f"{m.avg_latency_ms:>10.1f}ms"
        )
    lines.append("-" * 92)
    lines.append("")

    # 逐策略细节
    lines.append("各策略的智能体选择分布：")
    for name in sorted(result.metrics):
        m = result.metrics[name]
        picks = " ｜ ".join(
            f"{agent} {count}次" for agent, count in sorted(m.selections_per_agent.items())
        )
        recovery = (
            "全程未选中" if m.never_selected_deceptive
            else (f"第 {m.recovery_round} 轮起未再选中"
                  if m.recovery_round is not None else "始终未纠正")
        )
        lines.append(f"  {STRATEGY_LABELS.get(name, name)}：{picks}")
        lines.append(f"    虚报型智能体：{recovery}")
    lines.append("")
    return "\n".join(lines)
