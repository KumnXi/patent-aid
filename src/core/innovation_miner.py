"""
创新模式挖掘器

从授权专利中学习创新规律：识别创新类型、发现创新模式、
分析授权成功因素、为新想法建议创新方向。

核心能力:
1. 创新类型自动分类（8种类型）
2. 技术问题聚类（发现高频问题领域）
3. 解决方案策略归纳
4. 授权成功因素分析
5. 创新方向建议生成

数据真实性: 所有结论都附带 source_patents 证据追踪。
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import Counter
from enum import Enum

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans

from src.parsers.patent_parser import StructuredPatent, PatentParser
from src.core.database_loader import DatabaseLoader
from src.utils.text_utils import ChineseTextProcessor


class InnovationType(Enum):
    """创新类型枚举——基于对中国电力领域授权发明专利的分析归纳"""
    ALGORITHM_OPTIMIZATION = "算法优化型"          # 改进现有算法/模型，提升精度或效率
    SYSTEM_ARCHITECTURE = "系统架构型"             # 新的系统结构/分层架构/模块化设计
    PARAMETER_ADAPTIVE = "参数自适应型"            # 自适应参数调整/动态修正/在线优化
    MULTI_OBJECTIVE = "多目标协同型"               # 多目标优化/帕累托最优/协同控制
    PHYSICAL_DATA_FUSION = "物数融合型"            # 物理控制+数据驱动算法融合
    FEATURE_ENGINEERING = "特征工程型"             # 新特征/新指标的引入与建模
    CASCADE_HIERARCHICAL = "级联分层型"            # 多级/多层级联架构（如双层优化）
    HYBRID_METHOD = "混合方法型"                   # 多种技术方法的有机组合


@dataclass
class InnovationPattern:
    """创新模式"""
    pattern_type: InnovationType
    description: str
    typical_problem_template: str     # 典型问题模板
    typical_solution_template: str    # 典型方案模板
    example_patent_ids: List[str]     # 示例专利
    frequency: int                    # 出现频次
    success_indicators: List[str]     # 授权成功的关键因素
    keywords: List[str]               # 特征关键词


class InnovationMiner:
    """创新模式挖掘器

    从授权专利数据中学习创新规律，为新想法提供创新方向建议。

    使用方式:
        miner = InnovationMiner()
        miner.mine(patents)  # 挖掘创新模式
        patterns = miner.get_innovation_patterns()
        suggestion = miner.suggest_innovation_direction(user_idea)
    """

    def __init__(self):
        self.text_processor = ChineseTextProcessor()
        self.patterns: List[InnovationPattern] = []
        self.patent_classifications: Dict[str, InnovationType] = {}

        # 创新类型的特征关键词
        self.type_keywords = {
            InnovationType.ALGORITHM_OPTIMIZATION: [
                "优化", "改进", "提升精度", "降低误差", "修正", "校准",
                "提高准确", "减少偏差", "收敛速度", "精度提升",
            ],
            InnovationType.SYSTEM_ARCHITECTURE: [
                "系统", "架构", "平台", "模块", "被配置为", "框架",
                "分层", "分布式", "集中式", "体系",
            ],
            InnovationType.PARAMETER_ADAPTIVE: [
                "自适应", "动态调整", "在线修正", "实时调节", "自动调整",
                "适应", "动态修正", "在线更新", "自调整", "动态响应",
                "响应时间常数", "耦合修正因子",
            ],
            InnovationType.MULTI_OBJECTIVE: [
                "多目标", "帕累托", "协同", "双重目标", "兼顾",
                "多维度", "均衡", "多指标", "综合优化", "Pareto",
                "双重优化", "协调",
            ],
            InnovationType.PHYSICAL_DATA_FUSION: [
                "物理控制", "数据驱动", "低通滤波", "算法优化", "融合",
                "物理+数据", "模型+数据", "机理+数据", "控制+优化",
                "物理信息", "频域解耦",
            ],
            InnovationType.FEATURE_ENGINEERING: [
                "特征", "指标", "因子", "参数定义", "贡献度",
                "新特征", "特征提取", "指标构建", "特征向量",
                "耦合", "修正因子", "等效",
            ],
            InnovationType.CASCADE_HIERARCHICAL: [
                "双层", "分层", "多级", "级联", "上层", "下层",
                "第一层", "第二层", "顶层", "底层", "上级", "下级",
                "层调度", "层优化", "层控制",
            ],
            InnovationType.HYBRID_METHOD: [
                "结合", "组合", "集成", "混合", "综合", "多方法",
                "融合", "协同", "联合", "复合",
            ],
        }

    # ═══════════════════════════════════════════════════════════════
    # 创新模式挖掘
    # ═══════════════════════════════════════════════════════════════

    def mine(self, patents: List[StructuredPatent]) -> Dict:
        """从专利列表中挖掘所有创新模式

        Args:
            patents: 结构化专利列表

        Returns:
            挖掘结果摘要
        """
        # 1. 对每篇专利进行创新类型分类
        for p in patents:
            if p.is_parsed:
                innovation_type = self.classify_innovation(p)
                p.innovation_type = innovation_type.value
                self.patent_classifications[p.patent_id] = innovation_type

        # 2. 为每种创新类型构建模式
        self.patterns = self._build_patterns(patents)

        # 3. 分析问题-方案对
        self.problem_solution_pairs = self._extract_problem_solution_pairs(patents)

        # 4. 分析授权成功因素
        self.success_factors = self._analyze_grant_success_factors(patents)

        results = {
            "total_patents_analyzed": len([p for p in patents if p.is_parsed]),
            "innovation_types_found": len(set(p.innovation_type for p in patents
                                            if p.is_parsed and p.innovation_type)),
            "patterns_identified": len(self.patterns),
            "type_distribution": dict(Counter(
                p.innovation_type for p in patents
                if p.is_parsed and p.innovation_type
            )),
        }

        return results

    def classify_innovation(self, patent: StructuredPatent) -> InnovationType:
        """判断单个专利的创新类型

        基于关键词匹配和结构分析进行分类。一篇专利可能属于多种类型，
        取匹配得分最高的类型。

        Args:
            patent: 结构化专利

        Returns:
            创新类型枚举
        """
        # 收集用于分类的文本
        text_parts = []
        if patent.title:
            text_parts.append(patent.title)
        if patent.technical_solution:
            text_parts.append(patent.technical_solution)
        if patent.claims_tree:
            for claim in patent.claims_tree.independent_claims:
                text_parts.append(claim.claim_text)

        full_text = " ".join(text_parts)

        # 计算每种类型的匹配得分
        scores = {}
        for inno_type, keywords in self.type_keywords.items():
            score = 0
            for kw in keywords:
                if kw in full_text:
                    score += 1
            scores[inno_type] = score

        # 处理专利中的特殊结构信号
        if patent.claims_tree:
            # 有方法+装置双独立权利要求 → 系统架构型加分
            categories = set(c.claim_category for c in patent.claims_tree.independent_claims)
            if len(categories) >= 2:
                scores[InnovationType.SYSTEM_ARCHITECTURE] += 1

            # 权利要求中包含公式 → 算法优化型加分
            if any(c.has_formula for c in patent.claims_tree.get_all_claims()):
                scores[InnovationType.ALGORITHM_OPTIMIZATION] += 1
                scores[InnovationType.FEATURE_ENGINEERING] += 0.5

        # 说明书中有多层结构描述 → 级联分层型加分
        if patent.description_sections:
            impl_text = patent.description_sections.detailed_implementation
            if "第一层" in impl_text and "第二层" in impl_text:
                scores[InnovationType.CASCADE_HIERARCHICAL] += 2

            if "物理控制" in impl_text and ("算法" in impl_text or "优化" in impl_text):
                scores[InnovationType.PHYSICAL_DATA_FUSION] += 2

        # 取最高分类型，如果所有分数都为0则返回混合方法型
        if max(scores.values(), default=0) == 0:
            return InnovationType.HYBRID_METHOD

        best_type = max(scores, key=scores.get)
        return best_type

    def _build_patterns(self, patents: List[StructuredPatent]) -> List[InnovationPattern]:
        """为每种创新类型构建详细模式

        Args:
            patents: 已分类的专利列表

        Returns:
            创新模式列表
        """
        patterns = []

        # 按创新类型分组
        by_type: Dict[InnovationType, List[StructuredPatent]] = {}
        for p in patents:
            if not p.is_parsed or not p.innovation_type:
                continue
            try:
                inno_type = InnovationType(p.innovation_type)
            except ValueError:
                continue
            by_type.setdefault(inno_type, []).append(p)

        for inno_type, type_patents in by_type.items():
            if len(type_patents) == 0:
                continue

            # 提取该类型的典型问题模板（取最频繁的技术问题）
            problems = [p.technical_problem for p in type_patents if p.technical_problem]
            typical_problem = self._get_typical_text(problems) if problems else ""

            # 提取该类型的典型方案模板
            solutions = [p.technical_solution for p in type_patents if p.technical_solution]
            typical_solution = self._get_typical_text(solutions) if solutions else ""

            # 收集该类型的关键词
            all_keywords = []
            for p in type_patents:
                all_keywords.extend(p.keywords)
            top_keywords = [kw for kw, _ in Counter(all_keywords).most_common(8)]

            # 分析成功因素
            success_indicators = self._analyze_type_success_factors(inno_type, type_patents)

            pattern = InnovationPattern(
                pattern_type=inno_type,
                description=self._get_type_description(inno_type),
                typical_problem_template=typical_problem[:200],
                typical_solution_template=typical_solution[:200],
                example_patent_ids=[p.patent_id for p in type_patents[:5]],
                frequency=len(type_patents),
                success_indicators=success_indicators,
                keywords=top_keywords,
            )
            patterns.append(pattern)

        # 按频次降序
        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns

    def _get_typical_text(self, texts: List[str]) -> str:
        """从文本列表中提取最具代表性的文本（最长且包含最多关键信息的）

        Args:
            texts: 文本列表

        Returns:
            代表性文本
        """
        if not texts:
            return ""
        if len(texts) == 1:
            return texts[0]

        # 选文本长度中位数附近的（避免太短或太长）
        texts_by_len = sorted(texts, key=len)
        median_idx = len(texts_by_len) // 2
        return texts_by_len[median_idx]

    def _get_type_description(self, inno_type: InnovationType) -> str:
        """获取创新类型的详细描述

        Args:
            inno_type: 创新类型

        Returns:
            类型描述
        """
        descriptions = {
            InnovationType.ALGORITHM_OPTIMIZATION:
                "在现有算法或模型基础上进行改进，提升精度、效率或鲁棒性。"
                "典型手段包括：改进模型结构、优化参数估计方法、引入新的损失函数、"
                "改进求解算法等。此类创新的关键在于证明改进后的效果优于现有方法。",
            InnovationType.SYSTEM_ARCHITECTURE:
                "设计新的系统结构或分层架构，通过模块化的方式组织功能组件。"
                "典型手段包括：设计新的系统层级、定义新的模块接口、"
                "构建分布式或集中式架构。此类创新的关键在于证明新架构带来了性能或功能提升。",
            InnovationType.PARAMETER_ADAPTIVE:
                "引入参数的自适应调整机制，使系统能够根据运行条件动态优化。"
                "典型手段包括：自适应控制器、在线参数修正、动态权重调整。"
                "此类创新的关键在于证明自适应机制优于固定参数方案。",
            InnovationType.MULTI_OBJECTIVE:
                "同时优化多个相互制约的目标，寻找帕累托最优解或协同方案。"
                "典型手段包括：多目标优化建模、帕累托前沿求解、协同控制策略。"
                "此类创新的关键在于证明多目标协同优于单目标优化。",
            InnovationType.PHYSICAL_DATA_FUSION:
                "将物理机理模型与数据驱动算法有机融合，互补优势。"
                "典型手段包括：物理引导的神经网络、机理约束的优化算法、"
                "模型-数据混合驱动。此类创新的关键在于证明融合方案优于纯物理或纯数据方法。",
            InnovationType.FEATURE_ENGINEERING:
                "定义新的技术特征或评价指标，从新的维度描述技术问题。"
                "典型手段包括：设计新的特征参数、定义新的评价指标、"
                "构建特征提取方法。此类创新的关键在于证明新特征能有效反映问题本质。",
            InnovationType.CASCADE_HIERARCHICAL:
                "设计多层级的级联架构，实现从粗到细、从宏观到微观的递进式处理。"
                "典型手段包括：双层优化模型、多级控制架构、分层调度策略。"
                "此类创新的关键在于证明分层架构优于单层方案。",
            InnovationType.HYBRID_METHOD:
                "将两种或多种独立的技术方法有机组合，产生协同效应。"
                "典型手段包括：多种算法的组合、不同技术路线的融合。"
                "此类创新的关键在于证明组合产生了1+1大于2的效果。",
        }
        return descriptions.get(inno_type, "其他创新类型")

    # ═══════════════════════════════════════════════════════════════
    # 问题-方案对提取
    # ═══════════════════════════════════════════════════════════════

    def _extract_problem_solution_pairs(self, patents: List[StructuredPatent]) -> List[Dict]:
        """提取所有专利的 (技术问题, 技术方案) 对

        Args:
            patents: 结构化专利列表

        Returns:
            [{"problem": ..., "solution": ..., "patent_id": ...}, ...]
        """
        pairs = []
        for p in patents:
            if not p.is_parsed:
                continue
            if p.technical_problem and p.technical_solution:
                pairs.append({
                    "problem": p.technical_problem,
                    "solution": p.technical_solution,
                    "patent_id": p.patent_id,
                    "title": p.title,
                    "innovation_type": p.innovation_type,
                })
        return pairs

    # ═══════════════════════════════════════════════════════════════
    # 授权成功因素分析
    # ═══════════════════════════════════════════════════════════════

    def _analyze_grant_success_factors(self, patents: List[StructuredPatent]) -> Dict:
        """分析授权成功的共性因素

        基于所有授权专利的统计分析，找出成功授权的共性特征。

        Args:
            patents: 结构化专利列表

        Returns:
            成功因素分析结果
        """
        parsed = [p for p in patents if p.is_parsed]

        # 权利要求特征统计
        claim_stats = self._analyze_claim_statistics(parsed)

        # 说明书特征统计
        desc_stats = self._analyze_description_statistics(parsed)

        # 技术效果统计
        effect_stats = self._analyze_effect_statistics(parsed)

        return {
            "claim_statistics": claim_stats,
            "description_statistics": desc_stats,
            "effect_statistics": effect_stats,
            "summary": self._generate_success_summary(claim_stats, desc_stats, effect_stats),
        }

    def _analyze_claim_statistics(self, patents: List[StructuredPatent]) -> Dict:
        """统计权利要求特征

        Args:
            patents: 已解析专利列表

        Returns:
            权利要求统计
        """
        if not patents:
            return {}

        indep_counts = []
        dep_counts = []
        total_counts = []
        max_depths = []
        has_formula_count = 0
        multi_category_count = 0

        for p in patents:
            if not p.claims_tree:
                continue
            ct = p.claims_tree
            indep_counts.append(len(ct.independent_claims))
            dep_counts.append(len(ct.dependent_claims))
            total_counts.append(ct.total_claims)
            max_depths.append(ct.get_max_dependency_depth())

            if any(c.has_formula for c in ct.get_all_claims()):
                has_formula_count += 1

            categories = set(c.claim_category for c in ct.independent_claims)
            if len(categories) >= 2:
                multi_category_count += 1

        n = len([p for p in patents if p.claims_tree])

        return {
            "avg_independent_claims": sum(indep_counts) / n if n else 0,
            "avg_dependent_claims": sum(dep_counts) / n if n else 0,
            "avg_total_claims": sum(total_counts) / n if n else 0,
            "avg_max_depth": sum(max_depths) / n if n else 0,
            "formula_in_claims_ratio": has_formula_count / n if n else 0,
            "multi_category_ratio": multi_category_count / n if n else 0,
            "sample_size": n,
        }

    def _analyze_description_statistics(self, patents: List[StructuredPatent]) -> Dict:
        """统计说明书特征

        Args:
            patents: 已解析专利列表

        Returns:
            说明书统计
        """
        if not patents:
            return {}

        para_counts = []
        embodiment_counts = []
        effect_counts = []

        for p in patents:
            if not p.description_sections:
                continue
            ds = p.description_sections
            para_counts.append(ds.paragraph_count)
            embodiment_counts.append(len(ds.embodiments))
            effect_counts.append(len(ds.beneficial_effects))

        n = len([p for p in patents if p.description_sections])

        return {
            "avg_paragraphs": sum(para_counts) / n if n else 0,
            "avg_embodiments": sum(embodiment_counts) / n if n else 0,
            "avg_effects": sum(effect_counts) / n if n else 0,
            "sample_size": n,
        }

    def _analyze_effect_statistics(self, patents: List[StructuredPatent]) -> Dict:
        """统计技术效果特征

        Args:
            patents: 已解析专利列表

        Returns:
            效果统计
        """
        effect_keywords = Counter()

        for p in patents:
            for effect in p.technical_effects:
                for kw in ["提高", "降低", "减少", "增强", "改善", "实现", "消除", "避免"]:
                    if kw in effect:
                        effect_keywords[kw] += 1

        return {
            "common_effect_words": dict(effect_keywords.most_common(10)),
        }

    def _analyze_type_success_factors(self, inno_type: InnovationType,
                                      patents: List[StructuredPatent]) -> List[str]:
        """分析特定创新类型的成功因素

        Args:
            inno_type: 创新类型
            patents: 该类型的专利列表

        Returns:
            成功因素列表
        """
        factors = []

        # 通用因素
        if patents:
            avg_claims = sum(p.claims_tree.total_claims for p in patents
                          if p.claims_tree) / max(len(patents), 1)
            factors.append(f"平均权利要求{avg_claims:.0f}条，保护范围梯度合理")

            has_formula = sum(1 for p in patents if p.claims_tree and
                           any(c.has_formula for c in p.claims_tree.get_all_claims()))
            if has_formula > len(patents) * 0.3:
                factors.append(f"{has_formula}/{len(patents)}件引用数学公式增强技术说服力")

        # 类型特有因素
        type_specific = {
            InnovationType.CASCADE_HIERARCHICAL:
                ["双层/多层架构设计增强方案的完整性和可实施性",
                 "层级之间的衔接逻辑清晰，避免技术方案碎片化"],
            InnovationType.PHYSICAL_DATA_FUSION:
                ["物理机理提供理论支撑，数据算法提供精度提升",
                 "两者优势互补，避免单一方法的固有缺陷"],
            InnovationType.PARAMETER_ADAPTIVE:
                ["自适应机制使方案具有广泛的适用性",
                 "动态调整能力证明方案的鲁棒性和实用性"],
            InnovationType.MULTI_OBJECTIVE:
                ["多目标优化使方案更加全面和实用",
                 "帕累托最优解提供了灵活的选择空间"],
        }

        factors.extend(type_specific.get(inno_type, []))

        return factors

    def _generate_success_summary(self, claim_stats: Dict,
                                 desc_stats: Dict,
                                 effect_stats: Dict) -> str:
        """生成授权成功因素摘要

        Args:
            claim_stats, desc_stats, effect_stats: 各维度统计数据

        Returns:
            可读的摘要文本
        """
        parts = []

        if claim_stats:
            parts.append(
                f"授权专利平均有{claim_stats.get('avg_total_claims', 0):.1f}条权利要求，"
                f"其中独立权利要求{claim_stats.get('avg_independent_claims', 0):.1f}条，"
                f"最大依赖深度{claim_stats.get('avg_max_depth', 0):.1f}层。"
            )

        if desc_stats:
            parts.append(
                f"说明书平均{desc_stats.get('avg_paragraphs', 0):.0f}段落，"
                f"包含{desc_stats.get('avg_embodiments', 0):.1f}个实施例，"
                f"{desc_stats.get('avg_effects', 0):.1f}条有益效果。"
            )

        return " ".join(parts)

    # ═══════════════════════════════════════════════════════════════
    # 创新方向建议
    # ═══════════════════════════════════════════════════════════════

    def suggest_innovation_direction(self, idea: str,
                                    existing_solutions: List[str] = None) -> Dict:
        """为新想法建议创新方向

        基于已有的创新模式知识库，为用户的初步想法提供创新方向建议。

        Args:
            idea: 用户的初步想法描述
            existing_solutions: 已知的现有技术方案（可选）

        Returns:
            创新建议报告
        """
        suggestions = {
            "idea": idea,
            "matched_domain": self._identify_domain(idea),
            "innovation_directions": [],
        }

        # 匹配最相关的创新模式
        for pattern in self.patterns:
            relevance = self._calculate_relevance(idea, pattern)
            if relevance > 0:
                suggestions["innovation_directions"].append({
                    "innovation_type": pattern.pattern_type.value,
                    "description": pattern.description,
                    "relevance_score": relevance,
                    "typical_approach": pattern.typical_solution_template[:200],
                    "reference_patents": pattern.example_patent_ids,
                    "success_factors": pattern.success_indicators,
                })

        # 按相关度排序
        suggestions["innovation_directions"].sort(
            key=lambda d: d["relevance_score"], reverse=True
        )

        # 如果匹配太少，添加通用建议
        if len(suggestions["innovation_directions"]) < 3:
            suggestions["innovation_directions"].append({
                "innovation_type": "通用建议",
                "description": "考虑从系统架构、参数自适应或物数融合角度寻找创新空间",
                "relevance_score": 0.3,
                "typical_approach": "分析现有方案的不足，从架构设计、参数优化或方法融合角度提出改进",
                "reference_patents": [],
                "success_factors": [
                    "确保技术方案完整可实施",
                    "明确与现有技术的区别",
                    "提供充分的实施例支撑",
                ],
            })

        return suggestions

    def _identify_domain(self, idea: str) -> str:
        """识别想法所属的技术领域

        Args:
            idea: 想法描述

        Returns:
            技术领域
        """
        domain_keywords = {
            "虚拟电厂": ["虚拟电厂", "负荷响应", "需求响应"],
            "分布式光伏": ["光伏", "并网", "太阳能"],
            "储能系统": ["储能", "电池", "充放电"],
            "配电网": ["配电网", "配电", "馈线", "故障定位"],
            "继电保护": ["继电保护", "差动保护", "保护装置", "断路器"],
            "电解制氢": ["电解", "制氢", "氢能"],
            "电力调度": ["调度", "优化", "功率分配"],
            "电能质量": ["谐波", "电压", "频率", "电能质量"],
        }

        for domain, keywords in domain_keywords.items():
            for kw in keywords:
                if kw in idea:
                    return domain

        return "电力系统"

    def _calculate_relevance(self, idea: str, pattern: InnovationPattern) -> float:
        """计算想法与创新模式的相关度

        Args:
            idea: 想法描述
            pattern: 创新模式

        Returns:
            相关度分数 [0, 1]
        """
        # 关键词匹配
        match_count = 0
        for kw in pattern.keywords:
            if kw.lower() in idea.lower():
                match_count += 1

        # 问题模板匹配
        problem_similarity = 0.0
        if pattern.typical_problem_template:
            try:
                vec = TfidfVectorizer(max_features=200).fit_transform(
                    [idea, pattern.typical_problem_template]
                )
                problem_similarity = cosine_similarity(vec[0:1], vec[1:2])[0][0]
            except (ValueError, Exception):
                pass

        # 综合得分
        keyword_score = min(match_count / max(len(pattern.keywords), 1) * 0.6, 0.6)
        problem_score = problem_similarity * 0.4

        return keyword_score + problem_score

    # ═══════════════════════════════════════════════════════════════
    # 报告生成
    # ═══════════════════════════════════════════════════════════════

    def generate_innovation_report(self) -> str:
        """生成创新洞察报告（Markdown格式）

        供patent-writer在撰写过程中参考。

        Returns:
            Markdown格式的创新报告
        """
        lines = [
            "# 电力领域专利创新模式分析报告",
            "",
            f"基于{len(self.patent_classifications)}篇授权发明专利的分析。",
            "",
            "## 创新类型分布",
            "",
            "| 创新类型 | 数量 | 代表专利 |",
            "|---------|------|---------|",
        ]

        for pattern in self.patterns:
            example = pattern.example_patent_ids[0] if pattern.example_patent_ids else "N/A"
            lines.append(
                f"| {pattern.pattern_type.value} | {pattern.frequency} | {example} |"
            )

        lines.extend([
            "",
            "## 各创新类型详解",
            "",
        ])

        for pattern in self.patterns:
            lines.extend([
                f"### {pattern.pattern_type.value}（{pattern.frequency}篇）",
                "",
                f"**模式描述**: {pattern.description}",
                "",
                f"**典型方案**: {pattern.typical_solution_template[:200]}...",
                "",
                f"**成功关键因素**:",
            ])
            for factor in pattern.success_indicators:
                lines.append(f"- {factor}")
            lines.extend(["", f"**参考专利**: {', '.join(pattern.example_patent_ids[:3])}", ""])

        if self.success_factors:
            lines.extend([
                "## 授权成功因素总结",
                "",
                self.success_factors.get("summary", ""),
            ])

        return "\n".join(lines)

    def get_innovation_patterns(self) -> List[InnovationPattern]:
        """获取挖掘出的创新模式列表

        Returns:
            创新模式列表（按频次降序）
        """
        return self.patterns

    def get_type_distribution(self) -> Dict[str, int]:
        """获取创新类型分布

        Returns:
            {类型名: 数量}
        """
        return dict(Counter(
            p.innovation_type for p in self.patent_classifications.values()
        ))
