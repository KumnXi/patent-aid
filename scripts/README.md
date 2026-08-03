# 脚本说明

## 运行环境

```bash
# Python 解释器
D:/Anaconda3/envs/mathmodel/python.exe

# 工作目录
cd "d:\Jupyter code\专利撰写助手"
```

## 核心脚本

| 脚本 | 功能 | 运行方式 |
|------|------|----------|
| `slow_crawl.py` | 定向批量爬取（电力+管道方向） | 手动，约25分钟/100篇 |
| `fast_crawl.py` | 并发快速爬取（4线程+1s节流） | 手动，约2分钟/100篇 |
| `daily_crawl.py` | 每日增量爬取（Patenthub搜索+Google全文） | 定时任务/手动 |
| `db_maintain.py` | 数据库治理（规范化/去重/质量报告） | 爬取后按需 |
| `build_analysis.py` | 重建知识图谱 + RAG索引 + 创新模式 | 数据更新后 |
| `db_quality.py` | 数据库质量评分 | 按需 |
| `bigquery_patents.py` | BigQuery批量导入（备用） | 额度重置后 |
| `run_tests.py` | 自动化测试套件（22项，含多领域生成验证） | 按需 |
| `batch_quality_test.py` | 批量质量测试（10题多领域，Web批量测试同款） | 按需 |
| `runner.py` | 通用启动器（行缓冲/超时保护，被其他脚本导入） | 不单独运行 |

## 详细说明

### slow_crawl.py — 定向批量爬取

最常用脚本，按关键词从 Google Patents 批量抓取电力/管道方向专利全文。

```bash
D:/Anaconda3/envs/mathmodel/python.exe scripts/slow_crawl.py
```

**参数配置**（文件顶部常量）：
- `MAX_FETCH = 100`：单次最多抓取数量
- `INTERVAL = 15`：正常请求间隔（秒）
- `SEARCH_INTERVAL = 8`：搜索阶段间隔（秒）
- `SAVE_EVERY = 5`：每N篇批量保存
- `BACKOFF_LEVELS = [60, 120, 300]`：限流退避梯度

**搜索关键词**（16组）：
- 电力：配电网故障自愈、继电保护整定、虚拟电厂、分布式光伏、变压器监测、输电覆冰、智能变电站、微电网、电缆故障、储能、暂态稳定、无功补偿
- 管道：管道检测机器人、管道巡检深度学习、管道裂纹超声、pipeline inspection robot

**限流处理**：
- 连续3次失败触发退避（60s→120s→300s）
- 成功后自动重置退避等级
- SSL错误通常是代理节点被封，切换 Clash 节点即可

---

### daily_crawl.py — 每日增量爬取

多源版本，适合作为定时任务每天运行。

```bash
D:/Anaconda3/envs/mathmodel/python.exe scripts/daily_crawl.py
```

**执行流程**：
1. Patenthub 关键词搜索 → 发现新专利ID
2. Google Patents 获取全文（权利要求+说明书）
3. 补全历史缺失全文（每次最多20篇）
4. 增量重建知识图谱与RAG索引

**降级策略**：代理不可用时仅执行搜索（不获取全文），不报错。

---

### db_maintain.py — 数据库治理

对 `data/patent_database/index.json` 做字段规范化、去重和质量统计。运行前会自动备份建议（先手动备份 index.json）。

```bash
# 只分析不写回
D:/Anaconda3/envs/mathmodel/python.exe scripts/db_maintain.py --dry-run

# 规范化 + 同族去重 + 质量报告（自动写回，原子写入）
D:/Anaconda3/envs/mathmodel/python.exe scripts/db_maintain.py

# 额外删除标题相似度>0.85的近似重复（谨慎，先人工看报告）
D:/Anaconda3/envs/mathmodel/python.exe scripts/db_maintain.py --remove-similar
```

**治理内容**：
1. 日期统一为 `YYYY-MM-DD`（兼容 YYYYMMDD / 中文格式）
2. IPC 统一为字符串列表
3. 申请人去空白
4. 从说明书首段自动提取摘要（abstract 字段）
5. 同族去重（A/B 版保留 B 版或数据更全者）
6. 标题近似重复检测报告（输出到 quality_report.json）

**输出**：`data/patent_database/quality_report.json`（覆盖率/IPC分布/年份分布/申请人TOP20）

---

### build_analysis.py — 重建分析索引

数据库有新增/修改后运行，重建所有分析结果。引擎初始化时若 RAG 索引已覆盖全部专利会自动增量加载，无需每次全量重建。

```bash
D:/Anaconda3/envs/mathmodel/python.exe scripts/build_analysis.py
```

**构建内容**：
1. 解析所有完整专利文本
2. 构建知识图谱（问题→方案→效果→技术→设备）
3. 挖掘创新模式（8种类型分类）
4. 构建RAG索引（TF-IDF向量化）
5. 输出统计报告

---

### bigquery_patents.py — BigQuery批量导入（备用）

从 Google Patents Public Data 数据集批量查询专利。免费额度 1TB/月，单次查询约扫描 1TB。

```bash
# 打印SQL（复制到BigQuery网页端运行）
D:/Anaconda3/envs/mathmodel/python.exe scripts/bigquery_patents.py --sql

# 导入导出的JSON文件
D:/Anaconda3/envs/mathmodel/python.exe scripts/bigquery_patents.py --import data/bigquery_exports/xxx.json
```

**注意**：数据集字段为嵌套结构（ARRAY<STRUCT>），SQL必须用 UNNEST 展开。当前免费额度已用完，下月重置后可继续使用。

---

### run_tests.py — 自动化测试套件

22 项测试覆盖：引擎初始化、知识图谱、RAG 检索、三阶段交底书生成（电力/管道/新能源 3 领域）、质检报告、生成历史、报告输出。

```bash
D:/Anaconda3/envs/mathmodel/python.exe scripts/run_tests.py
```

**注意**：交底书生成测试会真实调用 LLM API（约 15-20 次调用，10-15 分钟），请确认 API Key 配置后再运行。

---

### batch_quality_test.py — 批量质量测试

10 个跨领域题目（管道/电力/新能源/自动驾驶/医疗/区块链等），逐题执行三阶段生成 + 质量审查，输出平均分/各维度均分，报告保存到 `output/quality_report_*.json`。Web 页面的“批量测试”按钮调用的就是本脚本的 `run_single_topic()`。

```bash
D:/Anaconda3/envs/mathmodel/python.exe scripts/batch_quality_test.py
```

**耗时**：约 30 分钟（每题 2.5-5 分钟，含 LLM 重试）。注意：脚本直连引擎，生成结果**不会**写入生成历史（仅 Web 接口保存）。

---

### runner.py — 通用启动器

被其他脚本 `from scripts.runner import setup; setup()` 导入，提供：UTF-8 行缓冲输出、全局超时保护（默认 600s）、网络请求超时兜底，解决 Windows 终端卡住问题。

## 辅助工具

| 文件 | 功能 |
|------|------|
| `run_crawl.bat` | Windows批处理快捷启动 daily_crawl |
| `run_crawl.ps1` | PowerShell快捷启动 daily_crawl |

## 定时任务

Windows 任务计划程序，任务名 `PatentCrawler`，每天凌晨2:00运行 daily_crawl。

```bash
schtasks //query //tn "PatentCrawler" //fo list   # 查看状态
schtasks //run //tn "PatentCrawler"               # 手动触发
schtasks //delete //tn "PatentCrawler" //f        # 删除任务
```

## 数据流

```
slow_crawl.py / daily_crawl.py
        ↓ 新专利入库
db_maintain.py（可选：规范化/去重）
        ↓
data/patent_database/index.json
        ↓
build_analysis.py / 引擎自动增量索引
        ↓ 重建索引
data/knowledge_graph/ + data/rag_index/
        ↓
src/core/PatentInnovationEngine → 查询/三阶段生成/质检
        ↓
data/disclosure_history/（生成历史自动保存）
```

## 注意事项

1. **代理必须开启**：Google Patents 在国内无法直接访问，需 Clash 代理（端口7890）
2. **限流问题**：单日爬取超过200篇容易触发 Google 503，建议分多天跑
3. **编码问题**：Windows终端默认GBK，脚本已内置UTF-8重配置
4. **数据安全**：每5篇自动保存，中断不丢失已抓取数据；db_maintain 采用原子写入防止损坏
