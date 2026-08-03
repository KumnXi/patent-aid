# 系统架构说明

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    应用层                                 │
│   app.py (Flask, 端口5000) + templates/index.html       │
│   生成/审查/批量测试/搜索/历史 API                         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    用户接口层                             │
│   PatentInnovationEngine (src/core/__init__.py)         │
│   query() / suggest_innovation() / generate_disclosure()│
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    分析引擎层                             │
│                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │KnowledgeGraph│ │  RAGEngine   │ │InnovationMiner │  │
│  │  知识图谱     │ │  语义检索     │ │  创新模式挖掘   │  │
│  └──────────────┘ └──────────────┘ └────────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ClaimAnalyzer │ │Terminology   │ │QualityReviewer │  │
│  │ 权利要求分析  │ │  术语分析     │ │  质量审查       │  │
│  └──────────────┘ └──────────────┘ └────────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │Disclosure    │ │  LLMClient   │ │  LLMPolisher   │  │
│  │ 三阶段生成    │ │  LLM客户端    │ │  LLM润色       │  │
│  └──────────────┘ └──────────────┘ └────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    解析层                                 │
│  PatentParser / ClaimsParser / DescriptionParser        │
│  原始文本 → StructuredPatent 结构化数据                   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    数据层                                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │ data/patent_database/index.json (主数据库 879篇) │    │
│  │ data/knowledge_graph/ (图谱持久化)              │    │
│  │ data/rag_index/ (向量索引 + 增量元数据)          │    │
│  │ data/disclosure_history/ (生成历史)             │    │
│  └─────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    数据采集层                             │
│  GooglePatentsClient / PatenthubClient / MultiSource    │
│  代理(Clash:7890) → Google Patents / Patenthub API      │
└─────────────────────────────────────────────────────────┘
```

## 模块详解

### 1. 数据采集层 (`src/api/`)

| 模块 | 职责 | 关键类 |
|------|------|--------|
| `google_patents.py` | 爬取Google Patents全文 | `GooglePatentsClient`, `GooglePatent` |
| `patenthub.py` | Patenthub API搜索 | `PatenthubClient` |
| `multi_source.py` | 多源协调+降级策略 | `PatentSourceManager` |

**数据流**：
- 搜索发现：Patenthub关键词搜索 → 专利ID列表
- 全文获取：Google Patents HTML解析 → 权利要求+说明书
- 降级：Google不可用 → 仅保存基本信息 → 标记待补全

**反爬策略**：
- 请求间隔控制（默认3秒，爬取脚本15秒）
- 指数退避重试（429/503/SSL错误）
- Session重建（连接池污染清除）
- 代理节点轮换（手动切换Clash节点）

### 2. 解析层 (`src/parsers/`)

| 模块 | 职责 | 输出 |
|------|------|------|
| `patent_parser.py` | 整体解析，生成结构化专利 | `StructuredPatent` |
| `claims_parser.py` | 权利要求树解析 | `ClaimsTree` / `ClaimNode` |
| `description_parser.py` | 说明书分段 | `DescriptionSections` |

**StructuredPatent 结构**：
```
patent_id, title, applicant, ipc_codes
claims_text → ClaimsTree (独立/从属/依赖关系)
description → DescriptionSections (背景/方案/效果/实施例)
```

### 3. 分析引擎层 (`src/core/`)

#### KnowledgeGraph（知识图谱）
- 存储：NetworkX DiGraph，JSON持久化
- 节点类型：problem / solution / effect / technology / equipment / parameter
- 边类型：solves / achieves / uses / composes / measures / similar_to
- 查询：TF-IDF余弦相似度匹配

#### RAGEngine（检索增强）
- 方案：TF-IDF + 余弦相似度（轻量级，适合当前规模），jieba 中文分词
- 分块策略：按段落类型（背景/方案/效果/实施例）切分
- 索引：`data/rag_index/`（vectors.npy + vectorizer.pkl + rag_index.json）
- 增量索引：`index_meta.json` 记录已索引专利 ID，`is_index_stale()` 判断是否过期，未过期直接加载（57s→38s）
- 可升级：sentence-transformers 嵌入模型

#### InnovationMiner（创新模式）
- 8种创新类型：算法优化/系统架构/参数自适应/多目标协同/物数融合/...
- 聚类：KMeans + TF-IDF
- 输出：创新方向建议 + source_patents 证据追踪

#### ClaimAnalyzer（权利要求）
- 分析：独立/从属数量、依赖深度、技术特征数
- 模式：方法+装置 / 单一方法 / 方法+系统 等
- 建议：根据创新类型推荐权利要求结构

#### DisclosureGenerator（三阶段生成）
- 阶段1 大纲规划：LLM 输出 JSON 大纲（问题/方案步骤/创新点/实施例）
- 阶段2 分章节生成：G1背景 → G2方案 → G3效果/实施例 → G4权利要求+摘要，
  每组独立调用，携带大纲+前文摘要，注入效果量化模板与权利要求范式
- 阶段3 质检迭代：QualityReviewer 评分 <70 的章节组自动重写一次
- 回退链：大纲失败 → 单次 LLM 生成 → 模板拼接（保证永不失败）
- 实测：全文 1.2-1.9 万字，质检平均 96 分

#### QualityReviewer（质量审查）
- 8维度评分：结构/篇幅/编号/技术深度/权利要求/实施例/领域相关性/新颖性
- 新颖性：与专利库 TF-IDF 相似度对比

#### LLMClient（通用 LLM 客户端）
- OpenAI 兼容格式（DeepSeek），重试 + 限流退避 + 代理，供生成/润色/审查复用

### 4. 配置层 (`config/`)

| 目录 | 内容 |
|------|------|
| `terminology/` | 术语规范（电力设备/保护/可再生能源/智能电网/禁用词） |
| `patent_law/` | 专利法条 + 常见驳回理由 |
| `effect_descriptions/` | 技术效果量化描述模板 |
| `review_cases/` | 审查案例（新颖性/创造性/充分性/清晰度/支持） |

## 关键设计决策

1. **轻量级RAG**：当前879篇规模用TF-IDF足够，无需GPU/大模型嵌入
2. **JSON存储**：单文件数据库，便于备份和版本管理，无需数据库服务
3. **多源降级**：Google Patents为主，Patenthub为辅，任一不可用不影响整体
4. **渐进退避**：应对Google限流，60→120→300秒自动恢复
5. **批量保存**：每5篇写盘一次，平衡性能与数据安全
6. **生成回退链**：三阶段→单次→模板，任何LLM故障都不阻断用户
7. **增量索引**：数据库未变化时跳过重建，启动从57s降到38s
8. **数据库治理**：db_maintain.py 规范化字段+同族去重，原子写入防损坏

## 扩展方向

- 数据库超过5000篇时考虑迁移到 SQLite/MongoDB
- RAG升级为 sentence-transformers 嵌入（需GPU）
- 增加 CNIPA 官方数据导入（FTP批量下载）
- BigQuery 批量查询（免费额度1TB/月，下月重置）
