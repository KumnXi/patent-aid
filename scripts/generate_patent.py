"""一键生成标准专利格式交底书（完整流水线）

流水线：
    想法 → ①三阶段LLM生成 → ②防无中生有自动修复 → ③权利要求格式校验
         → ④保存历史(加密) → ⑤导出Word(原生公式+说明书附图)

产出：标准中国专利格式 Word（发明名称→摘要→权利要求书→说明书五段式），
      LaTeX公式为Word原生可编辑公式，附图说明自动生成专利风格图。

用法：
    python scripts/generate_patent.py "技术想法" \
        [--title 发明名称] [--tech-field 技术领域] [--purpose 发明目的] \
        [--core-method 核心方法] [--problems 现有问题] [--out 输出.docx]

示例：
    python scripts/generate_patent.py "一种高温蒸汽管道缺陷评估方法" \
        --tech-field "火力发电高温蒸汽管道检测" --out output/交底书.docx
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import PatentInnovationEngine
from src.utils.history import save_disclosure
from src.utils.word_exporter import export_disclosure_to_word


def main():
    parser = argparse.ArgumentParser(description="一键生成标准专利格式交底书")
    parser.add_argument("idea", help="技术想法描述")
    parser.add_argument("--title", default="", help="发明名称")
    parser.add_argument("--tech-field", default="", help="技术领域")
    parser.add_argument("--purpose", default="", help="发明目的/要解决的问题")
    parser.add_argument("--core-method", default="", help="核心方法/技术路线")
    parser.add_argument("--problems", default="", help="现有技术问题")
    parser.add_argument("--out", default="", help="输出Word路径（默认 output/交底书.docx）")
    args = parser.parse_args()

    fields = {
        "tech_field": args.tech_field,
        "purpose": args.purpose,
        "core_method": args.core_method,
        "problems": args.problems,
    }

    print("=" * 60)
    print("专利交底书生成流水线")
    print("=" * 60)

    # ① 初始化 + 生成
    t0 = time.time()
    print("[1/5] 初始化引擎...")
    engine = PatentInnovationEngine()
    engine.initialize()

    print(f"[2/5] 三阶段LLM生成交底书...")
    result = engine.generate_disclosure(args.idea, title=args.title or None,
                                        fields=fields)
    disclosure = result["disclosure"]
    mode = result["mode"]
    qr = result.get("quality_report") or {}

    # ② 防无中生有（已在 generate_disclosure 内自动执行）
    auth = result.get("authenticity_fixed") or {}
    # ③ 权利要求校验（已在 generate_disclosure 内自动执行）
    claim = result.get("claim_validation") or {}

    # ④ 保存历史（加密）
    print("[3/5] 保存历史...")
    hid = save_disclosure(args.idea, disclosure, mode, title=args.title or None,
                          quality_report=qr or None)

    # ⑤ 导出 Word
    print("[4/5] 导出标准专利格式 Word...")
    out_path = args.out or str(Path("output") / "交底书.docx")
    export_disclosure_to_word(disclosure, out_path, title=args.title or None)

    # 报告
    print("[5/5] 完成")
    print("=" * 60)
    print(f"生成模式: {mode} | 字数: {len(disclosure)}")
    print(f"质检评分: {qr.get('total_score')} ({qr.get('grade')})")
    print(f"防无中生有: 修复{auth.get('fixed_count', 0)}处 | 剩余问题{auth.get('issue_count', 0)}个")
    print(f"权利要求校验: {claim.get('summary', 'N/A')}")
    print(f"历史ID: {hid}")
    print(f"Word输出: {out_path} ({Path(out_path).stat().st_size} bytes)")
    print(f"总耗时: {time.time() - t0:.0f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
