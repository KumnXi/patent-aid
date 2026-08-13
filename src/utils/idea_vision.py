"""想法看图输入：把技术资料图片/手绘/截图提炼成 idea 字段

给 idea-to-disclosure 流程补上"眼睛"：用户贴技术资料图片（设备照片、手绘示意、
系统框图、论文截图、表格等）时，先经 VL 读图 → 提炼成结构化输入字段
（idea/title/tech_field/purpose/core_method/problems）→ 再交给 generate_patent.py。

图片内容经 qwen-vl 转成文字描述，再喂给 DeepSeek 纯文本后端 ——
这是本项目视觉能力唯一可靠的桥接方式（LLMClient.chat() 只吃文本）。

使用：
    from src.utils.idea_vision import extract_idea_from_image
    fields = extract_idea_from_image(["图1.png", "图2.png"], hint="这是我在现场拍的")
    # → {idea, title, tech_field, purpose, core_method, problems}

命令行：
    D:/Anaconda3/envs/mathmodel/python.exe -m src.utils.idea_vision 图片1.png 图片2.png
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from src.api.vl_client import VLClient

# 结构字段（与 generate_patent.py 的 --title/--tech-field 等参数对应）
FIELD_KEYS = ["idea", "title", "tech_field", "purpose", "core_method", "problems"]

# 让 VL 按"缺陷/方法/效果"结构从图片提取交底书输入字段
EXTRACT_PROMPT = """你是一位专利代理师，正在帮发明人把一张技术资料图片整理成技术交底书的输入信息。

请仔细观察图片中的技术内容（设备结构、系统框图、手绘示意、论文截图、表格、曲线等），提取以下字段。用严格的 JSON 输出，不要输出任何其他文字：

{
  "idea": "对图片中技术内容的完整描述：发明是什么、解决什么问题、核心技术手段、达到的效果（300字以内）",
  "title": "建议的发明名称，以"一种"开头",
  "tech_field": "所属技术领域（如：电力系统 / 管道检测 / 信号处理）",
  "purpose": "要解决的技术问题（现有技术的缺陷，从图片内容推断）",
  "core_method": "核心技术方法或技术路线（从图片可见的结构/流程/模块提取）",
  "problems": "现有技术的不足（图片没有体现就填空字符串）"
}

要求：
- 所有内容必须基于图片中实际可见的信息，不要编造图片里没有的技术细节
- 涉及数值（尺寸、电压、频率、压力等）时如实记录
- 术语要专业规范
- 信息不足的字段填空字符串""
- 只输出一个 JSON 对象"""


def extract_idea_from_image(image_paths: Union[str, Path, List],
                            hint: str = "") -> Dict:
    """多图 VL 提炼 idea 字段

    Args:
        image_paths: 图片路径（单张或列表；多图时第一张为主，后续补充）
        hint: 用户补充的文字提示（如"这是我在产线上拍的设备照片"）

    Returns:
        {idea, title, tech_field, purpose, core_method, problems}
        未配置 DashScope 或读图失败时返回空 dict（调用方回退纯文本输入）
    """
    if isinstance(image_paths, (str, Path)):
        image_paths = [image_paths]

    client = VLClient()
    if not client.is_available():
        print("[idea_vision] DashScope 未配置，无法看图输入，请用纯文本想法")
        return {}

    result: Dict = {}
    for i, path in enumerate(image_paths):
        prompt = EXTRACT_PROMPT
        if hint:
            prompt += f"\n补充说明：{hint}"
        if i > 0:
            prompt += ("\n这是补充图片。如果与前面的图片信息重叠，就返回空 JSON {}，"
                       "只补充前面图片没有的新技术信息。")
        text = client.chat_with_image(path, prompt)
        if not text:
            print(f"[idea_vision] 第{i+1}张图读图失败: {path}")
            continue
        parsed = _parse_structured(text)
        if not parsed:
            print(f"[idea_vision] 第{i+1}张图返回无法解析: {text[:120]}")
            continue
        result = _merge_fields(result, parsed)
        print(f"[idea_vision] 第{i+1}张图提炼完成（{Path(path).name}）")

    return result


def _parse_structured(text: str) -> Dict:
    """从 VL 回复中提取 JSON（加固：去 markdown 代码块/去首尾杂质）"""
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    text = text[start:end + 1]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_fields(base: Dict, extra: Dict) -> Dict:
    """合并两轮提取：base 已有字段保留，空字段用补充图的填充"""
    merged = dict(base)
    for k in FIELD_KEYS:
        v = (extra.get(k) or "").strip()
        if v and not (merged.get(k) or "").strip():
            merged[k] = v
    return merged


if __name__ == "__main__":
    import sys
    # Windows 下控制台默认 cp936，重配置为 UTF-8 避免中文乱码（与 run_tests.py 一致）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    paths = sys.argv[1:]
    if not paths:
        print("用法: python -m src.utils.idea_vision <图片1> [图片2...]")
        sys.exit(1)
    out = extract_idea_from_image(paths)
    print(json.dumps(out, ensure_ascii=False, indent=2))
