"""
权利要求解析器

解析HTML格式的权利要求文本为层次化树形结构。
能够识别独立权利要求和从属权利要求，提取技术特征，构建依赖关系。

中国专利权利要求格式:
- 独立权利要求: "1.一种XXX方法，其特征在于，..."
- 从属权利要求: "2.如权利要求1所述的XXX方法，其特征在于，..."
- 分割符: <br/> 或 \n
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from src.utils.text_utils import ChineseTextProcessor


@dataclass
class ClaimNode:
    """单个权利要求节点"""
    claim_number: int                          # 权利要求编号
    claim_text: str                            # 权利要求完整文本
    claim_type: str = ""                       # "independent" | "dependent"
    parent_number: Optional[int] = None        # 从属权利要求的父权利要求编号
    children: List[int] = field(default_factory=list)  # 引用此权利要求的子权利要求编号
    features: List[str] = field(default_factory=list)  # 提取的技术特征
    preamble: str = ""                         # 前序部分（"其特征在于"之前）
    characterizing: str = ""                   # 特征部分（"其特征在于"之后）
    has_formula: bool = False                  # 是否包含数学公式
    claim_category: str = ""                   # 保护主题类别: "方法" | "装置" | "系统" | "设备"


@dataclass
class ClaimsTree:
    """权利要求树形结构"""
    patent_id: str = ""
    independent_claims: List[ClaimNode] = field(default_factory=list)
    dependent_claims: List[ClaimNode] = field(default_factory=list)
    total_claims: int = 0

    def get_all_claims(self) -> List[ClaimNode]:
        """获取所有权利要求（按编号排序）"""
        all_claims = self.independent_claims + self.dependent_claims
        all_claims.sort(key=lambda c: c.claim_number)
        return all_claims

    def get_claim_by_number(self, num: int) -> Optional[ClaimNode]:
        """按编号获取权利要求"""
        for c in self.get_all_claims():
            if c.claim_number == num:
                return c
        return None

    def get_dependency_chain(self, claim_num: int) -> List[int]:
        """获取某个权利要求的完整依赖链（从独立权利要求到该权利要求）"""
        chain = [claim_num]
        visited = {claim_num}  # 循环依赖检测
        current = self.get_claim_by_number(claim_num)
        while current and current.parent_number is not None:
            if current.parent_number in visited:
                break  # 检测到循环依赖，终止
            chain.insert(0, current.parent_number)
            visited.add(current.parent_number)
            current = self.get_claim_by_number(current.parent_number)
        return chain

    def get_max_dependency_depth(self) -> int:
        """获取最大依赖深度"""
        max_depth = 0
        for claim in self.dependent_claims:
            depth = len(self.get_dependency_chain(claim.claim_number)) - 1
            max_depth = max(max_depth, depth)
        return max_depth


class ClaimsParser:
    """权利要求解析器

    解析HTML格式的权利要求文本，构建树形依赖结构。

    使用方式:
        parser = ClaimsParser()
        tree = parser.parse("CN121863439B", raw_claims_text)
        print(f"独立权利要求: {len(tree.independent_claims)}")
        print(f"从属权利要求: {len(tree.dependent_claims)}")
    """

    def __init__(self):
        self.text_processor = ChineseTextProcessor()

    def parse(self, patent_id: str, claims_raw: str) -> ClaimsTree:
        """解析权利要求文本为树形结构

        Args:
            patent_id: 专利号
            claims_raw: 原始权利要求文本（HTML格式）

        Returns:
            解析后的权利要求树
        """
        tree = ClaimsTree(patent_id=patent_id)

        if not claims_raw:
            return tree

        # 清理HTML
        clean_text = self.text_processor.clean_html(claims_raw)

        # 拆分为独立权利要求条目
        claim_entries = self._split_claims(clean_text)
        tree.total_claims = len(claim_entries)

        # 解析每个权利要求
        for num, text in claim_entries:
            claim_node = self._parse_single_claim(num, text)

            if claim_node.claim_type == "independent":
                tree.independent_claims.append(claim_node)
            else:
                tree.dependent_claims.append(claim_node)

        # 构建父子引用关系
        self._build_references(tree)

        return tree

    def _split_claims(self, claims_text: str) -> List[Tuple[int, str]]:
        """将权利要求文本按编号拆分为独立条目

        Args:
            claims_text: 清理后的权利要求文本

        Returns:
            [(权利要求编号, 权利要求文本), ...] 列表
        """
        if not claims_text:
            return []

        # 匹配 "N." 或 "N、" 开头的权利要求（N为数字）
        # 中国专利权利要求格式: "1.xxx" 或 "1、xxx"
        pattern = r'(?:^|\n)\s*(\d+)\s*[.、．]\s*'

        parts = re.split(pattern, claims_text)

        entries = []
        i = 1
        while i < len(parts):
            try:
                claim_num = int(parts[i])
                claim_text = parts[i + 1].strip() if i + 1 < len(parts) else ""
                entries.append((claim_num, claim_text))
                i += 2
            except (ValueError, IndexError):
                i += 1

        return entries

    def _parse_single_claim(self, claim_num: int, claim_text: str) -> ClaimNode:
        """解析单个权利要求

        Args:
            claim_num: 权利要求编号
            claim_text: 权利要求文本

        Returns:
            ClaimNode实例
        """
        node = ClaimNode(claim_number=claim_num, claim_text=claim_text.strip())

        # 判断权利要求类型
        claim_type, parent_num = self._identify_claim_type(claim_text)
        node.claim_type = claim_type
        node.parent_number = parent_num

        # 拆分前序部分和特征部分
        preamble, characterizing = self._split_preamble_characterizing(claim_text)
        node.preamble = preamble
        node.characterizing = characterizing

        # 提取技术特征
        node.features = self._extract_features(characterizing or claim_text)

        # 检测是否包含公式
        node.has_formula = self._has_formula(claim_text)

        # 识别保护主题类别
        node.claim_category = self._identify_category(claim_text)

        return node

    def _identify_claim_type(self, claim_text: str) -> Tuple[str, Optional[int]]:
        """判断权利要求是独立还是从属，并提取父权利要求编号

        独立权利要求: 不包含"根据权利要求N所述"的表述
        从属权利要求: 包含"根据权利要求N所述"的表述

        Args:
            claim_text: 权利要求文本

        Returns:
            (类型, 父权利要求编号)
        """
        # 匹配"根据权利要求N所述"模式
        # 支持多种变体:
        # - "根据权利要求1所述的"
        # - "如权利要求1所述的"
        # - "根据权利要求1至3中任一项所述的"
        # - "根据权利要求1-3任一项所述的"

        patterns = [
            r'根据权利要求\s*(\d+)\s*(?:至|-)\s*(\d+)\s*(?:中)?任一项所述',
            r'如权利要求\s*(\d+)\s*(?:至|-)\s*(\d+)\s*(?:中)?任一项所述',
            r'根据权利要求\s*(\d+)\s*所述',
            r'如权利要求\s*(\d+)\s*所述',
        ]

        for pattern in patterns:
            match = re.search(pattern, claim_text)
            if match:
                parent_num = int(match.group(1))
                return ("dependent", parent_num)

        return ("independent", None)

    def _split_preamble_characterizing(self, claim_text: str) -> Tuple[str, str]:
        """按"其特征在于"拆分前序部分和特征部分

        Args:
            claim_text: 权利要求文本

        Returns:
            (前序部分, 特征部分)
        """
        # 支持多种"其特征在于"的表述
        patterns = [
            r'其特征在于[，,：:]?\s*',
            r'其特征为[，,：:]?\s*',
            r'其特点在于[，,：:]?\s*',
        ]

        for pattern in patterns:
            match = re.search(pattern, claim_text)
            if match:
                split_pos = match.start()
                preamble = claim_text[:split_pos].strip()
                characterizing = claim_text[match.end():].strip()
                return (preamble, characterizing)

        # 如果没有找到"其特征在于"，整个文本作为特征部分
        return ("", claim_text)

    def _extract_features(self, characterizing_text: str) -> List[str]:
        """从特征部分提取技术特征列表

        技术特征通常通过分号、编号或特定连接词分隔。

        Args:
            characterizing_text: 权利要求特征部分文本

        Returns:
            技术特征列表
        """
        features = []

        # 策略1: 按分号拆分（中国专利最常用的特征分隔符）
        parts = re.split(r'[；;]', characterizing_text)

        for part in parts:
            part = part.strip()

            # 跳过过于简短的片段和编号标记
            if len(part) < 5:
                continue
            if re.match(r'^[\d\s.、．]+$', part):
                continue

            # 清理段落编号标记
            part = re.sub(r'\[\d{4}\]', '', part).strip()

            if part:
                features.append(part)

        return features

    def _build_references(self, tree: ClaimsTree):
        """构建权利要求间的父子引用关系

        为每个从属权利要求的父节点添加children引用。

        Args:
            tree: 权利要求树（原地修改）
        """
        for claim in tree.dependent_claims:
            if claim.parent_number is not None:
                parent = tree.get_claim_by_number(claim.parent_number)
                if parent and claim.claim_number not in parent.children:
                    parent.children.append(claim.claim_number)

    def _has_formula(self, claim_text: str) -> bool:
        """检测权利要求是否包含数学公式

        识别希腊字母、数学运算符、LaTeX风格符号等。

        Args:
            claim_text: 权利要求文本

        Returns:
            True表示包含公式
        """
        # 希腊字母
        greek = re.search(r'[ͱ-Ͼ]', claim_text)
        # 数学符号
        math_symbols = re.search(r'[∑∏∫∂√∞≈≠≤≥]', claim_text)
        # 上标下标标记
        sub_sup = re.search(r'[\^_]\{|[\^_][a-zA-Z\d]', claim_text)

        return bool(greek or math_symbols or sub_sup)

    def _identify_category(self, claim_text: str) -> str:
        """识别权利要求的保护主题类别

        Args:
            claim_text: 权利要求文本

        Returns:
            类别字符串: "方法" | "装置" | "系统" | "设备" | "介质" | "其他"
        """
        # 取前100个字符判断（权利要求开头即声明类别）
        head = claim_text[:100]

        category_keywords = {
            "方法": ["方法", "步骤", "流程"],
            "装置": ["装置", "设备", "器"],
            "系统": ["系统", "平台"],
            "介质": ["介质", "存储介质", "程序产品"],
        }

        for category, keywords in category_keywords.items():
            for kw in keywords:
                if kw in head:
                    return category

        return "其他"

    # ═══════════════════════════════════════════════════════════════
    # 分析方法
    # ═══════════════════════════════════════════════════════════════

    def detect_claim_patterns(self, tree: ClaimsTree) -> Dict:
        """检测权利要求的撰写模式

        Args:
            tree: 权利要求树

        Returns:
            模式分析结果字典
        """
        all_claims = tree.get_all_claims()
        categories = set(c.claim_category for c in all_claims)
        indep_categories = set(c.claim_category for c in tree.independent_claims)

        patterns = {
            "structure_type": self._classify_structure(categories, indep_categories),
            "independent_count": len(tree.independent_claims),
            "dependent_count": len(tree.dependent_claims),
            "max_depth": tree.get_max_dependency_depth(),
            "formula_in_claims": any(c.has_formula for c in all_claims),
            "categories": list(categories),
            "features_per_claim": {c.claim_number: len(c.features)
                                   for c in all_claims},
        }

        return patterns

    def _classify_structure(self, categories: set,
                           indep_categories: set) -> str:
        """分类权利要求结构类型

        Args:
            categories: 所有权利要求的类别集合
            indep_categories: 独立权利要求的类别集合

        Returns:
            结构类型字符串
        """
        if len(indep_categories) == 1:
            cat = list(indep_categories)[0]
            return f"单一{cat}型"
        elif indep_categories == {"方法", "装置"}:
            return "方法+装置双保护型"
        elif indep_categories == {"方法", "系统"}:
            return "方法+系统型"
        elif "系统" in indep_categories and "装置" in indep_categories:
            return "系统+设备分层型"
        elif len(indep_categories) >= 3:
            return "多类别保护型"
        else:
            return "混合型"
