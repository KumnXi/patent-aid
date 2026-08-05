"""交底书 → 标准专利格式 Word 文档导出

按中国专利说明书格式要求生成 .docx：
- A4 纵向，页边距 上25 / 左25 / 右15 / 下15 mm
- 宋体小四（12pt），1.5 倍行距，纯黑色
- 发明名称第一页第一行居中
- 保留 [0001] 段落编号
- LaTeX 公式（$...$ / $$...$$）经 matplotlib mathtext 渲染为图片插入

使用：
    from src.utils.word_exporter import export_disclosure_to_word
    export_disclosure_to_word(disclosure_text, "output/交底书.docx")
"""

import re
import tempfile
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Pt, Mm, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn

# 页面规格（mm）
PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297
MARGIN_TOP_MM = 25
MARGIN_LEFT_MM = 25
MARGIN_RIGHT_MM = 15
MARGIN_BOTTOM_MM = 15

# LaTeX 公式：$$...$$ 或 $...$
FORMULA_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.DOTALL)


def _set_run_font(run, name_cn: str = "宋体", size_pt: int = 12,
                  bold: bool = False):
    """设置 run 字体（含中文字体）"""
    run.font.name = "Times New Roman"
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)
    # 设置中文字体
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name_cn)


def _render_formula_png(latex: str, fontsize: int = 14, dpi: int = 200) -> Optional[Path]:
    """将 LaTeX 公式渲染为 PNG（matplotlib mathtext，无需完整 LaTeX）

    Args:
        latex: LaTeX 公式（不含 $ 定界符）
        fontsize: 字号
        dpi: 分辨率

    Returns:
        PNG 临时文件路径，失败返回 None
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 清洗：LLM/JSON 转义可能产生双反斜杠，matplotlib mathtext 不认
    latex = latex.replace("\\\\", "\\").strip()

    try:
        fig = plt.figure(figsize=(0.1, 0.1))
        t = fig.text(0.5, 0.5, f"${latex}$",
                     fontsize=fontsize, ha="center", va="center")
        fig.canvas.draw()  # 触发渲染，提前暴露 LaTeX 错误

        tmp = Path(tempfile.gettempdir()) / "patent_formula.png"
        fig.savefig(tmp, dpi=dpi, bbox_inches="tight",
                    pad_inches=0.03, transparent=True)
        plt.close(fig)
        return tmp if tmp.exists() else None
    except Exception as e:
        plt.close("all")
        print(f"  公式渲染失败（回退为文本）: {e}")
        return None


def export_disclosure_to_word(disclosure: str, output_path: str,
                              title: Optional[str] = None) -> str:
    """导出交底书为标准专利格式 Word

    Args:
        disclosure: 交底书全文（支持 Markdown 标题和 $...$ LaTeX 公式）
        output_path: 输出 .docx 路径
        title: 发明名称（缺省从全文提取第一个 # 标题）

    Returns:
        保存的路径
    """
    doc = Document()

    # ── 页面设置 ──
    sec = doc.sections[0]
    sec.page_width = Mm(PAGE_WIDTH_MM)
    sec.page_height = Mm(PAGE_HEIGHT_MM)
    sec.top_margin = Mm(MARGIN_TOP_MM)
    sec.left_margin = Mm(MARGIN_LEFT_MM)
    sec.right_margin = Mm(MARGIN_RIGHT_MM)
    sec.bottom_margin = Mm(MARGIN_BOTTOM_MM)

    # Normal 样式：宋体 12pt
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    pf = normal.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.5

    # ── 提取发明名称：优先标准格式 "## 发明名称" 章节的下一行 ──
    m = re.search(r"##\s*发明名称\s*\n\s*([^\n]+)", disclosure)
    if m:
        title = m.group(1).strip()
    elif not title or title in ("专利交底书", "技术交底书"):
        m2 = re.search(r"^#\s+(.+)$", disclosure, re.M)
        title = m2.group(1).strip() if m2 else "专利交底书"

    # 名称第一页第一行，居中
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p_title.add_run(title)
    _set_run_font(run, size_pt=14, bold=True)
    doc.add_paragraph()  # 名称与正文之间空一行

    # ── 按行处理正文 ──
    # 移除"发明名称"章节（顶部已作为居中标题输出，避免重复）
    disclosure_clean = re.sub(
        r"##\s*发明名称\s*\n\s*[^\n]+\n?", "", disclosure, count=1)
    lines = disclosure_clean.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 跳过文档一级标题行（已作为名称输出）
        if stripped.startswith("# ") and i == 0:
            i += 1
            continue

        # Markdown 标题 → 加粗段落
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(heading)
            _set_run_font(run, size_pt=13, bold=True)
            i += 1
            continue
        if stripped.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(stripped[3:].strip())
            _set_run_font(run, size_pt=13, bold=True)
            i += 1
            continue

        # 公式：$$...$$ 单独成段
        if stripped.startswith("$$") or (stripped.startswith("$")
                                         and stripped.endswith("$")
                                         and len(stripped) > 6):
            latex = stripped.strip("$").strip()
            img = _render_formula_png(latex)
            if img:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                from docx.shared import Inches
                p.add_run().add_picture(str(img), width=Inches(3.5))
            else:
                p = doc.add_paragraph()
                run = p.add_run(stripped)
                _set_run_font(run)
            i += 1
            continue

        # 空行 → 跳过（用段落间距控制）
        if not stripped:
            i += 1
            continue

        # 普通文本段：行内 $...$ 公式拆出渲染
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74)  # 两字符缩进
        rest = line
        while rest:
            fm = FORMULA_RE.search(rest)
            if fm:
                # 公式前的文本
                before = rest[:fm.start()]
                if before.strip():
                    run = p.add_run(before)
                    _set_run_font(run)
                # 渲染公式
                latex = (fm.group(1) or fm.group(2))
                img = _render_formula_png(latex)
                if img:
                    from docx.shared import Inches
                    p.add_run().add_picture(str(img), width=Inches(2.8))
                else:
                    run = p.add_run(f"${latex}$")
                    _set_run_font(run)
                rest = rest[fm.end():]
            else:
                if rest.strip():
                    run = p.add_run(rest)
                    _set_run_font(run)
                rest = ""
        i += 1

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return str(out)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python src/utils/word_exporter.py <交底书.md> [输出.docx]")
        sys.exit(1)
    src = Path(sys.argv[1])
    text = src.read_text(encoding="utf-8")
    out = sys.argv[2] if len(sys.argv) > 2 else str(src.with_suffix(".docx"))
    path = export_disclosure_to_word(text, out)
    print(f"已导出: {path}")
