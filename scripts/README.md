# 定时任务说明

## 可用脚本

### daily_crawl.py - 每日专利爬取
- 按关键词搜索电力领域授权有效专利
- 从现有专利扩展相似专利
- 更新专利数据库
- 记录爬取日志

## 定时任务配置

### Windows 任务计划程序

1. 以管理员权限运行 `setup_scheduled_task.bat`
2. 或手动配置：
   - 打开"任务计划程序"
   - 创建基本任务
   - 触发器：每天凌晨2:00
   - 操作：启动程序 `D:\Anaconda3\envs\mathmodel\python.exe`
   - 参数：`D:\Jupyter code\专利撰写助手\scripts\daily_crawl.py`

### Linux/Mac cron

```bash
# 编辑crontab
crontab -e

# 添加以下行（每天凌晨2点执行）
0 2 * * * cd "D:/Jupyter code/专利撰写助手" && D:/Anaconda3/envs/mathmodel/python.exe scripts/daily_crawl.py
```

## 爬取策略

### 每日爬取内容
1. **关键词搜索**：5组关键词，每组10个专利
   - 虚拟电厂、负荷响应
   - 分布式光伏、光伏并网
   - 配电网故障、故障定位
   - 继电保护、差动保护
   - 储能系统、电池管理

2. **相似专利扩展**：从现有专利中选5个，每个扩展5个相似专利

3. **法律状态更新**（待实现）

### 爬取限制
- 免费账户API调用限制
- 避免请求过快（每次请求间隔0.5秒）
- 每日新增约50-100个专利

## 数据存储

```
data/patent_database/
├── index.json          # 专利索引（主数据库）
├── citations.json      # 引用关系
├── similar_patents.json # 相似专利关系
└── logs/               # 爬取日志
```

## 手动运行

```bash
cd "D:/Jupyter code/专利撰写助手"
D:/Anaconda3/envs/mathmodel/python.exe scripts/daily_crawl.py
```
