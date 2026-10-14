"""评分逻辑（算法核心，供实验框架复用）。

【为什么单独抽一个文件出来】

评分公式目前同时被两处需要：
  1. `app/main.py`  —— 线上 API 用它做 /discover 排序
  2. `app/strategies.py` —— 实验框架用它实现"可信度感知调度"策略

如果两边各写一份，将来调整算法时就会出现"改了 A 忘了改 B"，
实验结论和线上行为对不上 —— 这是最难排查的一类 bug。

所以实验侧统一引用这里，并在 `tests/test_strategies.py::TestConsistencyWithApi`
里用测试断言"这里的公式和 main.py 的公式结果完全一致"。
一旦将来有人只改了一边，测试会立刻变红。

【注意】
`app/main.py` 目前仍保留自己的一份实现（为了保证线上接口行为零变化、
已有的 49 个测试不被牵动）。后续重构时可以把 main.py 也改为引用这里，
那一步需要单独验证，属于独立的改动。
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

# 平滑常数：相当于先验地认为智能体"2 胜 2 负"。
# 作用是让新智能体（0 胜 0 负）的可信度落在 0.5，而不是 0 或 1。
PRIOR_SUCCESSES = 2.0
PRIOR_FAILURES = 2.0

# 综合分权重。三项相加必须等于 1.0，改动时请同步更新测试。
WEIGHT_CAPABILITY = 0.60
WEIGHT_TRUST = 0.30
WEIGHT_LATENCY = 0.10

# 延迟归一化的时间常数：延迟等于该值时延迟分正好 0.5
LATENCY_SCALE_MS = 1000.0


def trust_score(successes: int, failures: int) -> float:
    """可信度 = 平滑历史成功率。

    公式：(成功次数 + 2) / (成功次数 + 失败次数 + 4)

    性质：
      - 0 胜 0 负 -> 0.5      （冷启动既不盲信也不否定）
      - 1 胜 0 负 -> 0.6      （样本少时保守）
      - 10 胜 0 负 -> 0.857   （样本多时才接近 1，但永不为 1）
      - 越多成功越高，越多失败越低（严格单调）

    注意：这里**不接受**任何"宣称成功率"参数。
    智能体自己声称的水平不参与可信度计算，这是抗欺骗设计的前提。
    """
    if successes < 0 or failures < 0:
        raise ValueError(f"成功/失败次数不能为负：successes={successes}, failures={failures}")
    return (successes + PRIOR_SUCCESSES) / (
        successes + failures + PRIOR_SUCCESSES + PRIOR_FAILURES
    )


def normalize_capabilities(items: Iterable[str]) -> set:
    """把能力列表统一成小写、去空格的集合，避免大小写和空格导致匹配失败。"""
    return {str(x).strip().lower() for x in items if str(x).strip()}


def match_score(offered: Sequence[str], required: Sequence[str]) -> float:
    """能力匹配度 = 需求中被满足的比例，范围 0~1。

    - 完全满足 -> 1.0
    - 满足一半 -> 0.5
    - 完全不满足 -> 0.0
    - 需求为空 -> 0.0（防除零）
    - 能力超出需求不会超过 1.0（多余的技能不加分）
    """
    req = normalize_capabilities(required)
    if not req:
        return 0.0
    off = normalize_capabilities(offered)
    return len(req & off) / len(req)


def latency_score(latency_ms: float) -> float:
    """把延迟换算成 0~1 的分数，越低越好。

    公式：1000 / (1000 + 延迟)
      - 0ms   -> 1.00
      - 1000ms -> 0.50
      - 5000ms -> 0.167
    这样延迟再低也不会让总分爆掉，始终被限制在 10% 权重内。
    """
    if latency_ms < 0:
        raise ValueError(f"延迟不能为负：{latency_ms}")
    return LATENCY_SCALE_MS / (LATENCY_SCALE_MS + latency_ms)


def total_score(
    offered_capabilities: Sequence[str],
    required_capabilities: Sequence[str],
    successes: int,
    failures: int,
    latency_ms: float,
) -> float:
    """综合分 = 0.60*能力匹配 + 0.30*可信度 + 0.10*延迟分。

    参数刻意用扁平的基本类型，而不是直接传智能体对象，
    这样无论是 API 的字典还是模拟器的 dataclass 都能复用，也更好写测试。
    """
    return (
        WEIGHT_CAPABILITY * match_score(offered_capabilities, required_capabilities)
        + WEIGHT_TRUST * trust_score(successes, failures)
        + WEIGHT_LATENCY * latency_score(latency_ms)
    )


def read_latency_ms(agent: Mapping) -> float:
    """从字典形式的智能体里读出延迟，兼容两种字段名。

    - `avg_latency_ms`      : API 注册时填的（理论值或已平滑的均值）
    - `actual_avg_latency_ms`: 模拟器实际跑出来的均值

    优先用实测值，没有则退回理论值。
    """
    for key in ("actual_avg_latency_ms", "avg_latency_ms"):
        if key in agent and agent[key] is not None:
            return float(agent[key])
    raise KeyError("智能体记录里找不到延迟字段（avg_latency_ms / actual_avg_latency_ms）")


def score_breakdown(
    offered_capabilities: Sequence[str],
    required_capabilities: Sequence[str],
    successes: int,
    failures: int,
    latency_ms: float,
) -> dict:
    """返回分数的完整拆解，用于解释"为什么这个智能体排第一"。

    实验报告和答辩时非常有用：能说清是能力赢的、可信度赢的、还是延迟赢的。
    """
    m = match_score(offered_capabilities, required_capabilities)
    t = trust_score(successes, failures)
    lat = latency_score(latency_ms)
    return {
        "capability_match": m,
        "trust_score": t,
        "latency_score": lat,
        "weighted_capability": WEIGHT_CAPABILITY * m,
        "weighted_trust": WEIGHT_TRUST * t,
        "weighted_latency": WEIGHT_LATENCY * lat,
        "total": WEIGHT_CAPABILITY * m + WEIGHT_TRUST * t + WEIGHT_LATENCY * lat,
    }
