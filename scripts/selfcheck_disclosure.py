"""交底书交付自查脚本：docx → 渲染 → VL 回看 → 结构化报告

交付自查闭环：Word 导出 ≠ 交付。渲染成图后让 VL 回看显示质量
（公式/附图/布局/乱码），及时发现"导出成功但渲染有问题"的情况。

依赖：
- LibreOffice（未装时提示 winget 安装）
- DashScope VL（config/api_config.json 的 dashscope 段）

用法：
    python scripts/selfcheck_disclosure.py output/交底书.docx
    python scripts/selfcheck_disclosure.py output/交底书.docx --max-pages 3
    python scripts/selfcheck_disclosure.py output/交底书.docx --report report.json
"""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.disclosure_inspector import inspect_disclosure


def main():
    parser = argparse.ArgumentParser(description="交底书交付自查（渲染 + VL 回看）")
    parser.add_argument("docx", help="交底书 docx 路径")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="只查前 N 页（0 表示全部）")
    parser.add_argument("--dpi", type=int, default=150,
                        help="渲染分辨率（默认 150）")
    parser.add_argument("--report", default="",
                        help="把 JSON 报告写到文件")
    args = parser.parse_args()

    docx = Path(args.docx)
    if not docx.exists():
        print(f"文件不存在: {docx}")
        sys.exit(1)

    print("=" * 60)
    print("  交底书交付自查（渲染 → VL 回看）")
    print("=" * 60)
    report = inspect_disclosure(str(docx), max_pages=args.max_pages,
                                dpi=args.dpi)

    print("\n" + "=" * 60)
    print(f"自查结论: {report.get('summary', '无页面')}")
    if report.get("error"):
        print(f"错误: {report['error']}")
        sys.exit(2)
    if report.get("error_count"):
        print("有 error 级问题，建议修复后重新导出再自查。")
    print("=" * 60)

    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告已写入: {args.report}")


if __name__ == "__main__":
    main()
