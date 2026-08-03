"""
专利创新学习引擎 - 核心分析模块

统一的入口接口，整合所有分析能力:
- 专利文本解析 (parsers/)
- 知识图谱构建与查询 (knowledge_graph)
- 创新模式挖掘 (innovation_miner)
- 权利要求结构分析 (claim_analyzer)
- 术语使用分析 (terminology_analyzer)
- RAG检索增强生成 (rag_engine)
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from .database_loader import DatabaseLoader
from .knowledge_graph import KnowledgeGraph
from .innovation_miner import InnovationMiner, InnovationType
from .claim_analyzer import ClaimAnalyzer
from .terminology_analyzer import TerminologyAnalyzer
from .rag_engine import RAGEngine
from .disclosure_generator import DisclosureGenerator
from .quality_reviewer import QualityReviewer
from .llm_polisher import LLMPolisher

from src.parsers.patent_parser import PatentParser, StructuredPatent


class PatentInnovationEngine:
    """专利创新学习引擎——核心分析入口

    整合所有分析模块，提供统一的分析和查询接口。

    使用方式:
        engine = PatentInnovationEngine()
        engine.initialize()  # 首次运行或数据更新后调用

        # 查询
        solutions = engine.query("频率振荡的抑制方法")
        suggestions = engine.suggest_innovation("虚拟电厂调频优化")

        # 生成撰写上下文
        context = engine.generate_writing_context("光伏功率预测方法")
    """

    def __init__(self,
                 db_path: str = "data/patent_database",
                 config_dir: str = "config"):
        """初始化引擎

        Args:
            db_path: 专利数据库目录
            config_dir: 配置目录
        """
        self.db_path = Path(db_path)
        self.config_dir = Path(config_dir)

        # 组件
        self.db_loader = DatabaseLoader(str(db_path), str(config_dir))
        self.patent_parser = PatentParser(str(db_path), str(self.config_dir / "terminology"))
        self.knowledge_graph = KnowledgeGraph(str(Path("data") / "knowledge_graph"))
        self.innovation_miner = InnovationMiner()
        self.claim_analyzer = ClaimAnalyzer()
        self.terminology_analyzer = TerminologyAnalyzer(self.db_loader)
        self.rag_engine = RAGEngine(str(Path("data") / "rag_index"))

        # 状态
        self.patents: List[StructuredPatent] = []
        self.is_initialized = False
        self._init_stats = {}

    def initialize(self, force_rebuild: bool = False):
        """初始化引擎：解析专利、构建知识图谱和RAG索引

        首次使用或数据库更新后调用。如果已初始化且数据未变化，跳过重建。

        Args:
            force_rebuild: 强制重建所有分析结果
        """
        print("=" * 50)
        print("专利创新学习引擎初始化")
        print(f"时间: {datetime.now().isoformat()}")
        print("=" * 50)

        # 1. 重新加载数据库
        self.db_loader.reload_index()
        self.patent_parser.reload_database()

        # 2. 解析所有完整专利
        print("\n[1/5] 解析专利文本...")
        self.patents = self.patent_parser.parse_all_full_text()
        stats = self.patent_parser.get_parse_statistics(self.patents)
        print(f"  解析完成: {stats['fully_parsed']}/{stats['total']}篇")
        if stats['with_errors'] > 0:
            print(f"  警告: {stats['with_errors']}篇有解析错误")

        # 3. 构建知识图谱
        print("\n[2/5] 构建知识图谱...")
        self.knowledge_graph.build_from_patents(self.patents)
        kg_stats = self.knowledge_graph.get_statistics()
        print(f"  图谱: {kg_stats['total_nodes']}节点, {kg_stats['total_edges']}边")
        self.knowledge_graph.save()

        # 4. 挖掘创新模式
        print("\n[3/5] 挖掘创新模式...")
        mine_result = self.innovation_miner.mine(self.patents)
        print(f"  发现{mine_result['patterns_identified']}种创新模式")
        print(f"  类型分布: {mine_result['type_distribution']}")

        # 5. 构建术语语料库和分析权利要求
        print("\n[4/5] 构建术语语料库和分析权利要求...")
        self.terminology_analyzer.build_corpus(self.patents)
        self.claim_analyzer.analyze(self.patents)
        print(f"  术语语料: {len(self.terminology_analyzer.term_corpus)}个术语")
        print(f"  权利要求模式: {len(self.claim_analyzer.patterns)}种")

        # 6. 构建RAG索引（增量：索引已覆盖全部专利时直接加载）
        print("\n[5/5] 构建RAG索引...")
        patent_ids = {p.patent_id for p in self.patents}
        if not force_rebuild and not self.rag_engine.is_index_stale(patent_ids):
            self.rag_engine.load_index()
            print("  增量模式: 索引未过期，直接加载已有索引")
        else:
            self.rag_engine.build_index(self.patents)
            self.rag_engine.save_index()
        rag_stats = self.rag_engine.get_statistics()
        print(f"  索引: {rag_stats['total_chunks']}个文档块")

        self.is_initialized = True
        self._init_stats = {
            "patents_analyzed": stats['fully_parsed'],
            "kg_nodes": kg_stats['total_nodes'],
            "kg_edges": kg_stats['total_edges'],
            "innovation_patterns": mine_result['patterns_identified'],
            "rag_chunks": rag_stats['total_chunks'],
        }

        print(f"\n初始化完成! {self.get_summary()}")

    # ═══════════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════════

    def query(self, problem_description: str, top_k: int = 5) -> Dict:
        """综合查询：根据技术问题返回相关方案、专利和参考内容

        Args:
            problem_description: 技术问题描述
            top_k: 每类结果数量

        Returns:
            综合查询结果
        """
        if not self.is_initialized:
            return {"error": "引擎未初始化，请先调用 initialize()"}

        results = {
            "query": problem_description,
            "domain": self.innovation_miner._identify_domain(problem_description),
            "related_solutions": [],
            "similar_problems": [],
            "related_patents": [],
            "effect_references": [],
        }

        # 从知识图谱查询
        kg_solutions = self.knowledge_graph.query_by_problem(
            problem_description, top_k=top_k
        )
        results["related_solutions"] = kg_solutions

        # 从RAG检索相关背景技术
        rag_bg = self.rag_engine.retrieve_by_problem(problem_description, top_k=top_k)
        results["similar_problems"] = [r.to_dict() for r in rag_bg]

        # 从RAG检索相关专利
        rag_results = self.rag_engine.retrieve(problem_description, top_k=top_k)
        results["related_patents"] = [
            {"patent_id": r.chunk.patent_id,
             "text": r.chunk.text[:200],
             "score": r.score}
            for r in rag_results
        ]

        return results

    def suggest_innovation(self, idea: str) -> Dict:
        """为初步想法建议创新方向

        结合创新模式挖掘结果和术语分析提供建议。

        Args:
            idea: 用户的技术想法描述

        Returns:
            创新建议
        """
        if not self.is_initialized:
            return {"error": "引擎未初始化，请先调用 initialize()"}

        # 从创新模式挖掘器获取方向建议
        direction = self.innovation_miner.suggest_innovation_direction(idea)

        # 补充术语建议
        term_recs = []
        for word in idea.replace("，", " ").replace("、", " ").split():
            word = word.strip()
            if len(word) >= 2:
                rec = self.terminology_analyzer.recommend_terminology(word)
                if rec.get("issue_type") != "unknown":
                    term_recs.append(rec)

        direction["terminology_recommendations"] = term_recs[:5]

        return direction

    def recommend_claim_structure(self, innovation_type: str,
                                 tech_features: List[str] = None) -> Dict:
        """推荐权利要求结构

        Args:
            innovation_type: 创新类型
            tech_features: 技术特征列表

        Returns:
            权利要求结构建议
        """
        return self.claim_analyzer.recommend_claim_structure(
            innovation_type, tech_features
        )

    def generate_writing_context(self, topic: str) -> Dict:
        """生成撰写参考上下文

        从RAG引擎获取多维度的撰写参考。

        Args:
            topic: 撰写主题/技术方向

        Returns:
            撰写参考上下文
        """
        if not self.is_initialized:
            return {"error": "引擎未初始化，请先调用 initialize()"}

        # RAG 文本上下文
        context = self.rag_engine.generate_writing_context(topic)

        # 叠加知识图谱的结构化上下文（问题→方案→效果 关联 + 替代方案）
        try:
            context["graph_solutions"] = self.knowledge_graph.query_by_problem(
                topic, top_k=3
            )
            context["graph_alternatives"] = self.knowledge_graph.find_alternative_solutions(
                topic, top_k=3
            )
        except Exception as e:
            print(f"[图谱上下文] 失败: {e}")
            context["graph_solutions"] = []
            context["graph_alternatives"] = []

        return context

    def get_terminology_guidance(self, tech_concept: str) -> Dict:
        """获取术语使用指导

        Args:
            tech_concept: 技术概念

        Returns:
            术语使用建议
        """
        return self.terminology_analyzer.recommend_terminology(tech_concept)

    def evaluate_claim_draft(self, draft_claims_text: str) -> Dict:
        """评估权利要求草稿质量

        使用ClaimsParser解析草稿并评估。

        Args:
            draft_claims_text: 权利要求草稿文本

        Returns:
            质量评估报告
        """
        from src.parsers.claims_parser import ClaimsParser
        cp = ClaimsParser()
        tree = cp.parse("DRAFT", draft_claims_text)
        return self.claim_analyzer.evaluate_claim_quality(tree)

    # ═══════════════════════════════════════════════════════════════
    # 报告生成
    # ═══════════════════════════════════════════════════════════════

    def generate_disclosure(self, idea: str, title: str = None,
                            fields: dict = None, polish: bool = False) -> dict:
        """根据想法生成技术交底书（三阶段：大纲→分章节→质检迭代）

        Args:
            idea: 技术想法描述
            title: 发明名称（可选）
            fields: 结构化输入 {tech_field, purpose, core_method, problems}
            polish: 是否使用LLM二次润色（仅模板模式下生效）

        Returns:
            {"disclosure": str, "mode": "llm_staged"|"llm_single"|"template",
             "quality_report": dict}  # quality_report 仅 llm_staged 模式有
        """
        if not self.is_initialized:
            return {"disclosure": "错误：引擎未初始化", "mode": "error"}

        generator = DisclosureGenerator(self)
        disclosure, mode = generator.generate(idea, title, fields)
        result = {"disclosure": disclosure, "mode": mode}

        # 阶段 3：分段模式自动质检迭代
        if mode == "llm_staged":
            try:
                disclosure, report = generator.iterate_quality(
                    disclosure, idea, generator._last_sections
                )
                result["disclosure"] = disclosure
                result["quality_report"] = report
            except Exception as e:
                print(f"[质检迭代] 失败，保留原稿: {e}")
        elif polish and mode == "template":
            polisher = LLMPolisher(str(self.config_dir / "api_config.json"))
            result["disclosure"] = polisher.polish(disclosure, idea)

        return result

    def review_quality(self, disclosure: str, idea: str) -> dict:
        """对生成的交底书进行质量审查

        Args:
            disclosure: 交底书全文
            idea: 原始技术想法

        Returns:
            质量报告 {total_score, grade, dimensions, patent_comparison, suggestions}
        """
        reviewer = QualityReviewer(self if self.is_initialized else None)
        return reviewer.review(disclosure, idea)

    def get_innovation_report(self) -> str:
        """获取创新洞察报告"""
        return self.innovation_miner.generate_innovation_report()

    def get_claim_analysis_report(self) -> str:
        """获取权利要求分析报告"""
        return self.claim_analyzer.get_analysis_report()

    def get_terminology_report(self) -> str:
        """获取术语分析报告"""
        return self.terminology_analyzer.get_analysis_report()

    def get_summary(self) -> str:
        """获取引擎状态摘要"""
        if not self.is_initialized:
            return "引擎未初始化"

        s = self._init_stats
        return (f"已分析{s.get('patents_analyzed', 0)}篇专利 | "
                f"知识图谱{s.get('kg_nodes', 0)}节点/{s.get('kg_edges', 0)}边 | "
                f"创新模式{s.get('innovation_patterns', 0)}种 | "
                f"RAG索引{s.get('rag_chunks', 0)}块")

    def get_statistics(self) -> Dict:
        """获取引擎完整统计信息"""
        stats = {
            "initialized": self.is_initialized,
            "database": self.db_loader.get_statistics(),
            "patents_parsed": len(self.patents),
        }

        if self.is_initialized:
            stats["knowledge_graph"] = self.knowledge_graph.get_statistics()
            stats["rag_index"] = self.rag_engine.get_statistics()

        return stats
