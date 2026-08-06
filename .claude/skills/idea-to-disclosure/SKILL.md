---
name: idea-to-disclosure
description: 从技术想法生成标准专利交底书（项目核心流程）。use when 用户提供技术想法/问题/方案并要求"生成交底书""写技术交底"或一键出 Word，从想法起步而非从交底书起步
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
2. **调用流水线**（内部自动执行三阶段 LLM 生成 → 防无中生有修复 → 权利要求校验 → 加密保存历史 → Word 导出）：

```bash
D:/Anaconda3/envs/mathmodel/python.exe scripts/generate_patent.py "技术想法" \
    --title "一种..." --tech-field "技术领域" \
    --purpose "要解决的问题" --core-method "核心方法" \
    --problems "现有技术不足" --out output/交底书.docx
```

## 输出检查（生成后核对）

- 终端应显示：生成模式（llm_staged 为最优）、质检评分（>90 为好）、防无中生有修复数、权利要求校验摘要
- Word 内含附图：mermaid 流程图经 Graphviz `dot` 渲染（300dpi），见 `src/utils/diagram_generator.py`
- 生成历史已加密保存到 `data/disclosure_history/`（见 `src/utils/history.py`）

## 注意事项

- 首次运行引擎初始化约 1 分钟（建知识图谱/RAG 索引）
- 全文约 1.2-1.9 万字，三阶段模式质检平均 96 分
- 需要真实 DeepSeek API Key（`config/api_config.json`，保密，不入库）
- 若用户手上有现成交底书而非想法 → 引导用 `/patent-writer` 进入撰写阶段
