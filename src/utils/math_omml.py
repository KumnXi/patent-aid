"""LaTeX → Word 原生公式（OMML）转换

流程：LaTeX → MathML（latex2mathml）→ OMML（本模块递归转换）

Word 原生公式（m:oMath）是可编辑的公式对象，大小/基线/字体与正文自动协调，
比插入图片规范得多。

使用：
    from src.utils.math_omml import latex_to_omml
    omml_xml = latex_to_omml(r"\\varepsilon_c = A \\sigma^n \\exp(-Q/RT)")
    # omml_xml 可直接嵌入 docx 的 <m:oMath> 中
"""

import re
import xml.etree.ElementTree as ET

import latex2mathml.converter as l2m

# 命名空间
OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"

# 常见希腊字母/符号 → 保留原名（OMML 用 Unicode 或 m:t 文本）
# latex2mathml 输出 MathML 时已把符号转成 Unicode 实体

# mathtext 不支持的 \left\right 等，先清洗
_LATEX_CLEAN = [
    (r"\left|", "|"), (r"\right|", "|"),
    (r"\left(", "("), (r"\right)", ")"),
    (r"\left[", "["), (r"\right]", "]"),
    (r"\left\{", "{"), (r"\right\}", "}"),
    (r"\left.", ""), (r"\right.", ""),
    (r"\left", ""), (r"\right", ""),
]


def _localname(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def latex_to_mathml(latex: str, display: str = "inline") -> str:
    """LaTeX → MathML"""
    for old, new in _LATEX_CLEAN:
        latex = latex.replace(old, new)
    return l2m.convert(latex, display=display)


def _make(tag: str, children: list = None, text: str = None):
    """创建 OMML 元素"""
    el = ET.Element(f"{{{OMML_NS}}}{tag}")
    if text is not None and text != "":
        el.text = text
    if children:
        for c in children:
            if isinstance(c, ET.Element):
                el.append(c)
    return el


def _convert_children(nodes) -> list:
    """转换一组 MathML 子节点 → OMML 元素列表"""
    out = []
    for child in nodes:
        el = _convert_node(child)
        if isinstance(el, list):
            out.extend(el)
        elif el is not None:
            out.append(el)
    return out


def _convert_node(node) -> list:
    """递归转换单个 MathML 节点 → OMML 元素列表"""
    tag = _localname(node.tag)
    children = list(node)

    if tag == "math":
        return _convert_children(children)
    if tag == "mrow":
        return _convert_children(children)
    if tag == "mstyle":
        return _convert_children(children)

    # 文本节点（mi/mn/mo）→ 单个 run（必须用 <m:r><m:t>text</m:t></m:r>）
    if tag in ("mi", "mn", "mo", "mtext"):
        text = node.text or ""
        if not text and children:
            text = "".join(c.text or "" for c in children)
        r = ET.Element(f"{{{OMML_NS}}}r")
        t = ET.SubElement(r, f"{{{OMML_NS}}}t")
        t.text = text
        return [r]

    # 上标
    if tag == "msup" and len(children) >= 2:
        base = _convert_node(children[0])
        sup = _convert_node(children[1])
        el = _make("sSup", [])
        _add_child(el, "e", base)
        _add_child(el, "sup", sup)
        return [el]

    # 下标
    if tag == "msub" and len(children) >= 2:
        base = _convert_node(children[0])
        sub = _convert_node(children[1])
        el = _make("sSub", [])
        _add_child(el, "e", base)
        _add_child(el, "sub", sub)
        return [el]

    # 上下标
    if tag == "msubsup" and len(children) >= 3:
        base = _convert_node(children[0])
        sub = _convert_node(children[1])
        sup = _convert_node(children[2])
        el = _make("sSubSup", [])
        _add_child(el, "e", base)
        _add_child(el, "sub", sub)
        _add_child(el, "sup", sup)
        return [el]

    # 分数
    if tag == "mfrac" and len(children) >= 2:
        el = _make("f", [])
        num = _make("num", _convert_node(children[0]))
        den = _make("den", _convert_node(children[1]))
        el.append(num)
        el.append(den)
        return [el]

    # 根式
    if tag in ("msqrt", "mroot") and children:
        el = _make("rad", [])
        if tag == "mroot" and len(children) >= 2:
            deg = _make("deg", _convert_node(children[1]))
            el.append(deg)
        e = _make("e", _convert_node(children[0]))
        el.append(e)
        return [el]

    # 定界符（括号）
    if tag == "mfenced":
        el = _make("d", [])
        e = _make("e", _convert_children(children))
        el.append(e)
        return [el]

    # 缺省：递归子节点
    return _convert_children(children)


def _add_child(parent: ET.Element, tag: str, children: list):
    """把子元素列表包进 <tag> 并追加到 parent"""
    child = _make(tag, children)
    parent.append(child)


def latex_to_omml(latex: str) -> str:
    """LaTeX → OMML 元素 XML 字符串（不含 <m:oMath> 外壳）

    Args:
        latex: LaTeX 公式（可含 $ 或 \\( \\) 包裹，自动剥离）

    Returns:
        OMML 内容 XML；失败返回 ""（调用方应回退）
    """
    try:
        latex = latex.strip().strip("$").strip()
        latex = re.sub(r"^\\\\\(|\\\\\)$", "", latex.strip())
        mathml = latex_to_mathml(latex)
        root = ET.fromstring(mathml)
        elements = _convert_node(root)
        return "".join(ET.tostring(e, encoding="unicode") for e in elements)
    except Exception as e:
        print(f"  OMML 转换失败: {e}")
        return ""


def latex_to_omml_math(latex: str) -> str:
    """LaTeX → 完整的 <m:oMath> XML（可直接 parse 后插入 docx）"""
    content = latex_to_omml(latex)
    if not content:
        return ""
    return (f'<m:oMath xmlns:m="{OMML_NS}">{content}</m:oMath>')


if __name__ == "__main__":
    test = r"\dot{\varepsilon}_c = A \cdot \sigma^n \cdot \exp\left(-\frac{Q}{RT}\right)"
    omml = latex_to_omml_math(test)
    print("OMML 长度:", len(omml))
    print(omml[:400])
