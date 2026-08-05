"""Mermaid 流程图 → matplotlib 专利风格附图渲染

从交底书附图说明中的 ```mermaid 代码块，解析 flowchart 并用 matplotlib
渲染为专利附图（PNG）。支持中文节点标签。

支持语法（简化 flowchart）：
    flowchart TD/LR/BT/RL
    A[节点文本] --> B[节点文本]
    A --> C

使用：
    from src.utils.diagram_generator import mermaid_to_png
    mermaid_to_png(mermaid_text, "output/fig1.png")
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_mermaid(text: str) -> Optional[Dict]:
    """解析 Mermaid flowchart 文本 → {direction, nodes, edges}

    Args:
        text: Mermaid 代码块内容

    Returns:
        {"direction": "TD"|"LR"|..., "nodes": {id: label},
         "edges": [(from, to), ...]}，解析失败返回 None
    """
    nodes: Dict[str, str] = {}
    edges: List[Tuple[str, str]] = []
    direction = "TD"

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 方向声明
        m = re.match(r"^(?:flowchart|graph)\s+(TD|LR|BT|RL)\b", line)
        if m:
            direction = m.group(1)
            continue
        # 节点定义 A[文本]（整行，锚定结尾，label 不含 ]）
        m = re.match(r"(\w+)\s*\[([^\]]+)\]\s*$", line)
        if m:
            nodes[m.group(1)] = m.group(2)
            continue
        # 边 A --> B 或 A[文本] --> B[文本]（from/to 均可带 label）
        m = re.match(r"(\w+)(?:\[([^\]]+)\])?\s*-->+\s*(\w+)(?:\[([^\]]+)\])?", line)
        if m:
            f, to = m.group(1), m.group(3)
            edges.append((f, to))
            if m.group(2):  # from 节点文本
                nodes[f] = m.group(2)
            if m.group(4):  # to 节点文本
                nodes[to] = m.group(4)
            continue

    if not nodes:
        return None
    return {"direction": direction, "nodes": nodes, "edges": edges}


def _layout_td(nodes: Dict[str, str], edges: List[Tuple[str, str]]) -> Dict[str, Tuple[float, float]]:
    """Top-Down 布局：按拓扑层纵向排列，同层节点横向错开

    Returns:
        {node_id: (x, y)}
    """
    # 计算入度（找源节点）
    indegree = {nid: 0 for nid in nodes}
    for f, t in edges:
        indegree[t] = indegree.get(t, 0) + 1

    # 拓扑分层
    layers: List[List[str]] = []
    remaining = set(nodes)
    while remaining:
        layer = [n for n in remaining if indegree.get(n, 0) == 0]
        if not layer:
            # 有环或无入度的节点兜底
            layer = [next(iter(remaining))]
        layers.append(layer)
        for n in layer:
            remaining.discard(n)
            for f, t in edges:
                if f == n:
                    indegree[t] = max(0, indegree.get(t, 0) - 1)

    # 布局坐标（TD：y 向下）
    pos: Dict[str, Tuple[float, float]] = {}
    max_width = max(len(l) for l in layers)
    for li, layer in enumerate(layers):
        x_center = 0
        if len(layer) > 1:
            for ci, nid in enumerate(layer):
                x = (ci - (len(layer) - 1) / 2) * 2.0
                pos[nid] = (x, -li * 1.6)
        else:
            pos[layer[0]] = (0, -li * 1.6)
    return pos


def _layout_lr(nodes: Dict[str, str], edges: List[Tuple[str, str]]) -> Dict[str, Tuple[float, float]]:
    """Left-Right 布局：水平排列"""
    indegree = {nid: 0 for nid in nodes}
    for f, t in edges:
        indegree[t] = indegree.get(t, 0) + 1
    layers: List[List[str]] = []
    remaining = set(nodes)
    while remaining:
        layer = [n for n in remaining if indegree.get(n, 0) == 0]
        if not layer:
            layer = [next(iter(remaining))]
        layers.append(layer)
        for n in layer:
            remaining.discard(n)
            for f, t in edges:
                if f == n:
                    indegree[t] = max(0, indegree.get(t, 0) - 1)
    pos: Dict[str, Tuple[float, float]] = {}
    for li, layer in enumerate(layers):
        for ci, nid in enumerate(layer):
            pos[nid] = (li * 3.0, -ci * 1.2)
    return pos


def _render(diagram: Dict, out_path: str, fontname: str = "SimHei") -> bool:
    """用 matplotlib 渲染流程图"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    nodes = diagram["nodes"]
    edges = diagram["edges"]
    direction = diagram["direction"]

    pos = _layout_lr(nodes, edges) if direction == "LR" else _layout_td(nodes, edges)

    # 画布尺寸
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    bw, bh = 3.2, 1.2  # 节点宽高
    xmin, xmax = min(xs) - bw, max(xs) + bw
    ymin, ymax = min(ys) - bh, max(ys) + bh

    fig = plt.figure(figsize=(max(4, (xmax - xmin) * 1.3),
                              max(3, (ymax - ymin) * 1.3)), dpi=200)
    ax = fig.add_axes([0.04, 0.04, 0.92, 0.92])
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.axis("off")

    # 节点
    for nid, label in nodes.items():
        x, y = pos[nid]
        box = FancyBboxPatch((x - bw / 2, y - bh / 2), bw, bh,
                             boxstyle="round,pad=0.05",
                             linewidth=1.2, edgecolor="black", facecolor="white")
        ax.add_patch(box)
        ax.text(x, y, label, ha="center", va="center", fontsize=9,
                fontname=fontname, wrap=True,
                bbox=dict(facecolor="none", edgecolor="none", pad=0))

    # 边（箭头）
    for f, t in edges:
        if f in pos and t in pos:
            x1, y1 = pos[f]
            x2, y2 = pos[t]
            ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                        arrowprops=dict(arrowstyle="-|>", lw=1.2, color="black"))

    fig.savefig(out_path, dpi=200, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return True


def mermaid_to_png(mermaid_text: str, out_path: str,
                   fontname: str = "SimHei") -> Optional[str]:
    """Mermaid flowchart → PNG

    Args:
        mermaid_text: Mermaid 代码块内容
        out_path: 输出 PNG 路径
        fontname: 中文字体（默认 SimHei）

    Returns:
        保存路径，失败返回 None
    """
    diagram = parse_mermaid(mermaid_text)
    if not diagram:
        return None
    try:
        _render(diagram, out_path, fontname)
        return out_path if Path(out_path).exists() else None
    except Exception as e:
        print(f"  流程图渲染失败: {e}")
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
        print(mermaid_to_png(text, "output/_fig_test.png"))
