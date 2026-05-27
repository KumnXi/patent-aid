"""
每日专利爬取定时任务
建议每天运行一次，自动爬取电力领域专利并更新数据库

使用方法：
1. 手动运行：python scripts/daily_crawl.py
2. Windows任务计划程序：设置每天定时运行
3. Linux cron：0 2 * * * cd /path/to/project && python scripts/daily_crawl.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.api.patenthub import load_config
from src.api.patenthub_extended import PatentDatabaseBuilder


def main():
    print(f"{'='*50}")
    print(f"专利数据库每日爬取任务")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # 加载配置
    token = load_config()
    if not token:
        print("错误: 未找到API Token，请检查 config/api_config.json")
        return

    # 创建数据库构建器
    builder = PatentDatabaseBuilder(token, db_path="data/patent_database")

    # 执行每日爬取
    try:
        stats = builder.daily_crawl_task()

        # 记录日志
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / f"crawl_{datetime.now().strftime('%Y%m%d')}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"执行时间: {datetime.now().isoformat()}\n")
            f.write(f"新增专利: {stats['new_patents']}\n")
            f.write(f"扩展专利: {stats['expanded_patents']}\n")
            f.write(f"错误数量: {len(stats['errors'])}\n")
            if stats['errors']:
                f.write(f"错误详情: {stats['errors']}\n")

        print(f"\n日志已保存: {log_file}")

    except Exception as e:
        print(f"爬取任务异常: {e}")

    print(f"\n{'='*50}")
    print(f"任务完成")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
