"""
专利文本主解析器

调度ClaimsParser和DescriptionParser，将原始专利数据转换为
结构化的StructuredPatent对象，为所有分析模块提供统一的数据格式。
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from src.utils.text_utils import ChineseTextProcessor, ipc_to_str
from src.parsers.claims_parser import ClaimsParser, ClaimsTree
from src.parsers.description_parser import DescriptionParser, DescriptionSections


@dataclass
class StructuredPatent:
    """结构化专利数据——所有分析模块的统一输入格式

    将原始JSON专利数据解析为结构化的：
    - 权利要求树（独立/从属，依赖关系，技术特征）
    - 说明书章节（技术领域、背景、发明内容、实施方式等）
    - 提取的关键信息（技术问题、技术方案、技术效果、公式、关键词）
    """
    # 基本信息（来自数据库）
    patent_id: str = ""
    title: str = ""
    applicant: str = ""
    application_date: str = ""
    ipc: str = ""
    legal_status: str = ""

    # 原始文本（保留原始数据以追溯）
    claims_raw: str = ""
    description_raw: str = ""

    # 结构化解析结果
    claims_tree: Optional[ClaimsTree] = None
    description_sections: Optional[DescriptionSections] = None

    # 提取的关键信息
    technical_problem: str = ""             # 技术问题（合并自背景+发明内容）
    technical_solution: str = ""            # 技术方案概述
    technical_effects: List[str] = field(default_factory=list)  # 技术效果列表
    formulas: List[str] = field(default_factory=list)           # 数学公式列表
    keywords: List[str] = field(default_factory=list)           # 关键技术词
    innovation_type: Optional[str] = None   # 创新类型（待InnovationMiner分析后填充）

    # 元数据
    is_parsed: bool = False
    parse_errors: List[str] = field(default_factory=list)


class PatentParser:
    """专利文本主解析器

    从数据库加载专利数据，生成结构化的StructuredPatent。

    使用方式:
        parser = PatentParser(db_path="data/patent_database")
        patents = parser.parse_all_full_text()  # 解析所有完整专利
        patent = parser.parse_single("CN121863439B")  # 解析单个专利
    """

    def __init__(self,
                 db_path: str = "data/patent_database",
                 terminology_dir: str = "config/terminology"):
        """初始化解析器

        Args:
            db_path: 专利数据库目录
            terminology_dir: 术语库目录
        """
        self.db_path = Path(db_path)
        self.terminology_dir = Path(terminology_dir)

        self.text_processor = ChineseTextProcessor(str(terminology_dir))
        self.claims_parser = ClaimsParser()
        self.description_parser = DescriptionParser()

        # 加载数据库
        self._load_database()

    def _load_database(self):
        """加载专利数据库索引"""
        index_file = self.db_path / "index.json"
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                self.db = json.load(f)
        else:
            self.db = {"patents": {}}

    def reload_database(self):
        """重新加载数据库（在数据库更新后调用）"""
        self._load_database()

    # ═══════════════════════════════════════════════════════════════
    # 批量解析
    # ═══════════════════════════════════════════════════════════════

    def parse_all_full_text(self) -> List[StructuredPatent]:
        """解析数据库中所有拥有完整文本的专利

        Returns:
            StructuredPatent列表（按申请日期降序）
        """
        patents = []
        for pid, patent_data in self.db.get("patents", {}).items():
            if "claims" in patent_data and "description" in patent_data:
                try:
                    sp = self._parse_from_dict(pid, patent_data)
                    patents.append(sp)
                except Exception as e:
                    # 解析失败不应该阻塞整体流程
                    sp = StructuredPatent(patent_id=pid)
                    sp.parse_errors.append(str(e))
                    patents.append(sp)

        # 按申请日期降序
        patents.sort(key=lambda p: p.application_date or "", reverse=True)
        return patents

    def parse_all_with_text_flag(self) -> List[StructuredPatent]:
        """解析所有有文本标记的专利（包括没有内联文本的）

        Returns:
            StructuredPatent列表
        """
        patents = []
        for pid, patent_data in self.db.get("patents", {}).items():
            sp = self._parse_from_dict(pid, patent_data)
            patents.append(sp)

        patents.sort(key=lambda p: p.application_date or "", reverse=True)
        return patents

    def parse_single(self, patent_id: str) -> Optional[StructuredPatent]:
        """解析单个专利

        Args:
            patent_id: 专利号

        Returns:
            StructuredPatent对象，未找到返回None
        """
        patent_id = patent_id.strip().upper()
        patent_data = self.db.get("patents", {}).get(patent_id)
        if not patent_data:
            return None

        return self._parse_from_dict(patent_id, patent_data)

    # ═══════════════════════════════════════════════════════════════
    # 核心解析逻辑
    # ═══════════════════════════════════════════════════════════════

    def _parse_from_dict(self, patent_id: str,
                        patent_data: Dict) -> StructuredPatent:
        """从数据库字典构造StructuredPatent

        Args:
            patent_id: 专利号
            patent_data: 数据库中的专利数据字典

        Returns:
            结构化的专利对象
        """
        sp = StructuredPatent(
            patent_id=patent_id,
            title=patent_data.get("title", ""),
            applicant=patent_data.get("applicant", ""),
            application_date=patent_data.get("application_date", ""),
            ipc=ipc_to_str(patent_data.get("ipc", "")),
            legal_status=patent_data.get("legal_status", ""),
            claims_raw=patent_data.get("claims", ""),
            description_raw=patent_data.get("description", ""),
        )

        # 如果有完整的文本，进行深度解析
        if sp.claims_raw and sp.description_raw:
            try:
                self._deep_parse(sp)
            except Exception as e:
                sp.parse_errors.append(str(e))
        elif sp.description_raw:
            # 只有说明书没有权利要求，部分解析
            try:
                sp.description_sections = self.description_parser.parse(
                    patent_id, sp.description_raw
                )
            except Exception as e:
                sp.parse_errors.append(str(e))

        return sp

    def _deep_parse(self, sp: StructuredPatent):
        """对齐全文本的专利进行深度解析

        Args:
            sp: StructuredPatent实例（原地修改）
        """
        # 解析权利要求
        sp.claims_tree = self.claims_parser.parse(sp.patent_id, sp.claims_raw)

        # 解析说明书
        sp.description_sections = self.description_parser.parse(
            sp.patent_id, sp.description_raw
        )

        # 提取综合信息
        self._extract_cross_section_info(sp)

        sp.is_parsed = True

    def _extract_cross_section_info(self, sp: StructuredPatent):
        """从权利要求和说明书的交叉分析中提取综合信息

        Args:
            sp: StructuredPatent实例（原地修改）
        """
        # 提取技术问题（优先从背景技术中获取）
        if sp.description_sections:
            ds = sp.description_sections

            # 技术问题：合并发明目的和背景问题
            problem_parts = []
            if ds.invention_purpose:
                problem_parts.append(ds.invention_purpose)
            if ds.existing_problems:
                problem_parts.extend(ds.existing_problems[:2])
            sp.technical_problem = "；".join(problem_parts)

            # 技术方案：优先取方案概述，fallback到权利要求1的特征部分
            if ds.technical_solution_summary:
                sp.technical_solution = ds.technical_solution_summary
            elif sp.claims_tree and sp.claims_tree.independent_claims:
                claim1 = sp.claims_tree.independent_claims[0]
                sp.technical_solution = claim1.characterizing or claim1.claim_text

            # 技术效果
            if ds.beneficial_effects:
                sp.technical_effects = ds.beneficial_effects

            # 公式
            if ds.formulas:
                sp.formulas = ds.formulas

        # 提取关键词
        sp.keywords = self._extract_keywords(sp)

    def _extract_keywords(self, sp: StructuredPatent) -> List[str]:
        """从专利中提取关键技术词

        基于标题、权利要求和说明书文本，使用TF-IDF提取关键词。

        Args:
            sp: 结构化专利

        Returns:
            关键词列表
        """
        texts = []
        if sp.title:
            texts.append(sp.title)
        if sp.claims_raw:
            texts.append(sp.claims_raw[:1000])  # 只用权利要求前1000字
        if sp.description_sections:
            ds = sp.description_sections
            if ds.invention_content:
                texts.append(ds.invention_content[:500])

        if texts:
            return self.text_processor.extract_keywords_tfidf(texts, top_k=10)

        return []

    # ═══════════════════════════════════════════════════════════════
    # 统计方法
    # ═══════════════════════════════════════════════════════════════

    def get_parse_statistics(self, patents: List[StructuredPatent]) -> Dict:
        """获取解析统计信息

        Args:
            patents: 解析后的专利列表

        Returns:
            统计字典
        """
        total = len(patents)
        fully_parsed = sum(1 for p in patents if p.is_parsed)
        with_claims_tree = sum(1 for p in patents if p.claims_tree is not None)
        with_desc_sections = sum(1 for p in patents if p.description_sections is not None)
        with_problem = sum(1 for p in patents if p.technical_problem)
        with_effects = sum(1 for p in patents if p.technical_effects)
        errors = sum(1 for p in patents if p.parse_errors)

        return {
            "total": total,
            "fully_parsed": fully_parsed,
            "with_claims_tree": with_claims_tree,
            "with_description_sections": with_desc_sections,
            "with_problem_extracted": with_problem,
            "with_effects_extracted": with_effects,
            "with_errors": errors,
        }
