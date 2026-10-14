"""实验运行器的测试。

这一组要保证的是"实验本身可信"：
  1. 可复现   —— 同样参数跑两遍，数字必须一模一样
  2. 公平性   —— 三个策略必须从同样的起点出发
  3. 指标正确 —— 统计口径不能算错（算错了结论就全错）
  4. 产物完整 —— CSV / JSON 能正常生成且内容正确
"""
import csv
import json
from pathlib import Path

import pytest

from app.experiment import (
    EARLY_PHASE_ROUNDS,
    ExperimentConfig,
    RoundRecord,
    aggregate_metrics,
    build_success_curves,
    format_summary_table,
    metadata_to_json,
    records_to_csv,
    run_experiment,
    run_single_trial,
    save_all,
    summary_to_csv,
)
from app.strategies import STRATEGY_NAMES


def small_config(**overrides):
    """小规模配置，让测试跑得快。"""
    params = dict(rounds=20, seed=42, trials=2, required_capabilities=["research"])
    params.update(overrides)
    return ExperimentConfig(**params)


# ---------------------------------------------------------------------------
# 1. 可复现性
# ---------------------------------------------------------------------------
class TestReproducibility:
    def test_相同参数产生完全相同的结果(self):
        a = run_experiment(small_config())
        b = run_experiment(small_config())

        assert len(a.records) == len(b.records)
        for ra, rb in zip(a.records, b.records):
            assert ra == rb

    def test_相同种子指标完全一致(self):
        a = run_experiment(small_config())
        b = run_experiment(small_config())
        for name in a.metrics:
            assert a.metrics[name].task_success_rate == b.metrics[name].task_success_rate
            assert (
                a.metrics[name].deceptive_selection_count
                == b.metrics[name].deceptive_selection_count
            )

    def test_不同种子结果不同(self):
        a = run_experiment(small_config(seed=1))
        b = run_experiment(small_config(seed=2))
        assert [r.selected_agent for r in a.records] != [
            r.selected_agent for r in b.records
        ]

    def test_单次试验也满足可复现(self):
        cfg = small_config(trials=1)
        a = run_single_trial(cfg, trial=0, strategy_seed=999)
        b = run_single_trial(cfg, trial=0, strategy_seed=999)
        assert a == b

    def test_曲线也可复现(self):
        a = run_experiment(small_config())
        b = run_experiment(small_config())
        assert a.success_curve == b.success_curve


# ---------------------------------------------------------------------------
# 2. 公平性 —— 三个策略必须同起点
# ---------------------------------------------------------------------------
class TestFairness:
    def test_每个策略轮数相同(self):
        result = run_experiment(small_config())
        counts = {name: 0 for name in STRATEGY_NAMES}
        for r in result.records:
            counts[r.strategy] += 1
        assert len(set(counts.values())) == 1
        assert counts["random"] == 20 * 2   # rounds × trials

    def test_三个策略都从零战绩开始(self):
        """第 0 轮做决策时，被选中智能体的战绩必须是 0 胜 0 负。

        这证明每个策略拿到的都是全新副本，而不是被别人跑过的世界。
        """
        records = run_single_trial(small_config(trials=1), trial=0, strategy_seed=1)
        first_round = [r for r in records if r.round_index == 0]
        assert len(first_round) == 3

        for r in first_round:
            # 执行前的战绩 = 执行后的战绩减去这一次
            before_total = (r.agent_successes + r.agent_failures) - 1
            assert before_total == 0, (
                f"{r.strategy} 在第 0 轮时智能体已有 {before_total} 次战绩，"
                "说明没有从冷启动开始"
            )

    def test_三个策略面对同一组智能体名字(self):
        records = run_single_trial(small_config(trials=1), trial=0, strategy_seed=1)
        names = {r.selected_agent for r in records}
        assert names <= {"Reliable-Researcher", "Fast-Generalist", "Claimed-Expert"}

    def test_每个策略都有独立的智能体副本(self):
        """如果共用副本，先跑的策略会让后跑的策略看到不同的战绩。

        验证方式：三个策略在第 0 轮看到的智能体战绩必须都是 0（见上一个测试），
        同时整个实验里每个策略各自的累计决策数相同。
        """
        result = run_experiment(small_config())
        curves = result.success_curve
        assert all(len(curve) == 20 * 2 for curve in curves.values())


# ---------------------------------------------------------------------------
# 3. 指标统计口径
# ---------------------------------------------------------------------------
def make_record(**overrides) -> RoundRecord:
    params = dict(
        trial=0, strategy="random", round_index=0, selected_agent="A",
        deceptive_selected=False, success=True, latency_ms=100.0,
        trust_at_decision=0.5, agent_successes=1, agent_failures=0,
        market_avg_trust=0.5,
    )
    params.update(overrides)
    return RoundRecord(**params)


class TestMetrics:
    def test_任务成功率(self):
        rows = [make_record(success=True)] * 7 + [make_record(success=False)] * 3
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.task_success_rate == pytest.approx(0.7)
        assert m.success_count == 7
        assert m.failure_count == 3

    def test_欺骗被选中率(self):
        rows = [make_record(deceptive_selected=True)] * 4 + [make_record()] * 6
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.deceptive_selection_rate == pytest.approx(0.4)
        assert m.deceptive_selection_count == 4

    def test_从没选中过虚报型(self):
        rows = [make_record()] * 10
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.never_selected_deceptive is True
        assert m.recovery_round is None

    def test_前期后期被骗率分开统计(self):
        # 前 EARLY_PHASE_ROUNDS 轮：2 次选中虚报型
        early = [make_record(round_index=i, deceptive_selected=i < 2)
                 for i in range(EARLY_PHASE_ROUNDS)]
        # 之后 10 轮：全都没选中
        late = [make_record(round_index=EARLY_PHASE_ROUNDS + i, deceptive_selected=False)
                for i in range(10)]
        m = aggregate_metrics(early + late, small_config())["random"]

        assert m.early_rounds == EARLY_PHASE_ROUNDS
        assert m.late_rounds == 10
        assert m.early_deceptive_rate == pytest.approx(2 / EARLY_PHASE_ROUNDS)
        assert m.late_deceptive_rate == pytest.approx(0.0)

    def test_恢复轮次是最后一次被骗的下一轮(self):
        rows = [make_record(round_index=0, deceptive_selected=True),
                make_record(round_index=1, deceptive_selected=True),
                make_record(round_index=2, deceptive_selected=False),
                make_record(round_index=3, deceptive_selected=False)]
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.recovery_round == 2   # 最后一次被骗是第 1 轮，所以第 2 轮起恢复

    def test_平均延迟只统计真正执行了的轮次(self):
        """弃权轮（延迟为 0）不应拉低平均延迟。"""
        rows = [make_record(latency_ms=100), make_record(latency_ms=300),
                make_record(latency_ms=0.0)]
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.avg_latency_ms == pytest.approx(200)

    def test_选择分布统计(self):
        rows = [make_record(selected_agent="A")] * 3 + [make_record(selected_agent="B")] * 2
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.selections_per_agent == {"A": 3, "B": 2}

    def test_每个智能体的成功率(self):
        rows = [
            make_record(selected_agent="A", success=True),
            make_record(selected_agent="A", success=False),
            make_record(selected_agent="B", success=True),
        ]
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.success_rate_per_agent["A"] == pytest.approx(0.5)
        assert m.success_rate_per_agent["B"] == pytest.approx(1.0)

    def test_弃权轮不计入智能人选择分布(self):
        """没人能胜任任务时，不能凭空冒出一个叫 <无人胜任> 的"智能体"。

        这类占位记录如果混进选择分布，会污染"欺骗智能体被选中比例"等指标。
        """
        rows = [make_record(selected_agent="<无人胜任>", success=False, latency_ms=0.0)]
        m = aggregate_metrics(rows, small_config())["random"]

        assert m.selections_per_agent == {}
        assert m.abstention_count == 1
        assert m.final_trust_scores == {}

    def test_弃权轮仍计为任务失败(self):
        """口径一致性：对用户来说任务确实没完成，弃权不能算成功。

        如果弃权不计入分母，弃权多的策略会显得成功率虚高。
        """
        rows = [make_record(selected_agent="<无人胜任>", success=False, latency_ms=0.0),
                make_record(selected_agent="A", success=True)]
        m = aggregate_metrics(rows, small_config())["random"]
        assert m.task_success_rate == pytest.approx(0.5)   # 2 轮里成功 1 轮
        assert m.abstention_count == 1
        assert m.selections_per_agent == {"A": 1}

    def test_多策略分开统计(self):
        rows = [make_record(strategy="random"), make_record(strategy="trust_aware")]
        metrics = aggregate_metrics(rows, small_config())
        assert set(metrics) == {"random", "trust_aware"}
        assert metrics["random"].total_rounds == 1

    def test_汇总行字段完整(self):
        m = aggregate_metrics([make_record()], small_config())["random"]
        row = m.to_row()
        for key in ("strategy", "task_success_rate", "deceptive_selection_rate",
                    "early_deceptive_rate", "late_deceptive_rate", "avg_latency_ms"):
            assert key in row

    def test_空输入不会崩溃(self):
        assert aggregate_metrics([], small_config()) == {}


class TestSuccessCurve:
    def test_累计成功率曲线(self):
        rows = [make_record(round_index=0, success=True),
                make_record(round_index=1, success=False),
                make_record(round_index=2, success=True),
                make_record(round_index=3, success=True)]
        curves = build_success_curves(rows, small_config())
        assert curves["random"] == pytest.approx([1.0, 0.5, 2 / 3, 0.75])

    def test_曲线长度等于总轮数(self):
        result = run_experiment(small_config())
        for curve in result.success_curve.values():
            assert len(curve) == 20 * 2

    def test_曲线是单调不减的分子决定的(self):
        """累计成功率的分母递增，所以数值一定在 0~1 之间。"""
        result = run_experiment(small_config())
        for curve in result.success_curve.values():
            assert all(0.0 <= v <= 1.0 for v in curve)


# ---------------------------------------------------------------------------
# 4. 参数校验
# ---------------------------------------------------------------------------
class TestConfigValidation:
    @pytest.mark.parametrize("bad_rounds", [0, -1])
    def test_非法轮数被拒绝(self, bad_rounds):
        with pytest.raises(ValueError, match="rounds"):
            run_experiment(small_config(rounds=bad_rounds))

    @pytest.mark.parametrize("bad_trials", [0, -1])
    def test_非法试验次数被拒绝(self, bad_trials):
        with pytest.raises(ValueError, match="trials"):
            run_experiment(small_config(trials=bad_trials))

    def test_配置能转成字典(self):
        d = small_config().to_dict()
        assert d["rounds_per_trial"] == 20
        assert "scoring_weights" in d


# ---------------------------------------------------------------------------
# 5. 结果文件
# ---------------------------------------------------------------------------
class TestOutputFiles:
    def test_逐轮CSV能正常写入并读回(self, tmp_path):
        result = run_experiment(small_config(trials=1))
        path = records_to_csv(result.records, tmp_path / "rounds.csv")

        assert path.exists()
        with path.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == len(result.records)
        assert set(rows[0]) == set(RoundRecord.__dataclass_fields__.keys())

    def test_汇总CSV每个策略一行(self, tmp_path):
        result = run_experiment(small_config())
        path = summary_to_csv(result, tmp_path / "summary.csv")

        with path.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == len(STRATEGY_NAMES)
        assert {r["strategy"] for r in rows} == set(STRATEGY_NAMES)

    def test_JSON包含完整实验参数(self, tmp_path):
        config = small_config(rounds=15, seed=7, trials=3)
        result = run_experiment(config)
        path = metadata_to_json(result, tmp_path / "meta.json")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["config"]["seed"] == 7
        assert data["config"]["rounds_per_trial"] == 15
        assert data["config"]["trials"] == 3
        assert data["config"]["required_capabilities"] == ["research"]

    def test_JSON记录了智能体设定和已知局限(self, tmp_path):
        result = run_experiment(small_config())
        path = metadata_to_json(result, tmp_path / "meta.json")
        data = json.loads(path.read_text(encoding="utf-8"))

        assert len(data["agent_profiles"]) == 3
        liar = next(p for p in data["agent_profiles"] if p["is_deceptive"])
        assert liar["claimed_success_rate"] > liar["true_success_rate"]

        # 已知局限必须被写进文件，不能只留在代码注释里
        assert len(data["limitations"]) >= 3
        assert any("能力" in x for x in data["limitations"])

    def test_保存全部产物(self, tmp_path):
        result = run_experiment(small_config())
        outputs = save_all(result, tmp_path, "run1")
        for key, path in outputs.items():
            assert path.exists(), f"{key} 未生成"
        assert outputs["rounds"].name == "run1_rounds.csv"

    def test_目录不存在时自动创建(self, tmp_path):
        result = run_experiment(small_config())
        nested = tmp_path / "a" / "b" / "c"
        save_all(result, nested, "run1")
        assert nested.exists()

    def test_中文不乱码(self, tmp_path):
        """CSV 用 utf-8-sig 编码，Excel 打开中文才正常。"""
        result = run_experiment(small_config())
        path = summary_to_csv(result, tmp_path / "s.csv")
        text = path.read_text(encoding="utf-8-sig")
        assert "strategy" in text   # 表头可读
        assert "\ufffd" not in text  # 没有替换字符（乱码标志）


# ---------------------------------------------------------------------------
# 6. 打印格式
# ---------------------------------------------------------------------------
class TestFormatting:
    def test_表格包含所有策略(self):
        result = run_experiment(small_config())
        text = format_summary_table(result)
        for label in ("随机选择", "仅能力匹配", "可信度感知"):
            assert label in text

    def test_表格标出总决策数(self):
        result = run_experiment(small_config())
        text = format_summary_table(result)
        assert str(result.total_decisions) in text
        assert result.total_decisions == 20 * 2 * 3


# ---------------------------------------------------------------------------
# 7. 端到端：真的能得出结论吗
# ---------------------------------------------------------------------------
class TestEndToEndFindings:
    """这一组验证实验能稳定复现出核心结论。

    注意：这里断言的是"可信度感知策略明显优于另一个基线"，
    而不是硬编码某个具体百分比 —— 具体数字会随参数变化，
    写死数字会让测试变得脆弱且在参数调整后失效。
    """

    def test_可信度感知的任务成功率明显高于仅能力匹配(self):
        result = run_experiment(ExperimentConfig(
            rounds=100, seed=42, trials=3, required_capabilities=["research"]
        ))
        trust = result.metrics["trust_aware"].task_success_rate
        cap = result.metrics["capability_only"].task_success_rate
        assert trust > cap + 0.3, f"可信度感知 {trust:.2%} 未明显超过仅能力匹配 {cap:.2%}"

    def test_可信度感知最少选中虚报型(self):
        result = run_experiment(ExperimentConfig(
            rounds=100, seed=42, trials=3, required_capabilities=["research"]
        ))
        rates = {n: m.deceptive_selection_rate for n, m in result.metrics.items()}
        assert rates["trust_aware"] == min(rates.values())
        assert rates["capability_only"] == max(rates.values())

    def test_仅能力匹配会一直选同一个最快但最差的(self):
        """解释"为什么仅能力匹配比随机还差"：
        三家能力打平后它只能靠延迟决胜，而虚报型延迟最低，于是每轮都选它。"""
        result = run_experiment(small_config(trials=1))
        m = result.metrics["capability_only"]
        assert m.selections_per_agent.get("Claimed-Expert", 0) == m.total_rounds

    def test_可信度感知后期几乎不再被骗(self):
        result = run_experiment(ExperimentConfig(
            rounds=100, seed=42, trials=3, required_capabilities=["research"]
        ))
        m = result.metrics["trust_aware"]
        assert m.late_deceptive_rate < 0.05

    def test_随机策略被骗比例约为三分之一(self):
        """三个智能人里一个骗子，随机选择的期望被骗率约 1/3。
        这验证了随机基线本身是正常工作的。"""
        result = run_experiment(ExperimentConfig(
            rounds=200, seed=42, trials=5, required_capabilities=["research"]
        ))
        rate = result.metrics["random"].deceptive_selection_rate
        assert rate == pytest.approx(1 / 3, abs=0.12)
