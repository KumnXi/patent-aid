"""交底书交付自查：docx 渲染成图，VL 回看显示质量

解决"Word 导出了但没人看渲染结果"的问题：
docx → LibreOffice(soffice --headless) 转 PDF → PyMuPDF(fitz) 逐页渲染 PNG →
qwen-vl 看图 → 结构化质检报告（公式 / 附图 / 布局 / 乱码）。

依赖：
- LibreOffice：未装时 find_soffice() 返回 None，调用方给出 winget 安装提示
- PyMuPDF（fitz）、PIL（vl_client 用）、DashScope VL

使用：
    from src.utils.disclosure_inspector import inspect_disclosure
    report = inspect_disclosure("output/交底书.docx")
    # → {pages: [{page, png, overview, issues:[{type,severity,description,location}]}],
    #     total_issues, error_count, summary}
"""

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from src.api.vl_client import VLClient
from src.utils.idea_vision import _parse_structured

# 各平台 soffice 常见安装路径
_SOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
]

# 让 VL 按"公式/附图/布局/乱码"检查一页 Word 渲染图
INSPECT_PROMPT = """你是一位专利文档质检员，检查一页技术交底书 Word 渲染图的显示质量。

请仔细查看这一页图片，逐项检查以下问题，用严格的 JSON 输出（不要输出任何其他文字）：

{
  "page_overview": "这一页内容的一句话概述",
  "issues": [
    {
      "type": "formula | figure | layout | garbled | other",
      "severity": "error | warning",
      "description": "具体问题描述",
      "location": "问题在页面中的位置（如：右上角、中部公式附近）"
    }
  ]
}

检查点：
1. formula: 公式是否渲染正常（原生公式或图片），有无缺字符/变形/显示为文本
2. figure: 附图（流程图/示意图）是否清晰、有无文字重叠、是否超出页面
3. layout: 标题层级是否错乱、文字是否溢出页边距、段落编号如[0001]是否正常
4. garbled: 有无乱码（□、�、错别字、字体缺字形）
5. other: 其他明显显示问题

如果没有问题，issues 返回空数组。"""


def find_soffice() -> Optional[str]:
    """定位 soffice 可执行文件（LibreOffice）"""
    for cand in _SOFFICE_CANDIDATES:
        if Path(cand).exists():
            return cand
    which = shutil.which("soffice") or shutil.which("soffice.exe")
    return which if which else None


def render_docx_to_pngs(docx_path: str, out_dir: Optional[str] = None,
                        dpi: int = 150) -> List[Path]:
    """docx → PDF → 逐页 PNG

    Args:
        docx_path: 输入 .docx
        out_dir: PNG 输出目录（缺省为 docx 同目录下 _selfcheck_pages/）
        dpi: 渲染分辨率

    Returns:
        PNG 路径列表（按页序），失败返回 []
    """
    docx = Path(docx_path)
    if not docx.exists():
        print(f"[inspector] 文件不存在: {docx}")
        return []

    soffice = find_soffice()
    if not soffice:
        print("[inspector] 未找到 LibreOffice（soffice）。请先安装：")
        print("  winget install --id TheDocumentFoundation.LibreOffice")
        return []

    out_dir = Path(out_dir) if out_dir else docx.parent / "_selfcheck_pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. docx → pdf（soffice 输出的 pdf 与 docx 同名，落在 outdir 下）
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(out_dir), str(docx)],
            check=True, capture_output=True, timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[inspector] soffice 转换失败: {e}")
        return []

    # 2. pdf → 逐页 png
    pdf_path = out_dir / (docx.stem + ".pdf")
    if not pdf_path.exists():
        candidates = sorted(out_dir.glob("*.pdf"))
        pdf_path = candidates[0] if candidates else pdf_path
    if not pdf_path.exists():
        print(f"[inspector] 未找到转换出的 PDF: {pdf_path}")
        return []

    import fitz
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"[inspector] PDF 打开失败: {e}")
        return []

    pages = []
    try:
        for i in range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=dpi)
            png_path = out_dir / f"page_{i + 1:02d}.png"
            pix.save(str(png_path))
            pages.append(png_path)
    finally:
        doc.close()

    print(f"[inspector] 渲染 {len(pages)} 页 → {out_dir}")
    return pages


def inspect_disclosure(docx_path: str, max_pages: int = 0,
                       dpi: int = 150) -> Dict:
    """docx → 逐页 VL 质检（交付自查主入口）

    Args:
        docx_path: 输入 .docx
        max_pages: 只查前 N 页（0 表示全部）
        dpi: 渲染分辨率

    Returns:
        {"pages": [{page, png, overview, issues}], "total_issues",
         "error_count", "summary"}；渲染/配置失败时含 "error" 键
    """
    pages = render_docx_to_pngs(docx_path, dpi=dpi)
    if not pages:
        return {"error": "渲染失败（检查 LibreOffice 是否安装、路径是否正确）",
                "pages": []}

    client = VLClient()
    if not client.is_available():
        return {"error": "DashScope 未配置，无法 VL 回看", "pages": pages}

    if max_pages:
        pages = pages[:max_pages]

    results: List[Dict] = []
    total_issues = 0
    for i, png in enumerate(pages, 1):
        text = client.chat_with_image(str(png), INSPECT_PROMPT, max_tokens=1024)
        findings = _parse_structured(text) if text else {}
        issues = findings.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        total_issues += len(issues)
        results.append({
            "page": i,
            "png": str(png),
            "overview": findings.get("page_overview", ""),
            "issues": issues,
        })
        # 终端摘要（压缩显示）
        if issues:
            brief = "; ".join(x.get("description", "")[:28] for x in issues[:3])
            print(f"  P{i:02d} 检出 {len(issues)} 个问题: {brief}")
        else:
            print(f"  P{i:02d} 正常")

    error_count = sum(1 for p in results for x in p["issues"]
                      if x.get("severity") == "error")
    return {
        "pages": results,
        "total_issues": total_issues,
        "error_count": error_count,
        "summary": (f"共 {len(results)} 页，检出 {total_issues} 个问题"
                    f"（{error_count} 个 error）" if results else "无页面"),
    }


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("用法: python src/utils/disclosure_inspector.py <交底书.docx> [--max-pages N]")
        sys.exit(1)
    docx = sys.argv[1]
    mp = 0
    if "--max-pages" in sys.argv:
        mp = int(sys.argv[sys.argv.index("--max-pages") + 1])
    import json
    print(json.dumps(inspect_disclosure(docx, max_pages=mp),
                     ensure_ascii=False, indent=2))
