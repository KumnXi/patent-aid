"""Firecrawl 云端全文补充脚本（免代理）

用途: 对库中缺全文的专利，通过 Firecrawl 云端抓取 Google Patents 页面
HTML，复用 google_patents 的解析逻辑提取权利要求+说明书入库。
Firecrawl 在云端执行抓取，本地无需代理。

注意: 免费档约 500 credits/月，一篇专利页消耗数个 credits，
请用小 --limit 控制用量。

用法:
    python scripts/firecrawl_fulltext.py --limit 20          # 补前20篇缺全文的
    python scripts/firecrawl_fulltext.py --pids CNxxx,CNyyy  # 指定专利
    python scripts/firecrawl_fulltext.py --dry-run           # 只列清单
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.api.firecrawl import create_firecrawl_client
from src.api.google_patents import GooglePatentsClient

DB_PATH = PROJECT_ROOT / "data" / "patent_database" / "index.json"
PROGRESS_PATH = PROJECT_ROOT / "data" / "patent_database" / "firecrawl_progress.json"
REQUEST_INTERVAL = 2.0
SAVE_EVERY = 5


def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    db["metadata"]["updated"] = datetime.now().isoformat()
    db["metadata"]["total_patents"] = len(db["patents"])
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"done": {}, "failed": {}}


def save_progress(prog):
    PROGRESS_PATH.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Firecrawl 全文补充")
    parser.add_argument("--limit", type=int, default=10, help="最多处理N篇")
    parser.add_argument("--pids", default="", help="逗号分隔专利号")
    parser.add_argument("--dry-run", action="store_true", help="只列清单")
    args = parser.parse_args()

    fc = create_firecrawl_client()
    if not fc.is_available():
        print("错误: Firecrawl 未配置 api_key")
        return

    # 用 GooglePatentsClient 的解析器（不联网，只复用解析逻辑）
    parser_client = GooglePatentsClient.__new__(GooglePatentsClient)

    db = load_db()
    patents = db["patents"]

    if args.pids:
        targets = [p.strip() for p in args.pids.split(",") if p.strip()]
    else:
        targets = [pid for pid, p in patents.items()
                   if not p.get("has_claims") and p.get("title")]
    targets = targets[:args.limit]

    print(f"待补全文: {len(targets)} 篇 (Firecrawl 云端抓取, 免费档 credits 有限)")
    if args.dry_run:
        for pid in targets:
            print(f"  {pid} | {patents[pid].get('title', '')[:40]}")
        return

    prog = load_progress()
    done, failed = prog["done"], prog["failed"]
    todo = [pid for pid in targets if pid not in done and pid not in failed]
    print(f"本次处理: {len(todo)} 篇")

    ok_count = 0
    for i, pid in enumerate(todo, 1):
        try:
            html = fc.scrape_patent_html(pid)
            if not html:
                failed[pid] = {"reason": "Firecrawl无HTML", "at": datetime.now().isoformat()}
                print(f"[{i}/{len(todo)}] {pid} 无HTML")
                continue
            patent = parser_client._parse_patent_page(html, pid, f"https://patents.google.com/patent/{pid}")
            updated = False
            if patent.claims:
                patents[pid]["claims"] = patent.claims
                patents[pid]["has_claims"] = True
                updated = True
            if patent.description:
                patents[pid]["description"] = patent.description
                patents[pid]["has_description"] = True
                updated = True
            if patent.ipc_codes and not patents[pid].get("ipc"):
                patents[pid]["ipc"] = "; ".join(dict.fromkeys(patent.ipc_codes))
            patents[pid]["text_source"] = "firecrawl"
            patents[pid]["text_fetched_at"] = datetime.now().isoformat()
            if updated:
                done[pid] = {"at": datetime.now().isoformat()}
                ok_count += 1
                print(f"[{i}/{len(todo)}] {pid} OK: 权利要求{len(patent.claims or '')}字")
            else:
                failed[pid] = {"reason": "解析无claims/desc", "at": datetime.now().isoformat()}
                print(f"[{i}/{len(todo)}] {pid} 解析无内容")
        except Exception as e:
            failed[pid] = {"reason": str(e)[:200], "at": datetime.now().isoformat()}
            print(f"[{i}/{len(todo)}] {pid} 异常: {str(e)[:80]}")

        if i % SAVE_EVERY == 0 or i == len(todo):
            save_db(db)
            save_progress(prog)
        if i < len(todo):
            time.sleep(REQUEST_INTERVAL)

    save_db(db)
    save_progress(prog)
    print("\n" + "=" * 50)
    print(f"完成: 成功 {ok_count} | 失败 {len(todo) - ok_count}")
    pending = sum(1 for p in patents.values() if not p.get("has_claims"))
    print(f"库中仍缺全文: {pending} 篇")


if __name__ == "__main__":
    main()
