"""
中文专利文本处理工具

提供HTML标签清理、中文分句分词、段落提取等功能。
所有文本处理模块共享此工具，确保处理逻辑一致。
"""

import re
import json
import os
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import jieba


# ═══════════════════════════════════════════════════════════
# IPC 字段兼容工具（数据库治理后 ipc 为列表，旧数据可能是字符串）
# ═══════════════════════════════════════════════════════════

def ipc_to_list(raw) -> list:
    """将任意格式的 IPC 字段转为字符串列表"""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(i).strip() for i in raw if str(i).strip()]
    return [i.strip() for i in re.split(r"[;；,，、\s]+", str(raw)) if i.strip()]


def ipc_to_str(raw) -> str:
    """将任意格式的 IPC 字段转为分号分隔字符串"""
    return ";".join(ipc_to_list(raw))


class ChineseTextProcessor:
    """中文专利文本处理器

    处理专利文本的HTML标签、分句、分词等。
    自动加载电力领域术语库作为jieba自定义词典，提升分词准确率。

    使用方式:
        processor = ChineseTextProcessor(terminology_dir="config/terminology")
        clean_text = processor.clean_html(raw_html)
        sentences = processor.split_sentences(clean_text)
        words = processor.segment_words("虚拟电厂负荷响应方法")
        # => ["虚拟电厂", "负荷", "响应", "方法"]
    """

    def __init__(self, terminology_dir: str = "config/terminology"):
        """初始化文本处理器，加载电力领域术语作为自定义词典

        Args:
            terminology_dir: 术语库目录路径
        """
        self.terminology_dir = Path(terminology_dir)
        self._load_terminology_dict()

    def _load_terminology_dict(self):
        """加载所有术语JSON文件，将术语和别名注册为jieba自定义词典

        自定义词典确保jieba不拆分专业术语，例如:
        - "虚拟电厂" 不会被拆为 "虚拟" + "电厂"
        - "差动保护" 不会被拆为 "差动" + "保护"
        """
        self.known_terms: Dict[str, Dict] = {}
        self.term_set: set = set()

        if not self.terminology_dir.exists():
            return

        for json_file in self.terminology_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            # 处理标准格式: [{"term": "...", "aliases": [...], ...}, ...]
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and "term" in entry:
                        term = entry["term"]
                        self.known_terms[term] = entry
                        self.term_set.add(term)
                        jieba.add_word(term, freq=100)

                        # 别名也加入词典
                        for alias in entry.get("aliases", []):
                            self.term_set.add(alias)
                            jieba.add_word(alias, freq=80)

            # 处理forbidden.json的特殊格式
            elif isinstance(data, dict) and "categories" in data:
                for cat in data["categories"]:
                    for ft in cat.get("forbidden_terms", []):
                        forbidden = ft.get("forbidden", "")
                        correct = ft.get("correct", "")
                        if forbidden and correct:
                            self.term_set.add(forbidden)
                            self.term_set.add(correct)

    def clean_html(self, text: str) -> str:
        """清理HTML标签，转换换行符

        专利权利要求通常以HTML格式存储，使用<br/>作为换行。
        说明书可能包含其他HTML实体。

        Args:
            text: 原始HTML文本

        Returns:
            清理后的纯文本
        """
        if not text:
            return ""

        # 替换常见HTML换行标签
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<br\s+/>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '', text, flags=re.IGNORECASE)

        # 移除其他HTML标签
        text = re.sub(r'<[^>]+>', '', text)

        # 处理HTML实体
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&amp;', '&')
        text = text.replace('&quot;', '"')

        # 规范化空白字符：合并连续空行，但保留段落分隔
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +\n', '\n', text)

        return text.strip()

    def split_sentences(self, text: str) -> List[str]:
        """中文分句

        按句号、分号、问号、感叹号等标点拆分句子。
        特殊处理专利文本中的编号格式。

        Args:
            text: 输入文本

        Returns:
            句子列表
        """
        if not text:
            return []

        # 先保护专利段落编号 [NNNN]，避免被拆分
        placeholder_map = {}
        def _protect_marker(match):
            key = f"__MARKER_{len(placeholder_map)}__"
            placeholder_map[key] = match.group(0)
            return key
        text = re.sub(r'\[\d{4}\]', _protect_marker, text)

        # 中文分句：在句号、问号、感叹号后切分（但不能在数字小数点处切分）
        # 分号也作为切分点，但仅当后面是换行或中文字符时
        sentences = re.split(r'(?<=[。？！])(?![\d])', text)

        result = []
        for sent in sentences:
            # 按分号进一步切分（仅在长句中）
            if len(sent) > 100:
                sub_sents = re.split(r'(?<=[；;])(?=\s*[一-鿿])', sent)
                result.extend(sub_sents)
            else:
                result.append(sent)

        # 恢复段落编号
        result = [self._restore_placeholders(s, placeholder_map) for s in result]

        # 过滤空句子和纯空白句子
        return [s.strip() for s in result if s.strip()]

    def _restore_placeholders(self, text: str, placeholder_map: Dict[str, str]) -> str:
        """恢复被保护的占位符"""
        for key, value in placeholder_map.items():
            text = text.replace(key, value)
        return text

    def segment_words(self, text: str) -> List[str]:
        """中文分词

        使用jieba进行分词，过滤停用词和标点。
        由于已加载电力领域自定义词典，专业术语不会被拆分。

        Args:
            text: 输入文本

        Returns:
            分词结果列表
        """
        if not text:
            return []

        # 移除段落编号标记以提升分词质量
        text_clean = re.sub(r'\[\d{4}\]', '', text)

        words = jieba.lcut(text_clean)

        # 过滤：去除纯标点、单字符（除英文字母外）、空白
        filtered = []
        for w in words:
            w = w.strip()
            if not w:
                continue
            if len(w) == 1 and not w.isalpha():
                continue
            # 过滤纯数字
            if w.isdigit() and len(w) <= 2:
                continue
            filtered.append(w)

        return filtered

    def extract_paragraphs(self, text: str,
                           section_marker: str = r'\[\d{4}\]') -> List[Tuple[str, str]]:
        """按段落标记拆分专利说明书

        中国专利说明书使用 [0001], [0002]... 标记段落编号。
        返回 (段落编号, 段落文本) 的列表。

        Args:
            text: 说明书文本
            section_marker: 段落标记的正则表达式

        Returns:
            [(段落编号, 段落文本), ...] 列表
        """
        if not text:
            return []

        # 按 [NNNN] 标记拆分
        pattern = r'(\[\d{4}\])'
        parts = re.split(pattern, text)

        paragraphs = []
        i = 0
        # 跳过第一个标记前的内容（通常是标题行）
        while i < len(parts):
            if re.match(section_marker, parts[i]):
                marker = parts[i]
                content = parts[i + 1].strip() if i + 1 < len(parts) else ""
                paragraphs.append((marker, content))
                i += 2
            else:
                i += 1

        return paragraphs

    def extract_keywords_tfidf(self, texts: List[str],
                               top_k: int = 10) -> List[str]:
        """使用TF-IDF从文本列表中提取关键词

        Args:
            texts: 文本列表
            top_k: 返回前k个关键词

        Returns:
            关键词列表（按重要性降序）
        """
        from sklearn.feature_extraction.text import TfidfVectorizer

        if not texts:
            return []

        # 对每个文本进行分词
        segmented = [" ".join(self.segment_words(t)) for t in texts]

        vectorizer = TfidfVectorizer(max_features=top_k * 3)
        try:
            tfidf_matrix = vectorizer.fit_transform(segmented)
            feature_names = vectorizer.get_feature_names_out()

            # 取平均TF-IDF得分最高的词
            mean_scores = tfidf_matrix.mean(axis=0).A1
            top_indices = mean_scores.argsort()[-top_k:][::-1]

            return [feature_names[i] for i in top_indices]
        except ValueError:
            # 文本太少时fallback
            return []

    def normalize_patent_id(self, patent_id: str) -> str:
        """标准化专利号格式

        Args:
            patent_id: 原始专利号

        Returns:
            标准化后的专利号（大写，去除空格）
        """
        if not patent_id:
            return ""
        return patent_id.strip().upper().replace(" ", "")

    def detect_formulas(self, text: str) -> List[str]:
        """检测文本中的数学公式或表达式

        识别包含希腊字母、数学符号、LaTeX风格的公式。

        Args:
            text: 输入文本

        Returns:
            检测到的公式列表
        """
        formulas = []

        # 模式1: 包含希腊字母的文本片段
        greek_pattern = re.compile(
            r'[Ͱ-Ͽ∀-⋿]+'  # 希腊字母和数学运算符
        )

        # 模式2: 包含分数、上标、下标等数学符号的文本
        math_pattern = re.compile(
            r'(?:[A-Za-z]\s*[=≈≠≤≥<>]\s*.+)|'  # 等式/不等式
            r'(?:[∑∏∫∂√∞].+)|'                   # 数学符号开头
            r'(?:\d+(?:\.\d+)?\s*[+\-×÷]\s*\d+(?:\.\d+)?)'  # 算术表达式
        )

        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if greek_pattern.search(line) or math_pattern.search(line):
                if len(line) > 5:  # 过滤过短的匹配
                    formulas.append(line)

        return formulas

    def is_technical_sentence(self, sentence: str) -> bool:
        """判断一个句子是否是技术性描述

        用于过滤专利文本中的非技术内容（如法律声明、格式标记等）。

        Args:
            sentence: 待判断的句子

        Returns:
            True表示该句子包含技术内容
        """
        if not sentence or len(sentence) < 5:
            return False

        # 非技术内容的特征
        non_tech_patterns = [
            r'^\[\d{4}\]$',           # 纯段落编号
            r'^本[发明申请].*涉及',    # 过度通用的引入句（保留"具体的"引入句）
            r'^附图说明$',
            r'^图\d+[为是]',          # 纯附图标记
        ]

        for pat in non_tech_patterns:
            if re.match(pat, sentence):
                return False

        return True
