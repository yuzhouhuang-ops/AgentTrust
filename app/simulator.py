"""模拟任务执行器。

【这个文件解决什么问题】

原来的 `/demo/reset` 是直接把 "8 胜 2 负" 这种数字硬编码塞进智能体的。
那样得到的"实验结果"其实是预设出来的，不是跑出来的，不能作为参赛证据。

这个模块让任务结果**由概率真实产生**：
    每个智能体有一个"真实成功率"，执行任务时按这个概率随机决定成败。
    智能体自己"宣称"的成功率是另一个独立的数字，可以撒谎。

于是"系统是否盲信自我声明"就变成了一个可以真实测量的问题。

【为什么成功率和延迟要分开建模】

    真实成功率 true_success_rate  -> 决定任务实际成功还是失败
    真实延迟     latency_ms        -> 决定这次任务花了多久
    宣称成功率   claimed_success_rate -> 只用来展示和对比，**绝不参与真实结果判定**

【随机种子】

    所有随机都走同一个 random.Random 实例。
    给定相同种子，整个实验可以完全复现 —— 这是参赛"实验可复现"的硬要求。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List

# 能力词表：注册时校验用，防止拼写错误导致能力永远匹配不上
KNOWN_CAPABILITIES = frozenset(
    {"research", "summarization", "translation", "coding"}
)


@dataclass
class AgentProfile:
    """一个被模拟的智能体。

    truthful_agent() 和 deceptive_agent() 是两个工厂函数，用来说明
    "诚实智能体"和"撒谎智能体"的区别只在于 true 和 claimed 是否一致。
    """

    name: str
    capabilities: List[str]
    true_success_rate: float
    latency_ms: float
    claimed_success_rate: float
    # 备注：为什么这个智能体值得关注（会写进实验结果里，方便解释）
    note: str = ""

    # ---- 运行期统计（模拟过程中累积，不是预设的）----
    successes: int = field(default=0, init=False)
    failures: int = field(default=0, init=False)
    # 所有已完成任务的实际耗时总和，用来算真实平均延迟
    latency_sum: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        """校验参数，参数错了立刻报错，而不是等到实验跑出一堆垃圾数据。"""
        if not 0.0 <= self.true_success_rate <= 1.0:
            raise ValueError(f"true_success_rate 必须在 0~1 之间，收到 {self.true_success_rate}")
        if not 0.0 <= self.claimed_success_rate <= 1.0:
            raise ValueError(
                f"claimed_success_rate 必须在 0~1 之间，收到 {self.claimed_success_rate}"
            )
        if self.latency_ms <= 0:
            raise ValueError(f"latency_ms 必须大于 0，收到 {self.latency_ms}")
        if not self.capabilities:
            raise ValueError(f"{self.name} 至少要有一项能力")

    # ---- 派生属性 ----

    @property
    def total_tasks(self) -> int:
        """已完成的任务总数。"""
        return self.successes + self.failures

    @property
    def actual_success_rate(self) -> float:
        """实测成功率：真实跑出来的战绩，不是宣称值。

        一个任务都没跑过时返回 0.0 —— 调用方应先用 total_tasks 判断样本是否足够，
        不要拿 0 个样本的成功率下结论。
        """
        if self.total_tasks == 0:
            return 0.0
        return self.successes / self.total_tasks

    @property
    def actual_avg_latency_ms(self) -> float:
        """实测平均延迟。没跑过任务时退回理论延迟。"""
        if self.total_tasks == 0:
            return self.latency_ms
        return self.latency_sum / self.total_tasks

    @property
    def is_deceptive(self) -> bool:
        """是否属于"虚报型"：宣称的成功率明显高于真实水平。

        这里用 0.2 作为判定阈值，是一个可调的经验值，不是什么标准定义。
        """
        return self.claimed_success_rate - self.true_success_rate > 0.2

    @property
    def overclaim_gap(self) -> float:
        """虚报幅度 = 宣称值 - 真实值。正数表示高报，负数表示谦虚。"""
        return self.claimed_success_rate - self.true_success_rate

    def reset_stats(self) -> None:
        """清空运行期统计，回到"从零开始"的状态。

        初始化让智能体从冷启动开始（没有任何历史战绩），
        可信度由系统在真实任务中逐步学习得到。
        """
        self.successes = 0
        self.failures = 0
        self.latency_sum = 0.0

    def observed_capabilities(self) -> List[str]:
        """返回能力列表的副本，避免外部意外改动内部状态。"""
        return list(self.capabilities)


def truthful_agent(
    name: str,
    capabilities: List[str],
    success_rate: float,
    latency_ms: float,
    note: str = "",
) -> AgentProfile:
    """创建一个"诚实"智能体：宣称的成功率就等于它的真实水平。"""
    return AgentProfile(
        name=name,
        capabilities=list(capabilities),
        true_success_rate=success_rate,
        latency_ms=latency_ms,
        claimed_success_rate=success_rate,
        note=note,
    )


def deceptive_agent(
    name: str,
    capabilities: List[str],
    true_success_rate: float,
    claimed_success_rate: float,
    latency_ms: float,
    note: str = "",
) -> AgentProfile:
    """创建一个"虚报型"智能体：宣称的成功率高于真实水平。

    参数顺序刻意和 truthful_agent 不同，避免调用时把真假两个值写反。
    """
    if claimed_success_rate <= true_success_rate:
        raise ValueError(
            "虚报型智能体的 claimed_success_rate 必须大于 true_success_rate，"
            f"收到 claimed={claimed_success_rate}, true={true_success_rate}"
        )
    return AgentProfile(
        name=name,
        capabilities=list(capabilities),
        true_success_rate=true_success_rate,
        latency_ms=latency_ms,
        claimed_success_rate=claimed_success_rate,
        note=note,
    )


@dataclass(frozen=True)
class TaskOutcome:
    """一次任务执行的记录。frozen=True 表示创建后不可修改。"""

    agent_name: str
    success: bool
    latency_ms: float


class TaskSimulator:
    """任务执行器：调用 execute() 就真的"跑"一次任务，结果由概率决定。

    用法：
        sim = TaskSimulator(seed=42)
        outcome = sim.execute(profile)
        outcome.success   # True 或 False，由 profile.true_success_rate 决定

    注意：simulator 会顺带更新 profile 上的统计（successes / failures / latency_sum），
    所以同一个 profile 不要同时喂给两个 simulator，否则统计会串。
    """

    def __init__(self, seed: int | None = None) -> None:
        # 用独立的 Random 实例，而不是全局 random 模块。
        # 好处：不同实验之间互不干扰，且能精确复现。
        self._rng = random.Random(seed)
        self.seed = seed

    def execute(self, profile: AgentProfile) -> TaskOutcome:
        """执行一次任务，并把结果记到 profile 上。"""
        # random() 返回 [0, 1) 均匀分布的数。
        # 小于真实成功率就算成功 —— 成功率 0.82 时约有 82% 的次数会成功。
        success = self._rng.random() < profile.true_success_rate

        latency = self._sample_latency(profile)

        if success:
            profile.successes += 1
        else:
            profile.failures += 1
        profile.latency_sum += latency

        return TaskOutcome(
            agent_name=profile.name,
            success=success,
            latency_ms=latency,
        )

    def _sample_latency(self, profile: AgentProfile) -> float:
        """模拟延迟抖动。

        真实系统的响应时间不会是固定值，会在平均值附近波动。
        这里按平均延迟的 ±20% 均匀抖动，最小不低于 1ms。
        """
        base = profile.latency_ms
        low = base * 0.8
        high = base * 1.2
        return max(1.0, self._rng.uniform(low, high))


def default_demo_profiles() -> List[AgentProfile]:
    """实验用的三个智能体（最小可用版）。

    设计意图 —— 让"只看表面指标"的策略会踩坑：

    | 名称              | 能力匹配 | 延迟 | 宣称   | 真实   | 表面看起来 | 实际水平 |
    |-------------------|---------|------|--------|--------|-----------|---------|
    | Reliable-Researcher | 低(1/2) | 430  | 0.82   | 0.82   | 一般       | 很好     |
    | Fast-Generalist     | 高(2/2) | 180  | 0.75   | 0.75   | 很好       | 一般     |
    | Claimed-Expert      | 中(1/2) | 150  | 0.99   | 0.15   | 最好       | 很差     |

    Claimed-Expert 在"能力匹配度"和"延迟"上都很漂亮，宣称成功率 0.99 更是最高，
    但真实成功率只有 0.15 —— 它会拖垮任何盲信表面指标的策略。
    这正是我们要验证的场景。

    这些数字是**为演示而设计的参数**，不是从真实系统测得的统计数据。
    """
    return [
        truthful_agent(
            name="Reliable-Researcher",
            capabilities=["research"],
            success_rate=0.82,
            latency_ms=430,
            note="可靠型：能力窄但表现扎实",
        ),
        truthful_agent(
            name="Fast-Generalist",
            capabilities=["research", "summarization"],
            success_rate=0.75,
            latency_ms=180,
            note="快速通用型：能力强、速度快，但可靠性中等",
        ),
        deceptive_agent(
            name="Claimed-Expert",
            capabilities=["research", "translation", "coding"],
            true_success_rate=0.15,
            claimed_success_rate=0.99,
            latency_ms=150,
            note="虚报型：宣称 0.99 实际 0.15，且延迟最低最容易骗过排序",
        ),
    ]
