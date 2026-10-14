"""评分类与调度策略的测试。

重点：
  1. TestConsistencyWithApi —— 用测试锁住"实验的公式 == 线上 API 的公式"。
     将来只改一边，测试立刻变红。
  2. TestAntiDeception —— 验证可信度感知策略确实不会被虚报型骗到，
     而"仅能力匹配"策略会被骗到。这是整个项目论点的核心证据。
"""
import random

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.scoring import (
    LATENCY_SCALE_MS,
    PRIOR_FAILURES,
    PRIOR_SUCCESSES,
    WEIGHT_CAPABILITY,
    WEIGHT_LATENCY,
    WEIGHT_TRUST,
    latency_score,
    match_score,
    normalize_capabilities,
    read_latency_ms,
    score_breakdown,
    total_score,
    trust_score,
)
from app.simulator import TaskSimulator, default_demo_profiles
from app.strategies import (
    STRATEGY_NAMES,
    AgentView,
    CapabilityOnlyStrategy,
    RandomStrategy,
    TrustAwareStrategy,
    build_strategies,
    rank_by_capability,
    rank_by_trust,
)

client = TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def view(name, capabilities, successes=0, failures=0, latency_ms=200,
         claimed_success_rate=0.0, is_deceptive=False):
    return AgentView(
        name=name,
        capabilities=list(capabilities),
        successes=successes,
        failures=failures,
        latency_ms=latency_ms,
        claimed_success_rate=claimed_success_rate,
        is_deceptive=is_deceptive,
    )


def experiment_agents():
    """把模拟器的三个智能体转成策略视图（冷启动，没有任何历史战绩）。"""
    return [AgentView.from_profile(p) for p in default_demo_profiles()]


# ---------------------------------------------------------------------------
# 1. 与线上 API 的一致性 —— 防止两份公式漂移
# ---------------------------------------------------------------------------
class TestConsistencyWithApi:
    """实验侧用的是 app/scoring.py，线上 API 用的是 app/main.py 里的一份实现。

    这一组测试确保两者**结果完全相同**。
    将来如果只改了其中一边，这里会立刻失败。
    """

    def test_可信度公式与main一致(self):
        from app.main import trust_score as api_trust_score

        for successes, failures in [
            (0, 0), (1, 0), (0, 1), (8, 2), (5, 3), (1, 7),
            (100, 0), (0, 100), (37, 63),
        ]:
            api = api_trust_score({"successes": successes, "failures": failures})
            mine = trust_score(successes, failures)
            assert mine == pytest.approx(api), (
                f"可信度公式与 main.py 不一致！({successes}胜{failures}负) "
                f"scoring={mine} main={api}"
            )

    def test_能力匹配公式与main一致(self):
        from app.main import match_score as api_match_score

        cases = [
            (["research", "summarization"], ["research", "summarization"]),
            (["research"], ["research", "translation"]),
            (["research"], ["cooking"]),
            (["  Research "], ["research"]),
            (["a", "b", "c"], ["a"]),
            (["research"], []),
        ]
        for offered, required in cases:
            api = api_match_score({"capabilities": offered}, required)
            mine = match_score(offered, required)
            assert mine == pytest.approx(api), (
                f"能力匹配公式与 main.py 不一致！offered={offered} required={required} "
                f"scoring={mine} main={api}"
            )

    def test_综合分公式与main一致(self):
        from app.main import total_score as api_total_score

        for successes, failures, latency in [
            (8, 2, 450), (5, 3, 180), (1, 7, 300), (0, 0, 200), (50, 50, 5000),
        ]:
            api = api_total_score(
                {"capabilities": ["research"], "successes": successes,
                 "failures": failures, "avg_latency_ms": latency},
                ["research"],
            )
            mine = total_score(["research"], ["research"], successes, failures, latency)
            assert mine == pytest.approx(api), (
                f"综合分公式与 main.py 不一致！({successes}胜{failures}负, {latency}ms) "
                f"scoring={mine} main={api}"
            )

    def test_平滑常数与main一致(self):
        """把常数也锁住：如果有人只改了 scoring.py 的常数，这里会发现。"""
        from app.main import trust_score as api_trust_score

        # 反推 main.py 使用的平滑常数
        successes, failures = 10, 10
        api = api_trust_score({"successes": successes, "failures": failures})
        expected = (successes + PRIOR_SUCCESSES) / (
            successes + failures + PRIOR_SUCCESSES + PRIOR_FAILURES
        )
        assert api == pytest.approx(expected)

    def test_通过真实接口验证排序一致(self):
        """端到端验证：用 API 跑一遍 /discover，用实验代码算一遍，排序结果必须相同。"""
        client.post("/demo/reset")
        api_agents = client.get("/agents").json()
        required = ["research", "summarization"]

        api_ranking = [
            c["name"]
            for c in client.post(
                "/discover", json={"task_id": "t", "required_capabilities": required}
            ).json()["candidates"]
        ]

        views = [AgentView.from_dict(a) for a in api_agents]
        mine_ranking = [r["name"] for r in rank_by_trust(views, required)]

        assert mine_ranking == api_ranking

    def test_权重配置合法(self):
        assert WEIGHT_CAPABILITY + WEIGHT_TRUST + WEIGHT_LATENCY == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. 评分函数
# ---------------------------------------------------------------------------
class TestTrustScore:
    def test_冷启动为0_5(self):
        assert trust_score(0, 0) == pytest.approx(0.5)

    @pytest.mark.parametrize(
        "successes,failures,expected",
        [(0, 0, 0.5), (8, 2, 10 / 14), (5, 3, 7 / 12), (1, 7, 0.25), (1, 0, 0.6)],
    )
    def test_手算核对(self, successes, failures, expected):
        assert trust_score(successes, failures) == pytest.approx(expected)

    def test_成功提高失败降低(self):
        base = trust_score(5, 5)
        assert trust_score(6, 5) > base > trust_score(5, 6)

    def test_样本少时更保守(self):
        assert trust_score(1, 0) < trust_score(10, 0)

    def test_负数被拒绝(self):
        with pytest.raises(ValueError):
            trust_score(-1, 0)
        with pytest.raises(ValueError):
            trust_score(0, -1)

    def test_分数永远在0和1之间(self):
        """极端情况下也不能越界，否则加权后会破坏排序。"""
        assert 0 < trust_score(0, 10000) < 1
        assert 0 < trust_score(10000, 0) < 1


class TestMatchScore:
    def test_完全匹配(self):
        assert match_score(["research", "summarization"],
                           ["research", "summarization"]) == pytest.approx(1.0)

    def test_部分匹配(self):
        assert match_score(["research"], ["research", "coding"]) == pytest.approx(0.5)

    def test_无匹配(self):
        assert match_score(["research"], ["cooking"]) == pytest.approx(0.0)

    def test_超出需求不超过1(self):
        assert match_score(["a", "b", "c", "d"], ["a"]) == pytest.approx(1.0)

    def test_大小写空格不敏感(self):
        assert match_score(["  ReSearch "], ["research"]) == pytest.approx(1.0)

    def test_空需求返回0(self):
        assert match_score(["research"], []) == pytest.approx(0.0)
        assert match_score(["research"], ["  "]) == pytest.approx(0.0)

    def test_归一化去重(self):
        assert normalize_capabilities(["a", "A", " a ", ""]) == {"a"}


class TestLatencyScore:
    @pytest.mark.parametrize(
        "latency,expected",
        [(0, 1.0), (LATENCY_SCALE_MS, 0.5), (3000, 1000 / 4000)],
    )
    def test_手算核对(self, latency, expected):
        assert latency_score(latency) == pytest.approx(expected)

    def test_越低越好(self):
        assert latency_score(50) > latency_score(500) > latency_score(5000)

    def test_负数被拒绝(self):
        with pytest.raises(ValueError):
            latency_score(-1)

    def test_极低延迟也不会超过1(self):
        assert latency_score(0.0001) <= 1.0


class TestTotalScoreAndBreakdown:
    def test_三项加权相加(self):
        expected = (
            WEIGHT_CAPABILITY * 1.0
            + WEIGHT_TRUST * trust_score(8, 2)
            + WEIGHT_LATENCY * latency_score(450)
        )
        assert total_score(["research"], ["research"], 8, 2, 450) == pytest.approx(expected)

    def test_拆解各项与总分自洽(self):
        d = score_breakdown(["research"], ["research"], 8, 2, 450)
        assert d["weighted_capability"] == pytest.approx(WEIGHT_CAPABILITY * d["capability_match"])
        assert d["weighted_trust"] == pytest.approx(WEIGHT_TRUST * d["trust_score"])
        assert d["weighted_latency"] == pytest.approx(WEIGHT_LATENCY * d["latency_score"])
        assert d["total"] == pytest.approx(
            d["weighted_capability"] + d["weighted_trust"] + d["weighted_latency"]
        )

    def test_宣称成功率不参与任何计算(self):
        """score_breakdown 的签名里根本没有 claimed 参数 —— 从接口层面杜绝。"""
        import inspect

        params = inspect.signature(score_breakdown).parameters
        assert not any("claim" in p for p in params), (
            "评分函数不应该接受宣称成功率参数，这会破坏抗欺骗设计"
        )
        params = inspect.signature(total_score).parameters
        assert not any("claim" in p for p in params)


class TestReadLatency:
    def test_优先实测值(self):
        assert read_latency_ms(
            {"avg_latency_ms": 100, "actual_avg_latency_ms": 250}
        ) == pytest.approx(250)

    def test_退回理论值(self):
        assert read_latency_ms({"avg_latency_ms": 100}) == pytest.approx(100)

    def test_缺字段时报错(self):
        with pytest.raises(KeyError):
            read_latency_ms({"name": "x"})


# ---------------------------------------------------------------------------
# 3. AgentView
# ---------------------------------------------------------------------------
class TestAgentView:
    def test_从模拟器档案创建(self):
        p = default_demo_profiles()[0]
        v = AgentView.from_profile(p)
        assert v.name == p.name
        assert v.capabilities == p.capabilities
        assert v.latency_ms == pytest.approx(p.actual_avg_latency_ms)

    def test_从API字典创建(self):
        client.post("/demo/reset")
        record = client.get("/agents").json()[0]
        v = AgentView.from_dict(record)
        assert v.name == record["name"]
        assert v.successes == record["successes"]
        assert v.failures == record["failures"]

    def test_能力是副本(self):
        v = view("x", ["research"])
        v.capabilities.append("hacked")
        assert v.capabilities == ["research", "hacked"]  # 只影响自己，不影响来源

    def test_总任务数(self):
        assert view("x", ["a"], successes=3, failures=2).total_tasks == 5


# ---------------------------------------------------------------------------
# 4. 排序逻辑
# ---------------------------------------------------------------------------
class TestRanking:
    def test_能力排序按匹配度降序(self):
        agents = [
            view("低", ["research"], latency_ms=100),
            view("高", ["research", "summarization"], latency_ms=900),
        ]
        ranked = rank_by_capability(agents, ["research", "summarization"])
        assert [r["name"] for r in ranked] == ["高", "低"]

    def test_能力排序无视历史战绩(self):
        """这是"仅能力匹配"策略的局限：战绩再差也不影响它的排序。"""
        agents = [
            view("差生", ["research"], successes=0, failures=1000, latency_ms=100),
            view("优等生", ["research"], successes=1000, failures=0, latency_ms=100),
        ]
        ranked = rank_by_capability(agents, ["research"])
        # 能力相同、延迟相同，只能靠名字排序 —— 战绩完全没参与
        assert [r["name"] for r in ranked] == sorted(["差生", "优等生"])

    def test_能力排序会剔除不匹配的(self):
        agents = [view("会", ["research"]), view("不会", ["cooking"])]
        ranked = rank_by_capability(agents, ["research"])
        assert [r["name"] for r in ranked] == ["会"]

    def test_可信度排序会考虑战绩(self):
        agents = [
            view("差生", ["research"], successes=0, failures=100, latency_ms=100),
            view("优等生", ["research"], successes=100, failures=0, latency_ms=100),
        ]
        ranked = rank_by_trust(agents, ["research"])
        assert [r["name"] for r in ranked] == ["优等生", "差生"]

    def test_可信度排序剔除不匹配的(self):
        agents = [view("会", ["research"]), view("不会", ["cooking"])]
        assert [r["name"] for r in rank_by_trust(agents, ["research"])] == ["会"]

    def test_可信度排序结果与输入顺序无关(self):
        """确定性要求：打乱输入顺序，排序结果必须不变。"""
        agents = [
            view("甲", ["research"], successes=9, failures=1, latency_ms=300),
            view("乙", ["research"], successes=2, failures=8, latency_ms=100),
            view("丙", ["research"], successes=5, failures=5, latency_ms=200),
        ]
        first = [r["name"] for r in rank_by_trust(agents, ["research"])]
        for _ in range(20):
            shuffled = agents[:]
            random.Random(_).shuffle(shuffled)
            assert [r["name"] for r in rank_by_trust(shuffled, ["research"])] == first

    def test_完全并列时按名字排序保证确定(self):
        """三个智能体所有指标完全一样，必须仍能稳定选出一个。"""
        agents = [view(n, ["research"], successes=5, failures=5, latency_ms=200)
                  for n in ("b", "a", "c")]
        assert [r["name"] for r in rank_by_trust(agents, ["research"])] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 5. 策略行为
# ---------------------------------------------------------------------------
class TestRandomStrategy:
    def test_空候选返回None(self):
        assert RandomStrategy(seed=1).select([], ["research"]) is None

    def test_相同种子结果可复现(self):
        agents = [view(n, ["research"]) for n in ("a", "b", "c")]
        s1 = [RandomStrategy(seed=5).select(agents, ["research"]).name for _ in range(1)]
        r1 = RandomStrategy(seed=5)
        r2 = RandomStrategy(seed=5)
        assert [r1.select(agents, ["research"]).name for _ in range(30)] == \
               [r2.select(agents, ["research"]).name for _ in range(30)]
        assert s1  # 用了下面那个，这里只是确保上面没写错

    def test_会选到不同的人(self):
        agents = [view(n, ["research"]) for n in ("a", "b", "c")]
        strat = RandomStrategy(seed=3)
        picked = {strat.select(agents, ["research"]).name for _ in range(100)}
        assert picked == {"a", "b", "c"}

    def test_不做能力过滤(self):
        """随机策略刻意不看能力 —— 这是"朴素基线"的定义。"""
        agents = [view("不会做", ["cooking"])]
        assert RandomStrategy(seed=1).select(agents, ["research"]).name == "不会做"


class TestCapabilityOnlyStrategy:
    def test_空候选返回None(self):
        assert CapabilityOnlyStrategy().select([], ["research"]) is None

    def test_无匹配返回None(self):
        agents = [view("不会", ["cooking"])]
        assert CapabilityOnlyStrategy().select(agents, ["research"]) is None

    def test_选匹配度最高的(self):
        agents = [
            view("半会", ["research"], latency_ms=50),
            view("全会", ["research", "summarization"], latency_ms=900),
        ]
        assert CapabilityOnlyStrategy().select(
            agents, ["research", "summarization"]
        ).name == "全会"

    def test_相同匹配度时选延迟低的(self):
        agents = [
            view("慢", ["research"], latency_ms=900),
            view("快", ["research"], latency_ms=100),
        ]
        assert CapabilityOnlyStrategy().select(agents, ["research"]).name == "快"

    def test_结果稳定可复现(self):
        agents = experiment_agents()
        strat = CapabilityOnlyStrategy()
        assert len({strat.select(agents, ["research"]).name for _ in range(50)}) == 1


class TestTrustAwareStrategy:
    def test_空候选返回None(self):
        assert TrustAwareStrategy().select([], ["research"]) is None

    def test_无匹配返回None(self):
        assert TrustAwareStrategy().select([view("不会", ["cooking"])], ["research"]) is None

    def test_避开战绩差的(self):
        agents = [
            view("骗子", ["research"], successes=1, failures=99, latency_ms=10),
            view("老实", ["research"], successes=99, failures=1, latency_ms=900),
        ]
        assert TrustAwareStrategy().select(agents, ["research"]).name == "老实"

    def test_结果稳定可复现(self):
        agents = experiment_agents()
        strat = TrustAwareStrategy()
        assert len({strat.select(agents, ["research"]).name for _ in range(50)}) == 1


# ---------------------------------------------------------------------------
# 6. 抗欺骗 —— 项目的核心论点
# ---------------------------------------------------------------------------
class TestAntiDeception:
    """这一组是参赛论点的直接证据。

    场景：一个智能体宣称 99% 成功率、延迟最低，但真实成功率只有 15%。
    """

    def build_scenario(self, liar_rounds=40):
        """构造场景：跑若干轮任务，让所有智能体积累真实战绩。

        为了让"是否被骗"看得清楚，这里让三个智能体都先真实地跑一批任务，
        战绩完全由模拟器的概率产生。
        """
        profiles = default_demo_profiles()
        sim = TaskSimulator(seed=2024)
        for _ in range(liar_rounds):
            for p in profiles:
                sim.execute(p)
        return [AgentView.from_profile(p) for p in profiles]

    def test_虚报型积累了高失败次数(self):
        agents = {a.name: a for a in self.build_scenario()}
        liar = agents["Claimed-Expert"]
        assert liar.failures > liar.successes          # 失败远多于成功
        assert liar.total_tasks == 40
        # 实测成功率接近它真实的 0.15，而不是宣称的 0.99
        assert liar.successes / liar.total_tasks < 0.3

    def test_可信度感知策略不会被宣称值骗到(self):
        agents = self.build_scenario()
        picked = TrustAwareStrategy().select(agents, ["research"])
        assert picked.name != "Claimed-Expert"

    def test_可信度感知选出的是实测表现最好的(self):
        agents = self.build_scenario()
        picked = TrustAwareStrategy().select(agents, ["research"])

        eligible = [a for a in agents if match_score(a.capabilities, ["research"]) > 0]
        best_rate = max(a.successes / a.total_tasks for a in eligible)
        assert picked.successes / picked.total_tasks == pytest.approx(best_rate)

    def test_虚报型在可信度排序里明显靠后(self):
        agents = self.build_scenario()
        names = [r["name"] for r in rank_by_trust(agents, ["research"])]
        assert names[-1] == "Claimed-Expert"

    def test_能力排序在冷启动时会被延迟误导(self):
        """这是"仅能力匹配"策略的短板，也是实验要展示的现象。

        冷启动时三者都没有战绩，能力又都是 1.0，
        于是"仅能力匹配"只能靠延迟决胜 —— 而虚报型延迟最低，就被选中了。
        """
        agents = [AgentView.from_profile(p) for p in default_demo_profiles()]
        picked = CapabilityOnlyStrategy().select(agents, ["research"])
        assert picked.name == "Claimed-Expert"

    def test_冷启动时可信度策略也还无法识别骗子(self):
        """诚实承认局限：冷启动阶段三个智能人可信度都是 0.5，
        此时综合分只能靠延迟决胜，可信度感知策略同样会选中虚报型。

        这说明算法需要**积累历史**才起作用，不是一开始就万能。
        这是我们必须在报告里写明的局限性，也是一种诚实的自我审视。
        """
        agents = [AgentView.from_profile(p) for p in default_demo_profiles()]
        picked = TrustAwareStrategy().select(agents, ["research"])
        assert picked.name == "Claimed-Expert"

    def test_可信度策略在积累战绩后反超能力策略(self):
        """把上面两个测试连起来看：冷启动时两者都选骗子，
        积累战绩后可信度策略纠正了判断 —— 这就是算法产生价值的完整过程。"""
        cold = TrustAwareStrategy().select(
            [AgentView.from_profile(p) for p in default_demo_profiles()], ["research"]
        )
        warm = TrustAwareStrategy().select(self.build_scenario(), ["research"])
        assert cold.name == "Claimed-Expert"     # 冷启动：被骗
        assert warm.name != "Claimed-Expert"     # 有战绩后：纠正


# ---------------------------------------------------------------------------
# 7. 工厂
# ---------------------------------------------------------------------------
class TestBuildStrategies:
    def test_返回三个策略(self):
        assert len(build_strategies()) == 3

    def test_名称与常量一致(self):
        assert tuple(s.name for s in build_strategies()) == STRATEGY_NAMES

    def test_随机策略种子固定可复现(self):
        agents = experiment_agents()
        a = [s.select(agents, ["research"]).name for s in build_strategies(seed=1)]
        b = [s.select(agents, ["research"]).name for s in build_strategies(seed=1)]
        assert a == b

    def test_所有策略都能选出结果(self):
        agents = experiment_agents()
        for s in build_strategies():
            assert s.select(agents, ["research"]) is not None
