# 电力领域术语库

本术语库用于规范专利文件中的术语使用，确保符合行业标准和CNIPA要求。

## 目录结构

```
terminology/
├── README.md              # 本说明文件
├── general.json           # 电力通用术语
├── power_system.json      # 电力系统术语
├── renewable.json         # 新能源术语
├── smart_grid.json        # 智能电网术语
├── protection.json        # 继电保护术语
├── automation.json        # 电力自动化术语
├── equipment.json         # 电力设备术语
└── forbidden.json         # 禁用词/不规范表述
```

## 术语格式规范

每个术语条目包含：
- `term`: 标准术语（必须使用）
- `aliases`: 同义词/别名（可接受但不推荐）
- `forbidden`: 禁用表述（绝对不能使用）
- `definition`: 术语定义
- `english`: 英文对照
- `standards`: 相关标准号
- `category`: 所属分类
- `usage_notes`: 使用说明

## 使用原则

1. **首次出现**：使用全称，必要时括号注明英文
2. **后续出现**：使用"所述[术语]"指代
3. **同义词处理**：全文统一使用一个表述，不混用
4. **英文缩写**：首次出现写全称括号注明缩写，后续可用缩写
