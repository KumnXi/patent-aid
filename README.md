# 专利撰写助手

基于自建专利数据库的**电力行业 + 管道检测机器人**方向专利智能分析与撰写辅助系统。

核心能力：**从技术想法到标准专利格式交底书**的一键流水线——三阶段 LLM 生成 → 防无中生有自动修复 → 权利要求格式校验 → 导出标准 Word（原生公式 + 自动附图）。

## 功能概述

| 能力 | 说明 |
|------|------|
| 🚀 一键生成流水线 | `scripts/generate_patent.py`：想法 → 标准专利格式 Word，全自动 |
| 📝 标准专利格式 | 发明名称→摘要→权利要求书→说明书（技术领域/背景技术/发明内容/附图说明/具体实施方式） |
| 🧮 原生可编辑公式 | LaTeX → Word 原生 OMML 公式（无需 MathType/插件，可编辑） |
| 🖼️ 说明书附图自动生成 | 附图说明的 Mermaid 流程图 → 专利风格框图插入 Word |
| 🛡️ 防无中生有 | 5 类检查 + 生成后自动修复（删实验表述/量化改定性/删编造专利号） |
| ⚖️ 权利要求格式校验 | 编号/完整性/特征段/引用格式/存在性/顺序 6 项自动校验 |
| 🔐 历史加密存储 | 交底书 Fernet AES 加密，密钥本地管理 |
| 质量审查 | 9维度评分（含防编造 no-new-matter 校验） |
| 专利数据采集 | 多源爬取（Google Patents / Patenthub / Firecrawl 备用） |
| 知识图谱 | 问题→方案→效果→技术→设备 多维关系图谱 |
| RAG 检索 | TF-IDF + bge-m3 稠密向量 RRF 混合检索 |
| Web 应用 | Flask + 单页前端，生成/审查/搜索/导出 |

## 环境搭建（小白版 · 每一步都有说明）

> 本教程面向零编程经验的用户，全程复制粘贴命令即可。

### 1. 安装 Anaconda（如果已有可跳过）

Anaconda 是一个傻瓜式的 Python 环境管理器，不需要手动配置任何东西。

1. 打开 [Anaconda 官网](https://www.anaconda.com/download) → 下载 **Windows 64位** 安装包
2. 双击安装，一路点 **Next**（全部默认选项即可）
3. 安装完成后，按 `Win 键` → 输入 `Anaconda Prompt` → 打开这个黑窗口

> 之后的命令全部在 **Anaconda Prompt** 里输入。

### 2. 克隆项目

```bash
git clone https://github.com/KumnXi/patent-aid.git
cd patent-aid
```

> 如果提示 `git 不是内部命令`，去 [git-scm.com](https://git-scm.com/download/win) 安装 Git，一路 Next 就行。

### 3. 用 Anaconda 创建虚拟环境

虚拟环境 = 给这个项目划一个独立的 Python 空间，不会影响你电脑上其他东西。

```bash
conda create -n patent python=3.10 -y
conda activate patent
```

执行完后你的命令行前面会出现 `(patent)`，说明环境切换成功。

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

等待 2-3 分钟，出现 `Successfully installed` 就完成了。

### 5. 配置 API Key

DeepSeek 是生成交底书的 AI 引擎，需要一个密钥才能调用。

**① 获取 Key**：打开 [platform.deepseek.com](https://platform.deepseek.com) → 注册（手机号就行）→ 左侧点 **API Keys** → **创建新的 API Key** → 复制那一串 `sk-` 开头的东西。

**② 写入配置**：

```bash
copy config\api_config.example.json config\api_config.json
```

用记事本打开刚刚生成的 `config\api_config.json`，找到这一行：

```json
"api_key": "你的DeepSeek API Key",
```

把 `你的DeepSeek API Key` 替换成你刚才复制的 `sk-...`，保存。

> ⚠️ 这个文件含你的密钥，**千万**不要上传到任何地方。

### 6. 启动

```bash
python app.py
```

打开浏览器访问 **http://localhost:5000**，看到页面就成功了。

首次启动会有约一分钟的初始化过程（终端有进度显示），这是正常现象。

---

## 代理配置（Clash · 爬虫和部分功能需要）

国内直接访问 Google Patents 会被墙，所以爬取专利数据需要**代理**。

### 什么是 Clash？

Clash 是一款代理软件，让你能访问被墙的网站。网上常见的机场/订阅地址都能导入。

### 安装和配置

1. 找一个可用的 Clash 客户端（如 Clash Verge、Clash for Windows）
2. 导入你的订阅地址（机场提供的 `clash://` 开头的链接）
3. 开启**系统代理**，确保右下角图标变绿

### 验证代理是否生效

打开浏览器访问 [Google Patents](https://patents.google.com)，能打开就说明代理通了。

### 不需要代理的情况

- **Web 应用**（`python app.py`）——生成交底书、搜索本地库、质检都不需要代理
- 只有以下功能需要：爬取新专利（`fast_crawl.py`）、IPC 领域发现（`ipc_discovery.py`）
- 如果你不需要爬取新专利数据，**完全可以不用代理**，项目能正常运行

---

## 爬取专利数据（可选）

代理生效后，以下命令可以扩充你的专利库：

```bash
# 发现新专利（按 IPC 分类号检索，生成待爬清单）
python scripts/ipc_discovery.py 3

# 并发爬取全文
python scripts/fast_crawl.py
```

如果爬一会儿报一堆 503 错误，说明 Clash 当前节点的 IP 被 Google 封了——在 Clash 里换个节点就行。

### Firecrawl 备用通道（可选）

当本机 IP 被 Google 封（503）时，可配置 [Firecrawl](https://firecrawl.dev) 作为备用爬取通道
（它用数据中心代理池，抗封性更好）。在 `config/api_config.json` 配置：

```json
"firecrawl": {
  "api_key": "你的Firecrawl API Key",
  "base_url": "https://api.firecrawl.dev",
  "timeout": 60
}
```

配置后，主爬虫失败会自动切到 Firecrawl。免费档约 500 credits/月，仅作备用。

---

## 🚀 一键生成流水线

一条命令，从技术想法到**标准专利格式 Word**（含原生公式、自动附图、防编造修复、权利要求校验）：

```bash
python scripts/generate_patent.py "你的技术想法" \
    --title "一种..." \
    --tech-field "技术领域" \
    --purpose "要解决的问题" \
    --core-method "核心方法" \
    --problems "现有技术不足" \
    --out output/交底书.docx
```

流水线 5 步全自动：
```
想法 → ①三阶段LLM生成 → ②防无中生有自动修复 → ③权利要求格式校验
     → ④保存历史(加密) → ⑤导出标准Word(原生公式+说明书附图)
```

## 常用命令

```bash
python scripts/batch_quality_test.py   # 批量质量测试（10题）
python scripts/ipc_discovery.py 3      # IPC领域专利发现
python scripts/fast_crawl.py           # 并发爬取专利全文
```

更多脚本见 [scripts/README.md](scripts/README.md)。

### 代码调用

```python
from src.core import PatentInnovationEngine

engine = PatentInnovationEngine()
engine.initialize()

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
    "provider": "siliconflow",
    "api_key": "你的SiliconFlow API Key（硅基流动，可选）",
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "BAAI/bge-m3",
    "batch_size": 25,
    "proxy": "http://127.0.0.1:7890"
  }
}
```

> **检索模式**：RAG 检索默认 TF-IDF。配置 `embedding.api_key`（任意 OpenAI 兼容
> embedding 服务商均可，如硅基流动/智谱/OpenAI）后自动升级为
> **TF-IDF + 稠密向量 RRF 混合检索**（配置变更后下次启动自动重建索引，
> 首次向量化约 10-20 分钟，一次性）。未配置 key 时优雅降级为纯 TF-IDF。

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
