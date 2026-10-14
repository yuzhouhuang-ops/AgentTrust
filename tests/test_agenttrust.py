"""AgentTrust 自动化测试。

运行方式（在项目根目录 C:\\项目\\projects\\agenttrust 下）：
    .\\.venv\\Scripts\\python.exe -m pytest -v

测试分两部分：
  1. TestTrustScore / TestMatchScore / TestTotalScore
     —— 直接测算法函数，不需要经过 HTTP 接口，跑得最快，也最容易定位问题。
  2. TestAPIxxx
     —— 通过 TestClient 调用真实接口，验证接口之间的配合是否正确。
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app, match_score, total_score, trust_score

# TestClient 让我们不用真的启动服务器，就能发请求并拿到响应
client = TestClient(app)


# ---------------------------------------------------------------------------
# 准备工作：每个测试函数运行前，自动重置演示数据
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_demo_data():
    """autouse=True 表示每个测试都会自动执行，不用手动声明。

    为什么需要它？因为 app 里的 agents/history 是全局字典，
    如果不重置，前一个测试留下的数据会污染后一个测试，
    导致"单独跑能过、一起跑就失败"这种最难查的问题。
    """
    client.post("/demo/reset")
    yield  # yield 之前是准备，之后是收尾（这里不需要收尾）


def get_agents_by_name():
    """小工具：把 GET /agents 的结果整理成 {名字: 智能体} 的字典，方便取值。"""
    return {a["name"]: a for a in client.get("/agents").json()}


def discover(capabilities):
    """小工具：调用 /discover 并返回候选列表。"""
    resp = client.post(
        "/discover",
        json={"task_id": "task-test", "required_capabilities": capabilities},
    )
    assert resp.status_code == 200
    return resp.json()["candidates"]


# ---------------------------------------------------------------------------
# 第一部分：算法函数单元测试
# ---------------------------------------------------------------------------
class TestTrustScore:
    """可信度 = (成功次数 + 2) / (成功次数 + 失败次数 + 4)，即拉普拉斯平滑。"""

    def test_全新智能体初始可信度为0_5(self):
        """没有任何历史记录时，可信度应该是 0.5（既不盲信也不否定）。"""
        agent = {"successes": 0, "failures": 0}
        assert trust_score(agent) == pytest.approx(0.5)

    def test_全部成功时趋近1但小于1(self):
        agent = {"successes": 100, "failures": 0}
        score = trust_score(agent)
        assert score < 1.0          # 平滑的作用：永远不会给出满分
        assert score > 0.95         # 但样本多了就很接近 1

    def test_全部失败时趋近0但大于0(self):
        agent = {"successes": 0, "failures": 100}
        score = trust_score(agent)
        assert score > 0.0
        assert score < 0.05

    def test_新智能体样本少时更保守(self):
        """这是平滑最重要的意义：1 胜 0 负，不能等于 10 胜 0 负。"""
        few = trust_score({"successes": 1, "failures": 0})    # 3/5 = 0.6
        many = trust_score({"successes": 10, "failures": 0})  # 12/14 ≈ 0.857
        assert few < many

    @pytest.mark.parametrize(
        "successes,failures,expected",
        [
            (0, 0, 0.5),
            (8, 2, 10 / 14),
            (5, 3, 7 / 12),
            (1, 7, 3 / 12),
            (1, 0, 3 / 5),
        ],
    )
    def test_逐一手算核对(self, successes, failures, expected):
        """parametrize 会把这组数据展开成 5 个独立测试，每行一个用例。"""
        agent = {"successes": successes, "failures": failures}
        assert trust_score(agent) == pytest.approx(expected)

    def test_成功越多分数越高(self):
        """单调性：成功后分数必须上升，这是反馈闭环成立的前提。"""
        before = trust_score({"successes": 5, "failures": 5})
        after_win = trust_score({"successes": 6, "failures": 5})
        after_loss = trust_score({"successes": 5, "failures": 6})
        assert after_win > before > after_loss


class TestMatchScore:
    """能力匹配度 = 需求能力中被满足的比例。"""

    def test_完全匹配得1(self):
        agent = {"capabilities": ["research", "summarization"]}
        assert match_score(agent, ["research", "summarization"]) == pytest.approx(1.0)

    def test_部分匹配得一半(self):
        agent = {"capabilities": ["research"]}
        assert match_score(agent, ["research", "translation"]) == pytest.approx(0.5)

    def test_完全无关得0(self):
        agent = {"capabilities": ["research"]}
        assert match_score(agent, ["cooking"]) == pytest.approx(0.0)

    def test_大小写和空格不敏感(self):
        """真实输入经常带大小写和空格差异，这里验证做了归一化处理。"""
        agent = {"capabilities": ["  Research ", "SUMMARIZATION"]}
        assert match_score(agent, ["research", "summarization"]) == pytest.approx(1.0)

    def test_多余能力不加分(self):
        """智能体会的能力超过需求时，匹配度上限仍是 1，不能超过。"""
        agent = {"capabilities": ["research", "translation", "coding", "vision"]}
        assert match_score(agent, ["research"]) == pytest.approx(1.0)

    def test_空需求返回0而不是报错(self):
        """防御性测试：空列表做除数会崩溃，确认函数做了保护。"""
        agent = {"capabilities": ["research"]}
        assert match_score(agent, []) == 0.0
        assert match_score(agent, ["   "]) == 0.0


class TestTotalScore:
    """综合分 = 0.60*匹配度 + 0.30*可信度 + 0.10*延迟分。"""

    def test_三部分权重相加为1(self):
        """如果以后改权重，这个测试会提醒你重新核对配比。"""
        agent = {
            "capabilities": ["research"],
            "successes": 8,
            "failures": 2,
            "avg_latency_ms": 450,
        }
        expected = (
            0.60 * 1.0
            + 0.30 * (10 / 14)
            + 0.10 * (1000 / (1000 + 450))
        )
        assert total_score(agent, ["research"]) == pytest.approx(expected)

    def test_延迟越低延迟分越高(self):
        def score_with(latency):
            return total_score(
                {
                    "capabilities": ["research"],
                    "successes": 5,
                    "failures": 5,
                    "avg_latency_ms": latency,
                },
                ["research"],
            )

        assert score_with(100) > score_with(500) > score_with(2000)

    def test_延迟分不会超过0_1(self):
        """极低延迟也不能让延迟分突破它 10% 的权重上限。"""
        agent = {
            "capabilities": ["research"],
            "successes": 5,
            "failures": 5,
            "avg_latency_ms": 0.001,
        }
        base = 0.60 * 1.0 + 0.30 * trust_score(agent)
        assert total_score(agent, ["research"]) < base + 0.10 + 1e-9


# ---------------------------------------------------------------------------
# 第二部分：HTTP 接口测试
# ---------------------------------------------------------------------------
class TestHealthAndDemo:
    def test_健康检查(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["docs"] == "/docs"

    def test_重置后有三个演示智能体(self):
        agents = get_agents_by_name()
        assert set(agents) == {"Reliable-Researcher", "Fast-Generalist", "Claimed-Expert"}

    def test_重置后可信度符合手算结果(self):
        agents = get_agents_by_name()
        assert agents["Reliable-Researcher"]["trust_score"] == pytest.approx(10 / 14, abs=1e-4)
        assert agents["Fast-Generalist"]["trust_score"] == pytest.approx(7 / 12, abs=1e-4)
        assert agents["Claimed-Expert"]["trust_score"] == pytest.approx(3 / 12, abs=1e-4)

    def test_重置会清空历史记录(self):
        agents = get_agents_by_name()
        client.post(
            "/results",
            json={"agent_id": agents["Claimed-Expert"]["agent_id"],
                  "success": False, "latency_ms": 400},
        )
        assert len(client.get("/history").json()) == 1
        client.post("/demo/reset")  # 再次重置
        assert client.get("/history").json() == []


class TestDiscover:
    def test_返回全部能力匹配的候选(self):
        cands = discover(["research", "summarization"])
        assert len(cands) == 3   # 三个演示智能体都具备这两项能力

    def test_结果按分数降序排列(self):
        cands = discover(["research", "summarization"])
        scores = [c["score"] for c in cands]
        assert scores == sorted(scores, reverse=True)

    def test_可靠智能体排第一(self):
        cands = discover(["research", "summarization"])
        assert cands[0]["name"] == "Reliable-Researcher"

    def test_分数与手算一致(self):
        cands = {c["name"]: c for c in discover(["research", "summarization"])}
        expected = 0.60 * 1.0 + 0.30 * (10 / 14) + 0.10 * (1000 / 1450)
        assert cands["Reliable-Researcher"]["score"] == pytest.approx(expected, abs=1e-4)

    def test_无匹配能力时返回空列表(self):
        assert discover(["不存在的技能"]) == []

    def test_部分匹配的智能体也会入选(self):
        """只要求 coding 时，只有 Claimed-Expert 具备。"""
        cands = discover(["coding"])
        assert len(cands) == 1
        assert cands[0]["name"] == "Claimed-Expert"


class TestAntiDeception:
    """这一组是项目的核心卖点：系统不盲信智能体的自我声明。"""

    def test_虚报型智能体的可信度远低于其宣称值(self):
        agents = get_agents_by_name()
        claimed = agents["Claimed-Expert"]
        assert claimed["claimed_success_rate"] == pytest.approx(0.99)
        assert claimed["trust_score"] < 0.30   # 实际只有 1 胜 7 负

    def test_虚报型不会被排到第一(self):
        cands = discover(["research", "summarization"])
        assert cands[0]["name"] != "Claimed-Expert"

    def test_宣称成功率不参与打分(self):
        """把宣称值改成 0 或 1，综合分必须完全不变 —— 证明它被忽略了。"""
        agents = get_agents_by_name()
        target = agents["Claimed-Expert"]["agent_id"]

        before = {c["agent_id"]: c["score"] for c in discover(["research", "summarization"])}[target]

        # 通过接口无法直接改已注册智能体，这里直接改内存验证算法层行为
        from app.main import agents as agents_store

        agents_store[target]["claimed_success_rate"] = 0.0
        after_low = {
            c["agent_id"]: c["score"] for c in discover(["research", "summarization"])
        }[target]

        agents_store[target]["claimed_success_rate"] = 1.0
        after_high = {
            c["agent_id"]: c["score"] for c in discover(["research", "summarization"])
        }[target]

        assert before == after_low == after_high


class TestResults:
    def test_记录失败会降低可信度(self):
        target = get_agents_by_name()["Claimed-Expert"]
        resp = client.post(
            "/results",
            json={"agent_id": target["agent_id"], "success": False, "latency_ms": 400},
        )
        assert resp.status_code == 200
        # 1 胜 8 负 -> (1+2)/(1+8+4) = 3/13
        assert resp.json()["record"]["trust_score"] == pytest.approx(3 / 13, abs=1e-4)

    def test_记录成功会提高可信度(self):
        target = get_agents_by_name()["Claimed-Expert"]
        resp = client.post(
            "/results",
            json={"agent_id": target["agent_id"], "success": True, "latency_ms": 200},
        )
        # 2 胜 7 负 -> (2+2)/(2+7+4) = 4/13
        assert resp.json()["record"]["trust_score"] == pytest.approx(4 / 13, abs=1e-4)

    def test_失败后分数下降并影响排序(self):
        target = get_agents_by_name()["Claimed-Expert"]["agent_id"]
        before = {c["agent_id"]: c["score"] for c in discover(["research", "summarization"])}[target]

        client.post("/results", json={"agent_id": target, "success": False, "latency_ms": 500})

        after = {c["agent_id"]: c["score"] for c in discover(["research", "summarization"])}[target]
        assert after < before

    def test_平均延迟按累计均值更新(self):
        """Reliable-Researcher 初始 450ms、10 次历史，再记一次 950ms。
        新均值 = (450*10 + 950) / 11 = 495.45...
        """
        target = get_agents_by_name()["Reliable-Researcher"]
        assert target["avg_latency_ms"] == pytest.approx(450)

        resp = client.post(
            "/results",
            json={"agent_id": target["agent_id"], "success": True, "latency_ms": 950},
        )
        assert resp.status_code == 200

        updated = get_agents_by_name()["Reliable-Researcher"]
        assert updated["avg_latency_ms"] == pytest.approx((450 * 10 + 950) / 11)

    def test_未知智能体返回404(self):
        resp = client.post(
            "/results",
            json={"agent_id": "不存在的ID", "success": True, "latency_ms": 100},
        )
        assert resp.status_code == 404

    def test_历史记录按顺序累积(self):
        target = get_agents_by_name()["Fast-Generalist"]["agent_id"]
        for success in (True, False, True):
            client.post(
                "/results",
                json={"agent_id": target, "success": success, "latency_ms": 200},
            )
        history = client.get("/history").json()
        assert len(history) == 3
        assert [h["success"] for h in history] == [True, False, True]


class TestRegisterAgent:
    def test_注册新智能体初始可信度为0_5(self):
        resp = client.post(
            "/agents",
            json={"name": "Newcomer", "capabilities": ["research"],
                  "claimed_success_rate": 0.9, "avg_latency_ms": 300},
        )
        assert resp.status_code == 200
        assert resp.json()["trust_score"] == pytest.approx(0.5)

    def test_新智能体会被计入发现结果(self):
        client.post(
            "/agents",
            json={"name": "Newcomer", "capabilities": ["research"],
                  "claimed_success_rate": 0.9, "avg_latency_ms": 100},
        )
        names = [c["name"] for c in discover(["research", "summarization"])]
        assert "Newcomer" in names
        assert len(names) == 4


class TestInputValidation:
    """确认非法输入被 Pydantic 拦住并返回 422，而不是让服务器崩溃。"""

    @pytest.mark.parametrize(
        "payload",
        [
            {"task_id": "t", "required_capabilities": []},            # 空能力列表
            {"task_id": "t"},                                          # 缺字段
            {"required_capabilities": ["research"]},                   # 缺 task_id
        ],
    )
    def test_非法发现请求被拒绝(self, payload):
        assert client.post("/discover", json=payload).status_code == 422

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "", "capabilities": ["research"]},                # 空名字
            {"name": "x", "capabilities": []},                         # 无能力
            {"name": "x", "capabilities": ["a"], "claimed_success_rate": 1.5},  # 超出 0~1
            {"name": "x", "capabilities": ["a"], "avg_latency_ms": 0},          # 延迟须 > 0
            {"name": "x", "capabilities": ["a"], "avg_latency_ms": -5},         # 负数延迟
        ],
    )
    def test_非法注册请求被拒绝(self, payload):
        assert client.post("/agents", json=payload).status_code == 422

    def test_非法结果请求被拒绝(self):
        target = get_agents_by_name()["Claimed-Expert"]["agent_id"]
        resp = client.post(
            "/results",
            json={"agent_id": target, "success": True, "latency_ms": 0},
        )
        assert resp.status_code == 422   # latency_ms 必须 > 0
