"""合规审查模块（专利法格式 / 禁用表述 / 摘要字数 / 引用关系 / 支持性）

对标 claim_validator.py 与 data_authenticity_checker.py 的 check → report 风格。
消费 config/patent_law 与 config/terminology/forbidden.json 中**已有但此前未接线**的
合规弹药（此前只有 get_forbidden_words 被单词推荐 API 用到，全文合规扫描缺失）。

审查维度：
1. 禁用表述   forbidden.json 全文化扫描（口语化/AI痕迹/模糊/商业宣传 4 类）
2. 摘要字数   摘要章节 ≤ 300 字（专利法实施细则第 23 条）
3. 引用合法性  复用 claim_validator.validate_claims() 的结果
4. 支持性     权利要求技术特征能否在说明书前文 / 输入想法中找到依据（no-new-matter）
5. 充分公开   对照 patent_law.json 第 26 条，检查实施例是否足够

使用：
    from src.core.compliance_checker import ComplianceChecker
    checker = ComplianceChecker()              # 自动读 config/
    report = checker.check(disclosure, idea)   # → {score, grade, issues, summary}
    result = checker.auto_fix(disclosure)      # → {fixed, fixes, issue_count, fixed_count}
"""

import re
import json
from typing import Dict, List, Optional, Tuple

from .database_loader import DatabaseLoader
from .claim_validator import validate_claims
from .quality_reviewer import QualityReviewer


# 摘要章节正则（兼容 "## 摘要" 与 "## 十、摘要" 两种格式）
ABSTRACT_RE = re.compile(r"##?\s*(?:十、)?摘要\s*(.*?)(?=##?\s|$)", re.DOTALL)

# 权利要求书章节定位（与 claim_validator / quality_reviewer 保持一致）
CLAIMS_SECTION_RE = re.compile(r"权利要求.*?(?=##\s*十|$)", re.DOTALL)

# 段落编号 [0001]
PARA_NUM_RE = re.compile(r"\[\d{4}\]")


class ComplianceChecker:
    """交底书合规审查器（纯规则，不调 LLM）"""

    # 摘要字数上限（字）
    ABSTRACT_MAX = 300

    # 自动修复时跳过以"删除"开头的 correct（避免误删内容）
    NON_AUTO_FIX_PREFIXES = ("删除", "仅", "改为")

    def __init__(self, loader: Optional[DatabaseLoader] = None,
                 config_dir: str = "config"):
        """初始化合规审查器

        Args:
            loader: DatabaseLoader 实例（复用缓存，可选）
            config_dir: 配置目录（未传 loader 时用于构造）
        """
        self.loader = loader or DatabaseLoader("data/patent_database", config_dir)
        self._forbidden_cache: Optional[List[Dict]] = None
        self._law_cache: Optional[Dict] = None

    # ─────────────────────────────────────────────────────────────
    # 数据加载（带缓存）
    # ─────────────────────────────────────────────────────────────

    def _all_forbidden_terms(self) -> List[Dict]:
        """获取全部禁用词（扁平列表）"""
        if self._forbidden_cache is not None:
            return self._forbidden_cache
        self._forbidden_cache = self.loader.get_all_forbidden_terms()
        return self._forbidden_cache

    def _patent_law(self) -> Dict:
        """获取专利法条文"""
        if self._law_cache is not None:
            return self._law_cache
        self._law_cache = self.loader.get_patent_law()
        return self._law_cache

    # ─────────────────────────────────────────────────────────────
    # 各维度检查
    # ─────────────────────────────────────────────────────────────

    def _scan_forbidden(self, text: str) -> List[Dict]:
        """禁用表述全文化扫描

        forbidden.json 中带 "XX" 通配的项（如"提高XX%"）编译为正则；
        简单词直接子串匹配。返回带 severity 与上下文的 issues。
        """
        issues: List[Dict] = []
        for ft in self._all_forbidden_terms():
            forbidden = ft.get("forbidden", "")
            category = ft.get("category", "")
            correct = ft.get("correct", "")
            if not forbidden:
                continue

            matches = self._find_forbidden_matches(forbidden, text)
            for m in matches:
                # 商业宣传/口语化 → error；AI痕迹/模糊 → warning（与真实性检查器重叠项不重复计 critical）
                severity = "error" if category in ("商业宣传用语", "口语化表述") else "warning"
                issues.append({
                    "type": "forbidden",
                    "severity": severity,
                    "message": f"检测到{category}禁用表述「{m}」",
                    "location": self._context(text, m),
                    "suggestion": correct or "删除",
                    "category": category,
                })
        return issues

    @staticmethod
    def _find_forbidden_matches(forbidden: str, text: str) -> List[str]:
        """返回文本中所有命中的禁用词/模式实例（去重）"""
        if "XX" in forbidden:
            pat = re.escape(forbidden).replace("XX", r"[^。\n，；]{0,8}?")
            try:
                return list(dict.fromkeys(m.group(0) for m in re.finditer(pat, text)))
            except re.error:
                return []
        # 简单子串匹配
        hits = []
        start = 0
        while True:
            idx = text.find(forbidden, start)
            if idx == -1:
                break
            hits.append(forbidden)
            start = idx + len(forbidden)
        return hits

    @staticmethod
    def _context(text: str, phrase: str) -> str:
        """截取命中短语前后文（去换行，≤80字符）"""
        idx = text.find(phrase)
        if idx == -1:
            return ""
        start = max(0, idx - 30)
        end = min(len(text), idx + len(phrase) + 30)
        return text[start:end].replace("\n", " ")

    def _check_abstract(self, text: str) -> Optional[Dict]:
        """摘要字数检查（≤300字）"""
        m = ABSTRACT_RE.search(text)
        if not m:
            return None
        abstract = m.group(1)
        clean = PARA_NUM_RE.sub("", abstract)
        clean = re.sub(r"[#*\[\]\n\r\s]", "", clean)
        length = len(clean)
        if length <= self.ABSTRACT_MAX:
            return None
        return {
            "type": "abstract",
            "severity": "error",
            "message": f"摘要超出{self.ABSTRACT_MAX}字限制（当前{length}字）",
            "location": abstract[:80].replace("\n", " "),
            "suggestion": f"压缩至{self.ABSTRACT_MAX}字以内",
        }

    def _check_claim_references(self, text: str) -> List[Dict]:
        """权利要求引用合法性（复用 claim_validator.validate_claims）"""
        issues: List[Dict] = []
        try:
            report = validate_claims(text)
        except Exception:
            return issues
        for issue in report.get("issues", []):
            level = issue.get("level", "warning")
            issues.append({
                "type": "claims",
                "severity": "error" if level == "error" else "warning",
                "message": issue.get("message", ""),
                "location": f"权利要求{issue.get('claim', '?')}",
                "suggestion": "按专利法实施细则权利要求书写规范修正",
            })
        return issues

    def _check_support(self, text: str, idea: str = "") -> List[Dict]:
        """支持性检查（no-new-matter）

        有 idea 时：想法核心词在权利要求中的保留率（防编造/超范围）。
        无 idea 时：权利要求特征词在说明书前文的覆盖率（内部一致性）。
        """
        m = CLAIMS_SECTION_RE.search(text)
        if not m:
            return []
        claims_text = m.group(0)
        claim_terms = QualityReviewer._extract_terms(claims_text)
        if not claim_terms:
            return []

        if idea:
            idea_terms = QualityReviewer._extract_terms(idea)
            if not idea_terms:
                return []
            core_covered = idea_terms & claim_terms
            core_coverage = len(core_covered) / len(idea_terms)
            if core_coverage < 0.3:
                return [{
                    "type": "support",
                    "severity": "error",
                    "message": f"权利要求与输入想法脱节：想法核心词仅保留{core_coverage:.0%}，疑似超范围/编造",
                    "location": claims_text[:60].replace("\n", " "),
                    "suggestion": "收紧为想法涵盖的技术特征范围",
                }]
            if core_coverage < 0.6:
                return [{
                    "type": "support",
                    "severity": "warning",
                    "message": f"部分权利要求特征未在输入想法中找到依据（保留率{core_coverage:.0%}）",
                    "location": claims_text[:60].replace("\n", " "),
                    "suggestion": "补充想法中的技术特征，或删除超出范围的特征",
                }]
            return []

        # 无 idea：权利要求特征在说明书正文（排除权利要求书）的覆盖率
        body_text = text
        # 取发明内容+具体实施方式部分
        body_match = re.search(r"发明内容(.*?)(?=##\s*|$)", text, re.DOTALL)
        body_text = body_match.group(1) if body_match else text
        body_terms = QualityReviewer._extract_terms(body_text)
        if not body_terms:
            return []
        coverage = len(claim_terms & body_terms) / len(claim_terms)
        if coverage < 0.3:
            return [{
                "type": "support",
                "severity": "warning",
                "message": f"权利要求技术特征在发明内容中覆盖率低（{coverage:.0%}），部分特征无前文记载",
                "location": claims_text[:60].replace("\n", " "),
                "suggestion": "在发明内容/实施方式中补充权利要求特征的技术描述",
            }]
        return []

    def _check_disclosure(self, text: str) -> List[Dict]:
        """充分公开检查（专利法第 26 条）：实施例数量与必要手段"""
        issues: List[Dict] = []
        impl_match = re.search(r"实施方式(.*?)(?=##\s*九|$)", text, re.DOTALL)
        impl_text = impl_match.group(1) if impl_match else ""
        examples = re.findall(r"实施例\s*\d+", impl_text)
        if len(examples) < 2:
            issues.append({
                "type": "disclosure",
                "severity": "warning",
                "message": f"实施例不足（仅{len(examples)}个），说明书应充分公开技术方案",
                "location": impl_text[:60].replace("\n", " "),
                "suggestion": "补充至少 2 个含具体参数的实施例（专利法第26条第3款）",
            })
        # 必要技术手段：实施方式是否含量化参数
        if impl_text and not re.search(r"\d+(?:\.\d+)?\s*(?:mm|cm|℃|°|%|MPa|kPa|V|kV|s|ms|Hz)", impl_text):
            issues.append({
                "type": "disclosure",
                "severity": "warning",
                "message": "具体实施方式缺少量化参数，公开不充分",
                "location": impl_text[:60].replace("\n", " "),
                "suggestion": "补充尺寸/温度/压力/时间等示例性参数",
            })
        return issues

    # ─────────────────────────────────────────────────────────────
    # 主入口
    # ─────────────────────────────────────────────────────────────

    def check(self, disclosure: str, idea: str = "") -> Dict:
        """执行完整合规审查

        Args:
            disclosure: 交底书全文
            idea: 原始技术想法（可选，用于支持性校验）

        Returns:
            {score, grade, issues, summary, dimensions}
        """
        issues: List[Dict] = []
        dimensions: Dict[str, Dict] = {}

        # 1. 禁用表述
        forbidden = self._scan_forbidden(disclosure)
        dimensions["forbidden"] = {
            "count": len(forbidden),
            "issues": forbidden,
            "detail": f"{len(forbidden)} 处禁用表述",
        }
        issues.extend(forbidden)

        # 2. 摘要字数
        abstract = self._check_abstract(disclosure)
        dimensions["abstract"] = {
            "count": 1 if abstract else 0,
            "issues": [abstract] if abstract else [],
            "detail": "摘要合格" if not abstract else abstract["message"],
        }
        if abstract:
            issues.append(abstract)

        # 3. 权利要求引用合法性
        claims = self._check_claim_references(disclosure)
        dimensions["claims"] = {
            "count": len(claims),
            "issues": claims,
            "detail": f"{len(claims)} 处权利要求问题",
        }
        issues.extend(claims)

        # 4. 支持性（no-new-matter）
        support = self._check_support(disclosure, idea)
        dimensions["support"] = {
            "count": len(support),
            "issues": support,
            "detail": "支持性合格" if not support else support[0]["message"],
        }
        issues.extend(support)

        # 5. 充分公开
        disclosure_issues = self._check_disclosure(disclosure)
        dimensions["disclosure"] = {
            "count": len(disclosure_issues),
            "issues": disclosure_issues,
            "detail": "公开充分" if not disclosure_issues else "实施方式公开不足",
        }
        issues.extend(disclosure_issues)

        # 综合评分：100 起扣
        score = 100
        score -= sum(8 for i in issues if i["severity"] == "error")
        score -= sum(3 for i in issues if i["severity"] == "warning")
        score = max(0, min(100, score))

        if score >= 90:
            grade = "A"
        elif score >= 75:
            grade = "B"
        elif score >= 60:
            grade = "C"
        else:
            grade = "D"

        return {
            "score": score,
            "grade": grade,
            "issues": issues,
            "summary": self._build_summary(issues),
            "dimensions": dimensions,
        }

    def auto_fix(self, disclosure: str) -> Dict:
        """自动修复禁用表述（保守策略）

        修复规则：
        - 禁用词按 correct 首选项替换（correct 以"删除"等开头的跳过，仅报告）
        - 摘要超限 / 权利要求问题 / 支持性问题：不自动改（有误改风险）

        Args:
            disclosure: 交底书全文

        Returns:
            {"fixed": 修复后文本, "fixes": 修复记录列表, "issue_count": 原问题数,
             "fixed_count": 修复数}
        """
        fixes: List[Dict] = []
        text = disclosure

        for ft in self._all_forbidden_terms():
            forbidden = ft.get("forbidden", "")
            correct = ft.get("correct", "")
            category = ft.get("category", "")
            if not forbidden or not correct:
                continue
            # 只自动修简单词（无 XX 通配），且 correct 可安全替换
            if "XX" in forbidden:
                continue
            if any(correct.startswith(p) for p in self.NON_AUTO_FIX_PREFIXES):
                continue
            replacement = correct.split("/")[0].strip()
            if not replacement:
                continue

            count = text.count(forbidden)
            if count == 0:
                continue
            text = text.replace(forbidden, replacement)
            fixes.append({
                "type": "forbidden",
                "action": f"替换禁用词",
                "detail": f"「{forbidden}」→「{replacement}」（{category}）",
                "count": count,
            })

        return {
            "fixed": text,
            "fixes": fixes,
            "issue_count": len(self._scan_forbidden(disclosure)),
            "fixed_count": len(fixes),
        }

    # ─────────────────────────────────────────────────────────────
    # 辅助
    # ─────────────────────────────────────────────────────────────

    def _build_summary(self, issues: List[Dict]) -> str:
        if not issues:
            return "合规审查通过：未发现禁用表述/格式/支持性问题"
        err = sum(1 for i in issues if i["severity"] == "error")
        warn = sum(1 for i in issues if i["severity"] == "warning")
        parts = []
        if err:
            parts.append(f"{err} 处 error（禁用词/摘要超限/引用错误）")
        if warn:
            parts.append(f"{warn} 处 warning")
        return "；".join(parts)


def check_from_file(disclosure_path: str, idea: str = "",
                    config_dir: str = "config") -> Dict:
    """从文件检查（脚本入口）"""
    text = __import__("pathlib").Path(disclosure_path).read_text(encoding="utf-8")
    return ComplianceChecker(config_dir=config_dir).check(text, idea)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    if len(sys.argv) < 2:
        print("用法: python src/core/compliance_checker.py <交底书.md> [想法.txt]")
        sys.exit(1)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    idea = ""
    if len(sys.argv) > 2:
        idea = Path(sys.argv[2]).read_text(encoding="utf-8")
    print(json.dumps(ComplianceChecker().check(text, idea), ensure_ascii=False, indent=2))
