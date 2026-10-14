"""调度策略基线。

【实验要回答的问题】

面对同一个任务和同一批智能体，不同的选择策略表现差多少？

本模块实现三种策略，它们的复杂度递增：

  1. RandomStrategy        —— 随机选择。完全不做判断，纯粹的对照底线。
  2. CapabilityOnlyStrategy —— 只按能力匹配度选。会筛掉能力不匹配的，
                               但仍然完全无视智能体的真实历史战绩。
  3. TrustAwareStrategy     —— 能力匹配 + 可信度 + 延迟综合排序。
                               这是我们要验证的"可信度感知调度"。

【三者公平性说明】

为了让比较有意义，三种策略看到的是**同一批智能体、同一份历史战绩**，
唯一的差别只是"怎么选"。实验运行器负责保证这一点。

【关于候选池的重要设计决定】

- 随机选择：从**全部**智能体里挑，不做任何能力过滤。
  这符合"朴素基线"的定义 —— 它连任务需要什么能力都不看。
- 能力匹配 / 可信度感知：只保留能力匹配度 > 0 的智能体。
  因为一个能力完全对不上的智能体，派它去做任务是没有意义的选择，
  把它算进候选会让"能力匹配"这个对照失去意义。

这个差异是**刻意设计**的，会在实验报告里说明。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Protocol, Sequence

from app.scoring import (
    match_score,
    read_latency_ms,
    score_breakdown,
    total_score,
)


class AgentView:
    """策略看到的智能体视图。

    把"字典形式的 API 智能体"和"dataclass 形式的模拟器智能体"
    统一成同一种结构，策略代码就不用关心数据从哪来。

    这是一个**快照**：创建之后历史战绩不会再变。
    策略在一次选择中必须基于同一时刻的数据做判断，
    否则同一轮里"边选边变"会导致结果不可复现。
    """

    __slots__ = ("name", "capabilities", "successes", "failures",
                 "latency_ms", "claimed_success_rate", "is_deceptive")

    def __init__(
        self,
        name: str,
        capabilities: Sequence[str],
        successes: int,
        failures: int,
        latency_ms: float,
        claimed_success_rate: float = 0.0,
        is_deceptive: bool = False,
    ) -> None:
        self.name = name
        self.capabilities = list(capabilities)
        self.successes = successes
        self.failures = failures
        self.latency_ms = latency_ms
        self.claimed_success_rate = claimed_success_rate
        self.is_deceptive = is_deceptive

    @property
    def total_tasks(self) -> int:
        return self.successes + self.failures

    @classmethod
    def from_profile(cls, profile: Any) -> "AgentView":
        """从模拟器的 AgentProfile 创建视图。"""
        return cls(
            name=profile.name,
            capabilities=profile.observed_capabilities(),
            successes=profile.successes,
            failures=profile.failures,
            latency_ms=profile.actual_avg_latency_ms,
            claimed_success_rate=profile.claimed_success_rate,
            is_deceptive=profile.is_deceptive,
        )

    @classmethod
    def from_dict(cls, record: Dict[str, Any]) -> "AgentView":
        """从 API 的字典形式智能体创建视图。"""
        return cls(
            name=record["name"],
            capabilities=record.get("capabilities", []),
            successes=record.get("successes", 0),
            failures=record.get("failures", 0),
            latency_ms=read_latency_ms(record),
            claimed_success_rate=record.get("claimed_success_rate", 0.0),
            is_deceptive=record.get("is_deceptive_demo", False),
        )

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return (
            f"AgentView({self.name!r}, {self.successes}胜{self.failures}负, "
            f"{self.latency_ms:.0f}ms)"
        )


class SelectionStrategy(Protocol):
    """策略接口。

    任何实现了 select() 的对象都可以当策略用（Python 的"鸭子类型"）。
    返回被选中的 AgentView，或 None 表示放弃这次任务。
    """

    name: str

    def select(
        self, agents: Sequence[AgentView], required: Sequence[str]
    ) -> Optional[AgentView]:
        ...


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _eligible(agents: Sequence[AgentView], required: Sequence[str]) -> List[AgentView]:
    """筛出至少有部分能力匹配的智能体。"""
    return [a for a in agents if match_score(a.capabilities, required) > 0]


def _desc(values: Sequence[float]) -> List[float]:
    return sorted(values, reverse=True)


def rank_by_capability(
    agents: Sequence[AgentView], required: Sequence[str]
) -> List[Dict[str, Any]]:
    """只按能力匹配度排序（延迟最低作为并列时的次要依据）。

    这是"仅能力匹配"策略的内部实现，也用于实验报告里展示排序细节。
    **完全不看成功/失败次数** —— 这正是它的局限所在。
    """
    rows = []
    for a in agents:
        m = match_score(a.capabilities, required)
        if m <= 0:
            continue
        rows.append(
            {
                "name": a.name,
                "capability_match": m,
                "latency_ms": a.latency_ms,
                "successes": a.successes,
                "failures": a.failures,
            }
        )
    # 排序键：能力匹配降序 -> 延迟升序 -> 名字升序
    # 最后加名字是为了让结果完全确定，不受输入顺序影响
    rows.sort(key=lambda r: (-r["capability_match"], r["latency_ms"], r["name"]))
    return rows


def rank_by_trust(
    agents: Sequence[AgentView], required: Sequence[str]
) -> List[Dict[str, Any]]:
    """按综合分排序，并给出每一项的分数拆解。

    排序键：综合分降序 -> 可信度降序 -> 延迟升序 -> 名字升序。
    后面几项都是为了让并列情况下的结果完全确定。
    """
    rows = []
    for a in agents:
        m = match_score(a.capabilities, required)
        if m <= 0:
            continue
        detail = score_breakdown(
            offered_capabilities=a.capabilities,
            required_capabilities=required,
            successes=a.successes,
            failures=a.failures,
            latency_ms=a.latency_ms,
        )
        rows.append({"name": a.name, **detail, "latency_ms": a.latency_ms,
                     "successes": a.successes, "failures": a.failures})
    rows.sort(
        key=lambda r: (-r["total"], -r["trust_score"], r["latency_ms"], r["name"])
    )
    return rows


# ---------------------------------------------------------------------------
# 策略一：随机选择
# ---------------------------------------------------------------------------
class RandomStrategy:
    """随机选择基线：完全不做判断，从全部智能体里随机挑一个。

    它的作用是给出"什么都不做"的成绩底线。
    如果可信度感知策略赢不过随机选择，那这套机制就没有价值 ——
    这是一个必须诚实面对的对照。
    """

    name = "random"

    def __init__(self, seed: Optional[int] = None) -> None:
        # 用独立 Random 实例而非全局 random，保证实验可复现
        self._rng = random.Random(seed)
        self.seed = seed

    def select(
        self, agents: Sequence[AgentView], required: Sequence[str]
    ) -> Optional[AgentView]:
        if not agents:
            return None
        return self._rng.choice(list(agents))


# ---------------------------------------------------------------------------
# 策略二：仅按能力匹配
# ---------------------------------------------------------------------------
class CapabilityOnlyStrategy:
    """只按能力匹配度选择，无视历史战绩。

    它比随机选择聪明一点：会筛掉能力完全不匹配的智能体。
    但它完全不知道"这个智能体过去失败过多少次"，
    所以很容易选中"能力很强但实际经常失败"的虚报型智能体。

    这正是我们要在实验里展示的短板。
    """

    name = "capability_only"

    def select(
        self, agents: Sequence[AgentView], required: Sequence[str]
    ) -> Optional[AgentView]:
        ranked = rank_by_capability(agents, required)
        if not ranked:
            return None
        winner = ranked[0]["name"]
        return next(a for a in agents if a.name == winner)


# ---------------------------------------------------------------------------
# 策略三：可信度感知调度（本项目的方案）
# ---------------------------------------------------------------------------
class TrustAwareStrategy:
    """能力匹配 + 可信度 + 延迟综合排序。

    综合分 = 0.60*能力匹配 + 0.30*可信度 + 0.10*延迟分

    与"仅能力匹配"的关键差别：它把**实际历史战绩**纳入决策。
    一个宣称自己 99% 成功、但实际 1 胜 7 负的智能体，
    在能力项上可能并列第一，却会因为可信度低而排到后面。
    """

    name = "trust_aware"

    def select(
        self, agents: Sequence[AgentView], required: Sequence[str]
    ) -> Optional[AgentView]:
        ranked = rank_by_trust(agents, required)
        if not ranked:
            return None
        winner = ranked[0]["name"]
        return next(a for a in agents if a.name == winner)


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------
STRATEGY_NAMES = ("random", "capability_only", "trust_aware")


def build_strategies(seed: int = 42) -> List[SelectionStrategy]:
    """按固定顺序创建三种策略，用于横向对比实验。

    随机策略用固定种子，保证整个实验可复现。
    """
    return [
        RandomStrategy(seed=seed),
        CapabilityOnlyStrategy(),
        TrustAwareStrategy(),
    ]
