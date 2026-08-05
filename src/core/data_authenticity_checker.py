"""数据真实性检查模块（防无中生有）

检查生成的交底书是否存在"AI 编造"问题，5 类检查：
1. 暗示实验表述：如"经实验证明""测试结果表明"（违反数据真实性最高原则）
2. 无来源量化效果：如"提高效率 30%"但输入想法无此依据
3. 具体参数无来源：±0.1mm、材料常数范围等工程值，建议标注来源或改"示例性"
4. 引用专利真实性核验：文中的 CN 专利号是否真实存在于数据库
5. 数据背景交代：温度/压力/材质等关键参数是否有明确背景来源

使用：
    from src.core.data_authenticity_checker import DataAuthenticityChecker
    checker = DataAuthenticityChecker()
    report = checker.check(disclosure, idea, patent_db)
"""

import re
import json
from typing import Dict, List, Optional
from pathlib import Path


class DataAuthenticityChecker:
    """数据真实性检查器"""

    # 暗示实验的表述（违规，需删除）
    EXPERIMENT_PATTERNS = [
        r"经实验证明", r"实验证明", r"测试表明", r"试验结果",
        r"实测表明", r"实验数据", r"测试结果表明", r"经试验验证",
        r"经仿真验证(?!.*(?:例如|具体实施))", r"实验结果",
        r"现场试验", r"工业试验表明",
    ]

    # 无来源量化效果表述
    EFFECT_PATTERNS = re.compile(
        r"[^。\n]*(?:提高|降低|缩短|减少|增加|提升|节约|延长|加快|节省|提升至)"
        r"[^。\n]*\d+(?:\.\d+)?%[^。\n]*[。]?"
    )

    # 具体工程参数（带单位数值，需确认来源）
    PARAM_PATTERN = re.compile(
        r"[±∓]?\d+(?:\.\d+)?\s*(?:mm|MPa|℃|°C|h|kJ/mol|mol|K|Pa|s|ms|组|层|个)"
    )

    # 专利号
    PATENT_ID_PATTERN = re.compile(r"CN\d{6,9}[ABU]")

    # 关键物理量（应有关联背景交代）
    KEY_PARAMS = ["温度", "压力", "材质", "壁厚", "运行时间", "工况"]

    def check(self, disclosure: str, idea: str = "",
              patent_db: Optional[Dict] = None) -> Dict:
        """执行完整检查

        Args:
            disclosure: 交底书全文
            idea: 原始技术想法（用于判断量化效果是否有来源）
            patent_db: 专利数据库 dict（{"patents": {...}}），用于核验引用专利

        Returns:
            检查报告：{score, grade, issues, stats}
        """
        issues: List[Dict] = []
        stats = {"experiment": 0, "effect": 0, "param": 0, "patent": 0}

        # 1. 暗示实验表述
        for pat in self.EXPERIMENT_PATTERNS:
            for m in re.finditer(pat, disclosure):
                start = max(0, m.start() - 30)
                ctx = disclosure[start:m.end() + 30].replace("\n", " ")
                issues.append({
                    "type": "experiment",
                    "severity": "critical",
                    "message": f"出现暗示实验的表述「{m.group(0)}」",
                    "context": ctx,
                })
                stats["experiment"] += 1

        # 2. 无来源量化效果
        idea_terms = set(self._extract_terms(idea)) if idea else set()
        for m in self.EFFECT_PATTERNS.finditer(disclosure):
            sent = m.group(0).strip()
            # 若是分级决策阈值（含"设计寿命的X%"）等工程判据，跳过
            if "设计寿命" in sent or "剩余寿命" in sent or "判定准则" in sent:
                continue
            # 判断表述中的关键名词是否在想法中出现（有来源）
            terms = self._extract_terms(sent)
            has_source = bool(terms & idea_terms)
            issues.append({
                "type": "effect",
                "severity": "warning" if has_source else "error",
                "message": f"量化效果表述无实验/输入依据: {sent[:50]}",
                "context": sent[:100],
                "has_source_in_idea": has_source,
            })
            stats["effect"] += 1

        # 3. 具体参数无来源提示
        param_ctxs = []
        for m in self.PARAM_PATTERN.finditer(disclosure):
            # 只看权利要求书部分，避免正文大量重复
            if "权利要求" not in disclosure[:m.start()]:
                continue
            ctx = disclosure[max(0, m.start() - 40):m.end() + 20].replace("\n", " ")
            param_ctxs.append((m.group(0), ctx))
        # 去重
        seen_p = set()
        for val, ctx in param_ctxs:
            key = (val, ctx[:60])
            if key in seen_p:
                continue
            seen_p.add(key)
            # 判断是否有来源交代
            has_source = any(kw in ctx for kw in
                             ("根据", "查取", "示例", "范围", "设计", "手册", "标准"))
            if not has_source:
                issues.append({
                    "type": "param",
                    "severity": "warning",
                    "message": f"具体参数「{val}」未交代来源，建议标注'示例性'或'按材料手册查取'",
                    "context": ctx,
                })
                stats["param"] += 1

        # 4. 引用专利真实性核验
        if patent_db:
            patents = patent_db.get("patents", {})
            seen_cn = set()
            for pid in self.PATENT_ID_PATTERN.findall(disclosure):
                if pid in seen_cn:
                    continue
                seen_cn.add(pid)
                if pid not in patents:
                    issues.append({
                        "type": "patent",
                        "severity": "critical",
                        "message": f"引用专利 {pid} 不在专利库中，疑似编造专利号",
                        "context": pid,
                    })
                    stats["patent"] += 1

        # 5. 数据背景交代评分
        background_score = self._check_background(disclosure)

        # 综合评分：满分 100，按严重度扣分
        score = 100
        score -= stats["experiment"] * 30   # 实验表述最严重
        score -= stats["patent"] * 25       # 编造专利号严重
        score -= sum(1 for i in issues if i["severity"] == "error") * 10
        score -= sum(1 for i in issues if i["severity"] == "warning") * 3
        score = max(0, min(100, score))
        score = round((score * 0.8 + background_score * 0.2))

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
            "background_score": background_score,
            "issues": issues[:50],
            "stats": stats,
            "summary": self._build_summary(issues, background_score),
        }

    def _check_background(self, disclosure: str) -> int:
        """数据背景交代评分：关键物理量是否有关联背景说明"""
        if not disclosure:
            return 0
        scores = 0
        for kw in self.KEY_PARAMS:
            if kw in disclosure:
                scores += 1
        return round(scores / len(self.KEY_PARAMS) * 100)

    @staticmethod
    def _extract_terms(text: str) -> set:
        """提取中文术语（简单字符 bigram，够用）"""
        text = text or ""
        terms = set()
        for i in range(len(text) - 1):
            t = text[i:i + 2]
            if re.match(r"[一-鿿]", t):
                terms.add(t)
        return terms

    def _build_summary(self, issues: List[Dict], bg_score: int) -> str:
        crit = sum(1 for i in issues if i["severity"] == "critical")
        err = sum(1 for i in issues if i["severity"] == "error")
        warn = sum(1 for i in issues if i["severity"] == "warning")
        parts = []
        if crit:
            parts.append(f"发现 {crit} 处严重问题（疑似编造实验/专利号）")
        if err:
            parts.append(f"{err} 处无来源量化效果")
        if warn:
            parts.append(f"{warn} 处参数/效果建议补充来源")
        parts.append(f"数据背景交代完整度 {bg_score}%")
        return "；".join(parts) if parts else "未发现明显无中生有问题"


def check_from_file(disclosure_path: str, idea: str = "",
                    db_path: str = "data/patent_database/index.json") -> Dict:
    """从文件检查（脚本入口）"""
    text = Path(disclosure_path).read_text(encoding="utf-8")
    db = None
    if Path(db_path).exists():
        db = json.load(open(db_path, encoding="utf-8"))
    checker = DataAuthenticityChecker()
    return checker.check(text, idea, db)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python src/core/data_authenticity_checker.py <交底书.md> [想法.txt]")
        sys.exit(1)
    report = check_from_file(sys.argv[1])
    print(json.dumps(report, ensure_ascii=False, indent=2))
