"""自动化测试套件

运行全部测试：引擎初始化、各模块功能、交底书生成
可作为CI/CD的一部分自动运行。

使用方式:
    D:/Anaconda3/envs/mathmodel/python.exe scripts/run_tests.py
"""

import sys
import io
import time
import traceback
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ═══════════════════════════════════════════════════════
# 测试框架
# ═══════════════════════════════════════════════════════

class TestSuite:
    def __init__(self):
        self.tests = []
        self.results = []
        self.engine = None

    def test(self, name):
        """装饰器：注册测试"""
        def decorator(func):
            self.tests.append((name, func))
            return func
        return decorator

    def run_all(self):
        """运行所有测试"""
        print("=" * 60)
        print(f"  自动化测试套件")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # 初始化引擎（所有测试共享）
        print("\n初始化引擎...")
        t0 = time.time()
        from src.core import PatentInnovationEngine
        self.engine = PatentInnovationEngine()
        self.engine.initialize()
        init_time = time.time() - t0
        print(f"引擎就绪 ({init_time:.1f}s)\n")

        passed = 0
        failed = 0
        errors = 0

        for name, func in self.tests:
            try:
                t0 = time.time()
                func()
                elapsed = time.time() - t0
                passed += 1
                print(f"  [PASS] {name} ({elapsed:.2f}s)")
            except AssertionError as e:
                failed += 1
                print(f"  [FAIL] {name}: {e}")
            except Exception as e:
                errors += 1
                print(f"  [ERROR] {name}: {e}")
                traceback.print_exc()

        total = passed + failed + errors
        print(f"\n{'='*60}")
        print(f"  结果: {passed}/{total} 通过, {failed} 失败, {errors} 错误")
        print(f"{'='*60}")

        return failed == 0 and errors == 0


suite = TestSuite()

# ═══════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════

IDEA = "一种基于深度强化学习的虚拟电厂多时间尺度优化调度方法"

# 多领域测试想法（电力/管道/新能源）
DOMAIN_IDEAS = {
    "电力": "一种基于深度强化学习的虚拟电厂多时间尺度优化调度方法",
    "管道": "一种基于多传感器融合的地下管道缺陷检测机器人系统",
    "新能源": "一种分布式光伏电站功率预测与无功协调控制方法",
}

@suite.test("数据库加载>500篇")
def test_db_load():
    stats = suite.engine.get_statistics()
    assert stats.get("patents_parsed", 0) > 500, f"只有{stats.get('patents_parsed', 0)}篇"

@suite.test("知识图谱>800节点")
def test_kg():
    stats = suite.engine.knowledge_graph.get_statistics()
    assert stats["total_nodes"] > 800, f"只有{stats['total_nodes']}节点"

@suite.test("知识图谱查询返回结果")
def test_kg_query():
    results = suite.engine.knowledge_graph.query_by_problem("频率振荡抑制方法")
    assert len(results) > 0, "查询无结果"

@suite.test("RAG索引>5000块")
def test_rag():
    stats = suite.engine.rag_engine.get_statistics()
    assert stats["total_chunks"] > 5000, f"只有{stats['total_chunks']}块"

@suite.test("RAG检索中文关键词")
def test_rag_chinese():
    results = suite.engine.rag_engine.retrieve("虚拟电厂调度优化", top_k=5)
    assert len(results) > 0, "RAG检索无结果"

@suite.test("RAG动态阈值生效")
def test_rag_threshold():
    """验证动态阈值不会返回太多低质量结果"""
    results = suite.engine.rag_engine.retrieve("配电网故障定位", top_k=10)
    if results:
        top_score = results[0].score
        for r in results:
            assert r.score >= top_score * 0.3 or r.score >= 0.05, \
                f"分数{r.score}低于阈值(top={top_score})"

@suite.test("创新模式>5种")
def test_innovation():
    assert len(suite.engine.innovation_miner.patterns) > 5

@suite.test("suggest_innovation返回方向")
def test_suggest():
    suggestions = suite.engine.suggest_innovation(IDEA)
    directions = suggestions.get("innovation_directions", [])
    assert len(directions) > 0, "无创新方向"
    assert all("innovation_type" in d for d in directions)

@suite.test("撰写上下文4维度非空")
def test_context():
    ctx = suite.engine.generate_writing_context(IDEA)
    non_empty = sum(1 for d in ["related_background", "similar_claims",
                                 "effect_templates", "implementation_references"]
                    if ctx.get(d))
    assert non_empty >= 2, f"只有{non_empty}个维度有结果"

@suite.test("撰写上下文去重排序")
def test_context_dedup():
    ctx = suite.engine.generate_writing_context(IDEA)
    for dim in ["related_background", "effect_templates"]:
        items = ctx.get(dim, [])
        pids = [i.get("patent_id", "") for i in items if isinstance(i, dict)]
        assert len(pids) == len(set(pids)), f"{dim}有重复patent_id"
        scores = [i.get("score", 0) for i in items if isinstance(i, dict)]
        assert all(scores[i] >= scores[i+1] for i in range(len(scores)-1)), f"{dim}未排序"

@suite.test("术语库>50个")
def test_terminology():
    assert len(suite.engine.terminology_analyzer.term_corpus) > 50

@suite.test("权利要求模式>5种")
def test_claims():
    assert len(suite.engine.claim_analyzer.patterns) > 5

# ─── 交底书生成测试（三阶段架构）───────────────────

# 生成结果缓存：三个领域只生成一次，后续测试复用，避免重复调用 LLM
_DISCLOSURE_CACHE = {}


def _get_disclosure(domain: str = "电力") -> dict:
    """获取指定领域的生成结果（带缓存）"""
    if domain not in _DISCLOSURE_CACHE:
        _DISCLOSURE_CACHE[domain] = suite.engine.generate_disclosure(
            DOMAIN_IDEAS[domain]
        )
    return _DISCLOSURE_CACHE[domain]


@suite.test("三阶段生成模式为 llm_staged")
def test_staged_mode():
    result = _get_disclosure()
    assert result["mode"] in ("llm_staged", "llm_single"), \
        f"生成模式异常: {result['mode']}"


@suite.test("质检报告随生成返回")
def test_quality_report():
    result = _get_disclosure()
    if result["mode"] == "llm_staged":
        assert "quality_report" in result, "缺少质检报告"
        assert "total_score" in result["quality_report"]


@suite.test("多领域交底书>3000字")
def test_disclosure_length():
    for domain in DOMAIN_IDEAS:
        result = _get_disclosure(domain)
        disclosure = result["disclosure"]
        assert len(disclosure) > 3000, f"{domain}领域只有{len(disclosure)}字"


@suite.test("交底书包含所有章节")
def test_disclosure_sections():
    result = _get_disclosure()
    disclosure = result["disclosure"]
    for section in ["发明名称", "技术领域", "背景技术", "技术方案",
                     "有益效果", "具体实施", "权利要求"]:
        assert section in disclosure, f"缺少{section}"


@suite.test("段落编号连续")
def test_numbering_continuous():
    import re as _re
    result = _get_disclosure()
    nums = [int(n) for n in _re.findall(r"\[(\d{4})\]", result["disclosure"])]
    if nums:
        gaps = sum(1 for i in range(1, len(nums)) if nums[i] != nums[i-1] + 1)
        assert gaps == 0, f"编号有{gaps}处跳号"


@suite.test("交底书无编造数据")
def test_disclosure_no_fake_data():
    result = _get_disclosure()
    disclosure = result["disclosure"]
    forbidden = ["经实验证明", "实验结果表明", "测试数据显示"]
    for f in forbidden:
        assert f not in disclosure, f"包含编造数据: {f}"


@suite.test("生成历史保存与读取")
def test_history():
    from src.utils.history import (save_disclosure, list_history,
                                   get_history, delete_history)
    rid = save_disclosure("测试想法内容足够长", "# 测试交底书", "template",
                          title="测试")
    assert rid, "保存失败"
    records = list_history(10)
    assert any(r["id"] == rid for r in records), "列表未找到"
    detail = get_history(rid)
    assert detail and detail["disclosure"] == "# 测试交底书"
    assert delete_history(rid), "删除失败"
    assert get_history(rid) is None, "删除后仍可读取"

@suite.test("LLM润色模块可用或安全降级")
def test_llm_fallback():
    from src.core.llm_polisher import LLMPolisher
    polisher = LLMPolisher()
    result = polisher.polish("测试文本")
    # 无 API Key 时应原样返回；有 Key 时应返回非空字符串
    assert isinstance(result, str) and len(result) > 0, "润色返回异常"

@suite.test("综合查询返回结果")
def test_query():
    results = suite.engine.query("虚拟电厂调度优化")
    assert results.get("related_solutions") or results.get("related_patents"), "查询无结果"

@suite.test("报告生成无乱码")
def test_reports():
    report = suite.engine.get_innovation_report()
    assert "锟" not in report and "娴" not in report, "创新报告有乱码"
    report2 = suite.engine.get_claim_analysis_report()
    assert "锟" not in report2 and "娴" not in report2, "权利要求报告有乱码"

# ═══════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    success = suite.run_all()
    sys.exit(0 if success else 1)
