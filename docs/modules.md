# src/ 源码模块说明

## 模块总览

```
src/
├── api/            # 外部数据源接口
├── core/           # 核心分析引擎
├── parsers/        # 专利文本解析器
└── utils/          # 共享工具函数
```

## api/ — 数据采集接口

### google_patents.py
Google Patents 爬虫客户端，通过 HTTP 代理访问。

- `GooglePatent`：专利数据类（id/title/claims/description/ipc_codes等）
- `GooglePatentsClient`：核心客户端
  - `search_patents(query, num_results, country)` → 专利ID列表
  - `get_patent_detail(patent_id)` → GooglePatent 对象
  - `download_pdf(patent_id)` → 保存PDF文件
  - `check_proxy()` → 代理可用性检测
- `create_client_from_config()`：从 `config/api_config.json` 创建实例

### patenthub.py
Patenthub API 客户端（免费搜索接口）。

- `PatenthubClient`：关键词搜索、专利详情
- 限制：免费额度用尽返回 202 状态码

### multi_source.py
多源管理器，协调 Patenthub + Google Patents。

- `PatentSourceManager`：
  - `discover_patents(keywords)` → 搜索新专利
  - `batch_fetch(patent_list)` → 批量获取全文
  - `backfill_missing_text()` → 补全历史缺失
  - `is_google_available()` → 检测代理状态

## core/ — 分析引擎

### __init__.py → PatentInnovationEngine
统一入口，整合所有分析能力。

```python
engine = PatentInnovationEngine()
engine.initialize()           # 构建图谱/索引（支持增量加载）
engine.query("问题描述")       # 综合查询
engine.suggest_innovation()   # 创新建议
engine.generate_disclosure()  # 交底书生成（三阶段：大纲→分章节→质检迭代）
engine.review_quality()       # 质量审查
```

### knowledge_graph.py
知识图谱引擎（NetworkX）。

- 节点：problem / solution / effect / technology / equipment / parameter
- 边：solves / achieves / uses / composes / measures / similar_to
- 持久化：`data/knowledge_graph/knowledge_graph.json`

### rag_engine.py
RAG 检索引擎（TF-IDF + cosine similarity）。

- 文档分块：按段落类型（背景/方案/效果/实施例）
- 索引文件：`data/rag_index/`（vectors.npy + vectorizer.pkl + rag_index.json + index_meta.json）
- 检索维度：技术问题/方案描述/效果关键词/实施方法
- 增量索引：`is_index_stale()` 判断索引是否覆盖全部专利，未过期时 `load_index()` 直接加载

### innovation_miner.py
创新模式挖掘器。

- 8种创新类型枚举（InnovationType）
- KMeans 聚类发现高频问题领域
- 输出附带 source_patents 证据

### claim_analyzer.py
权利要求结构分析。

- 统计：独立/从属数量、依赖深度、特征数
- 模式识别：方法+装置 / 方法+系统 等
- 推荐：根据创新类型建议权利要求结构

### terminology_analyzer.py
术语规范分析。

- 语料库：从专利库自动构建
- 配置：`config/terminology/` 下的规范词表
- 功能：推荐标准术语、检测禁用词

### disclosure_generator.py
技术交底书生成器（三阶段架构）。

- 阶段 1：大纲规划——LLM 输出 JSON 大纲（问题/方案步骤/创新点/实施例）
- 阶段 2：分章节生成——4 组独立调用（背景→方案→效果/实施例→权利要求），
  每组携带大纲+前文摘要，注入效果模板和权利要求范式
- 阶段 3：质检迭代——低于 70 分的章节组自动重写一次
- 回退链：分段失败 → 单次生成 → 模板拼接

### quality_reviewer.py
交底书质量审查。

- 维度：新颖性/创造性/充分性/清晰度/支持性
- 对比：与现有专利库比较

### llm_polisher.py
LLM 文本润色（DeepSeek API）。

### database_loader.py
数据库加载器，读取 index.json 并统计。

## parsers/ — 文本解析

### patent_parser.py
- `PatentParser`：解析所有完整专利
- `StructuredPatent`：结构化专利数据类

### claims_parser.py
- `ClaimsParser`：权利要求文本 → 树结构
- `ClaimsTree`：权利要求树（独立/从属关系）
- `ClaimNode`：单条权利要求节点

### description_parser.py
- `DescriptionParser`：说明书 → 分段结构
- `DescriptionSections`：背景/方案/效果/实施例

## utils/ — 工具

### text_utils.py
- `ChineseTextProcessor`：中文分词、停用词、TF-IDF辅助
- `ipc_to_list()` / `ipc_to_str()`：IPC 字段格式兼容（列表/字符串互转）

### logger.py
统一日志模块，`get_logger(__name__)` 获取。

- 同时输出到控制台（INFO）和 `logs/app.log`（DEBUG，5MB 轮转保留 3 份）

### history.py
交底书生成历史管理，存储于 `data/disclosure_history/`。

- `save_disclosure()`：保存全文 .md + 元信息 .json
- `list_history()` / `get_history()` / `delete_history()`

### llm_client.py（core/）
通用 LLM 调用客户端（OpenAI 兼容格式），含重试/限流退避/代理，
供交底书生成和润色模块复用。
