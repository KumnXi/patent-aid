"""
统一数据访问层

为所有核心分析模块提供统一的数据加载接口。
加载专利数据库索引、术语库、法律条文、效果描述模板等。
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


def ipc_to_list(raw) -> list:
    """将任意格式的 IPC 字段转为字符串列表（兼容 list/str）"""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(i).strip() for i in raw if str(i).strip()]
    return [i.strip() for i in re.split(r"[;；,，、\s]+", str(raw)) if i.strip()]


class DatabaseLoader:
    """统一数据加载器

    集中管理所有数据源的读取和缓存，为分析模块提供一致的数据接口。

    使用方式:
        loader = DatabaseLoader()
        patents = loader.get_patents_with_full_text()  # 19篇完整专利
        patent = loader.get_patent_by_id("CN121863439B")
        all_terms = loader.get_all_terminology()
        rejections = loader.get_rejection_patterns()
    """

    def __init__(self,
                 db_dir: str = "data/patent_database",
                 config_dir: str = "config"):
        """初始化数据加载器

        Args:
            db_dir: 专利数据库目录
            config_dir: 配置文件目录
        """
        self.db_dir = Path(db_dir)
        self.config_dir = Path(config_dir)

        # 缓存
        self._index_cache: Optional[Dict] = None
        self._terminology_cache: Optional[Dict] = None
        self._patent_law_cache: Optional[Dict] = None
        self._effect_cache: Optional[Dict] = None
        self._rejection_cache: Optional[Dict] = None
        self._templates_cache: Optional[Dict] = None
        self._forbidden_cache: Optional[Dict] = None

        # 加载核心数据
        self.index = self._load_index()

    # ═══════════════════════════════════════════════════════════════
    # 专利数据库
    # ═══════════════════════════════════════════════════════════════

    def _load_index(self) -> Dict:
        """加载专利数据库索引"""
        if self._index_cache is not None:
            return self._index_cache

        index_file = self.db_dir / "index.json"
        if not index_file.exists():
            self._index_cache = {"metadata": {}, "patents": {}, "keywords": {}, "applicants": {}}
            return self._index_cache

        with open(index_file, "r", encoding="utf-8") as f:
            self._index_cache = json.load(f)
        return self._index_cache

    def reload_index(self):
        """强制重新加载索引（数据库更新后调用）"""
        self._index_cache = None
        self.index = self._load_index()

    def get_patents_with_full_text(self) -> List[Dict]:
        """获取拥有完整文本（权利要求+说明书）的专利列表

        完整文本指数据库中内联存储了claims和description字段的专利。

        Returns:
            专利字典列表，每个包含完整的claims和description文本
        """
        result = []
        for pid, patent in self.index.get("patents", {}).items():
            if "claims" in patent and "description" in patent:
                result.append(patent)
        return result

    def get_patents_with_text_flag(self) -> List[Dict]:
        """获取has_claims=True且has_description=True的专利

        注意：这包含有flag但可能没有内联文本的专利（flag标记了API获取成功但文本可能未存储）
        """
        result = []
        for pid, patent in self.index.get("patents", {}).items():
            if patent.get("has_claims") and patent.get("has_description"):
                result.append(patent)
        return result

    def get_patent_by_id(self, patent_id: str) -> Optional[Dict]:
        """获取单个专利的完整数据

        Args:
            patent_id: 专利号（如 CN121863439B）

        Returns:
            专利数据字典，未找到返回None
        """
        patent_id = patent_id.strip().upper()
        return self.index.get("patents", {}).get(patent_id)

    def get_all_patents(self) -> Dict[str, Dict]:
        """获取所有专利（key为专利号）

        Returns:
            专利字典 {patent_id: patent_data}
        """
        return self.index.get("patents", {})

    def search_patents_by_keywords(self, keywords: List[str]) -> List[Dict]:
        """按关键词搜索专利

        在专利标题、权利要求、说明书中搜索关键词。

        Args:
            keywords: 关键词列表

        Returns:
            匹配的专利列表，按匹配度排序
        """
        results = []
        for pid, patent in self.index.get("patents", {}).items():
            score = 0
            title = patent.get("title", "")
            claims = patent.get("claims", "")
            desc = patent.get("description", "")

            search_text = f"{title} {str(claims)[:500]}"
            for kw in keywords:
                if kw in search_text:
                    score += 1

            if score > 0:
                results.append((score, patent))

        results.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in results]

    def get_patents_by_applicant(self, applicant_name: str) -> List[Dict]:
        """按申请人检索专利

        Args:
            applicant_name: 申请人名称（支持部分匹配）

        Returns:
            该申请人的专利列表
        """
        results = []
        for pid, patent in self.index.get("patents", {}).items():
            if applicant_name in patent.get("applicant", ""):
                results.append(patent)
        return results

    def get_patents_by_ipc(self, ipc_prefix: str) -> List[Dict]:
        """按IPC分类号检索专利

        Args:
            ipc_prefix: IPC前缀（如 "H02J"）

        Returns:
            该IPC分类下的专利列表
        """
        results = []
        for pid, patent in self.index.get("patents", {}).items():
            ipc_codes = ipc_to_list(patent.get("ipc", ""))
            if any(code.startswith(ipc_prefix) for code in ipc_codes):
                results.append(patent)
        return results

    def get_statistics(self) -> Dict:
        """获取数据库统计信息

        Returns:
            统计数据字典
        """
        patents = self.index.get("patents", {})
        total = len(patents)
        with_claims = sum(1 for p in patents.values() if "claims" in p)
        with_desc = sum(1 for p in patents.values() if "description" in p)
        with_both = sum(1 for p in patents.values()
                       if "claims" in p and "description" in p)
        flag_claims = sum(1 for p in patents.values() if p.get("has_claims"))
        flag_desc = sum(1 for p in patents.values() if p.get("has_description"))

        # IPC分布（取第一个分类号的小类）
        from collections import Counter
        ipcs = Counter(
            ipc_to_list(p.get("ipc", ""))[0][:4]
            for p in patents.values() if ipc_to_list(p.get("ipc", ""))
        )

        return {
            "total_patents": total,
            "with_claims_inline": with_claims,
            "with_description_inline": with_desc,
            "with_both_inline": with_both,
            "has_claims_flag": flag_claims,
            "has_description_flag": flag_desc,
            "ipc_distribution": dict(ipcs.most_common()),
            "database_updated": self.index.get("metadata", {}).get("updated", ""),
        }

    # ═══════════════════════════════════════════════════════════════
    # 术语库
    # ═══════════════════════════════════════════════════════════════

    def _load_terminology(self) -> Dict:
        """加载所有术语库文件"""
        if self._terminology_cache is not None:
            return self._terminology_cache

        self._terminology_cache = {}
        term_dir = self.config_dir / "terminology"

        if not term_dir.exists():
            return self._terminology_cache

        for json_file in term_dir.glob("*.json"):
            domain = json_file.stem  # 文件名作为领域名
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._terminology_cache[domain] = data
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

        return self._terminology_cache

    def get_all_terminology(self) -> Dict[str, List[Dict]]:
        """获取所有术语

        Returns:
            {领域名: [术语条目列表], ...}
        """
        terminology = self._load_terminology()
        result = {}
        for domain, data in terminology.items():
            if isinstance(data, list):
                result[domain] = data
            elif isinstance(data, dict) and "terms" in data:
                # 处理嵌套结构: {"metadata": {...}, "terms": [...]}
                result[domain] = data["terms"]
        return result

    def get_all_terms_flat(self) -> List[Dict]:
        """获取所有术语的扁平列表

        Returns:
            术语条目列表
        """
        all_terms = []
        for domain, data in self._load_terminology().items():
            if isinstance(data, list):
                all_terms.extend(data)
        return all_terms

    def get_term_by_name(self, term_name: str) -> Optional[Dict]:
        """按术语名称查找术语条目

        Args:
            term_name: 术语名称

        Returns:
            术语条目字典
        """
        for domain, data in self._load_terminology().items():
            if isinstance(data, list):
                for entry in data:
                    if entry.get("term") == term_name:
                        return entry
                    if term_name in entry.get("aliases", []):
                        return entry
        return None

    def get_forbidden_words(self) -> Dict:
        """获取禁用词库

        Returns:
            禁用词分类数据
        """
        if self._forbidden_cache is not None:
            return self._forbidden_cache

        term_dir = self.config_dir / "terminology"
        forbidden_file = term_dir / "forbidden.json"

        if forbidden_file.exists():
            with open(forbidden_file, "r", encoding="utf-8") as f:
                self._forbidden_cache = json.load(f)
        else:
            self._forbidden_cache = {"categories": []}

        return self._forbidden_cache

    def get_all_forbidden_terms(self) -> List[Dict]:
        """获取所有禁用词的扁平列表

        Returns:
            禁用词列表，每项含 forbidden, correct, reason 字段
        """
        forbidden_data = self.get_forbidden_words()
        all_forbidden = []
        for cat in forbidden_data.get("categories", []):
            for ft in cat.get("forbidden_terms", []):
                ft["category"] = cat.get("category", "")
                all_forbidden.append(ft)
        return all_forbidden

    # ═══════════════════════════════════════════════════════════════
    # 专利法律条文和驳回原因
    # ═══════════════════════════════════════════════════════════════

    def get_patent_law(self) -> Dict:
        """获取专利法相关条文

        Returns:
            专利法条文数据
        """
        if self._patent_law_cache is not None:
            return self._patent_law_cache

        law_dir = self.config_dir / "patent_law"
        law_file = law_dir / "patent_law.json"

        if law_file.exists():
            with open(law_file, "r", encoding="utf-8") as f:
                self._patent_law_cache = json.load(f)
        else:
            self._patent_law_cache = {"articles": []}

        return self._patent_law_cache

    def get_rejection_patterns(self) -> List[Dict]:
        """获取常见驳回原因列表

        Returns:
            驳回原因列表，每项含 legal_basis, description, symptoms, prevention
        """
        if self._rejection_cache is not None:
            return self._rejection_cache

        law_dir = self.config_dir / "patent_law"
        rej_file = law_dir / "common_rejections.json"

        if rej_file.exists():
            with open(rej_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._rejection_cache = data.get("rejections", [])
        else:
            self._rejection_cache = []

        return self._rejection_cache

    # ═══════════════════════════════════════════════════════════════
    # 技术效果描述模板
    # ═══════════════════════════════════════════════════════════════

    def get_effect_templates(self) -> Dict:
        """获取技术效果描述模板

        Returns:
            {通用效果: 模板, 电力效果: 模板, 量化指南: 规则}
        """
        if self._effect_cache is not None:
            return self._effect_cache

        self._effect_cache = {}
        effect_dir = self.config_dir / "effect_descriptions"

        if effect_dir.exists():
            for json_file in effect_dir.glob("*.json"):
                key = json_file.stem
                with open(json_file, "r", encoding="utf-8") as f:
                    self._effect_cache[key] = json.load(f)

        return self._effect_cache

    # ═══════════════════════════════════════════════════════════════
    # 模板
    # ═══════════════════════════════════════════════════════════════

    def get_template(self, template_name: str) -> Optional[str]:
        """获取指定模板的文本内容

        Args:
            template_name: 模板文件名（不含路径）

        Returns:
            模板文本内容
        """
        if self._templates_cache is None:
            self._templates_cache = {}

        if template_name in self._templates_cache:
            return self._templates_cache[template_name]

        template_path = self.config_dir.parent / "templates" / template_name
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._templates_cache[template_name] = content
            return content

        return None

    # ═══════════════════════════════════════════════════════════════
    # 审查案例
    # ═══════════════════════════════════════════════════════════════

    def get_review_cases(self) -> Dict:
        """获取审查案例数据

        Returns:
            审查案例数据库
        """
        case_file = self.config_dir / "review_cases" / "cases.json"
        if case_file.exists():
            with open(case_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"cases": [], "learning_points": {}}

    # ═══════════════════════════════════════════════════════════════
    # 摘要方法
    # ═══════════════════════════════════════════════════════════════

    def get_data_summary(self) -> str:
        """生成数据库状态摘要

        Returns:
            可读的摘要字符串
        """
        stats = self.get_statistics()
        lines = [
            f"专利数据库状态 (更新于 {stats['database_updated'][:10]})",
            f"  总专利数: {stats['total_patents']}",
            f"  有完整内联文本(claims+description): {stats['with_both_inline']}",
            f"  有has_claims/description标记: {stats['has_claims_flag']}",
            f"  IPC分布: {stats['ipc_distribution']}",
        ]
        return "\n".join(lines)
