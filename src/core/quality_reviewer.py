"""交底书质量审查模块

对生成的技术交底书进行多维度评分和专利对比审查。
纯规则+统计方法，不依赖 LLM 调用。
"""

import re
from typing import Dict, List

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

REQUIRED_SECTIONS = [
    ("发明名称", r"##\s*一、|发明名称"),
    ("技术领域", r"##\s*二、|技术领域"),
    ("背景技术", r"##\s*三、|背景技术"),
    ("发明目的", r"##\s*四、|发明目的"),
    ("技术方案", r"##\s*五、|技术方案"),
    ("有益效果", r"##\s*六、|有益效果"),
    ("附图说明", r"##\s*七、|附图说明"),
    ("具体实施方式", r"##\s*八、|实施方式"),
    ("权利要求书", r"##\s*九、|权利要求"),
    ("摘要", r"##\s*十、|摘要"),
]

# 量化参数正则：数字+单位
PARAM_PATTERN = re.compile(
    r'\d+\.?\d*\s*(?:mm|cm|m|km|kg|g|s|ms|Hz|kHz|MHz|GHz|dB|fps|'
    r'像素|°|℃|%|MPa|kPa|Pa|N|W|kW|MW|V|kV|A|mA|Ω|'
    r'帧|个|台|套|组|层|步|维|元|次|秒|分钟|小时|天)'
)

# 数学公式特征
FORMULA_PATTERN = re.compile(r'[=∑∫∏√≤≥±×÷∈∀∃]|exp\(|log\(|sin\(|cos\(|Σ|σ|λ|η|γ|α|β|θ|φ|ψ|Δ')


# ═══════════════════════════════════════════════════════════
# 质量审查主类
# ═══════════════════════════════════════════════════════════

class QualityReviewer:
    """交底书质量审查器"""

    def __init__(self, engine=None):
        """
        Args:
            engine: PatentInnovationEngine 实例（用于专利对比，可选）
        """
        self.engine = engine

    def review(self, disclosure: str, idea: str) -> Dict:
        """执行完整质量审查

        Args:
            disclosure: 生成的交底书全文
            idea: 原始技术想法

        Returns:
            质量报告字典
        """
        # 专利对比（提前计算，供 novelty 和建议生成复用）
        patent_comparison = self._compare_with_database(disclosure, idea)

        dimensions = {
            "structure": self._check_structure(disclosure),
            "length": self._check_length(disclosure),
            "numbering": self._check_numbering(disclosure),
            "technical_depth": self._check_technical_depth(disclosure),
            "claims": self._check_claims(disclosure),
            "implementation": self._check_implementation(disclosure),
            "relevance": self._check_relevance(disclosure, idea),
            "novelty": self._check_novelty(disclosure, idea, patent_comparison),
        }

        # 计算总分（加权平均）
        weights = {
            "structure": 15, "length": 10, "numbering": 10,
            "technical_depth": 20, "claims": 15, "implementation": 10,
            "relevance": 10, "novelty": 10,
        }
        total = sum(dimensions[k]["score"] * weights[k] for k in weights) / sum(weights.values())

        # 生成建议
        suggestions = self._generate_suggestions(dimensions, patent_comparison)

        # 评级
        grade = self._score_to_grade(total)

        return {
            "total_score": round(total, 1),
            "grade": grade,
            "dimensions": dimensions,
            "patent_comparison": patent_comparison,
            "suggestions": suggestions,
        }

    # ─── 各维度评分 ─────────────────────────────────────────

    def _check_structure(self, text: str) -> Dict:
        """检查10个章节是否齐全"""
        found = []
        missing = []
        for name, pattern in REQUIRED_SECTIONS:
            if re.search(pattern, text):
                found.append(name)
            else:
                missing.append(name)
        score = len(found) / len(REQUIRED_SECTIONS) * 100
        detail = f"{len(found)}/10 章节完整"
        if missing:
            detail += f"，缺少：{'、'.join(missing)}"
        return {"score": round(score), "detail": detail}

    def _check_length(self, text: str) -> Dict:
        """检查篇幅是否充分（4000字满分）"""
        # 去除 Markdown 标记后统计中文字符+英文单词
        clean = re.sub(r'[#*\[\]\n\r\s]', '', text)
        char_count = len(clean)
        score = min(100, char_count / 4000 * 100)
        return {"score": round(score), "detail": f"{char_count}字"}

    def _check_numbering(self, text: str) -> Dict:
        """检查段落编号 [0001] 是否连续"""
        numbers = re.findall(r'\[(\d{4})\]', text)
        if not numbers:
            return {"score": 0, "detail": "未使用段落编号"}
        nums = [int(n) for n in numbers]
        # 检查是否递增
        gaps = 0
        for i in range(1, len(nums)):
            if nums[i] != nums[i - 1] + 1:
                gaps += 1
        max_num = max(nums)
        if gaps == 0:
            score = 100
            detail = f"编号连续，[0001]-[{max_num:04d}]"
        else:
            score = max(0, 100 - gaps * 10)
            detail = f"存在{gaps}处跳号，最大编号[{max_num:04d}]"
        return {"score": score, "detail": detail}

    def _check_technical_depth(self, text: str) -> Dict:
        """检查技术深度：量化参数和公式"""
        params = PARAM_PATTERN.findall(text)
        formulas = FORMULA_PATTERN.findall(text)
        param_count = len(params)
        formula_count = len(formulas)

        # 参数>=10且公式>=3得满分
        param_score = min(60, param_count / 10 * 60)
        formula_score = min(40, formula_count / 3 * 40)
        score = param_score + formula_score

        detail = f"含{param_count}个量化参数，{formula_count}处公式/符号"
        return {"score": round(score), "detail": detail}

    def _check_claims(self, text: str) -> Dict:
        """检查权利要求质量"""
        # 提取权利要求部分
        claims_match = re.search(r'权利要求书?.*?(?=##\s*十|$)', text, re.DOTALL)
        claims_text = claims_match.group(0) if claims_match else ""

        # 统计独立权利要求和从属权利要求
        independent = len(re.findall(r'权利要求\s*\d+|一种.*其特征在于', claims_text))
        dependent = len(re.findall(r'根据权利要求|如权利要求.*所述', claims_text))
        has_feature = "其特征在于" in claims_text

        score = 0
        if independent >= 2:
            score += 40
        elif independent >= 1:
            score += 20
        if dependent >= 3:
            score += 30
        elif dependent >= 1:
            score += 15
        if has_feature:
            score += 20
        # 权利要求文本长度
        if len(claims_text) > 500:
            score += 10

        score = min(100, score)
        detail = f"{independent}独立+{dependent}从属"
        if not has_feature:
            detail += "，缺少'其特征在于'"
        return {"score": score, "detail": detail}

    def _check_implementation(self, text: str) -> Dict:
        """检查实施例充分性"""
        impl_match = re.search(r'实施方式(.*?)(?=##\s*九|$)', text, re.DOTALL)
        impl_text = impl_match.group(1) if impl_match else ""

        examples = re.findall(r'实施例\s*\d+', impl_text)
        example_count = len(examples)
        has_params = bool(PARAM_PATTERN.search(impl_text))
        text_len = len(impl_text)

        score = 0
        if example_count >= 2:
            score += 50
        elif example_count >= 1:
            score += 25
        if has_params:
            score += 25
        if text_len > 1000:
            score += 25
        elif text_len > 300:
            score += 10

        score = min(100, score)
        detail = f"{example_count}个实施例"
        if has_params:
            detail += "，含具体参数"
        return {"score": score, "detail": detail}

    def _check_relevance(self, text: str, idea: str) -> Dict:
        """检查生成内容与输入想法的领域相关性"""
        # 提取想法中的 bigram
        chinese = re.findall(r'[\u4e00-\u9fff]+', idea)
        bigrams = set()
        for seg in chinese:
            for i in range(len(seg) - 1):
                bigrams.add(seg[i:i + 2])
        for w in re.findall(r'[A-Za-z]{2,}', idea):
            bigrams.add(w.lower())

        # 去除通用词
        stopwords = {'的', '了', '和', '与', '在', '是', '一种', '方法', '系统', '技术'}
        bigrams -= stopwords

        if not bigrams:
            return {"score": 50, "detail": "无法提取领域关键词"}

        text_lower = text.lower()
        hits = sum(1 for w in bigrams if w in text_lower)
        hit_rate = hits / len(bigrams)
        score = min(100, hit_rate * 120)  # 83%命中率即满分

        detail = f"bigram命中率{hit_rate:.0%}（{hits}/{len(bigrams)}）"
        return {"score": round(score), "detail": detail}

    def _check_novelty(self, text: str, idea: str, comparisons: List[Dict] = None) -> Dict:
        """检查新颖性（与专利库对比）
        
        Args:
            text: 交底书文本
            idea: 技术想法
            comparisons: 预计算的专利对比结果（避免重复TF-IDF计算）
        """
        if comparisons is None:
            comparisons = self._compare_with_database(text, idea)
        if not comparisons:
            return {"score": 70, "detail": "未找到相关专利对比"}

        max_sim = comparisons[0]["similarity"]
        # 相似度越低越新颖
        if max_sim < 0.3:
            score = 90
            level = "高新颖性"
        elif max_sim < 0.6:
            score = 70
            level = "中等新颖性"
        else:
            score = 40
            level = "新颖性偏低"

        pid = comparisons[0]["patent_id"]
        detail = f"{level}，最相似{pid}(相似度{max_sim:.2f})"
        return {"score": score, "detail": detail}

    # ─── 专利对比 ─────────────────────────────────────────

    def _compare_with_database(self, disclosure: str, idea: str) -> List[Dict]:
        """与专利库进行对比审查"""
        if not self.engine or not hasattr(self.engine, 'rag_engine'):
            return []

        try:
            # 检索最相关的专利
            rag_results = self.engine.rag_engine.retrieve(idea, top_k=5)
            if not rag_results:
                return []

            # 提取交底书的技术方案段落
            solution_text = self._extract_solution_section(disclosure)
            if not solution_text or len(solution_text) < 50:
                solution_text = disclosure[:2000]

            comparisons = []
            seen_patents = set()

            for result in rag_results:
                pid = result.chunk.patent_id if hasattr(result, 'chunk') else ""
                if not pid or pid in seen_patents:
                    continue
                seen_patents.add(pid)

                patent_text = result.chunk.text if hasattr(result, 'chunk') else str(result)
                if not patent_text or len(patent_text) < 30:
                    continue

                # TF-IDF 余弦相似度
                sim = self._tfidf_similarity(solution_text, patent_text)
                # 重叠关键短语
                overlaps = self._find_overlaps(solution_text, patent_text)

                comparisons.append({
                    "patent_id": pid,
                    "similarity": round(sim, 3),
                    "overlaps": overlaps[:5],
                })

            comparisons.sort(key=lambda x: -x["similarity"])
            return comparisons[:5]

        except Exception as e:
            print(f"[质量审查] 专利对比异常: {e}")
            return []

    def _extract_solution_section(self, text: str) -> str:
        """提取技术方案章节"""
        match = re.search(r'##\s*五、技术方案(.*?)(?=##\s*六、|$)', text, re.DOTALL)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _tfidf_similarity(text1: str, text2: str) -> float:
        """计算两段文本的 TF-IDF 余弦相似度"""
        try:
            words1 = " ".join(jieba.cut(text1[:3000]))
            words2 = " ".join(jieba.cut(text2[:3000]))
            vec = TfidfVectorizer(max_features=500).fit_transform([words1, words2])
            return float(cosine_similarity(vec[0:1], vec[1:2])[0][0])
        except Exception:
            return 0.0

    @staticmethod
    def _find_overlaps(text1: str, text2: str) -> List[str]:
        """找出两段文本的共同关键短语"""
        words1 = set(jieba.cut(text1))
        words2 = set(jieba.cut(text2))
        # 只保留2字以上的词
        common = {w for w in words1 & words2 if len(w) >= 2}
        # 去除停用词
        stopwords = {'的', '了', '和', '与', '在', '是', '对', '为', '中', '不', '有',
                     '通过', '包括', '进行', '采用', '实现', '方法', '系统', '装置',
                     '模块', '单元', '数据', '信息', '技术', '一种', '发明'}
        common -= stopwords
        return sorted(common, key=len, reverse=True)

    # ─── 辅助方法 ─────────────────────────────────────────

    def _generate_suggestions(self, dimensions: Dict, comparisons: List[Dict]) -> List[str]:
        """根据评分生成改进建议"""
        suggestions = []
        for key, dim in dimensions.items():
            if dim["score"] < 60:
                if key == "structure":
                    suggestions.append("缺少必要章节，请确保包含全部10个标准章节")
                elif key == "length":
                    suggestions.append("篇幅不足4000字，建议扩充技术方案和实施例细节")
                elif key == "numbering":
                    suggestions.append("段落编号不规范，应使用[0001]格式连续编号")
                elif key == "technical_depth":
                    suggestions.append("技术深度不足，建议增加具体参数指标和数学公式")
                elif key == "claims":
                    suggestions.append("权利要求不完整，建议至少2条独立权利要求+5条从属权利要求")
                elif key == "implementation":
                    suggestions.append("实施例不充分，建议提供至少2个含具体参数的实施例")
                elif key == "relevance":
                    suggestions.append("内容与输入想法相关性偏低，建议紧扣核心技术方案")
                elif key == "novelty":
                    suggestions.append("与现有专利相似度较高，建议突出差异化创新点")

        if comparisons and comparisons[0]["similarity"] > 0.5:
            suggestions.append(
                f"注意：与{comparisons[0]['patent_id']}相似度较高"
                f"({comparisons[0]['similarity']:.2f})，建议在背景技术中引用并明确区别"
            )
        return suggestions

    @staticmethod
    def _score_to_grade(score: float) -> str:
        if score >= 85:
            return "A"
        elif score >= 70:
            return "B"
        elif score >= 55:
            return "C"
        return "D"
