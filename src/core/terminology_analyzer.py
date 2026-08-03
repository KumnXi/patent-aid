"""
术语使用分析器

从授权专利的实际文本中学习术语使用规范：
- 术语的上下文搭配模式
- 术语首次出现时的介绍方式
- 发现新术语（未在现有术语库中的高频技术词）
- 术语使用建议

数据溯源: 所有分析结果标注 source_patents。
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Set
from collections import Counter, defaultdict

from src.parsers.patent_parser import StructuredPatent
from src.core.database_loader import DatabaseLoader
from src.utils.text_utils import ChineseTextProcessor


class TerminologyAnalyzer:
    """术语使用分析器

    从实际专利文本中学习术语的规范使用方式。

    使用方式:
        analyzer = TerminologyAnalyzer()
        analyzer.build_corpus(patents)
        usage = analyzer.get_term_usage("虚拟电厂")
        recommendations = analyzer.recommend_terminology("负荷响应")
    """

    def __init__(self, db_loader: DatabaseLoader = None):
        self.db_loader = db_loader or DatabaseLoader()
        self.text_processor = ChineseTextProcessor()

        # 术语使用语料库 {术语: TermUsage}
        self.term_corpus: Dict[str, Dict] = {}

        # 术语搭配统计
        self.collocations: Dict[str, Counter] = defaultdict(Counter)

        # 术语在专利中出现频率 {术语: 专利数}
        self.term_frequency: Counter = Counter()

    def build_corpus(self, patents: List[StructuredPatent]):
        """从专利列表构建术语使用语料库

        Args:
            patents: 结构化专利列表
        """
        # 获取已知术语
        all_terms = self._get_all_known_terms()

        for p in patents:
            if not p.is_parsed:
                continue

            # 收集专利的所有文本
            texts = self._collect_patent_texts(p)

            for term in all_terms:
                if term not in texts:
                    continue

                self.term_frequency[term] += 1

                if term not in self.term_corpus:
                    self.term_corpus[term] = {
                        "term": term,
                        "contexts": [],
                        "sections": defaultdict(int),
                        "first_appearances": [],
                    }

                corpus = self.term_corpus[term]

                # 提取术语出现的上下文（前后各30字符）
                idx = texts.find(term)
                start = max(0, idx - 30)
                end = min(len(texts), idx + len(term) + 30)
                context = texts[start:end].replace('\n', ' ')
                if len(context) > 20:
                    corpus["contexts"].append(context[:200])

                # 统计术语在各章节的出现次数
                sections = self._find_term_sections(term, p)
                for section_name, count in sections.items():
                    corpus["sections"][section_name] += count

                # 记录术语首次出现时的介绍模式
                first_app = self._detect_first_appearance_pattern(term, p)
                if first_app:
                    corpus["first_appearances"].append(first_app)

        # 分析搭配模式
        self._analyze_collocations(patents, all_terms)

    def _get_all_known_terms(self) -> Set[str]:
        """获取所有已知术语的集合"""
        all_terms = set()
        for domain, terms in self.db_loader.get_all_terminology().items():
            for entry in terms:
                all_terms.add(entry.get("term", ""))
                for alias in entry.get("aliases", []):
                    all_terms.add(alias)
        return all_terms - {""}

    def _collect_patent_texts(self, patent: StructuredPatent) -> str:
        """收集专利的所有文本内容

        Args:
            patent: 结构化专利

        Returns:
            合并后的文本
        """
        parts = [patent.title]
        if patent.description_sections:
            ds = patent.description_sections
            parts.extend([
                ds.technical_field,
                ds.background,
                ds.invention_content,
                ds.detailed_implementation,
            ])
        parts.append(patent.claims_raw)
        return " ".join(parts)

    def _find_term_sections(self, term: str, patent: StructuredPatent) -> Dict[str, int]:
        """查找术语在各说明书中章节的出现次数

        Args:
            term: 术语
            patent: 结构化专利

        Returns:
            {章节名: 次数}
        """
        counts = {}
        if not patent.description_sections:
            return counts

        ds = patent.description_sections
        sections = {
            "technical_field": ds.technical_field,
            "background": ds.background,
            "invention_content": ds.invention_content,
            "detailed_implementation": ds.detailed_implementation,
        }

        for section_name, text in sections.items():
            count = text.count(term)
            if count > 0:
                counts[section_name] = count

        return counts

    def _detect_first_appearance_pattern(self, term: str,
                                        patent: StructuredPatent) -> Optional[str]:
        """检测术语在专利中首次出现时的介绍模式

        中国专利中术语的常见引入方式:
        - "所述[术语]..."（权利要求的典型用法）
        - "[全称]（以下简称[简称]）..."（缩写引入）
        - "[术语]，即..."（定义式引入）

        Args:
            term: 术语
            patent: 结构化专利

        Returns:
            首次出现模式的描述
        """
        if not patent.description_sections:
            return None

        ds = patent.description_sections
        # 从背景技术开始搜索
        search_text = ds.background + ds.invention_content

        idx = search_text.find(term)
        if idx < 0:
            return None

        # 取首次出现位置前后100字符
        start = max(0, idx - 50)
        end = min(len(search_text), idx + len(term) + 50)
        snippet = search_text[start:end].strip()

        # 检测引入模式
        patterns = []
        if re.search(r'所述\s*' + re.escape(term), snippet):
            patterns.append("权利要求式引用")
        if re.search(r'[（\(]以下简称.*' + re.escape(term), snippet):
            patterns.append("缩写定义式")
        if re.search(re.escape(term) + r'\s*[，,即].*指', snippet):
            patterns.append("定义式引入")
        if re.search(r'(?:属于|涉及|用于).*' + re.escape(term), snippet):
            patterns.append("领域归属式")

        if not patterns:
            patterns.append("直接使用式")

        return "|".join(patterns)

    def _analyze_collocations(self, patents: List[StructuredPatent],
                             all_terms: Set[str]):
        """分析术语的搭配模式

        统计术语前后相邻的词，识别常见搭配。

        Args:
            patents: 结构化专利列表
            all_terms: 所有已知术语
        """
        for p in patents:
            if not p.is_parsed:
                continue
            text = self._collect_patent_texts(p)

            for term in all_terms:
                if term not in text:
                    continue

                # 查找术语的所有出现位置
                idx = 0
                while True:
                    idx = text.find(term, idx)
                    if idx < 0:
                        break

                    # 提取术语前后的词（使用jieba分词）
                    before = text[max(0, idx-10):idx]
                    after = text[idx+len(term):min(len(text), idx+len(term)+10)]

                    for w in self.text_processor.segment_words(before):
                        if len(w) >= 2:
                            self.collocations[term][f"前→{w}"] += 1

                    for w in self.text_processor.segment_words(after):
                        if len(w) >= 2:
                            self.collocations[term][f"后→{w}"] += 1

                    idx += len(term)

    def get_term_usage(self, term: str) -> Optional[Dict]:
        """获取特定术语的使用情况

        Args:
            term: 术语名称

        Returns:
            使用情况字典
        """
        if term not in self.term_corpus:
            return None

        corpus = self.term_corpus[term]
        return {
            "term": term,
            "frequency": self.term_frequency.get(term, 0),
            "common_contexts": corpus.get("contexts", [])[:5],
            "section_distribution": dict(corpus.get("sections", {})),
            "introduction_patterns": Counter(corpus.get("first_appearances", [])).most_common(5),
            "common_collocations": self.collocations.get(term, Counter()).most_common(10),
        }

    def discover_new_terms(self, patents: List[StructuredPatent],
                          min_freq: int = 3) -> List[Dict]:
        """从专利文本中发现新的高频术语

        通过TF-IDF提取高频词，过滤已知术语，发现潜在的领域新术语。

        Args:
            patents: 结构化专利列表
            min_freq: 最低出现频次

        Returns:
            新术语候选列表
        """
        known_terms = self._get_all_known_terms()

        # 统计所有分词的出现频率
        word_counter = Counter()
        for p in patents:
            if not p.is_parsed:
                continue
            text = self._collect_patent_texts(p)
            words = self.text_processor.segment_words(text)
            # 只统计2字以上的词
            long_words = [w for w in words if len(w) >= 2]
            word_counter.update(long_words)

        # 过滤已知术语和通用词
        new_terms = []
        for word, freq in word_counter.most_common(50):
            if word in known_terms:
                continue
            if freq < min_freq:
                continue
            # 过滤通用的中文词
            if any(common in word for common in
                  ["所述", "包括", "用于", "一个", "进行", "获取", "其中", "以及"]):
                continue

            new_terms.append({
                "term": word,
                "frequency": freq,
                "suggestion": f"建议评估是否将'{word}'加入术语库",
            })

        return new_terms

    def recommend_terminology(self, tech_concept: str) -> Dict:
        """为技术概念推荐标准术语和规范表述

        Args:
            tech_concept: 用户使用的不规范表述

        Returns:
            术语建议
        """
        # 检查禁用词
        forbidden_data = self.db_loader.get_forbidden_words()
        for cat in forbidden_data.get("categories", []):
            for ft in cat.get("forbidden_terms", []):
                if ft["forbidden"] in tech_concept:
                    return {
                        "detected": ft["forbidden"],
                        "recommended": ft["correct"],
                        "reason": ft.get("reason", ""),
                        "category": cat.get("category", ""),
                        "issue_type": "forbidden",
                    }

        # 在术语库中查找最佳匹配
        all_terms = self.db_loader.get_all_terms_flat()
        best_match = None
        best_score = 0

        for entry in all_terms:
            term = entry.get("term", "")
            # 简单的文本重叠度匹配
            score = len(set(tech_concept) & set(term)) / max(len(set(tech_concept) | set(term)), 1)
            if score > best_score and score > 0.3:
                best_score = score
                best_match = entry

        if best_match:
            return {
                "detected": tech_concept,
                "recommended": best_match.get("term", tech_concept),
                "definition": best_match.get("definition", ""),
                "standard": best_match.get("standards", []),
                "usage_notes": best_match.get("usage_notes", ""),
                "issue_type": "suggestion",
            }

        return {
            "detected": tech_concept,
            "recommended": tech_concept,
            "message": "未在术语库中找到匹配，建议确认是否需要新增术语",
            "issue_type": "unknown",
        }

    def get_analysis_report(self) -> str:
        """生成术语分析报告"""
        lines = [
            "# 术语使用分析报告",
            "",
            f"## 语料库概况",
            f"- 已分析术语数: {len(self.term_corpus)}",
            f"- 总出现频次: {sum(self.term_frequency.values())}",
            "",
            "## 高频术语 Top 20",
            "",
            "| 术语 | 出现专利数 | 主要出现章节 |",
            "|------|-----------|------------|",
        ]

        for term, freq in self.term_frequency.most_common(20):
            corpus = self.term_corpus.get(term, {})
            sections = corpus.get("sections", {})
            top_section = max(sections, key=sections.get) if sections else "N/A"
            lines.append(f"| {term} | {freq} | {top_section} |")

        return "\n".join(lines)


