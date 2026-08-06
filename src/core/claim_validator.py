"""权利要求书格式自动校验（符合专利法实施细则 / 审查指南）

检查项：
1. 编号连续（1. 2. 3. ...）
2. 每条权利要求内容完整（非空、非过短）
3. 独立权利要求含"其特征在于"（前序+特征两段式）
4. 从属权利要求引用格式正确（"根据权利要求X所述的" / "如权利要求X所述"）
5. 引用存在性：被引用的权利要求编号必须存在
6. 引用顺序：从属权利要求只能引用在前的权利要求
7. 多重引用提示：从属引用从属且为多项时提醒

使用：
    from src.core.claim_validator import validate_claims
    report = validate_claims(disclosure_text)
"""

import re
from typing import Dict, List, Optional


def parse_claims(text: str) -> List[Dict]:
    """从交底书/权利要求书文本中解析权利要求列表

    Args:
        text: 全文（自动定位权利要求书部分）

    Returns:
        [{"number": int, "text": str}, ...]
    """
    # 定位权利要求书部分（到说明书或结尾）
    m = re.search(r"##?\s*权利要求书\s*(.*?)(?=##?\s*说明书|##?\s*技术领域|$)",
                  text, re.DOTALL)
    section = m.group(1) if m else text

    # 兼容标准编号 "1. " 与 "**权利要求1.**" 加粗格式
    matches = list(re.finditer(
        r"(?:\*\*)?权利要求?\s*(\d+)\s*[.、]?\s*\*\*?|^\s*(\d+)\s*[.、]\s*",
        section, re.MULTILINE))
    claims = []
    for i, mm in enumerate(matches):
        num = int(mm.group(1) or mm.group(2))
        start = mm.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        body = section[start:end].strip()
        claims.append({"number": num, "text": body})
    return claims


# 引用格式：根据权利要求X所述 / 如权利要求X所述 / 根据权利要求X-1
REF_RE = re.compile(r"(?:根据|如)权利要求\s*(\d+)(?:[-~至](\d+))?\s*所述")


def validate_claims(disclosure: str) -> Dict:
    """校验权利要求书格式

    Args:
        disclosure: 交底书全文

    Returns:
        {total, independent, dependent, valid, issues: [{level, message, claim}], summary}
    """
    claims = parse_claims(disclosure)
    issues: List[Dict] = []
    num_set = {c["number"] for c in claims}

    # 1. 编号连续性
    expected = 1
    for c in claims:
        if c["number"] != expected:
            issues.append({
                "level": "error",
                "claim": c["number"],
                "message": f"权利要求编号不连续：应第{expected}项，实际为第{c['number']}项",
            })
        expected = c["number"] + 1

    # 逐条校验
    for c in claims:
        num = c["number"]
        body = c["text"]

        # 2. 内容完整性（过短报错但不中断，继续检查引用/特征）
        if len(body) < 30:
            issues.append({
                "level": "error", "claim": num,
                "message": f"权利要求{num}内容过短({len(body)}字)，可能不完整",
            })

        # 判定独权/从权
        refs = REF_RE.findall(body)
        if refs:
            # 从属权利要求
            for r0, r1 in refs:
                ref_base = int(r0)
                # 3. 引用存在性
                if ref_base not in num_set:
                    issues.append({
                        "level": "error", "claim": num,
                        "message": f"权利要求{num}引用了不存在的权利要求{ref_base}",
                    })
                # 4. 引用顺序：只能引用在前的
                if ref_base >= num:
                    issues.append({
                        "level": "error", "claim": num,
                        "message": f"权利要求{num}引用了在后的权利要求{ref_base}，违反引用规则",
                    })
                # 5. 多重引用提示（引用另一从属且为范围引用）
                if r1:
                    issues.append({
                        "level": "warning", "claim": num,
                        "message": f"权利要求{num}为多项引用({r0}-{r1})，多项引多项需审查员允许",
                    })
        else:
            # 独立权利要求：必须有"其特征在于"
            if "其特征在于" not in body:
                issues.append({
                    "level": "error", "claim": num,
                    "message": f"独立权利要求{num}缺少'其特征在于'（应为前序+特征两段式）",
                })

    # 主题一致性快速检查：第一条应含"一种"
    if claims and "一种" not in claims[0]["text"][:50]:
        issues.append({
            "level": "warning", "claim": claims[0]["number"],
            "message": "权利要求1开头应为'一种...'（保护主题），请检查",
        })

    independent = sum(1 for c in claims if not REF_RE.search(c["text"]))
    dependent = len(claims) - independent
    errors = sum(1 for i in issues if i["level"] == "error")
    warnings = sum(1 for i in issues if i["level"] == "warning")
    valid = errors == 0

    if not claims:
        summary = "未解析到权利要求（可能交底书不含权利要求书部分）"
    elif errors == 0 and warnings == 0:
        summary = f"权利要求格式校验通过：{independent}独立+{dependent}从属，无问题"
    elif errors == 0:
        summary = f"基本合格：{independent}独立+{dependent}从属，{warnings}个提醒"
    else:
        summary = f"发现{errors}个格式错误、{warnings}个提醒，需修正"

    return {
        "total": len(claims),
        "independent": independent,
        "dependent": dependent,
        "valid": valid,
        "issues": issues,
        "summary": summary,
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
        import json
        print(json.dumps(validate_claims(text), ensure_ascii=False, indent=2))
