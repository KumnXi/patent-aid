# 专利撰写助手

基于自建专利数据库的**电力行业 + 管道检测机器人**方向专利智能分析与撰写辅助系统。

核心能力：**三阶段 LLM 交底书生成**（大纲规划 → 分章节生成 → 自动质检迭代），配套 879 篇专利知识库、知识图谱、RAG 检索和质量审查。

## 功能概述

| 能力 | 说明 |
|------|------|
| 技术交底书生成 | 三阶段架构：大纲 → 4组分章节生成 → 质检迭代（<70分组自动重写） |
| 质量审查 | 8维度评分（结构/篇幅/编号/技术深度/权利要求/实施例/领域相关性/新颖性） |
| 专利数据采集 | 多源爬取（Google Patents / Patenthub），自动入库，879 篇 |
| 知识图谱 | 问题→方案→效果→技术→设备 多维关系图谱（1165节点/9492边） |
| RAG 检索 | TF-IDF + 余弦相似度语义检索，增量索引 |
| 创新模式挖掘 | 8种创新类型自动分类、创新方向建议 |
| 权利要求分析 | 结构模式学习、保护范围策略、依赖深度统计 |
| Web 应用 | Flask + 单页前端，生成/审查/搜索/历史管理 |

## 快速开始

### 环境要求

- Python 3.10+（项目使用 `D:/Anaconda3/envs/mathmodel/python.exe`）
- 依赖：`requests`, `beautifulsoup4`, `lxml`, `networkx`, `scikit-learn`, `numpy`, `scipy`, `jieba`, `flask`
- LLM：DeepSeek API Key（`config/api_config.json` 中配置，没有 Key 时生成降级为模板模式）
- 代理：Clash（仅爬取/LLM 需要，默认端口 `7890`）

### 启动 Web 应用

```bash
cd "d:\Jupyter code\专利撰写助手"
D:/Anaconda3/envs/mathmodel/python.exe app.py
# 浏览器访问 http://localhost:5000
```

首次启动需初始化引擎（解析专利 + 建图谱，约 40-60 秒；RAG 索引未变化时自动增量加载）。

页面功能：生成交底书、质量审查、批量测试（10题）、专利搜索、生成历史、下载 Markdown。

### 常用命令

```bash
# 爬取新专利（需 Clash 代理）
D:/Anaconda3/envs/mathmodel/python.exe scripts/slow_crawl.py

# 数据库治理（规范化/去重/质量报告，爬取后建议运行）
D:/Anaconda3/envs/mathmodel/python.exe scripts/db_maintain.py

# 全链路自动化测试（22项，含3领域真实LLM生成，约15分钟）
D:/Anaconda3/envs/mathmodel/python.exe scripts/run_tests.py

# 批量质量测试（10题命令行版）
D:/Anaconda3/envs/mathmodel/python.exe scripts/batch_quality_test.py
```

更多脚本说明见 [scripts/README.md](scripts/README.md)。

### 代码调用引擎

```python
from src.core import PatentInnovationEngine

engine = PatentInnovationEngine()
engine.initialize()   # RAG索引未变化时自动增量加载

# 生成技术交底书（三阶段 + 自动质检迭代）
result = engine.generate_disclosure(
    "一种配电网故障自愈控制方法",
    fields={"tech_field": "电力系统", "purpose": "...", "core_method": "..."}
)
print(result["disclosure"])        # 交底书全文
print(result["mode"])              # llm_staged / llm_single / template
print(result["quality_report"])    # 质检报告（仅 llm_staged 模式）

# 其他能力
engine.query("频率振荡抑制")               # 综合查询
engine.suggest_innovation("虚拟电厂调频")   # 创新方向建议
engine.review_quality(disclosure, idea)    # 独立质量审查
```

## 项目结构

```
专利撰写助手/
├── app.py                      # Flask Web 应用入口（端口5000）
│
├── config/                     # 配置文件
│   ├── api_config.json         # API密钥和代理配置（不入库）
│   ├── terminology/            # 术语规范库（电力/保护/可再生能源等）
│   ├── patent_law/             # 专利法条/常见驳回理由
│   ├── effect_descriptions/    # 技术效果量化描述模板
│   └── review_cases/           # 审查案例库
│
├── data/                       # 数据目录
│   ├── patent_database/        # 专利数据库（核心，879篇）
│   │   ├── index.json          # 主索引（IPC为列表格式，858篇含摘要）
│   │   ├── index_backup_*.json # 治理前自动备份
│   │   └── quality_report.json # 数据质量报告
│   ├── knowledge_graph/        # 知识图谱持久化
│   ├── rag_index/              # RAG索引（含 index_meta.json 增量标记）
│   ├── disclosure_history/     # 交底书生成历史（自动保存 .md + .json）
│   ├── patent_pdfs/            # 专利PDF文件
│   └── reference_patents/      # 人工标注的参考专利
│
├── src/                        # 核心源码（详见 docs/modules.md）
│   ├── api/                    # 数据源接口（google_patents/patenthub/multi_source）
│   ├── core/                   # 分析引擎
│   │   ├── __init__.py         # PatentInnovationEngine 统一入口
│   │   ├── disclosure_generator.py # 三阶段交底书生成器
│   │   ├── quality_reviewer.py # 质量审查（8维度）
│   │   ├── llm_client.py       # 通用LLM客户端（重试/退避/代理）
│   │   ├── rag_engine.py       # RAG检索（增量索引）
│   │   └── ...                 # 图谱/创新挖掘/权利要求/术语/数据库加载
│   ├── parsers/                # 文本解析器（权利要求树/说明书分段）
│   └── utils/                  # 工具（logger统一日志/history生成历史/text_utils）
│
├── scripts/                    # 运行脚本（详见 scripts/README.md）
│   ├── slow_crawl.py           # 定向批量爬取（电力+管道）
│   ├── daily_crawl.py          # 每日增量爬取
│   ├── db_maintain.py          # 数据库治理（规范化/去重）
│   ├── run_tests.py            # 自动化测试套件（22项）
│   ├── batch_quality_test.py   # 批量质量测试（10题）
│   └── build_analysis.py       # 重建知识图谱/RAG索引
│
├── templates/                  # 前端页面 + 撰写模板
│   ├── index.html              # Web应用单页前端
│   ├── specification_template.md   # 说明书模板
│   └── claims_template.md          # 权利要求模板
│
├── logs/                       # 运行日志（app.log 轮转保留3份）
├── docs/                       # 项目文档（architecture/modules）
└── output/                     # 下载报告等输出
```

## 交底书生成流程

```
用户输入（想法 + 可选结构化字段）
    ↓
阶段1 大纲规划：LLM 输出 JSON 大纲（问题/方案步骤/创新点/实施例）
    ↓
阶段2 分章节生成：G1 背景 → G2 技术方案 → G3 效果/实施例 → G4 权利要求+摘要
    （每组独立调用，携带大纲+前文摘要，注入效果量化模板和权利要求范式）
    ↓
阶段3 质检迭代：8维度评分，<70分的章节组自动重写一次
    ↓
回退链：大纲失败 → 单次LLM生成 → 模板拼接（保证永不失败）
    ↓
全文组装（[xxxx]段落编号统一重排）→ 自动保存到生成历史
```

实测质量：三阶段模式全文 1.2-1.9 万字，质检平均 96 分左右。

## 数据源说明

| 数据源 | 用途 | 限制 |
|--------|------|------|
| Google Patents | 全文获取（权利要求+说明书） | 需代理，频繁访问会503限流 |
| Patenthub API | 关键词搜索、发现新专利 | 免费额度有限（202状态码=超限） |
| BigQuery | 批量查询（备用） | 免费1TB/月，需Google Cloud账号 |

### 爬取策略

- 正常间隔：15秒/篇；搜索间隔：8秒/关键词
- 限流退避：60s → 120s → 300s 渐进，成功后重置
- 每5篇批量保存，中断不丢数据
- 代理节点被封（连续SSL错误）时切换 Clash 节点即可恢复

## 配置说明

`config/api_config.json`（不入库，需手动创建）：

```json
{
  "patenthub": {
    "token": "你的Patenthub Token",
    "base_url": "https://www.patenthub.cn"
  },
  "google_patents": {
    "enabled": true,
    "proxy": "http://127.0.0.1:7890",
    "base_url": "https://patents.google.com",
    "request_interval": 3,
    "max_retries": 3,
    "timeout": 30
  },
  "llm": {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "api_key": "你的API Key",
    "proxy": "http://127.0.0.1:7890"
  },
  "embedding": {
    "provider": "dashscope",
    "api_key": "你的DashScope API Key（阿里云百炼，可选）",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "text-embedding-v3",
    "dimensions": 1024,
    "batch_size": 25,
    "proxy": "http://127.0.0.1:7890"
  }
}
```

> **检索模式**：RAG 检索默认 TF-IDF。配置 `embedding.api_key` 后自动升级为
> **TF-IDF + 稠密向量 RRF 混合检索**（配置变更后下次启动自动重建索引，约 3-5 分钟）。
> 未配置 key 时优雅降级为纯 TF-IDF，不影响使用。

## 数据库格式

`data/patent_database/index.json` 结构（经 db_maintain 治理后的规范格式）：

```json
{
  "metadata": {
    "total_patents": 879,
    "updated": "2026-08-03T..."
  },
  "patents": {
    "CN117977607B": {
      "id": "CN117977607B",
      "title": "一种虚拟电厂负荷侧响应资源统一调度通用模型构建方法",
      "applicant": "申请人",
      "ipc": ["H02J 3/00"],
      "publication_date": "2026-01-01",
      "abstract": "摘要（从说明书首段提取）",
      "claims": "权利要求全文...",
      "description": "说明书全文...",
      "has_claims": true,
      "has_description": true,
      "category": "electrical",
      "source": "slow_crawl"
    }
  }
}
```

**字段规范**：`ipc` 为字符串列表；日期统一 `YYYY-MM-DD`；代码中读写 IPC 请用 `src/utils/text_utils.py` 的 `ipc_to_list()` / `ipc_to_str()` 兼容函数。

## Web API 一览

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/generate` | POST | 生成交底书（返回 disclosure/mode/quality_report/history_id） |
| `/api/quality-review` | POST | 独立质量审查 |
| `/api/batch-test` | POST | 批量测试 10 题（同步，约 30 分钟） |
| `/api/search` | GET | 专利搜索（关键词/IPC/申请人） |
| `/api/patent/<id>` | GET | 专利详情 |
| `/api/history` | GET | 生成历史列表 |
| `/api/history/<id>` | GET/DELETE | 历史详情/删除 |
| `/api/status` | GET | 引擎状态（前端轮询） |

## 文档导航

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 系统分层架构、设计决策、扩展方向 |
| [docs/modules.md](docs/modules.md) | src/ 各模块类和函数说明 |
| [scripts/README.md](scripts/README.md) | 所有脚本的用法和参数 |

## 技术栈

- **Web**: Flask + 原生 JS 单页前端
- **爬虫**: requests + BeautifulSoup4 + lxml
- **知识图谱**: NetworkX + TF-IDF 相似度
- **RAG检索**: scikit-learn TfidfVectorizer + scipy 稀疏矩阵 + jieba 分词
- **LLM**: DeepSeek API（OpenAI 兼容格式），三阶段生成 + 质检迭代
- **日志**: logging + RotatingFileHandler（logs/app.log，5MB 轮转保留 3 份）
- **代理**: Clash (HTTP proxy, 端口7890)
