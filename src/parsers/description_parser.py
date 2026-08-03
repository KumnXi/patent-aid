"""
说明书解析器

解析中国专利说明书文本，按[NNNN]段落编号拆分章节，
提取技术问题、技术方案、技术效果、具体实施方式等结构化信息。

中国专利说明书标准结构:
[0001] 技术领域
[0002]-[0003] 背景技术
[0004]-[0037] 发明内容（含发明目的、技术方案、有益效果）
[0038]-[0041] 附图说明
[0042]-[0081] 具体实施方式
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from src.utils.text_utils import ChineseTextProcessor


@dataclass
class DescriptionSections:
    """说明书各章节结构化数据"""
    patent_id: str = ""

    # 各章节原始文本
    technical_field: str = ""          # 技术领域
    background: str = ""               # 背景技术
    invention_content: str = ""        # 发明内容
    drawings_description: str = ""     # 附图说明
    detailed_implementation: str = ""  # 具体实施方式
    abstract_text: str = ""            # 摘要

    # 从发明内容中提取的细分
    invention_purpose: str = ""        # 发明目的/要解决的技术问题
    technical_solution_summary: str = ""  # 技术方案概述
    beneficial_effects: List[str] = field(default_factory=list)  # 有益效果列表

    # 从背景技术中提取的
    existing_problems: List[str] = field(default_factory=list)   # 现有技术问题
    existing_solutions: List[str] = field(default_factory=list)  # 现有方案描述

    # 从具体实施方式中提取的
    embodiments: List[Dict] = field(default_factory=list)        # 实施例
    formulas: List[str] = field(default_factory=list)            # 数学公式

    # 元数据
    paragraph_count: int = 0
    section_boundaries: Dict[str, Tuple[int, int]] = field(default_factory=dict)


class DescriptionParser:
    """说明书解析器

    解析中国专利说明书文本，按章节拆分并提取结构化信息。

    使用方式:
        parser = DescriptionParser()
        sections = parser.parse("CN121863439B", raw_description_text)
        print(f"技术问题: {sections.invention_purpose}")
        print(f"效果数量: {len(sections.beneficial_effects)}")
    """

    def __init__(self):
        self.text_processor = ChineseTextProcessor()

    def parse(self, patent_id: str, desc_raw: str) -> DescriptionSections:
        """解析说明书文本为结构化章节

        Args:
            patent_id: 专利号
            desc_raw: 原始说明书文本

        Returns:
            结构化的说明书各章节
        """
        sections = DescriptionSections(patent_id=patent_id)

        if not desc_raw:
            return sections

        # 清理HTML
        clean_text = self.text_processor.clean_html(desc_raw)

        # 提取标题行（第一行，在[0001]之前的内容）
        first_marker_pos = clean_text.find('[0001]')
        if first_marker_pos > 0:
            title_line = clean_text[:first_marker_pos].strip()
            sections.abstract_text = title_line

        # 按[NNNN]标记拆分段落
        paragraphs = self.text_processor.extract_paragraphs(clean_text)
        sections.paragraph_count = len(paragraphs)

        if paragraphs:
            # 分类段落到对应章节
            section_map = self._classify_paragraphs(paragraphs, sections)
            # 填充各章节文本
            self._fill_sections(sections, section_map)
        else:
            # 回退路径：无[NNNN]标记的连续文本（Google Patents/PDF抽取格式，约占93%）
            self._fill_sections_plain_text(sections, clean_text)

        # 深度分析各章节
        self._analyze_background(sections)
        self._analyze_invention_content(sections)
        self._analyze_detailed_implementation(sections)
        self._extract_formulas_from_all(sections)

        return sections

    # ═══════════════════════════════════════════════════════════════
    # 段落分类
    # ═══════════════════════════════════════════════════════════════

    def _classify_paragraphs(self, paragraphs: List[Tuple[str, str]],
                            sections: DescriptionSections) -> Dict[str, List[Tuple[str, str]]]:
        """将段落按内容分类到不同的章节

        使用章节标题关键词和段落编号范围双重策略进行分类。

        Args:
            paragraphs: [(段落编号, 段落文本), ...] 列表
            sections: DescriptionSections实例（用于记录边界信息）

        Returns:
            {章节名: [(编号, 文本), ...]} 的字典
        """

        # 第一遍：按关键词检测章节边界
        boundaries = self._detect_section_boundaries(paragraphs)

        # 记录边界信息
        sections.section_boundaries = {
            name: (indices[0], indices[-1]) if indices else (0, 0)
            for name, indices in boundaries.items()
        }

        # 按边界分配合并段落
        result = {
            "technical_field": [],
            "background": [],
            "invention_content": [],
            "drawings_description": [],
            "detailed_implementation": [],
        }

        current_section = "technical_field"

        # 第二遍：根据已知边界分配段落
        # 从段落编号推断章节位置
        for marker, text in paragraphs:
            try:
                para_num = int(marker.strip('[]'))
            except ValueError:
                continue

            section = self._classify_by_number(para_num, boundaries, marker, text)
            if section in result:
                result[section].append((marker, text))

        return result

    def _detect_section_boundaries(self, paragraphs: List[Tuple[str, str]]) -> Dict[str, List[int]]:
        """检测各章节的起始段落编号

        通过关键词匹配识别章节边界。

        Args:
            paragraphs: [(编号, 文本), ...] 列表

        Returns:
            {章节名: [段落索引列表]}
        """
        boundaries = {
            "technical_field": [],
            "background": [],
            "invention_content": [],
            "drawings_description": [],
            "detailed_implementation": [],
        }

        section_keywords = {
            "technical_field": ["技术领域", "本发明属于", "本发明涉及"],
            "background": ["背景技术", "现有技术"],
            "invention_content": ["发明内容", "本发明提供", "本发明提出",
                                  "本发明解决", "本发明采用"],
            "drawings_description": ["附图说明", "图1", "图2"],
            "detailed_implementation": ["具体实施方式", "实施方式", "实施例",
                                       "下面结合附图", "为使本发明的"],
        }

        for marker, text in paragraphs:
            text_head = text[:30]  # 段落的开头部分通常包含章节标记

            for section_name, keywords in section_keywords.items():
                for kw in keywords:
                    if kw in text_head:
                        try:
                            para_num = int(marker.strip('[]'))
                            boundaries[section_name].append(para_num)
                        except ValueError:
                            pass
                        break

        return boundaries

    def _classify_by_number(self, para_num: int,
                            boundaries: Dict[str, List[int]],
                            marker: str, text: str) -> str:
        """根据段落编号判断属于哪个章节

        策略：检测边界与规范默认编号"取较早者"，并强制各章节起点**单调递增**，
        避免部分章节检测到边界、其余章节缺失时出现空区间/倒挂
        （如 background 检测到第6段、invention_content 未检测到用默认4，导致背景为空）。

        Args:
            para_num: 段落编号（整数）
            boundaries: 检测到的章节边界
            marker: 段落编号标记（如 [0001]）
            text: 段落文本

        Returns:
            章节名
        """
        defaults = {
            "technical_field": 1,
            "background": 2,
            "invention_content": 4,
            "drawings_description": 38,
            "detailed_implementation": 42,
        }
        order = ["technical_field", "background", "invention_content",
                 "drawings_description", "detailed_implementation"]

        # 各章节起始编号：检测边界与规范默认取较早者，并保证单调递增
        starts = {}
        prev = 0
        for sec in order:
            detected = min(boundaries.get(sec) or [defaults[sec]])
            start = max(min(detected, defaults[sec]), prev + 1)
            starts[sec] = start
            prev = start

        # 归类：起点 <= para_num 的最后一个章节
        best = "technical_field"
        for sec in order:
            if para_num >= starts[sec]:
                best = sec
        return best

    # ═══════════════════════════════════════════════════════════════
    # 章节文本填充
    # ═══════════════════════════════════════════════════════════════

    def _fill_sections(self, sections: DescriptionSections,
                      section_map: Dict[str, List[Tuple[str, str]]]):
        """将分类后的段落文本填充到DescriptionSections各字段

        Args:
            sections: DescriptionSections实例（原地修改）
            section_map: {章节名: [(编号, 文本), ...]} 字典
        """
        for section_name, para_list in section_map.items():
            text = "\n".join(text for _, text in para_list)
            setattr(sections, section_name, text)

    def _fill_sections_plain_text(self, sections: DescriptionSections,
                                  clean_text: str):
        """回退路径：填充无[NNNN]标记的连续文本（Google Patents/PDF抽取格式）

        按章节标题词（背景技术/发明内容/附图说明/具体实施方式）切分；
        找不到任何标题时，整段归入具体实施方式，保证全文仍可被 RAG 检索。

        Args:
            sections: DescriptionSections实例（原地修改）
            clean_text: 清理后的说明书全文
        """
        if not clean_text:
            return

        headers = [
            ("background", "背景技术"),
            ("invention_content", "发明内容"),
            ("drawings_description", "附图说明"),
            ("detailed_implementation", "具体实施方式"),
        ]

        # 收集各章节标题首次出现位置（同章节保留最早位置）
        found = []
        for name, kw in headers:
            pos = clean_text.find(kw)
            if pos >= 0:
                found.append((pos, name, kw))
        found.sort()

        unique = {}
        for pos, name, kw in found:
            if name not in unique:
                unique[name] = (pos, kw)

        if not unique:
            # 无任何章节标题：整段作为实施方式，供全文检索
            if len(clean_text) > 50:
                sections.detailed_implementation = clean_text
            return

        # 标题之前的文本归入技术领域/引子
        ordered = sorted(unique.items(), key=lambda x: x[1][0])
        first_pos = ordered[0][1][0]
        if first_pos > 0:
            sections.technical_field = clean_text[:first_pos].strip()

        # 按标题切分各章节（去掉标题词本身）
        for i, (name, (pos, kw)) in enumerate(ordered):
            end = ordered[i + 1][1][0] if i + 1 < len(ordered) else len(clean_text)
            text = clean_text[pos + len(kw):end].strip()
            if text:
                setattr(sections, name, text)

    # ═══════════════════════════════════════════════════════════════
    # 背景技术分析
    # ═══════════════════════════════════════════════════════════════

    def _analyze_background(self, sections: DescriptionSections):
        """分析背景技术章节，提取现有技术问题和现有方案

        Args:
            sections: DescriptionSections实例（原地修改）
        """
        bg_text = sections.background
        if not bg_text:
            return

        # 提取现有方案描述（通常包含"目前"、"现有"、"传统"等关键词的句子）
        existing_patterns = re.findall(
            r'(?:目前|现有|传统|当前|常规)(?:的|技术中，|方法中，)?'
            r'[^。！？\n]{20,200}[。！？]',
            bg_text
        )
        sections.existing_solutions = [p.strip() for p in existing_patterns]

        # 提取现有技术的问题（通常包含"缺点"、"不足"、"问题"、"缺陷"、"导致"等）
        problem_patterns = re.findall(
            r'(?:但是|然而|但|其|该方法|该方案|该技术|现有技术)?'
            r'[^。！？\n]*(?:不足|缺陷|问题|缺点|导致|制约|限制|难以|无法|不能|'
            r'误差|偏差|振荡|不稳定|失衡|错配|降低)[^。！？\n]{10,200}[。！？]',
            bg_text
        )
        sections.existing_problems = [p.strip() for p in problem_patterns]

    # ═══════════════════════════════════════════════════════════════
    # 发明内容分析
    # ═══════════════════════════════════════════════════════════════

    def _analyze_invention_content(self, sections: DescriptionSections):
        """分析发明内容章节，提取发明目的、技术方案和有益效果

        Args:
            sections: DescriptionSections实例（原地修改）
        """
        content = sections.invention_content
        if not content:
            return

        # 提取发明目的/要解决的技术问题
        sections.invention_purpose = self._extract_invention_purpose(content)

        # 提取技术方案概述
        sections.technical_solution_summary = self._extract_solution_summary(content)

        # 提取有益效果
        sections.beneficial_effects = self._extract_beneficial_effects(content)

    def _extract_invention_purpose(self, content: str) -> str:
        """从发明内容中提取发明目的

        Args:
            content: 发明内容文本

        Returns:
            发明目的描述
        """
        # 匹配"本发明（旨在/的目的/要解决...）"等句式
        patterns = [
            r'(?:本发明的目的|本发明旨在|本发明要解决|本发明针对|'
            r'本发明提供|本发明提出)[^。！？\n]{20,300}[。！？]',
            r'(?:针对|为了解决)[^，,]{0,50}(?:问题|不足|缺陷)'
            r'[^。！？\n]{20,200}[。！？]',
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(0).strip()

        # Fallback: 取发明内容的第一段
        first_sentence = re.split(r'[。！？\n]', content)[0]
        if len(first_sentence) > 15:
            return first_sentence.strip()

        return ""

    def _extract_solution_summary(self, content: str) -> str:
        """从发明内容中提取技术方案概述

        Args:
            content: 发明内容文本

        Returns:
            技术方案概述
        """
        # 通常技术方案在"本发明采用以下技术方案"或"技术方案如下"之后
        patterns = [
            r'技术方案[如为是][：:,，\s]*([^。！？\n]{100,500})',
            r'(?:本发明|本申请)(?:采用|提出|提供)(?:了|一种|如下)'
            r'(?:技术方案|方法|系统|装置)[：:,，\s]*([^。！？\n]{100,500})',
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1).strip() if match.lastindex else match.group(0).strip()

        # Fallback: 取发明内容中较长的句子
        sentences = re.split(r'[。！？\n]', content)
        long_sentences = [s.strip() for s in sentences if len(s) > 80]
        if long_sentences:
            return long_sentences[0]

        return ""

    def _extract_beneficial_effects(self, content: str) -> List[str]:
        """从发明内容中提取有益效果列表

        中国专利的效果描述通常在"[0042]-[0043]"或"有益效果"、"与现有技术相比"等标记之后。

        Args:
            content: 发明内容文本

        Returns:
            有益效果列表
        """
        effects = []

        # 方法1: 寻找"有益效果"或"与现有技术相比"之后的段落
        effect_section_patterns = [
            r'(?:有益效果|技术效果|积极效果|与现有技术相比)'
            r'[：:,，\s]*\n?(.+?)(?=\[\d{4}\]|\Z)',
        ]

        for pattern in effect_section_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                effect_text = match.group(1) if match.lastindex else match.group(0)
                # 按编号拆分效果
                effect_items = re.split(r'(?:\d+[.、．）\)]\s*)', effect_text)
                for item in effect_items:
                    item = item.strip()
                    if len(item) > 10:
                        # 进一步按分号拆分（如果效果条目很长）
                        if len(item) > 200:
                            sub_items = re.split(r'[；;]', item)
                            effects.extend(s.strip() for s in sub_items if len(s.strip()) > 10)
                        else:
                            effects.append(item)

        # 方法2: 如果没有找到明确的"有益效果"标记，从发明内容后半部分提取
        if not effects:
            # 取发明内容的最后30%
            sentences = re.split(r'[。！？\n]', content)
            start_idx = int(len(sentences) * 0.7)
            for sent in sentences[start_idx:]:
                sent = sent.strip()
                # 效果描述通常包含比较级和效果关键词
                if re.search(r'(?:提高|降低|减少|增强|改善|避免|消除|实现|有效|显著|'
                            r'快速|精确|稳定|安全)', sent) and len(sent) > 15:
                    effects.append(sent)

        return effects[:10]  # 限制最多10条

    # ═══════════════════════════════════════════════════════════════
    # 具体实施方式分析
    # ═══════════════════════════════════════════════════════════════

    def _analyze_detailed_implementation(self, sections: DescriptionSections):
        """分析具体实施方式章节，提取实施例和公式

        Args:
            sections: DescriptionSections实例（原地修改）
        """
        impl_text = sections.detailed_implementation
        if not impl_text:
            return

        # 提取实施例
        sections.embodiments = self._extract_embodiments(impl_text)

    def _extract_embodiments(self, impl_text: str) -> List[Dict]:
        """从实施方式中提取实施例

        识别"实施例1"、"实施例一"等标记，提取每个实施例的步骤和参数。

        Args:
            impl_text: 具体实施方式文本

        Returns:
            实施例列表 [{"index": 1, "title": "", "steps": [...], "params": {}}, ...]
        """
        embodiments = []

        # 按"实施例N"拆分
        parts = re.split(r'(?:实施例\s*(\d+|[一二三四五六七八九十]+))', impl_text)

        i = 1
        while i < len(parts):
            try:
                # parts[i] 是实施例编号
                idx_str = parts[i]
                # 中文数字转阿拉伯数字
                cn_num_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
                if idx_str in cn_num_map:
                    idx = cn_num_map[idx_str]
                else:
                    idx = int(idx_str)

                # parts[i+1] 是实施例内容
                content = parts[i+1] if i+1 < len(parts) else ""

                embodiment = {
                    "index": idx,
                    "content": content.strip(),
                    "steps": self._extract_steps(content),
                }
                embodiments.append(embodiment)
                i += 2
            except (ValueError, IndexError):
                i += 1

        return embodiments

    def _extract_steps(self, content: str) -> List[str]:
        """从实施例内容中提取步骤列表

        识别S1、步骤1、第1步等标记。

        Args:
            content: 实施例文本

        Returns:
            步骤列表
        """
        steps = []

        # 匹配 S1: S2: 或 步骤1: 步骤2: 或 (1) (2) 格式
        step_patterns = [
            r'[Ss]\s*(\d+)[.、．:：]\s*([^Ss\n]{15,200})',
            r'步骤\s*(\d+)[.、．:：]\s*([^步\n]{15,200})',
            r'[\(（]\s*(\d+)\s*[\)）][.、．:：]?\s*([^\(（\n]{15,200})',
        ]

        for pattern in step_patterns:
            matches = re.findall(pattern, content)
            if matches:
                for num, text in matches:
                    steps.append(f"S{num}: {text.strip()}")
                break

        return steps

    # ═══════════════════════════════════════════════════════════════
    # 公式提取
    # ═══════════════════════════════════════════════════════════════

    def _extract_formulas_from_all(self, sections: DescriptionSections):
        """从所有章节中提取数学公式

        Args:
            sections: DescriptionSections实例（原地修改）
        """
        all_text = " ".join([
            sections.invention_content,
            sections.detailed_implementation
        ])

        sections.formulas = self.text_processor.detect_formulas(all_text)
