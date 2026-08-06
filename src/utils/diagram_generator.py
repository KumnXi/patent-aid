"""Mermaid 流程图 → 专利风格附图渲染

从交底书附图说明中的 ```mermaid 代码块，解析 flowchart 并渲染为专利附图（PNG）。

渲染引擎（v3，升级自调研）：
- **首选 Graphviz `dot` 引擎**：自动节点避让、最小化连线交叉、专业箭头路由
  （业界标准布局，解决手写布局的节点重叠/连线交叉问题）
- **回退 matplotlib**：Graphviz 不可用或渲染失败时，用自绘渲染（中文可靠）

支持语法（简化 flowchart）：
    flowchart TD/LR/BT/RL
    A[节点文本] --> B[节点文本]
    A{判断节点} -->|是| B[处理]
    A -->|标签| C
    A -- 标签 --> C      （双短横内嵌标签，Mermaid 另一写法）
    A[第一行<br/>第二行] --> B

使用：
    from src.utils.diagram_generator import mermaid_to_png
    mermaid_to_png(mermaid_text, "output/fig1.png")
"""

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ──────────────────────────────────────────────
#  解析
# ──────────────────────────────────────────────

_NODE_PATTERN = r"(?:\[([^\]]+)\]|\{([^}]+)\})"


def parse_mermaid(text: str) -> Optional[Dict]:
    """解析 Mermaid flowchart 文本 → {direction, nodes, edges, shapes}

    节点：{id: label}，形状：{id: "box"|"diamond"}
    边：[(from, to, label_or_None), ...]

    支持语法：
        flowchart TD/LR/BT/RL
        A[文本]            ← 方框节点
        A{文本}            ← 菱形/判断节点
        A --> B            ← 实线箭头
        A -->|标签| B      ← 带标签边
        A --> B{文本}      ← 边中定义节点（含形状）
    """
    nodes: Dict[str, str] = {}
    shapes: Dict[str, str] = {}  # "box" | "diamond"
    edges: List[Tuple[str, str, Optional[str]]] = []  # (from, to, label)
    direction = "TD"

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # 方向声明
        m = re.match(r"^(?:flowchart|graph)\s+(TD|LR|BT|RL)\b", line, re.IGNORECASE)
        if m:
            direction = m.group(1).upper()
            continue

        # 带标签边（管道式）：A -->|标签| B  或  A[文本] -->|标签| B[文本]  或  A{文本} -->|标签| B
        m = re.match(
            r"(\w+)" + _NODE_PATTERN + r"?\s*-+\>+\|([^|]+)\|\s*(\w+)" + _NODE_PATTERN + r"?",
            line)
        if m:
            f_id = m.group(1)
            f_label = m.group(2) or m.group(3)
            f_shape = "diamond" if m.group(3) else "box"
            edge_label = m.group(4).strip()
            t_id = m.group(5)
            t_label = m.group(6) or m.group(7)
            t_shape = "diamond" if m.group(7) else "box"

            edges.append((f_id, t_id, edge_label))
            if f_label:
                nodes[f_id] = f_label
                shapes[f_id] = f_shape
            if t_label:
                nodes[t_id] = t_label
                shapes[t_id] = t_shape
            continue

        # 带标签边（双短横内嵌）：A -- 标签 --> B（Mermaid 另一写法）
        m = re.match(
            r"(\w+)" + _NODE_PATTERN + r"?\s*--\s*([^>]+?)\s*-->\s*(\w+)" + _NODE_PATTERN + r"?",
            line)
        if m:
            f_id = m.group(1)
            f_label = m.group(2) or m.group(3)
            f_shape = "diamond" if m.group(3) else "box"
            edge_label = m.group(4).strip()
            t_id = m.group(5)
            t_label = m.group(6) or m.group(7)
            t_shape = "diamond" if m.group(7) else "box"

            edges.append((f_id, t_id, edge_label or None))
            if f_label:
                nodes[f_id] = f_label
                shapes[f_id] = f_shape
            if t_label:
                nodes[t_id] = t_label
                shapes[t_id] = t_shape
            continue

        # 普通边：A --> B  或  A[文本] --> B[文本]  或  A{文本} --> B
        m = re.match(
            r"(\w+)" + _NODE_PATTERN + r"?\s*-+\>+\s*(\w+)" + _NODE_PATTERN + r"?",
            line)
        if m:
            f_id = m.group(1)
            f_label = m.group(2) or m.group(3)
            f_shape = "diamond" if m.group(3) else "box"
            t_id = m.group(4)
            t_label = m.group(5) or m.group(6)
            t_shape = "diamond" if m.group(6) else "box"

            edges.append((f_id, t_id, None))
            if f_label:
                nodes[f_id] = f_label
                shapes[f_id] = f_shape
            if t_label:
                nodes[t_id] = t_label
                shapes[t_id] = t_shape
            continue

        # 独立节点定义：A[文本] 或  A{文本}
        m = re.match(r"(\w+)\s*" + _NODE_PATTERN + r"\s*$", line)
        if m:
            nid = m.group(1)
            label = m.group(2) or m.group(3)
            shape = "diamond" if m.group(3) else "box"
            nodes[nid] = label
            shapes[nid] = shape
            continue

    if not nodes:
        return None
    return {"direction": direction, "nodes": nodes, "edges": edges, "shapes": shapes}


# ──────────────────────────────────────────────
#  节点尺寸估算
# ──────────────────────────────────────────────

def _estimate_node_size(label: str, fontsize: float = 12) -> Tuple[float, float]:
    """根据文本估算节点渲染尺寸（单位：matplotlib data coords）

    Args:
        label: 节点标签（可能含 <br/> 换行）
        fontsize: 字体大小（pt），节点尺寸随字号线性缩放

    Returns:
        (width, height) — 半宽半高各为全尺寸的一半
    """
    lines = label.replace("<br/>", "\n").replace("<br>", "\n").split("\n")
    max_line_len = max((len(line) for line in lines), default=0)

    # 基准字号 9pt 的字符宽度系数，随字号线性缩放
    scale = fontsize / 9.0
    # 中文字符宽度约 0.20 单位/字（@9pt）
    w = max(2.6 * scale, max_line_len * 0.20 * scale + 0.9 * scale)
    h = max(0.9 * scale, len(lines) * 0.38 * scale + 0.35 * scale)
    return w, h


def _pick_fontsize(node_count: int) -> int:
    """按节点数量选择字号：节点少用大字，节点多用适中字

    目的：保证导出 Word 后文字清晰可读（大图不会因缩放而看不清）。
    """
    if node_count <= 5:
        return 15
    if node_count <= 8:
        return 14
    if node_count <= 12:
        return 12
    return 11


# ──────────────────────────────────────────────
#  布局
# ──────────────────────────────────────────────

def _topo_layers(nodes: Dict[str, str],
                 edges: List[Tuple[str, str, Optional[str]]]) -> List[List[str]]:
    """拓扑分层：返回 [[node_id, ...], ...]，每层节点入度为0（相对于上层）"""
    indegree: Dict[str, int] = {nid: 0 for nid in nodes}
    adj: Dict[str, List[str]] = {nid: [] for nid in nodes}
    for f, t, _ in edges:
        if f in indegree and t in indegree:
            indegree[t] += 1
            adj[f].append(t)

    layers: List[List[str]] = []
    remaining = set(nodes)
    while remaining:
        layer = [n for n in remaining if indegree.get(n, 0) == 0]
        if not layer:
            # 有环：取剩余第一个
            layer = [next(iter(remaining))]
        layers.append(layer)
        for n in layer:
            remaining.discard(n)
            for child in adj.get(n, []):
                if child in indegree:
                    indegree[child] = max(0, indegree[child] - 1)
    return layers


def _layout_td(nodes: Dict[str, str],
               edges: List[Tuple[str, str, Optional[str]]],
               node_sizes: Dict[str, Tuple[float, float]]) -> Dict[str, Tuple[float, float]]:
    """Top-Down 布局：纵向拓扑分层，同层节点横向居中分布

    纵向间距 = 最大节点高度 + 1.5 单位空隙
    横向间距 = 最大节点宽度 + 1.2 单位空隙
    """
    layers = _topo_layers(nodes, edges)

    # 每层最大节点高度 / 全局最大节点宽度
    max_h = max((h for _, h in node_sizes.values()), default=1.0)
    max_w = max((w for w, _ in node_sizes.values()), default=2.5)

    v_gap = max_h + 1.8   # 层间垂直间距
    h_gap = max_w + 1.5   # 同层节点水平间距

    pos: Dict[str, Tuple[float, float]] = {}

    for li, layer in enumerate(layers):
        y = -li * v_gap  # y 轴向下为负
        n = len(layer)
        # 同层节点居中排列
        total_w = (n - 1) * h_gap
        for ci, nid in enumerate(layer):
            x = ci * h_gap - total_w / 2
            pos[nid] = (x, y)

    return pos


def _layout_lr(nodes: Dict[str, str],
               edges: List[Tuple[str, str, Optional[str]]],
               node_sizes: Dict[str, Tuple[float, float]]) -> Dict[str, Tuple[float, float]]:
    """Left-Right 布局：横向拓扑分层，同列节点纵向分布"""
    layers = _topo_layers(nodes, edges)

    max_w = max((w for w, _ in node_sizes.values()), default=2.5)
    max_h = max((h for _, h in node_sizes.values()), default=1.0)

    h_gap = max_w + 2.0   # 列间水平间距
    v_gap = max_h + 1.2   # 同列节点垂直间距

    pos: Dict[str, Tuple[float, float]] = {}

    for li, layer in enumerate(layers):
        x = li * h_gap
        n = len(layer)
        total_h = (n - 1) * v_gap
        for ci, nid in enumerate(layer):
            y = ci * v_gap - total_h / 2
            pos[nid] = (x, -y)  # 反转 y 让顶层在上

    return pos


# ──────────────────────────────────────────────
#  框边界交点计算（箭头边到边的关键）
# ──────────────────────────────────────────────

def _box_edge_point(cx: float, cy: float,
                    hw: float, hh: float,
                    tx: float, ty: float) -> Tuple[float, float]:
    """计算从框中心 (cx,cy) 到目标点 (tx,ty) 的射线与框边界的交点

    Args:
        cx, cy: 框中心坐标
        hw, hh: 框半宽、半高
        tx, ty: 目标点坐标（通常是另一个框的中心）

    Returns:
        (ix, iy): 框边界上的交点
    """
    dx = tx - cx
    dy = ty - cy

    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return (cx, cy + hh)  # 默认向下

    # 检查四条边的交点
    candidates = []

    # 右边：x = cx + hw
    if dx > 1e-9:
        t = hw / dx
        iy = cy + t * dy
        if abs(iy - cy) <= hh + 1e-6:
            candidates.append((t, cx + hw, iy))

    # 左边：x = cx - hw
    if dx < -1e-9:
        t = -hw / dx
        iy = cy + t * dy
        if abs(iy - cy) <= hh + 1e-6:
            candidates.append((t, cx - hw, iy))

    # 上边：y = cy + hh
    if dy > 1e-9:
        t = hh / dy
        ix = cx + t * dx
        if abs(ix - cx) <= hw + 1e-6:
            candidates.append((t, ix, cy + hh))

    # 下边：y = cy - hh
    if dy < -1e-9:
        t = -hh / dy
        ix = cx + t * dx
        if abs(ix - cx) <= hw + 1e-6:
            candidates.append((t, ix, cy - hh))

    if candidates:
        candidates.sort()  # 取最近的交点（最小 t）
        _, ix, iy = candidates[0]
        return (ix, iy)

    return (cx, cy)


# ──────────────────────────────────────────────
#  Graphviz 渲染（首选，v3 升级）
# ──────────────────────────────────────────────

# 常见 Graphviz dot 二进制位置（Windows 优先，兼容 POSIX）
_DOT_CANDIDATES = [
    "dot",  # PATH 中的 dot（类 Unix）
    r"C:\Program Files\Graphviz\bin\dot.exe",
    r"C:\Program Files (x86)\Graphviz\bin\dot.exe",
]


def _find_dot_binary() -> Optional[str]:
    """定位 Graphviz dot 可执行文件

    查找顺序：
    1. 环境变量 GRAPHVIZ_DOT（用户显式指定）
    2. shutil.which("dot")（PATH 中有）
    3. Windows 常见安装路径

    Returns:
        dot 可执行文件路径，未找到返回 None
    """
    # 1. 环境变量显式指定
    env = os.environ.get("GRAPHVIZ_DOT", "").strip()
    if env and Path(env).exists():
        return env

    # 2. PATH
    found = shutil.which("dot")
    if found:
        return found

    # 3. Windows 常见路径
    for cand in _DOT_CANDIDATES:
        if Path(cand).exists():
            return cand

    # 4. conda 环境 Library/bin
    for p in sys.path:
        if p and p.lower().endswith(("site-packages", "lib")):
            root = Path(p).parent.parent
            for cand in (root / "Library" / "bin" / "dot.exe",
                         root / "bin" / "dot"):
                if cand.exists():
                    return str(cand)
    return None


def _escape_dot_label(label: str) -> str:
    """转义 DOT label 字符串（引号、反斜杠、换行）"""
    if label is None:
        return ""
    # <br/> → \n 换行
    label = label.replace("<br/>", "\n").replace("<br>", "\n")
    return (label.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n"))


def _build_dot(diagram: Dict, fontsize: int = 14) -> str:
    """把 parse_mermaid 结果转成 DOT 图描述字符串

    Args:
        diagram: parse_mermaid() 输出
        fontsize: 节点字号（pt）

    Returns:
        DOT 文本
    """
    direction = diagram["direction"]
    nodes = diagram["nodes"]
    edges = diagram["edges"]
    shapes = diagram.get("shapes", {})

    # 方向映射：Mermaid TD→dot TB（top-bottom），LR→LR
    rankdir = "TB" if direction in ("TD", "BT") else "LR"

    lines = [f"digraph G {{"]
    lines.append(f"  rankdir={rankdir};")
    lines.append(f"  nodesep=0.7;")
    lines.append(f"  ranksep=0.9;")
    lines.append(
        f'  node [shape=box, fontname="SimHei", fontsize={fontsize}, '
        f'style="filled", fillcolor="white", color="#333333", '
        f'margin="0.25,0.12"];')
    lines.append(
        f'  edge [fontname="SimHei", fontsize={max(10, fontsize - 3)}, '
        f'color="#333333", arrowsize=0.9];')

    # 节点定义
    for nid, label in nodes.items():
        shape = "diamond" if shapes.get(nid) == "diamond" else "box"
        esc = _escape_dot_label(label)
        lines.append(f'  {nid} [label="{esc}", shape={shape}];')

    # 边定义
    for f_id, t_id, edge_label in edges:
        if f_id not in nodes or t_id not in nodes:
            continue
        if edge_label:
            esc = _escape_dot_label(edge_label)
            lines.append(f'  {f_id} -> {t_id} [label="{esc}"];')
        else:
            lines.append(f'  {f_id} -> {t_id};')

    lines.append("}")
    return "\n".join(lines)


def _render_graphviz(diagram: Dict, out_path: str,
                     dpi: int = 300) -> bool:
    """用 Graphviz dot 引擎渲染流程图

    Args:
        diagram: parse_mermaid() 输出
        out_path: 输出 PNG 路径
        dpi: 输出分辨率（专利要求 ≥300）

    Returns:
        成功返回 True，失败返回 False
    """
    dot_bin = _find_dot_binary()
    if not dot_bin:
        return False

    try:
        dot_text = _build_dot(diagram)
        with tempfile.TemporaryDirectory() as tmp:
            dot_path = Path(tmp) / "diagram.dot"
            dot_path.write_text(dot_text, encoding="utf-8")
            result = subprocess.run(
                [dot_bin, "-Tpng", f"-Gdpi={dpi}", str(dot_path)],
                capture_output=True, timeout=60)
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="replace")
                # 字体缺失等警告：graphviz 有时返回 0 但输出空
                if not result.stdout:
                    print(f"  Graphviz 渲染失败: {err.strip()[:200]}")
                    return False
            if not result.stdout:
                return False
            Path(out_path).write_bytes(result.stdout)
            return True
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  Graphviz 渲染异常: {e}")
        return False


# ──────────────────────────────────────────────
#  渲染
# ──────────────────────────────────────────────

def _render(diagram: Dict, out_path: str, fontname: str = "SimHei") -> bool:
    """用 matplotlib 渲染流程图

    关键原则：
    1. 节点尺寸根据文本动态计算
    2. 先画框（底层）→ 再画箭头（上层，从框边缘到框边缘）
    3. 箭头完整可见，不被框遮挡
    4. 支持 box（圆角矩形）和 diamond（菱形）两种节点形状
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Polygon as MplPolygon

    nodes = diagram["nodes"]
    edges = diagram["edges"]
    direction = diagram["direction"]
    shapes = diagram.get("shapes", {})

    # 0. 按节点数量选择字号（保证导出 Word 后文字清晰）
    node_font = _pick_fontsize(len(nodes))
    edge_font = max(9, node_font - 3)

    # 1. 计算节点尺寸（菱形用稍大的尺寸以容纳文本）
    node_sizes: Dict[str, Tuple[float, float]] = {}
    for nid, label in nodes.items():
        w, h = _estimate_node_size(label, fontsize=node_font)
        if shapes.get(nid) == "diamond":
            w *= 1.5  # 菱形需要更宽
            h *= 1.5
        node_sizes[nid] = (w, h)

    # 2. 布局
    if direction == "LR":
        pos = _layout_lr(nodes, edges, node_sizes)
    elif direction == "BT":
        pos = _layout_td(nodes, edges, node_sizes)
        pos = {n: (x, -y) for n, (x, y) in pos.items()}
    elif direction == "RL":
        pos = _layout_lr(nodes, edges, node_sizes)
        pos = {n: (-x, y) for n, (x, y) in pos.items()}
    else:
        pos = _layout_td(nodes, edges, node_sizes)

    # 3. 计算画布边界
    all_x, all_y = [], []
    for nid, (x, y) in pos.items():
        hw, hh = node_sizes[nid]
        if shapes.get(nid) == "diamond":
            # 菱形的实际边界是 hw/hh
            all_x.extend([x - hw, x + hw])
            all_y.extend([y - hh, y + hh])
        else:
            all_x.extend([x - hw, x + hw])
            all_y.extend([y - hh, y + hh])

    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)

    # 画布留白
    margin = 1.8
    data_w = xmax - xmin + 2 * margin
    data_h = ymax - ymin + 2 * margin

    # 计算合适的 figsize，保持数据长宽比（避免 set_aspect("equal") 导致留白过大）
    target_ratio = data_w / max(data_h, 1e-9)
    base = max(4, min(data_w, data_h) / 1.0)
    if target_ratio > 1:
        fig_w = max(5, base * target_ratio)
        fig_h = max(4, base)
    else:
        fig_w = max(5, base)
        fig_h = max(4, base / max(target_ratio, 1e-9))

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=200)
    ax = fig.add_axes([0.06, 0.06, 0.88, 0.88])
    ax.set_xlim(xmin - margin, xmax + margin)
    ax.set_ylim(ymin - margin, ymax + margin)
    ax.axis("off")

    # 4. 先画节点（框/菱形）——底层
    for nid, label in nodes.items():
        x, y = pos[nid]
        hw, hh = node_sizes[nid]
        shape = shapes.get(nid, "box")

        if shape == "diamond":
            # 菱形四个顶点：上下左右
            diamond_verts = [
                (x, y + hh),       # 上
                (x + hw, y),       # 右
                (x, y - hh),       # 下
                (x - hw, y),       # 左
            ]
            patch = MplPolygon(diamond_verts, closed=True,
                               linewidth=1.5, edgecolor="#333333",
                               facecolor="white", zorder=2)
            ax.add_patch(patch)
        else:
            patch = FancyBboxPatch(
                (x - hw, y - hh), hw * 2, hh * 2,
                boxstyle="round,pad=0.08",
                linewidth=1.5,
                edgecolor="#333333",
                facecolor="white",
                zorder=2,
            )
            ax.add_patch(patch)

        # 文本（支持 <br/> 换行）
        display_label = label.replace("<br/>", "\n").replace("<br>", "\n")
        ax.text(x, y, display_label,
                ha="center", va="center", fontsize=node_font,
                fontname=fontname, zorder=3,
                linespacing=1.3)

    # 5. 再画边（箭头）——上层，从节点边缘到节点边缘
    for f_id, t_id, edge_label in edges:
        if f_id not in pos or t_id not in pos:
            continue

        fx, fy = pos[f_id]
        tx, ty = pos[t_id]
        fw, fh = node_sizes[f_id]
        tw, th = node_sizes[t_id]

        # 计算从 f 节点边缘 到 t 节点边缘 的端点
        start_x, start_y = _box_edge_point(fx, fy, fw, fh, tx, ty)
        end_x, end_y = _box_edge_point(tx, ty, tw, th, fx, fy)

        # 缩短箭头终点，避免箭头尖进入框内
        adx = end_x - start_x
        ady = end_y - start_y
        arr_len = math.sqrt(adx**2 + ady**2)
        if arr_len > 0.1:
            shrink = 0.1 / arr_len
            end_x -= adx * shrink
            end_y -= ady * shrink

        ax.annotate(
            "",
            xy=(end_x, end_y),
            xytext=(start_x, start_y),
            arrowprops=dict(
                arrowstyle="-|>",
                lw=1.5,
                color="#333333",
                connectionstyle="arc3,rad=0",
            ),
            zorder=4,
        )

        # 边标签（画在箭头中点，微偏垂直于箭头方向）
        if edge_label:
            mid_x = (start_x + end_x) / 2
            mid_y = (start_y + end_y) / 2
            offset_x = -ady / (arr_len + 1e-9) * 0.3
            offset_y = adx / (arr_len + 1e-9) * 0.3
            ax.text(mid_x + offset_x, mid_y + offset_y,
                    edge_label,
                    ha="center", va="center",
                    fontsize=edge_font, fontname=fontname,
                    color="#555555", zorder=5,
                    bbox=dict(facecolor="white", edgecolor="none",
                              pad=1, alpha=0.9))

    fig.savefig(out_path, dpi=200, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return True


# ──────────────────────────────────────────────
#  公共接口
# ──────────────────────────────────────────────

def mermaid_to_png(mermaid_text: str, out_path: str,
                   fontname: str = "SimHei") -> Optional[str]:
    """Mermaid flowchart → PNG

    渲染顺序（v3）：
    1. Graphviz `dot` 引擎（自动布局/路由，输出 300dpi）
    2. Graphviz 不可用或失败 → 回退 matplotlib 自绘

    Args:
        mermaid_text: Mermaid 代码块内容
        out_path: 输出 PNG 路径
        fontname: 中文字体（matplotlib 回退路径用，默认 SimHei）

    Returns:
        保存路径，失败返回 None
    """
    diagram = parse_mermaid(mermaid_text)
    if not diagram:
        print(f"  流程图解析失败，无法识别节点/边")
        return None

    # 首选：Graphviz（若已安装）
    if _find_dot_binary():
        try:
            if _render_graphviz(diagram, out_path, dpi=300):
                return out_path if Path(out_path).exists() else None
        except Exception as e:
            print(f"  Graphviz 渲染失败，回退 matplotlib: {e}")
    else:
        print("  [提示] 未检测到 Graphviz，使用 matplotlib 渲染")

    # 回退：matplotlib
    try:
        _render(diagram, out_path, fontname)
        return out_path if Path(out_path).exists() else None
    except Exception as e:
        print(f"  流程图渲染失败: {e}")
        return None


# ──────────────────────────────────────────────
#  直接测试
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
        print(mermaid_to_png(text, "output/_fig_test.png"))
    else:
        # 默认自测：复杂流程图（含菱形判断 + 边标签）
        test = """flowchart TD
    A[数据采集模块] --> B[信号预处理]
    B --> C{缺陷检测}
    C -->|检测到缺陷| D[缺陷识别]
    C -->|无缺陷| E[结果输出]
    D --> F[生成报告]
    A -->|实时数据| G[数据缓冲队列]
    G --> B"""

        print("Testing diagram generation...")
        result = mermaid_to_png(test, "output/_fig_test.png")
        print(f"Result: {result}")
