"""
每日专利爬取定时任务（多源版本 v2）

数据流:
    1. Patenthub搜索 → 发现新专利ID（免费接口）
    2. Google Patents → 获取完整权利要求+说明书（通过代理，无日限额）
    3. 增量重建知识图谱与RAG索引（仅在有新增时）

增强功能:
    - 每步独立错误恢复，单步失败不影响其他步骤
    - 增量更新：仅在有新增数据时重建索引
    - 指数退避重试
    - 结构化日志

使用方法：
1. 手动运行：D:/Anaconda3/envs/mathmodel/python.exe scripts/daily_crawl.py
2. Windows任务计划程序：每天凌晨2:00自动运行

前提条件：
- Clash代理已启动（Google Patents需要）
- 如果代理未启动，自动降级为旧模式（Patenthub PDF）
"""

import sys
import os
import io
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime

# 处理Windows GBK编码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.api.multi_source import PatentSourceManager


# 每日搜索关键词组（电力领域）
DAILY_KEYWORDS = [
    ["虚拟电厂", "负荷响应"],
    ["分布式光伏", "光伏并网"],
    ["配电网故障", "故障定位"],
    ["继电保护", "差动保护"],
    ["储能系统", "电池管理"],
    ["智能电网", "配电自动化"],
]


def step1_discover(manager: PatentSourceManager, max_retries: int = 2) -> list:
    """步骤1: 搜索发现新专利（带重试）"""
    print(f"\n{'='*50}")
    print(f"步骤1: 搜索发现新专利 (Patenthub)")
    print(f"{'='*50}")

    all_new_patents = []
    failed_keywords = []

    for i, keywords in enumerate(DAILY_KEYWORDS):
        for attempt in range(max_retries + 1):
            try:
                print(f"\n--- 关键词组 {i+1}/{len(DAILY_KEYWORDS)}: {keywords} ---")
                new_patents = manager.discover_patents(keywords, max_results=15)
                all_new_patents.extend(new_patents)
                break
            except Exception as e:
                print(f"  [重试 {attempt+1}/{max_retries+1}] 搜索失败: {e}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt * 3)
                else:
                    failed_keywords.append(keywords)

    # 去重
    seen = set()
    unique_patents = []
    for p in all_new_patents:
        if p["id"] not in seen:
            seen.add(p["id"])
            unique_patents.append(p)

    print(f"\n本次发现新专利: {len(unique_patents)} 篇")
    if failed_keywords:
        print(f"  [警告] {len(failed_keywords)}组关键词搜索失败: {failed_keywords}")
    return unique_patents


def step2_fetch_text(manager: PatentSourceManager, patent_list: list) -> dict:
    """步骤2: 获取全文 (Google Patents, 带错误恢复)"""
    print(f"\n{'='*50}")
    print(f"步骤2: 获取专利全文 (Google Patents)")
    print(f"{'='*50}")

    if not patent_list:
        print("无新专利需要处理")
        return {"total": 0, "added": 0, "with_text": 0, "failed": 0, "skipped": 0}

    try:
        # 批量获取
        stats = manager.batch_fetch(patent_list, fetch_text=True)
    except Exception as e:
        print(f"  [错误] 批量获取异常: {e}")
        # 降级为逐个获取（full_text=None 表示不获取全文，仅保存基本信息）
        stats = {"total": len(patent_list), "added": 0, "with_text": 0, "failed": 0, "skipped": 0}
        for i, p in enumerate(patent_list):
            try:
                manager.add_patent_to_db(p, full_text=None)
                stats["added"] += 1
            except Exception as e2:
                stats["failed"] += 1
                print(f"  [{i+1}] {p.get('id','')}: 失败 - {e2}")

    print(f"\n全文获取结果:")
    print(f"  处理: {stats['total']}")
    print(f"  入库: {stats['added']}")
    print(f"  有全文: {stats['with_text']}")
    print(f"  失败: {stats['failed']}")

    return stats


def step3_backfill(manager: PatentSourceManager) -> dict:
    """步骤3: 补全历史缺失"""
    print(f"\n{'='*50}")
    print(f"步骤3: 补全历史缺失全文")
    print(f"{'='*50}")

    pending = manager.get_pending_patents()
    if not pending:
        print("无待补全专利")
        return {"total": 0, "filled": 0, "failed": 0}

    print(f"待补全: {len(pending)} 篇（本次最多处理20篇）")
    stats = manager.backfill_missing_text(max_count=20)

    print(f"补全结果: 成功{stats['filled']} / 失败{stats['failed']}")
    return stats


def step4_rebuild_index(force: bool = False):
    """步骤4: 增量重建知识图谱与RAG索引
    
    Args:
        force: 强制重建（即使没有新数据）
    """
    print(f"\n{'='*50}")
    print(f"步骤4: 重建知识图谱与RAG索引")
    print(f"{'='*50}")

    if not force:
        print("无新增数据，跳过索引重建")
        return

    python_exe = sys.executable
    build_script = str(project_root / "scripts" / "build_analysis.py")

    try:
        result = subprocess.run(
            [python_exe, build_script],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=600,  # 10分钟超时
        )

        if result.returncode != 0:
            print(f"索引重建异常，返回码: {result.returncode}")
            if result.stderr:
                print(f"错误: {result.stderr[-500:]}")
        else:
            print("索引重建完成")
    except subprocess.TimeoutExpired:
        print("索引重建超时（>10分钟），已终止")
    except Exception as e:
        print(f"索引重建失败: {e}")


def save_log(crawl_stats, text_stats: dict, backfill_stats: dict, errors: list = None):
    """保存结构化运行日志"""
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / f"crawl_{datetime.now().strftime('%Y%m%d')}.log"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"执行时间: {datetime.now().isoformat()}\n")
        f.write(f"模式: 多源v2(Patenthub搜索 + Google Patents全文 + 错误恢复)\n")
        f.write(f"发现新专利: {len(crawl_stats) if isinstance(crawl_stats, list) else crawl_stats.get('total', 0)}\n")
        f.write(f"全文获取: {text_stats.get('with_text', 0)}/{text_stats.get('total', 0)}\n")
        f.write(f"历史补全: {backfill_stats.get('filled', 0)}\n")
        f.write(f"Google成功: {text_stats.get('with_text', 0) + backfill_stats.get('filled', 0)}\n")
        if errors:
            f.write(f"错误数: {len(errors)}\n")
            for err in errors:
                f.write(f"  - {err}\n")

    print(f"\n日志已保存: {log_file}")


def main():
    print(f"{'='*50}")
    print(f"专利数据库每日爬取任务（多源版本）")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # 初始化多源管理器
    manager = PatentSourceManager(
        db_path=str(project_root / "data" / "patent_database")
    )

    # 检测数据源可用性
    google_ok = manager.is_google_available()
    if not google_ok:
        print("\n[警告] Google Patents 不可用，本次仅执行搜索（不获取全文）")
        print("提示: 启动Clash代理后可获取全文\n")

    # 错误收集
    errors = []
    has_new_data = False

    try:
        # 步骤1: 搜索发现
        try:
            new_patents = step1_discover(manager)
        except Exception as e:
            print(f"\n[错误] 步骤1失败: {e}")
            errors.append(f"步骤1: {e}")
            new_patents = []

        # 步骤2: 获取全文
        try:
            if google_ok:
                text_stats = step2_fetch_text(manager, new_patents)
                if text_stats.get("with_text", 0) > 0:
                    has_new_data = True
            else:
                # 降级: 只保存基本信息
                text_stats = {"total": len(new_patents), "added": 0, "with_text": 0, "failed": 0, "skipped": 0}
                for p in new_patents:
                    try:
                        manager.add_patent_to_db(p, full_text=None)
                        text_stats["added"] += 1
                    except Exception as e:
                        text_stats["failed"] += 1
        except Exception as e:
            print(f"\n[错误] 步骤2失败: {e}")
            errors.append(f"步骤2: {e}")
            text_stats = {"total": 0, "added": 0, "with_text": 0, "failed": 0, "skipped": 0}

        # 步骤3: 补全历史缺失
        try:
            if google_ok:
                backfill_stats = step3_backfill(manager)
                if backfill_stats.get("filled", 0) > 0:
                    has_new_data = True
            else:
                backfill_stats = {"total": 0, "filled": 0, "failed": 0}
        except Exception as e:
            print(f"\n[错误] 步骤3失败: {e}")
            errors.append(f"步骤3: {e}")
            backfill_stats = {"total": 0, "filled": 0, "failed": 0}

        # 步骤4: 增量重建索引
        step4_rebuild_index(force=has_new_data)

        # 保存日志
        save_log(new_patents, text_stats, backfill_stats, errors)

        # 最终统计
        manager.print_stats()

    except Exception as e:
        print(f"\n爬取任务异常: {e}")
        import traceback
        traceback.print_exc()
        errors.append(f"全局: {e}")

    print(f"\n{'='*50}")
    print(f"全流程完成")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
