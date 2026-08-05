"""专利技术交底书生成器（三阶段架构）

阶段 1：大纲规划——LLM 先生成 JSON 大纲（发明名称/问题/方案步骤/创新点/实施例规划）
阶段 2：分章节生成——按大纲分 4 组调用 LLM，每组独立 max_tokens，携带大纲+前文摘要
阶段 3：自动质检迭代——QualityReviewer 评分低于阈值的章节组自动重写一次

回退路径：
- LLM 某组调用失败 → 重试 1 次 → 仍失败则回退单次生成 → 模板生成
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from .llm_client import LLMClient, LLMError
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 质检迭代阈值
QUALITY_THRESHOLD = 70
# 章节组 → 质检维度映射（用于定向重写）
GROUP_DIMENSIONS = {
    "G1": ["structure", "relevance"],
    "G2": ["technical_depth"],
    "G3": ["implementation", "length"],
    "G4": ["claims"],
}


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _get_text(item, max_len=0) -> str:
    """从 RAG 条目中提取文本"""
    if isinstance(item, dict):
        text = item.get("text_preview", item.get("text", ""))
    else:
        text = str(item)
    if max_len > 0 and len(text) > max_len:
        text = text[:max_len] + "..."
    return text


def _get_pid(item) -> str:
    """从 RAG 条目中提取专利号"""
    return item.get("patent_id", "") if isinstance(item, dict) else ""


def _domain_relevance(text: str, idea: str) -> int:
    """基于 bigram 计算文本与想法的领域相关性分数"""
    stopwords = {
        '的', '了', '和', '与', '在', '是', '对', '为', '中', '上', '下',
        '不', '有', '被', '将', '把', '从', '到', '及', '等', '用',
        '该', '其', '所', '以', '于', '而', '并', '或', '且', '但',
        '系统', '方法', '装置', '模块', '单元', '数据', '信息', '技术',
        '实现', '包括', '进行', '通过', '采用', '基于', '利用', '根据',
        '一种', '发明', '专利', '方案', '问题', '结果', '过程', '步骤',
        '获取', '输出', '输入', '处理', '分析', '计算', '确定', '生成',
    }
    chinese = re.findall(r'[\u4e00-\u9fff]+', idea)
    bigrams = set()
    for seg in chinese:
        for i in range(len(seg) - 1):
            bigrams.add(seg[i:i + 2])
    for w in re.findall(r'[A-Za-z]{2,}', idea):
        bigrams.add(w.lower())
    bigrams -= stopwords
    if not bigrams:
        return 0
    text_lower = text.lower()
    return sum(1 for w in bigrams if w in text_lower)


def _filter_by_domain(items: list, idea: str, min_score: int = 0) -> list:
    """过滤 RAG 结果，只保留领域相关条目（按相关性降序）"""
    chinese = re.findall(r'[\u4e00-\u9fff]+', idea)
    n_bigrams = sum(max(0, len(seg) - 1) for seg in chinese)
    if min_score <= 0:
        min_score = max(2, n_bigrams // 12)
    scored = []
    for item in items:
        score = _domain_relevance(_get_text(item), idea)
        if score >= min_score:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored]


def _renumber_paragraphs(text: str) -> str:
    """将全文 [xxxx] 段落编号重新顺序编排，保证质检通过"""
    counter = {"n": 0}

    def _sub(m):
        counter["n"] += 1
        return f"[{counter['n']:04d}]"

    return re.sub(r"\[\d{4}\]", _sub, text)


def _extract_json(raw: str) -> Optional[dict]:
    """从 LLM 输出中提取 JSON

    多候选策略，兼容：代码块包裹、前后缀文本、嵌套大括号、多个 JSON 对象。
    任意一个候选能解析即返回，显著降低"大纲 JSON 解析失败"的概率。
    """
    raw = raw.strip()
    if not raw:
        return None

    # 直接解析
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    candidates = []

    # 代码块包裹
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        candidates.append(m.group(1))

    # 原始解码器：找第一个合法 JSON 前缀（处理尾部多余文本）
    decoder = json.JSONDecoder()
    idx = raw.find("{")
    while idx >= 0:
        try:
            obj, _ = decoder.raw_decode(raw[idx:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = raw.find("{", idx + 1)

    # 平衡大括号块（处理嵌套大括号，取首个完整闭合块）
    start = raw.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(raw[start:i + 1])
                    break

    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


# ═══════════════════════════════════════════════════════════
# 参考资料加载（效果模板 / 权利要求范式）
# ═══════════════════════════════════════════════════════════

def _load_effect_reference() -> str:
    """从 config/effect_descriptions 加载量化效果描述参考"""
    lines = []
    for name in ["power_effects.json", "general_effects.json"]:
        path = PROJECT_ROOT / "config" / "effect_descriptions" / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for cat in data.get("effect_categories", [])[:6]:
            descs = cat.get("qualitative_descriptions", [])[:4]
            stds = cat.get("standard_references", [])[:2]
            if descs:
                lines.append(f"- {cat.get('category', '')}: {'、'.join(descs)}")
            if stds:
                lines.append(f"  标准引用: {'；'.join(stds)}")
    return "\n".join(lines[:20])


def _load_claims_reference() -> str:
    """从 templates/claims_template.md 加载权利要求写法范式（截断）"""
    path = PROJECT_ROOT / "templates" / "claims_template.md"
    try:
        text = path.read_text(encoding="utf-8")
        return text[:2000]
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════

ROLE_PROMPT = """\
你是一位资深专利代理师，拥有10年以上中国发明专利撰写经验，精通电力系统和智能装备领域。

## 撰写规范
1. 使用段落编号 [0001]、[0002]... 依次递增（每组内部从[0001]开始即可，最终会统一重排）
2. 技术术语规范统一，首次出现给出全称
3. 【数据真实性·最高原则】严禁编造任何未经实践验证的内容：
   - 严禁出现具体工程案例（如"某电厂""某600MW机组""某项目"）
   - 严禁出现实测/实验数据（如"测得""实测""检测发现减薄5.8mm"、"精度±0.1mm"）
   - 严禁出现模型性能指标（如"R²""MAPE""准确率98%""误差率""预测精度"等具体数值）
   - 严禁出现具体设备品牌型号（如"Olympus Omniscan"、"Intel Xeon"）
   - 严禁出现"经试验""实验证明""测试表明""验证表明"等暗示已实践验证的表述
   - 有益效果只做定性描述（"有效降低""显著改善"），不得编造具体百分比或数值
4. 具体实施方式采用"示例性实施方式"框架：描述技术方案如何实施（步骤、流程、模块连接关系），
   需要参数的场合用"示例性取值，本领域技术人员可根据实际工况调整"表述；
   需要用户提供真实数据的场合用【此处补充实际数据】占位符标注
5. 技术方案要具体可实施（说清步骤和流程），但不得用编造的数值填充
6. 使用 Markdown 格式输出，章节标题用 "## 一、xxx" 形式
7. 直接输出章节内容，不要添加任何额外说明或前缀
"""

OUTLINE_SYSTEM = ROLE_PROMPT + """
你的任务是为技术交底书规划大纲。必须输出严格的 JSON（不要输出其他内容），格式：
{
  "invention_name": "发明名称（一种...的方法/系统）",
  "tech_field": "技术领域描述（一句话）",
  "problems": ["要解决的技术问题1", "问题2", "问题3"],
  "solution_steps": [
    {"name": "步骤名称", "detail": "该步骤的核心内容要点（30-60字）"}
  ],
  "innovation_points": ["创新点1", "创新点2", "创新点3"],
  "embodiments": [
    {"name": "实施例1", "scenario": "应用场景与要点"},
    {"name": "实施例2", "scenario": "替代/优化方案要点"}
  ]
}
要求：solution_steps 至少5步，innovation_points 至少3个，结合参考专利找出真正的差异化创新点。
"""

SECTION_SYSTEM = ROLE_PROMPT + """
你正在分段撰写一份完整的技术交底书。请严格只输出本次要求的章节，保持与大纲和前文一致。
"""

GROUP_SPECS = [
    {
        "key": "G1",
        "title": "技术领域 + 背景技术",
        "instruction": (
            "请输出以下章节：\n"
            "## 一、发明名称\n"
            "## 二、技术领域（[0001] 开头，说明所属技术领域和具体对象）\n"
            "## 三、背景技术（3-5段：先介绍技术背景与现状，再逐一分析相关现有专利的公开内容，"
            "最后总结现有技术的至少3点具体不足。引用参考专利时写明专利号。）"
        ),
        "max_tokens": 3000,
    },
    {
        "key": "G2",
        "title": "发明目的 + 技术方案",
        "instruction": (
            "请输出以下章节：\n"
            "## 四、发明目的（明确要解决的技术问题和3-5个技术目标）\n"
            "## 五、技术方案（先概述整体技术路线，然后按大纲的 solution_steps 逐步展开，"
            "每步包含：步骤名称、实现方法、判断规则/流程、与前后步骤的衔接。"
            "参数用示例性取值表述，严禁编造实测数据。这是全文核心，至少8段。）"
        ),
        "max_tokens": 4096,
    },
    {
        "key": "G3",
        "title": "有益效果 + 附图说明 + 具体实施方式",
        "instruction": (
            "请输出以下章节：\n"
            "## 六、有益效果（与现有技术对比至少4点，用定性描述（有效降低/显著改善），"
            "严禁编造具体百分比或实验数据，可引用效果参考中的规范表述）\n"
            "## 七、附图说明（列出4-6幅建议附图及内容说明）\n"
            "## 八、具体实施方式（按大纲的 embodiments 写至少2个示例性实施例，"
            "描述实施步骤与工作流程，参数用'示例性取值，可根据实际工况调整'表述；"
            "严禁编造具体工程案例、实测数据、设备型号，需要真实数据处用【此处补充实际数据】占位）"
        ),
        "max_tokens": 4096,
    },
    {
        "key": "G4",
        "title": "权利要求书 + 摘要",
        "instruction": (
            "请输出以下章节：\n"
            "## 九、权利要求书（建议）\n"
            "权利要求1为方法独立权利要求（包含完整的步骤特征，使用'其特征在于'），"
            "权利要求2为装置/系统独立权利要求，另有5-8条从属权利要求（'根据权利要求X所述的...'），"
            "从属权利要求应对技术方案中的关键参数、算法、结构做进一步限定。\n"
            "## 十、摘要（200字以内的技术摘要）"
        ),
        "max_tokens": 3000,
    },
]

# 兼容旧接口的单次生成 Prompt（分段失败时的二级回退）
SINGLE_SHOT_SYSTEM = ROLE_PROMPT + """
根据用户提供的技术想法，撰写一份完整、专业的技术交底书，包含以下章节：
一、发明名称 / 二、技术领域 / 三、背景技术（引用参考专利） / 四、发明目的 /
五、技术方案（分步骤详细描述，含关键参数） / 六、有益效果（至少4点，尽量量化） /
七、附图说明 / 八、具体实施方式（至少2个实施例） / 九、权利要求书（建议） / 十、摘要
全文不少于4000字。
"""


# ═══════════════════════════════════════════════════════════
# 生成器主类
# ═══════════════════════════════════════════════════════════

class DisclosureGenerator:
    """技术交底书生成器（三阶段：大纲→分章节→质检迭代）"""

    def __init__(self, engine):
        self.engine = engine
        config_path = str(engine.config_dir / "api_config.json")
        self.llm = LLMClient(config_path)
        self._effect_ref = _load_effect_reference()
        self._claims_ref = _load_claims_reference()

    @property
    def llm_available(self) -> bool:
        return self.llm.is_available()

    def generate(self, idea: str, title: str = None,
                 fields: Dict = None) -> Tuple[str, str]:
        """生成技术交底书

        Args:
            idea: 技术想法描述
            title: 发明名称（可选）
            fields: 结构化输入字段 {tech_field, purpose, core_method, problems}

        Returns:
            (disclosure_text, mode) 元组，
            mode 为 "llm_staged" / "llm_single" / "template"
        """
        fields = fields or {}
        if not title:
            title = self._extract_title(idea)

        # 获取 RAG 上下文、知识图谱上下文和创新建议
        context = self.engine.generate_writing_context(idea)
        suggestions = self.engine.suggest_innovation(idea)

        # 知识图谱结构化上下文（问题→方案→替代方向），注入基础 prompt
        self._graph_ref = self._format_graph_context(
            context.get("graph_solutions", []),
            context.get("graph_alternatives", []),
        )

        # 领域过滤后的深度上下文（5 篇 × 500 字）
        rag_backgrounds = _filter_by_domain(
            context.get("related_background", []), idea
        )[:5]
        rag_claims = _filter_by_domain(
            context.get("similar_claims", []), idea
        )[:3]

        if not self.llm_available:
            logger.info("LLM 不可用，使用模板生成")
            disclosure = self._generate_template(idea, title, fields, context, suggestions)
            return disclosure, "template"

        # ── 阶段 1：大纲 ──
        logger.info("[阶段1] 规划交底书大纲...")
        outline = None
        try:
            outline = self._plan_outline(idea, title, fields,
                                         rag_backgrounds, suggestions)
            logger.info(f"[阶段1] 大纲完成: {outline.get('invention_name', '')}，"
                        f"{len(outline.get('solution_steps', []))}个方案步骤")
        except LLMError as e:
            logger.warning(f"[阶段1] 大纲生成失败: {e}")

        # ── 阶段 2：分章节生成 ──
        if outline:
            try:
                sections = self._generate_sections(
                    idea, fields, outline, rag_backgrounds, rag_claims
                )
                disclosure = self._assemble(sections)
                logger.info(f"[阶段2] 分章节生成完成，全文 {len(disclosure)} 字")
                return disclosure, "llm_staged"
            except LLMError as e:
                logger.warning(f"[阶段2] 分章节生成失败: {e}，回退单次生成")

        # ── 二级回退：单次生成 ──
        try:
            disclosure = self._generate_single_shot(
                idea, title, fields, rag_backgrounds, suggestions
            )
            disclosure = _renumber_paragraphs(disclosure)
            return disclosure, "llm_single"
        except LLMError as e:
            logger.warning(f"单次生成失败({e})，回退模板生成")

        disclosure = self._generate_template(idea, title, fields, context, suggestions)
        return disclosure, "template"

    def iterate_quality(self, disclosure: str, idea: str,
                        sections: Dict[str, str]) -> Tuple[str, Dict]:
        """阶段 3：自动质检迭代

        评分低于阈值的章节组重写一次（最多 1 轮）。

        Args:
            disclosure: 当前交底书全文
            idea: 原始想法
            sections: 各章节组文本 {"G1": ..., "G2": ..., "G3": ..., "G4": ...}

        Returns:
            (新全文, 质检报告)
        """
        from .quality_reviewer import QualityReviewer
        reviewer = QualityReviewer(
            self.engine if self.engine.is_initialized else None
        )
        report = reviewer.review(disclosure, idea)
        total = report.get("total_score", 100)
        logger.info(f"[阶段3] 质检总分 {total}")

        if total >= QUALITY_THRESHOLD or not self.llm_available:
            return disclosure, report

        # 找出低分章节组并重写
        dims = report.get("dimensions", {})
        weak_groups = []
        for group, dim_names in GROUP_DIMENSIONS.items():
            scores = [dims.get(d, {}).get("score", 100) for d in dim_names]
            if scores and min(scores) < QUALITY_THRESHOLD:
                weak_groups.append(group)

        if not weak_groups:
            return disclosure, report

        logger.info(f"[阶段3] 重写低分章节组: {weak_groups}")
        try:
            new_sections = dict(sections)
            for group in weak_groups:
                spec = next(s for s in GROUP_SPECS if s["key"] == group)
                preceding = self._preceding_summary(new_sections, group)
                new_sections[group] = self._generate_one_group(
                    spec, idea, self._last_outline or {}, preceding,
                    self._last_bg, self._last_claims,
                    base_prompt=getattr(self, "_last_base", None),
                    feedback=self._dim_feedback(dims, GROUP_DIMENSIONS[group])
                )
            disclosure = self._assemble(new_sections)
            report = reviewer.review(disclosure, idea)
            logger.info(f"[阶段3] 重写后总分 {report.get('total_score')}")
        except LLMError as e:
            logger.warning(f"[阶段3] 重写失败: {e}，保留原文")

        return disclosure, report

    # ─── 阶段 1：大纲规划 ────────────────────────────────

    def _plan_outline(self, idea, title, fields, rag_context, suggestions) -> Dict:
        user_prompt = self._build_base_prompt(idea, title, fields,
                                              rag_context, suggestions,
                                              graph_context=getattr(self, "_graph_ref", ""))
        user_prompt += "\n\n请规划交底书大纲，输出 JSON。"
        raw = self.llm.chat(OUTLINE_SYSTEM, user_prompt,
                            max_tokens=3000, temperature=0.5)
        outline = _extract_json(raw)
        if not outline or "solution_steps" not in outline:
            raise LLMError("大纲 JSON 解析失败")
        return outline

    # ─── 阶段 2：分章节生成 ──────────────────────────────

    def _generate_sections(self, idea, fields, outline,
                           rag_backgrounds, rag_claims) -> Dict[str, str]:
        """生成全部 4 组章节，返回 {group_key: text}"""
        # 缓存供质检迭代复用
        self._last_outline = outline
        self._last_bg = rag_backgrounds
        self._last_claims = rag_claims

        sections = {}
        base = self._build_base_prompt(idea, outline.get("invention_name", ""),
                                       fields, rag_backgrounds, None,
                                       graph_context=getattr(self, "_graph_ref", ""))
        self._last_base = base
        for spec in GROUP_SPECS:
            preceding = self._preceding_summary(sections, spec["key"])
            sections[spec["key"]] = self._generate_one_group(
                spec, idea, outline, preceding,
                rag_backgrounds, rag_claims, base_prompt=base
            )
        self._last_sections = sections
        return sections

    def _generate_one_group(self, spec, idea, outline, preceding,
                            rag_backgrounds, rag_claims,
                            base_prompt: str = None,
                            feedback: str = "") -> str:
        """生成一组章节（带 1 次重试）"""
        parts = []
        if base_prompt:
            parts.append(base_prompt)
        parts.append(f"【交底书大纲】\n{json.dumps(outline, ensure_ascii=False, indent=1)}")
        if preceding:
            parts.append(f"【前文已完成内容摘要】\n{preceding}")

        # 组特定参考资料
        if spec["key"] == "G1" and rag_backgrounds:
            refs = self._format_patent_refs(rag_backgrounds, 500)
            parts.append("【相关现有技术（背景技术中须引用分析）】\n" + refs)
        if spec["key"] == "G3" and self._effect_ref:
            parts.append("【有益效果规范表述参考】\n" + self._effect_ref)
        if spec["key"] == "G4":
            if rag_claims:
                refs = self._format_patent_refs(rag_claims, 300)
                parts.append("【权利要求写法参考（来自相似专利）】\n" + refs)
            if self._claims_ref:
                parts.append("【权利要求结构范式】\n" + self._claims_ref)
        if feedback:
            parts.append(f"【上一版质量审查意见（请针对性改进）】\n{feedback}")

        parts.append(f"【本次任务】\n{spec['instruction']}")
        user_prompt = "\n\n".join(parts)

        last_error = None
        for attempt in range(2):
            try:
                logger.info(f"[阶段2] 生成章节组 {spec['key']} "
                            f"({spec['title']})...")
                text = self.llm.chat(SECTION_SYSTEM, user_prompt,
                                     max_tokens=spec["max_tokens"],
                                     temperature=0.7)
                if len(text.strip()) < 200:
                    raise LLMError(f"{spec['key']} 输出过短")
                return text.strip()
            except LLMError as e:
                last_error = e
                logger.warning(f"[阶段2] {spec['key']} 第{attempt+1}次失败: {e}")
        raise last_error

    def _assemble(self, sections: Dict[str, str]) -> str:
        """拼装全文并重排段落编号"""
        header = "# 技术交底书\n"
        body = "\n\n".join(sections[k] for k in ["G1", "G2", "G3", "G4"]
                           if sections.get(k))
        footer = (f"\n\n---\n*本交底书由专利撰写助手自动生成（AI 分段模式）*\n"
                  f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return _renumber_paragraphs(header + "\n" + body + footer)

    # ─── 二级回退：单次生成 ──────────────────────────────

    def _generate_single_shot(self, idea, title, fields,
                              rag_context, suggestions) -> str:
        user_prompt = self._build_base_prompt(idea, title, fields,
                                              rag_context, suggestions,
                                              graph_context=getattr(self, "_graph_ref", ""))
        user_prompt += "\n\n请撰写完整的技术交底书。"
        logger.info("[回退] 单次 LLM 生成完整交底书...")
        result = self.llm.chat(SINGLE_SHOT_SYSTEM, user_prompt,
                               max_tokens=8192, temperature=0.7)
        logger.info(f"[回退] 单次生成完成，{len(result)} 字")
        return result

    # ─── Prompt 构建 ────────────────────────────────────

    def _build_base_prompt(self, idea, title, fields,
                           rag_context, suggestions,
                           graph_context: str = None) -> str:
        """构建基础信息 prompt（想法/字段/创新方向/知识图谱参考）"""
        parts = [f"【技术想法】\n{idea}"]
        if title:
            parts.append(f"【发明名称】\n{title}")
        if fields.get("tech_field"):
            parts.append(f"【技术领域】\n{fields['tech_field']}")
        if fields.get("purpose"):
            parts.append(f"【发明目的】\n{fields['purpose']}")
        if fields.get("core_method"):
            parts.append(f"【核心方法/技术路线】\n{fields['core_method']}")
        if fields.get("problems"):
            parts.append(f"【要解决的问题】\n{fields['problems']}")

        if suggestions:
            directions = suggestions.get("innovation_directions", [])
            if directions:
                inno_items = [
                    f"- {d.get('innovation_type', '')}: {d.get('description', '')[:80]}"
                    for d in directions[:3]
                ]
                parts.append("【创新方向建议】\n" + "\n".join(inno_items))

        if graph_context:
            parts.append(graph_context)
        return "\n\n".join(parts)

    def _format_graph_context(self, solutions: list, alternatives: list) -> str:
        """格式化知识图谱结构化上下文（问题→方案→替代方向）"""
        lines = []
        if solutions:
            lines.append("【知识图谱：解决相似问题的已有方案】")
            for s in solutions[:3]:
                name = s.get("solution_name", "")
                desc = (s.get("description", "") or "")[:150]
                srcs = ", ".join(s.get("source_patents", [])[:3])
                lines.append(f"- {name}（来源专利: {srcs or '无'}）：{desc}")
        if alternatives:
            lines.append("【知识图谱：同一问题的替代/改进方向】")
            for a in alternatives[:3]:
                name = a.get("solution_name", "")
                desc = (a.get("description", "") or "")[:150]
                srcs = ", ".join(a.get("source_patents", [])[:3])
                lines.append(f"- {name}（来源专利: {srcs or '无'}）：{desc}")
        return "\n".join(lines)

    def _format_patent_refs(self, items: list, text_len: int) -> str:
        """格式化专利参考列表（含专利号 + 文本）"""
        refs = []
        seen = set()
        for item in items:
            pid = _get_pid(item)
            text = _get_text(item, text_len)
            if not pid or pid in seen or not text:
                continue
            seen.add(pid)
            refs.append(f"- {pid}: {text}")
        return "\n".join(refs) if refs else "（无）"

    def _preceding_summary(self, sections: Dict[str, str],
                           current_key: str) -> str:
        """提取已完成章节组的摘要（每组前 200 字）"""
        order = ["G1", "G2", "G3", "G4"]
        idx = order.index(current_key)
        parts = []
        for key in order[:idx]:
            text = sections.get(key, "")
            if text:
                parts.append(text[:200])
        return "\n...\n".join(parts)

    @staticmethod
    def _dim_feedback(dims: Dict, dim_names: List[str]) -> str:
        """把低分维度的审查意见拼成反馈文本"""
        lines = []
        for d in dim_names:
            info = dims.get(d, {})
            if info.get("score", 100) < QUALITY_THRESHOLD:
                lines.append(f"- {d}: {info.get('detail', '')}")
        return "\n".join(lines)

    # ─── 模板回退路径 ────────────────────────────────────

    def _generate_template(self, idea, title, fields, context, suggestions) -> str:
        """模板拼接生成（LLM 不可用时的降级方案）"""
        sections = [
            f"# 技术交底书\n\n## 一、发明名称\n\n{title}",
            self._tpl_field(idea, fields),
            self._tpl_background(idea, context),
            self._tpl_purpose(idea, fields),
            self._tpl_solution(idea, fields),
            self._tpl_effects(idea),
            self._tpl_drawings(),
            self._tpl_implementation(idea, fields),
            self._tpl_claims(title),
            self._tpl_abstract(idea, title),
            f"---\n*本交底书由专利撰写助手自动生成（模板模式）*\n"
            f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ]
        return "\n\n".join(s for s in sections if s)

    def _tpl_field(self, idea, fields) -> str:
        if fields.get("tech_field"):
            return f"## 二、技术领域\n\n[0001] 本发明涉及{fields['tech_field']}技术领域。"
        if any(w in idea for w in ["管道", "机器人", "检测"]):
            field = "管道检测与智能机器人"
        elif any(w in idea for w in ["电力", "电网", "调度"]):
            field = "电力系统运行与控制"
        else:
            field = "工程技术"
        return f"## 二、技术领域\n\n[0001] 本发明涉及{field}技术领域。"

    def _tpl_background(self, idea, context) -> str:
        lines = ["## 三、背景技术\n"]
        bgs = _filter_by_domain(context.get("related_background", []), idea)
        if bgs:
            lines.append("[0002] 经检索，与本发明相关的现有技术如下：\n")
            for i, bg in enumerate(bgs[:3], 3):
                pid = _get_pid(bg)
                text = _get_text(bg, 150)
                if pid:
                    lines.append(f"[{i:04d}] 专利{pid}公开了：{text}\n")
        lines.append("\n现有技术存在以下不足：")
        if "管道" in idea or "检测" in idea:
            lines.append("- 现有检测方式效率低，智能化程度不足")
            lines.append("- 对复杂环境的适应性有限，缺陷识别精度不高")
        else:
            lines.append("- 现有方法难以满足实际工程需求")
            lines.append("- 缺乏系统性的解决方案")
        return "\n".join(lines)

    def _tpl_purpose(self, idea, fields) -> str:
        lines = ["## 四、发明目的\n"]
        if fields.get("purpose"):
            lines.append(f"[0005] {fields['purpose']}")
        else:
            lines.append(f"[0005] 本发明旨在解决现有技术中存在的不足，提供{_extract_short(idea)}。")
        return "\n".join(lines)

    def _tpl_solution(self, idea, fields) -> str:
        lines = ["## 五、技术方案\n"]
        if fields.get("core_method"):
            lines.append(f"[0007] 本发明采用如下技术方案：\n{fields['core_method']}")
        else:
            lines.append("[0007] 本发明提出的技术方案包括以下步骤：\n")
            lines.append("[0008] 步骤一：系统架构设计与数据采集。")
            lines.append("[0009] 步骤二：核心算法设计与模型构建。")
            lines.append("[0010] 步骤三：系统集成与在线运行。")
            lines.append("[0011] 步骤四：结果输出与性能评估。")
        return "\n".join(lines)

    def _tpl_effects(self, idea) -> str:
        effects = ("## 六、有益效果\n\n"
                   "[0016] 与现有技术相比，本发明具有以下有益效果：\n")
        # 从配置库读取领域化效果描述，避免空洞
        if self._effect_ref:
            return effects + self._effect_ref
        return (effects +
                "1. 提高了系统的智能化水平和运行效率\n"
                "2. 增强了复杂场景下的适应性和鲁棒性\n"
                "3. 降低了人工成本，提升了自动化程度\n"
                "4. 具有良好的可扩展性和工程应用前景")

    def _tpl_drawings(self) -> str:
        return ("## 七、附图说明\n\n"
                "[0017] 图1为本发明系统整体架构示意图；\n"
                "图2为本发明方法流程图；\n"
                "图3为关键模块结构图；\n"
                "图4为实验结果对比图。")

    def _tpl_implementation(self, idea, fields) -> str:
        return ("## 八、具体实施方式\n\n"
                "[0018] 下面结合附图和实施例对本发明作进一步说明。\n\n"
                "[0019] 实施例1：按照技术方案描述的步骤依次实施，"
                "根据具体应用场景调整参数配置，验证系统性能满足设计要求。")

    def _tpl_claims(self, title) -> str:
        return (f"## 九、权利要求书（建议）\n\n"
                f"**权利要求1**：一种方法，其特征在于，包括以下步骤：...\n\n"
                f"**权利要求2**：一种装置/系统，其特征在于，包括：...\n\n"
                "（建议委托专利代理师完善权利要求书）")

    def _tpl_abstract(self, idea, title) -> str:
        return f"## 十、摘要\n\n本发明公开了{title}，属于相关技术领域。解决了现有技术中的不足，具有良好的应用前景。"

    # ─── 工具 ────────────────────────────────────────────

    @staticmethod
    def _extract_title(idea: str) -> str:
        """从想法中提取发明名称"""
        if idea.startswith("一种"):
            for sep in ["，", "。", ",", ".", "\n"]:
                idx = idea.find(sep)
                if idx > 0:
                    return idea[:idx]
            return idea[:40]
        return f"一种{idea[:30]}的方法"


def _extract_short(idea: str) -> str:
    """提取想法的简短描述"""
    for sep in ["，", "。", ",", ".", "\n"]:
        idx = idea.find(sep)
        if 0 < idx < 50:
            return idea[:idx]
    return idea[:40]
