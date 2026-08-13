"""IPC 字段回填脚本

背景：391 篇专利（主要来自 slow_crawl 通道）抓取时未保存 IPC 分类号，
导致领域统计失真（管道方向专利被漏计）。本脚本：
1. 扫描 index.json 中 ipc 为空的专利
2. 重新请求 Google Patents 详情页，用增强后的提取逻辑拿 IPC
3. 只更新 ipc 字段（不覆盖其他内容），断点续传（进度文件）

用法：
    python scripts/backfill_ipc.py              # 回填全部空IPC
    python scripts/backfill_ipc.py --limit 50   # 只处理前50篇（试跑）
    python scripts/backfill_ipc.py --pids CNxxx,CNyyy  # 指定专利

前置：Clash 代理已启动（Google Patents 需要）
"""

import sys
import io
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.api.google_patents import create_client_from_config

DB_PATH = project_root / "data" / "patent_database" / "index.json"
PROGRESS_PATH = project_root / "data" / "patent_database" / "ipc_backfill_progress.json"
REQUEST_INTERVAL = 3.0  # 秒/篇（详情页较重，保守限速）


def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    db["metadata"]["updated"] = datetime.now().isoformat()
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def load_progress() -> dict:
    """断点续传：记录已处理的专利及其结果"""
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"done": {}, "failed": {}}


def save_progress(prog):
    PROGRESS_PATH.write_text(
        json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="IPC 字段回填")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N篇（0=全部）")
    parser.add_argument("--pids", default="", help="逗号分隔的专利号列表")
    args = parser.parse_args()

    google = create_client_from_config()
    if not google.check_proxy():
        print("错误: 代理不可用，请确认 Clash 已启动")
        return

    db = load_db()
    patents = db["patents"]
    empty = [pid for pid, p in patents.items() if not p.get("ipc")]
    print(f"数据库 {len(patents)} 篇, IPC 为空 {len(empty)} 篇")

    # 目标清单
    if args.pids:
        targets = [p.strip() for p in args.pids.split(",") if p.strip()]
    else:
        targets = empty
    if args.limit > 0:
        targets = targets[:args.limit]

    prog = load_progress()
    done, failed = prog["done"], prog["failed"]
    todo = [pid for pid in targets if pid not in done and pid not in failed]
    print(f"本次待处理: {len(todo)} 篇 (已完成 {len(done)}, 失败 {len(failed)})\n")

    ok_count = 0
    fail_count = 0
    for i, pid in enumerate(todo, 1):
        try:
            patent = google.get_patent_detail(pid)
            ipc = "; ".join(patent.ipc_codes) if patent and patent.ipc_codes else ""
            if ipc:
                patents[pid]["ipc"] = ipc
                done[pid] = {"ipc": ipc, "at": datetime.now().isoformat()}
                ok_count += 1
                print(f"[{i}/{len(todo)}] {pid} OK: {ipc[:70]}")
            else:
                failed[pid] = {"reason": "页面无IPC", "at": datetime.now().isoformat()}
                fail_count += 1
                print(f"[{i}/{len(todo)}] {pid} 无IPC")
        except Exception as e:
            failed[pid] = {"reason": str(e)[:200], "at": datetime.now().isoformat()}
            fail_count += 1
            print(f"[{i}/{len(todo)}] {pid} 异常: {e}")

        # 每5篇保存一次数据库和进度
        if i % 5 == 0 or i == len(todo):
            save_db(db)
            save_progress(prog)

        if i < len(todo):
            time.sleep(REQUEST_INTERVAL)

    save_db(db)
    save_progress(prog)
    print("\n" + "=" * 50)
    print(f"回填完成: 成功 {ok_count} | 失败 {fail_count}")
    remaining = sum(1 for p in patents.values() if not p.get("ipc"))
    print(f"数据库 IPC 空余: {remaining} 篇")
    print(f"进度文件: {PROGRESS_PATH}（再次运行自动跳过已完成）")


if __name__ == "__main__":
    main()
