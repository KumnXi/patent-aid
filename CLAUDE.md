# 专利撰写助手 · 项目约定

## 项目定位

AI 辅助专利撰写系统，面向**电力行业 + 管道检测机器人**方向。

**核心目标：从技术想法到标准专利格式交底书**（不是从交底书到专利）。

核心链路：想法 → 三阶段 LLM 生成 → 防无中生有自动修复 → 权利要求格式校验 → 导出标准 Word（原生 OMML 公式 + Graphviz 附图）。

## 环境

- Python 解释器：`D:/Anaconda3/envs/mathmodel/python.exe`（conda 环境 `mathmodel`）
- 依赖见 `requirements.txt`；Graphviz 已装（`dot` 二进制），无需 pip 依赖

## 常用命令

```bash
# 一键生成交底书（核心入口）
python scripts/generate_patent.py "技术想法" \
    --title "一种..." --tech-field "技术领域" \
    --purpose "要解决的问题" --core-method "核心方法" \
    --problems "现有技术不足" --out output/交底书.docx

# 自动化测试（22 项，会真实调用 LLM，约 10-15 分钟，需 API Key）
python scripts/run_tests.py

# 绘图自测（生成 output/_fig_test.png）
python src/utils/diagram_generator.py

# 专利数据（需 Clash 代理 127.0.0.1:7890）
python scripts/ipc_discovery.py 3        # IPC 领域发现
python scripts/fast_crawl.py             # 并发爬取全文
python scripts/firecrawl_discover.py --query "管道检测 专利"  # Firecrawl 备用通道
python scripts/db_maintain.py --dry-run  # 数据库治理（先分析不写回）
```

## 安全红线（重要）

- `config/api_config.json`、`data/.secret.key`、`.env` 含**真实 API 密钥**，永不提交/推送
- `git add` 前先 `git status` 检查；推送前确认无敏感文件入库
- `data/disclosure_history/` 为加密历史，不入库
- `output/`、`.claude/settings.local.json` 亦不入库

## 架构约束

- 外部代码只应 `from src.core import PatentInnovationEngine`（统一入口，见 `src/core/__init__.py`）
- `src/core` 内部模块保持扁平，不要为外部新增直接依赖（改 `src/core/__init__.py` 导出即可）
- 绘图统一走 `src/utils/diagram_generator.mermaid_to_png()`：Graphviz `dot` 首选（300dpi 自动布局），matplotlib 回退
- Word 导出走 `src/utils/word_exporter.export_disclosure_to_word()`；历史加密走 `src/utils/history.py`

## 交流

- 优先使用中文交流与代码注释（与 `.claude/settings.json` 约定一致）
- 所有生成类代码交付前必须实际运行验证
