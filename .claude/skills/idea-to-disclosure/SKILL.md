---
name: idea-to-disclosure
description: "Convert a technical idea into a submission-ready Chinese patent disclosure (docx). Three-stage LLM generation with anti-hallucination checks and claim-format validation. Works for any technical domain; built-in examples include power-grid and pipeline-inspection robotics. use when 用户提供技术想法/问题/方案并要求\"生成交底书\"\"写技术交底\"或一键出 Word，从想法起步而非从交底书起步"
user_invocable: true
---

# 想法 → 技术交底书

项目核心目标：**从想法到技术交底书**。当用户提供技术想法（而非现成交底书）时，按此流程执行。

## 输入字段

| 字段 | 说明 | 必需 |
|------|------|------|
| idea | 技术想法描述 | ✅ |
| title | 发明名称（"一种..."） | 建议 |
| tech-field | 技术领域 | 可选 |
| purpose | 要解决的问题 | 可选 |
| core-method | 核心方法/技术路线 | 可选 |
| problems | 现有技术不足 | 可选 |

想法若含"针对某缺陷…用某方法…达到某效果"结构即可直接生成；缺字段可让用户补充或用默认。

## 执行步骤

1. **确认想法已收集**：从用户描述中提炼 idea（含缺陷/方法/效果要素）
2. **若用户贴图（照片/手绘/系统框图/论文截图/PDF）**：先经 VL"看图"提炼字段，再进入流水线。图片转成结构化字段后才交给 DeepSeek（`src/api/vl_client.py` 文字桥接）：

```bash
# 单图或多图：输出 {idea, title, tech_field, purpose, core_method, problems}
D:/Anaconda3/envs/mathmodel/python.exe -m src.utils.idea_vision 图1.png 图2.png
```

   - 图片内容（设备结构/流程/数值）会被提炼成 idea 字段，缺的字段留空让用户补或走默认
   - 未配置 DashScope / 读图失败时自动回退纯文本输入，不阻断流程
3. **调用流水线**（内部自动执行三阶段 LLM 生成 → 防无中生有修复 → 权利要求校验 → 合规审查 → 加密保存历史 → Word 导出）：

```bash
D:/Anaconda3/envs/mathmodel/python.exe scripts/generate_patent.py "技术想法" \
    --title "一种..." --tech-field "技术领域" \
    --purpose "要解决的问题" --core-method "核心方法" \
    --problems "现有技术不足" --out output/交底书.docx
```

3b. **交付自查（可选，交付前建议跑）**：Word 导出后渲染回看显示质量（公式/附图/布局/乱码），由 VL 看图质检，避免"导出成功但渲染有问题"：

```bash
# 生成后直接自查；或对已有 docx 单独自查
D:/Anaconda3/envs/mathmodel/python.exe scripts/generate_patent.py ... --selfcheck
D:/Anaconda3/envs/mathmodel/python.exe scripts/selfcheck_disclosure.py output/交底书.docx
```

   - 原理：docx → LibreOffice 转 PDF → 逐页 PNG → qwen-vl 回看（见 `src/utils/disclosure_inspector.py`）
   - 需 LibreOffice（`winget install --id TheDocumentFoundation.LibreOffice`）；未装时提示安装，不阻断生成
   - 终端显示每页问题数；有 error 级问题建议修复后重新导出

## 输出检查（生成后核对）

- 终端应显示：生成模式（llm_staged 为最优）、质检评分（>90 为好）、防无中生有修复数、权利要求校验摘要
- Word 内含附图：mermaid 流程图经 Graphviz `dot` 渲染（300dpi），见 `src/utils/diagram_generator.py`
- 生成历史已加密保存到 `data/disclosure_history/`（见 `src/utils/history.py`）
- `--selfcheck` 后终端应显示每页自查结论（P01 正常 / 检出 N 个问题）

## 注意事项

- 首次运行引擎初始化约 1 分钟（建知识图谱/RAG 索引）
- 全文约 1.2-1.9 万字，三阶段模式质检平均 96 分
- 需要真实 DeepSeek API Key（`config/api_config.json`，保密，不入库）
- 若用户手上有现成交底书而非想法 → 引导用 `/patent-writer` 进入撰写阶段
