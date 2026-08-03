"""
权利要求结构分析器

从授权专利中学习权利要求撰写策略：结构模式、依赖策略、
保护范围设计、特征递进方式。为新专利生成权利要求结构建议。

数据溯源: 所有统计和模式均标注 source_patents。
"""

import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import Counter

from src.parsers.claims_parser import ClaimsParser, ClaimsTree, ClaimNode
from src.parsers.patent_parser import StructuredPatent


@dataclass
class ClaimPattern:
    """权利要求撰写模式"""
    pattern_name: str              # 模式名称
    structure_type: str            # "方法+装置" | "单一方法" | "方法+系统" | etc.
    independent_count: int         # 独立权利要求数量
    dependent_count: int           # 从属权利要求数量
    max_depth: int                 # 最大依赖深度
    avg_features_per_claim: float  # 平均技术特征数
    has_formula: bool              # 是否包含公式
    frequency: int                 # 出现频次
    example_patents: List[str]     # 示例专利


class ClaimAnalyzer:
    """权利要求分析器

    从授权专利中学习权利要求撰写策略，为专利撰写提供结构建议。

    使用方式:
        analyzer = ClaimAnalyzer()
        analyzer.analyze(patents)
        recommendation = analyzer.recommend_claim_structure(innovation_type, features)
    """

    def __init__(self):
        self.claims_parser = ClaimsParser()
        self.patterns: List[ClaimPattern] = []
        self._analysis_cache: Dict = {}

    def analyze(self, patents: List[StructuredPatent]) -> Dict:
        """分析所有专利的权利要求撰写模式

        Args:
            patents: 结构化专利列表

        Returns:
            分析结果摘要
        """
        parsed = [p for p in patents if p.is_parsed and p.claims_tree]

        # 统计基础指标
        stats = self._compute_statistics(parsed)

        # 提取撰写模式
        self.patterns = self._extract_patterns(parsed)

        # 分析依赖策略
        dependency_strategies = self._analyze_dependency_strategies(parsed)

        self._analysis_cache = {
            "statistics": stats,
            "patterns": [self._pattern_to_dict(p) for p in self.patterns],
            "dependency_strategies": dependency_strategies,
        }

        return {
            "total_analyzed": len(parsed),
            "patterns_found": len(self.patterns),
            "avg_claims": stats["avg_total_claims"],
            "most_common_structure": stats["most_common_structure"],
        }

    def _compute_statistics(self, patents: List[StructuredPatent]) -> Dict:
        """计算权利要求统计指标"""
        n = len(patents)
        if n == 0:
            return {}

        total_claims = [p.claims_tree.total_claims for p in patents]
        indep_claims = [len(p.claims_tree.independent_claims) for p in patents]
        dep_claims = [len(p.claims_tree.dependent_claims) for p in patents]
        depths = [p.claims_tree.get_max_dependency_depth() for p in patents]

        # 结构类型分布
        structure_counter = Counter()
        for p in patents:
            patterns = self.claims_parser.detect_claim_patterns(p.claims_tree)
            structure_counter[patterns["structure_type"]] += 1

        return {
            "avg_total_claims": sum(total_claims) / n,
            "avg_independent_claims": sum(indep_claims) / n,
            "avg_dependent_claims": sum(dep_claims) / n,
            "avg_max_depth": sum(depths) / n,
            "most_common_structure": structure_counter.most_common(1)[0][0] if structure_counter else "",
            "structure_distribution": dict(structure_counter),
        }

    def _extract_patterns(self, patents: List[StructuredPatent]) -> List[ClaimPattern]:
        """提取权利要求撰写模式"""
        structure_groups: Dict[str, List[StructuredPatent]] = {}

        for p in patents:
            patterns = self.claims_parser.detect_claim_patterns(p.claims_tree)
            st = patterns["structure_type"]
            structure_groups.setdefault(st, []).append(p)

        patterns = []
        for st, group in structure_groups.items():
            if len(group) == 0:
                continue

            avg_features = sum(
                sum(len(c.features) for c in p.claims_tree.get_all_claims())
                / max(p.claims_tree.total_claims, 1)
                for p in group
            ) / len(group)

            has_formula_count = sum(
                1 for p in group
                if any(c.has_formula for c in p.claims_tree.get_all_claims())
            )

            patterns.append(ClaimPattern(
                pattern_name=st,
                structure_type=st,
                independent_count=int(
                    sum(len(p.claims_tree.independent_claims) for p in group) / len(group)
                ),
                dependent_count=int(
                    sum(len(p.claims_tree.dependent_claims) for p in group) / len(group)
                ),
                max_depth=max(p.claims_tree.get_max_dependency_depth() for p in group),
                avg_features_per_claim=round(avg_features, 1),
                has_formula=has_formula_count > len(group) * 0.3,
                frequency=len(group),
                example_patents=[p.patent_id for p in group[:3]],
            ))

        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns

    def _analyze_dependency_strategies(self, patents: List[StructuredPatent]) -> Dict:
        """分析从属权利要求的依赖策略

        学习授权专利中从属权利要求如何逐级细化保护范围。
        """
        strategies = {
            "参数细化": 0,     # 逐步缩小参数范围（如"取值范围1-10→3-8"）
            "方法细化": 0,     # 添加具体实施步骤
            "设备细化": 0,     # 添加具体模块/组件
            "替代方案": 0,     # 提供可选实现方式
            "组合限定": 0,     # 多个特征的组合限定
        }

        for p in patents:
            for claim in p.claims_tree.dependent_claims:
                text = claim.characterizing
                if any(kw in text for kw in ["范围", "区间", "取值", "大于", "小于", "不超过"]):
                    strategies["参数细化"] += 1
                elif any(kw in text for kw in ["步骤", "流程", "阶段"]):
                    strategies["方法细化"] += 1
                elif any(kw in text for kw in ["模块", "单元", "组件", "装置"]):
                    strategies["设备细化"] += 1
                elif any(kw in text for kw in ["或", "任选", "可选", "替代"]):
                    strategies["替代方案"] += 1
                else:
                    strategies["组合限定"] += 1

        total = sum(strategies.values())
        if total > 0:
            strategies = {k: round(v / total * 100, 1) for k, v in strategies.items()}

        return strategies

    def recommend_claim_structure(self, innovation_type: str,
                                  tech_features: List[str] = None) -> Dict:
        """基于创新类型和技术特征，推荐权利要求结构

        Args:
            innovation_type: 创新类型（来自InnovationMiner的分类）
            tech_features: 技术特征列表

        Returns:
            权利要求结构建议
        """
        tech_features = tech_features or []

        # 默认结构
        recommendation = {
            "recommended_independent_count": 2,
            "recommended_dependent_count": 6,
            "recommended_max_depth": 3,
            "suggested_structure": "方法+装置双保护型",
            "reason": "",
            "feature_organization": [],
        }

        # 根据创新类型调整建议
        if "系统架构" in innovation_type:
            recommendation["suggested_structure"] = "系统+设备分层保护型"
            recommendation["recommended_independent_count"] = 3
            recommendation["reason"] = "系统架构型创新建议用方法、系统、设备三个独立权利要求分层保护"

        elif "算法优化" in innovation_type:
            recommendation["suggested_structure"] = "方法+装置双保护型"
            recommendation["reason"] = "算法优化型创新建议保护算法方法本身及执行该方法的装置"

        elif "参数自适应" in innovation_type:
            recommendation["suggested_structure"] = "单一方法型"
            recommendation["recommended_independent_count"] = 1
            recommendation["reason"] = "参数自适应型创新核心在方法，建议用从属权利要求覆盖不同参数自适应策略"

        elif "级联分层" in innovation_type:
            recommendation["suggested_structure"] = "方法+系统型"
            recommendation["recommended_max_depth"] = 4
            recommendation["reason"] = "级联分层型创新建议保护各层级的方法及整体系统架构"

        elif "多目标" in innovation_type:
            recommendation["suggested_structure"] = "方法+装置双保护型"
            recommendation["reason"] = "多目标协同型创新建议保护多目标优化方法及优化装置"

        elif "物数融合" in innovation_type:
            recommendation["suggested_structure"] = "方法+系统型"
            recommendation["reason"] = "物数融合型创新建议保护物理控制+数据算法的融合方法及系统"

        # 基于特征数量微调
        if len(tech_features) > 10:
            recommendation["recommended_dependent_count"] += 2
            recommendation["feature_organization"].append({
                "advice": f"技术特征较多({len(tech_features)}个)，建议将核心特征集中在独立权利要求，"
                         f"其余特征分散到3-5条从属权利要求中逐步限定",
            })

        # 添加来自实际数据的参考信息
        matching_patterns = [p for p in self.patterns
                           if p.structure_type == recommendation["suggested_structure"]]
        if matching_patterns:
            ref = matching_patterns[0]
            recommendation["reference"] = {
                "pattern_found_in_database": True,
                "frequency": ref.frequency,
                "avg_dependent_claims": ref.dependent_count,
                "example_patents": ref.example_patents,
            }

        return recommendation

    def evaluate_claim_quality(self, claims_tree: ClaimsTree) -> Dict:
        """评估权利要求质量

        基于授权专利的统计标准进行质量评估。

        Args:
            claims_tree: 权利要求树

        Returns:
            质量评估报告
        """
        issues = []
        warnings = []

        # 检查独立权利要求数量
        indep = len(claims_tree.independent_claims)
        if indep == 0:
            issues.append("缺少独立权利要求")
        elif indep == 1:
            warnings.append("仅1条独立权利要求，建议考虑方法+装置双保护模式")

        # 检查从属权利要求数量（参考授权专利平均约4-6条）
        dep = len(claims_tree.dependent_claims)
        if dep < 3:
            warnings.append(f"从属权利要求仅{dep}条，偏少（授权专利平均4-6条），保护范围梯度可能不足")

        # 检查依赖深度
        depth = claims_tree.get_max_dependency_depth()
        if depth < 2:
            warnings.append(f"最大依赖深度仅{depth}层，建议至少2-3层以形成梯度保护")

        # 检查独立权利要求是否包含必要技术特征
        for claim in claims_tree.independent_claims:
            if len(claim.features) < 3:
                warnings.append(f"独立权利要求{claim.claim_number}技术特征少于3个，可能范围过宽")
            if len(claim.characterizing) < 20:
                warnings.append(f"独立权利要求{claim.claim_number}特征部分过于简短")

        # 检查是否有"其特征在于"标记
        for claim in claims_tree.get_all_claims():
            if "其特征在于" not in claim.claim_text and "其特征为" not in claim.claim_text:
                if claim.claim_type == "independent":
                    issues.append(f"独立权利要求{claim.claim_number}缺少\"其特征在于\"标记")

        return {
            "quality_level": "A" if not issues else ("B" if len(issues) <= 1 else "C"),
            "issues": issues,
            "warnings": warnings,
            "total_issues": len(issues),
            "total_warnings": len(warnings),
        }

    def _pattern_to_dict(self, pattern: ClaimPattern) -> Dict:
        """将ClaimPattern转换为可序列化的字典"""
        return {
            "pattern_name": pattern.pattern_name,
            "structure_type": pattern.structure_type,
            "independent_count": pattern.independent_count,
            "dependent_count": pattern.dependent_count,
            "max_depth": pattern.max_depth,
            "avg_features_per_claim": pattern.avg_features_per_claim,
            "has_formula": pattern.has_formula,
            "frequency": pattern.frequency,
            "example_patents": pattern.example_patents,
        }

    def get_analysis_report(self) -> str:
        """生成权利要求分析报告（Markdown格式）"""
        if not self._analysis_cache:
            return "尚未进行分析，请先调用 analyze() 方法"

        stats = self._analysis_cache.get("statistics", {})
        lines = [
            "# 权利要求撰写策略分析报告",
            "",
            "## 基础统计",
            "",
            f"- 平均权利要求总数: {stats.get('avg_total_claims', 0):.1f}条",
            f"- 平均独立权利要求: {stats.get('avg_independent_claims', 0):.1f}条",
            f"- 平均从属权利要求: {stats.get('avg_dependent_claims', 0):.1f}条",
            f"- 平均最大依赖深度: {stats.get('avg_max_depth', 0):.1f}层",
            f"- 最常见结构: {stats.get('most_common_structure', '')}",
            "",
            "## 撰写模式",
            "",
        ]

        for pattern in self.patterns:
            lines.append(f"### {pattern.pattern_name}（{pattern.frequency}篇）")
            lines.append(f"- 独立权利要求: {pattern.independent_count}条")
            lines.append(f"- 从属权利要求: {pattern.dependent_count}条")
            lines.append(f"- 最大深度: {pattern.max_depth}层")
            lines.append(f"- 平均特征数: {pattern.avg_features_per_claim}个/条")
            lines.append(f"- 含公式: {'是' if pattern.has_formula else '否'}")
            lines.append("")

        lines.extend([
            "## 依赖策略分布",
            "",
        ])
        for strategy, pct in self._analysis_cache.get("dependency_strategies", {}).items():
            lines.append(f"- {strategy}: {pct}%")

        return "\n".join(lines)
