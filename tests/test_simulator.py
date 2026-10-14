"""模拟任务执行器的测试。

这一组测试要回答三个关键问题：
  1. 结果真的由概率决定吗？（而不是写死的）
  2. 相同种子能复现吗？（参赛要求"实验可复现"）
  3. 宣称成功率真的不影响结果吗？（抗欺骗的地基）
"""
from statistics import mean

import pytest

from app.simulator import (
    AgentProfile,
    TaskSimulator,
    deceptive_agent,
    default_demo_profiles,
    truthful_agent,
)


def make_profile(**overrides):
    """建一个测试用智能体，只覆盖需要改的字段。"""
    params = dict(
        name="Tester",
        capabilities=["research"],
        true_success_rate=0.5,
        latency_ms=200,
        claimed_success_rate=0.5,
    )
    params.update(overrides)
    return AgentProfile(**params)


# ---------------------------------------------------------------------------
# 1. 基本信息与参数校验
# ---------------------------------------------------------------------------
class TestAgentProfile:
    def test_新智能体没有历史战绩(self):
        p = make_profile()
        assert p.total_tasks == 0
        assert p.actual_success_rate == 0.0

    def test_没跑过任务时退回理论延迟(self):
        p = make_profile(latency_ms=333)
        assert p.actual_avg_latency_ms == pytest.approx(333)

    @pytest.mark.parametrize("bad_rate", [-0.1, 1.1, 2.0])
    def test_非法真实成功率被拒绝(self, bad_rate):
        with pytest.raises(ValueError, match="true_success_rate"):
            make_profile(true_success_rate=bad_rate)

    @pytest.mark.parametrize("bad_rate", [-0.1, 1.5])
    def test_非法宣称成功率被拒绝(self, bad_rate):
        with pytest.raises(ValueError, match="claimed_success_rate"):
            make_profile(claimed_success_rate=bad_rate)

    @pytest.mark.parametrize("bad_latency", [0, -1, -100])
    def test_非法延迟被拒绝(self, bad_latency):
        with pytest.raises(ValueError, match="latency_ms"):
            make_profile(latency_ms=bad_latency)

    def test_没有能力被拒绝(self):
        with pytest.raises(ValueError, match="至少要有一项能力"):
            make_profile(capabilities=[])


class TestAgentFactories:
    def test_诚实智能体的宣称值等于真实值(self):
        p = truthful_agent("Honest", ["research"], success_rate=0.7, latency_ms=100)
        assert p.claimed_success_rate == p.true_success_rate == 0.7
        assert p.is_deceptive is False
        assert p.overclaim_gap == 0.0

    def test_虚报智能体宣称值高于真实值(self):
        p = deceptive_agent(
            "Liar", ["research"], true_success_rate=0.15,
            claimed_success_rate=0.99, latency_ms=100,
        )
        assert p.is_deceptive is True
        assert p.overclaim_gap == pytest.approx(0.84)

    def test_虚报幅度不够大就不算虚报型(self):
        """宣称只比真实高一点点，属于"高估自己"，不算恶意虚报。"""
        p = make_profile(true_success_rate=0.6, claimed_success_rate=0.7)
        assert p.is_deceptive is False

    def test_虚报工厂拒绝非虚报的参数(self):
        """防呆设计：claimed 不比 true 高，说明调用方把参数写反了。"""
        with pytest.raises(ValueError, match="必须大于"):
            deceptive_agent(
                "Oops", ["research"], true_success_rate=0.9,
                claimed_success_rate=0.5, latency_ms=100,
            )

    def test_能力列表返回的是副本(self):
        """外部改动返回值不应影响智能体本身。"""
        p = make_profile(capabilities=["research"])
        caps = p.observed_capabilities()
        caps.append("hacked")
        assert p.capabilities == ["research"]


class TestDemoProfiles:
    def test_返回三个智能体(self):
        assert len(default_demo_profiles()) == 3

    def test_其中恰好一个是虚报型(self):
        liars = [p for p in default_demo_profiles() if p.is_deceptive]
        assert len(liars) == 1
        assert liars[0].name == "Claimed-Expert"

    def test_虚报型的表面指标最有吸引力(self):
        """这是实验设计的关键前提：虚报型在延迟和宣称值上都要最好，
        否则"抗欺骗"就没有被真正考验到。"""
        profiles = default_demo_profiles()
        liar = next(p for p in profiles if p.is_deceptive)

        assert liar.latency_ms == min(p.latency_ms for p in profiles)      # 延迟最低
        assert liar.claimed_success_rate == max(
            p.claimed_success_rate for p in profiles
        )                                                                   # 宣称最高
        assert liar.true_success_rate == min(p.true_success_rate for p in profiles)  # 实际最差

    def test_虚报型真实水平远低于宣称值(self):
        liar = next(p for p in default_demo_profiles() if p.is_deceptive)
        assert liar.true_success_rate < 0.2
        assert liar.claimed_success_rate > 0.9

    def test_每个智能体的能力都在已知词表内(self):
        """防止拼写错误导致能力永远匹配不上。"""
        from app.simulator import KNOWN_CAPABILITIES

        for p in default_demo_profiles():
            for cap in p.capabilities:
                assert cap in KNOWN_CAPABILITIES, f"{p.name} 有未知能力 {cap}"


# ---------------------------------------------------------------------------
# 2. 可复现性 —— 参赛的硬要求
# ---------------------------------------------------------------------------
class TestReproducibility:
    def test_相同种子产生完全相同的序列(self):
        """同样的种子跑两遍，每次结果的成败序列必须一模一样。"""
        def run_sequence():
            sim = TaskSimulator(seed=42)
            p = make_profile(true_success_rate=0.5)
            return [sim.execute(p).success for _ in range(50)]

        assert run_sequence() == run_sequence()

    def test_相同种子产生完全相同的延迟(self):
        def run_latencies():
            sim = TaskSimulator(seed=7)
            p = make_profile(latency_ms=200)
            return [sim.execute(p).latency_ms for _ in range(30)]

        assert run_latencies() == run_latencies()

    def test_不同种子产生不同序列(self):
        """如果换种子结果还一样，说明种子根本没起作用。"""
        def run_sequence(seed):
            sim = TaskSimulator(seed=seed)
            p = make_profile(true_success_rate=0.5)
            return [sim.execute(p).success for _ in range(50)]

        assert run_sequence(1) != run_sequence(2)

    def test_无种子时也能正常运行(self):
        """seed=None 表示不固定种子，用于探索性运行。"""
        sim = TaskSimulator()
        p = make_profile()
        outcome = sim.execute(p)
        assert isinstance(outcome.success, bool)


# ---------------------------------------------------------------------------
# 3. 统计正确性 —— 结果真的由概率决定吗？
# ---------------------------------------------------------------------------
class TestStochasticBehaviour:
    @pytest.mark.parametrize("rate", [0.2, 0.5, 0.8])
    def test_实测成功率接近设定的真实成功率(self, rate):
        """跑 3000 次，实测成功率应接近设定值。
        容差 0.04 是统计波动，不是代码误差。"""
        sim = TaskSimulator(seed=123)
        p = make_profile(true_success_rate=rate)
        for _ in range(3000):
            sim.execute(p)
        assert p.actual_success_rate == pytest.approx(rate, abs=0.04)

    def test_成功率为0时永不成功(self):
        sim = TaskSimulator(seed=1)
        p = make_profile(true_success_rate=0.0)
        for _ in range(200):
            assert sim.execute(p).success is False
        assert p.failures == 200

    def test_成功率为1时永远成功(self):
        sim = TaskSimulator(seed=1)
        p = make_profile(true_success_rate=1.0)
        for _ in range(200):
            assert sim.execute(p).success is True
        assert p.successes == 200

    def test_两次结果都有出现(self):
        """0.5 的成功率跑 100 次，必须两种结果都出现，
        否则说明判定写成了固定值。"""
        sim = TaskSimulator(seed=99)
        p = make_profile(true_success_rate=0.5)
        results = {sim.execute(p).success for _ in range(100)}
        assert results == {True, False}

    def test_延迟在理论值上下抖动(self):
        """延迟不应是固定值，但平均值应贴近设定值。"""
        sim = TaskSimulator(seed=5)
        p = make_profile(latency_ms=1000)
        latencies = [sim.execute(p).latency_ms for _ in range(2000)]

        assert len(set(latencies)) > 100                      # 确实有抖动
        assert mean(latencies) == pytest.approx(1000, rel=0.05)  # 均值贴近

    def test_延迟抖动范围受控(self):
        """抖动限定在 ±20% 内，不应出现离谱的极值。"""
        sim = TaskSimulator(seed=11)
        p = make_profile(latency_ms=1000)
        latencies = [sim.execute(p).latency_ms for _ in range(5000)]

        assert min(latencies) >= 800 - 1e-6
        assert max(latencies) <= 1200 + 1e-6

    def test_延迟永远大于0(self):
        """极小的理论延迟也不能抖动出 0 或负数，否则会被接口校验拒绝。"""
        sim = TaskSimulator(seed=3)
        p = make_profile(latency_ms=1)
        assert all(sim.execute(p).latency_ms > 0 for _ in range(500))


# ---------------------------------------------------------------------------
# 4. 抗欺骗的地基 —— 宣称成功率绝不能影响结果
# ---------------------------------------------------------------------------
class TestClaimedRateDoesNotAffectOutcome:
    def test_相同种子下宣称值不影响成败(self):
        """两个智能体真实水平一样、只有宣称值不同，
        相同种子下成败序列必须完全一致。"""
        sim_a = TaskSimulator(seed=2024)
        honest = make_profile(true_success_rate=0.3, claimed_success_rate=0.3)

        sim_b = TaskSimulator(seed=2024)
        liar = make_profile(true_success_rate=0.3, claimed_success_rate=0.99)

        seq_honest = [sim_a.execute(honest).success for _ in range(200)]
        seq_liar = [sim_b.execute(liar).success for _ in range(200)]

        assert seq_honest == seq_liar

    def test_宣称满分也不会提高实测成功率(self):
        """宣称 1.0 但真实 0.1 的智能体，实测成功率必须仍在 0.1 附近。"""
        sim = TaskSimulator(seed=8)
        p = make_profile(true_success_rate=0.1, claimed_success_rate=1.0)
        for _ in range(3000):
            sim.execute(p)
        assert p.actual_success_rate == pytest.approx(0.1, abs=0.03)


# ---------------------------------------------------------------------------
# 5. 统计累积
# ---------------------------------------------------------------------------
class TestStatisticsAccumulation:
    def test_成功失败分别累加(self):
        sim = TaskSimulator(seed=4)
        p = make_profile(true_success_rate=0.5)
        for _ in range(300):
            sim.execute(p)
        assert p.successes + p.failures == 300
        assert p.successes > 0 and p.failures > 0

    def test_实测平均延迟来自实际记录(self):
        sim = TaskSimulator(seed=6)
        p = make_profile(latency_ms=500)
        recorded = [sim.execute(p).latency_ms for _ in range(100)]
        assert p.actual_avg_latency_ms == pytest.approx(mean(recorded))

    def test_重置统计会清空战绩(self):
        sim = TaskSimulator(seed=9)
        p = make_profile()
        for _ in range(50):
            sim.execute(p)
        assert p.total_tasks == 50

        p.reset_stats()
        assert p.total_tasks == 0
        assert p.actual_avg_latency_ms == pytest.approx(p.latency_ms)

    def test_重置后相同种子仍可复现(self):
        """重置 + 重建同种子执行器，结果应与首次完全一致。"""
        def run():
            sim = TaskSimulator(seed=77)
            p = make_profile(true_success_rate=0.5)
            seq = [sim.execute(p).success for _ in range(40)]
            p.reset_stats()
            return seq

        assert run() == run()

    def test_outcome_记录智能体名字(self):
        sim = TaskSimulator(seed=2)
        p = make_profile(name="我的智能体")
        assert sim.execute(p).agent_name == "我的智能体"
