"""Firecrawl 云端批量爬取（免代理主力通道）

数据流:
  1. 搜索发现: Firecrawl search 按关键词/领域查询 → 提取专利号（云端搜索）
  2. 全文抓取: Firecrawl scrape Google Patents 页面（云端执行，本地零代理）
  3. 解析入库: 复用 google_patents._parse_patent_page 提取 claims/desc/IPC

用法:
    python scripts/firecrawl_crawl.py --query "管道检测机器人 缺陷识别"   # 关键词发现+抓取
    python scripts/firecrawl_crawl.py --discover-only                    # 只搜索发现专利号
    python scripts/firecrawl_crawl.py --pids CNxxx,CNyyy                 # 直接抓指定专利
    python scripts/firecrawl_crawl.py --limit 30                         # 本次最多处理30篇
    python scripts/firecrawl_crawl.py --dry-run                          # 只列计划

注意:
    - Firecrawl 免费档约 500 credits/月，一篇专利页消耗数个 credits
    - 建议小批量多轮（--limit 20~30），避免一次烧完额度
"""

import sys
import io
import json
import time
import re
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
DISCOVER_PATH = PROJECT_ROOT / "data" / "target_patents_firecrawl.json"
PROGRESS_PATH = PROJECT_ROOT / "data" / "patent_database" / "firecrawl_progress.json"
REQUEST_INTERVAL = 6.0   # 免费档限流约 11 req/min → 6s/请求
SAVE_EVERY = 5

# 默认发现查询（电力+管道方向，与数据库定位一致）
DEFAULT_QUERIES = [
    "site:patents.google.com 管道检测机器人",
    "site:patents.google.com 管道 缺陷 检测 方法",
    "site:patents.google.com 管道 剩余寿命 评估",
    "site:patents.google.com 海底管道 检测 机器人",
    "site:patents.google.com 燃气管道 泄漏 检测",
    "site:patents.google.com 电缆隧道 巡检 机器人",
    "site:patents.google.com 虚拟电厂 调度 优化",
    "site:patents.google.com 配电网 故障 自愈",
    "site:patents.google.com 储能 电池 均衡 管理",
    "site:patents.google.com 变压器 状态监测 故障诊断",
    "site:patents.google.com 继电保护 整定 计算",
    "site:patents.google.com 输电线路 覆冰 监测",
    "site:patents.google.com 光伏 并网 逆变器",
    "site:patents.google.com pipeline inspection robot",
    "site:patents.google.com pipeline defect detection",
]

PATENT_ID_RE = re.compile(
    r"(CN\s?\d{6,9}\s?[ABU])|(WO\s?\d{4}/\s?\d+)|(CN\d{6,9})", re.IGNORECASE)


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


def extract_patent_ids(results: list) -> list:
    """从搜索结果提取专利号

    优先从 url 路径（/patent/CNxxxxxxxA/zh）提取，再回退到 title/description 全文匹配。
    """
    ids = set()
    for r in results:
        if not isinstance(r, dict):
            continue
        url = r.get("url", "") or ""
        # 路径提取: patents.google.com/patent/CN102913715A/zh
        m_path = re.search(r"/patent/(CN\d{6,9}[ABU]?)/", url, re.IGNORECASE)
        if m_path:
            ids.add(m_path.group(1).upper())
            continue
        # 通用匹配
        for field in ("url", "title", "description"):
            text = r.get(field, "") or ""
            for m in PATENT_ID_RE.finditer(text):
                pid = (m.group(1) or m.group(2) or "").replace(" ", "").upper()
                if pid:
                    ids.add(pid)
    return sorted(ids)


def discover(fc, queries, limit_per_query=10) -> list:
    """搜索发现专利号"""
    found = set()
    for q in queries:
        print(f"  搜索: {q}")
        try:
            results = fc.search(q, limit=limit_per_query)
            ids = extract_patent_ids(results)
            found.update(ids)
            print(f"    → {len(results)} 条结果, 发现 {len(ids)} 个专利号")
        except Exception as e:
            print(f"    失败: {e}")
        time.sleep(1)
    return sorted(found)


def discover_by_xhr(fc, ipcs, num_per_ipc=50) -> dict:
    """按 IPC 检索式批量发现（Firecrawl 抓 Google Patents xhr/query 接口）

    Google Patents xhr 接口按 IPC 精确检索，返回结构化 JSON
    （publication_number/title/assignee/dates），一次可达数千条。

    返回: {patent_id: {"ipc": 检索IPC, "title": ..., "assignee": ..., "filing_date": ...}}
    """
    import requests as _req
    found = {}
    for ipc in ipcs:
        print(f"  xhr检索: {ipc}")
        try:
            q = f"q=({ipc})%26country%3DCN%26type%3DPATENT%26num%3D{num_per_ipc}"
            url = f"https://patents.google.com/xhr/query?url={q}"
            resp = _req.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={"Authorization": f"Bearer {fc.api_key}",
                         "Content-Type": "application/json"},
                json={"url": url, "formats": ["rawHtml"]},
                timeout=90)
            if resp.status_code != 200:
                print(f"    HTTP {resp.status_code}")
                continue
            raw = resp.json().get("data", {}).get("rawHtml", "")
            if not raw:
                print("    无返回")
                continue
            data = json.loads(raw)
            clusters = data.get("results", {}).get("cluster", [])
            count = 0
            for cluster in clusters:
                for item in cluster.get("result", []):
                    p = item.get("patent", {})
                    pid = p.get("publication_number", "")
                    if not pid or not pid.startswith("CN"):
                        continue
                    if pid not in found:
                        found[pid] = {
                            "ipc": ipc,
                            "title": p.get("title", "").strip(),
                            "assignee": p.get("assignee", ""),
                            "filing_date": p.get("filing_date", ""),
                        }
                        count += 1
            print(f"    → 发现 {count} 个新专利号")
        except Exception as e:
            print(f"    失败: {e}")
        time.sleep(1.5)
    return found


def main():
    parser = argparse.ArgumentParser(description="Firecrawl 云端批量爬取")
    parser.add_argument("--query", default="", help="搜索关键词（逗号分隔多个）")
    parser.add_argument("--ipcs", default="", help="IPC检索式列表(逗号分隔,如 F16L55/26,H02J3/38)")
    parser.add_argument("--all-ipcs", action="store_true", help="全部领域组IPC(复用ipc_discovery清单)")
    parser.add_argument("--num-per-ipc", type=int, default=50, help="每个IPC检索条数")
    parser.add_argument("--discover-only", action="store_true", help="只搜索发现，不抓全文")
    parser.add_argument("--pids", default="", help="直接抓指定专利号(逗号分隔)")
    parser.add_argument("--limit", type=int, default=20, help="本次最多抓取篇数")
    parser.add_argument("--dry-run", action="store_true", help="只列计划不执行")
    parser.add_argument("--no-discover", action="store_true", help="跳过搜索发现(只用清单)")
    parser.add_argument("--retry-failed", action="store_true", help="重试失败的专利(默认跳过)")
    args = parser.parse_args()

    fc = create_firecrawl_client()
    if not fc.is_available():
        print("错误: Firecrawl 未配置 api_key (config/api_config.json firecrawl.api_key)")
        return

    db = load_db()
    patents = db["patents"]

    # ── 1. 确定目标专利号 ─────────────────────────────
    targets = []
    ipc_of = {}   # pid -> 检索IPC（用于填充）
    if args.pids:
        targets = [p.strip() for p in args.pids.split(",") if p.strip()]
    elif args.ipcs or args.all_ipcs:
        # xhr IPC 批量发现模式
        if args.all_ipcs:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from ipc_discovery import DOMAIN_IPCS
            ipcs = [ipc for group in DOMAIN_IPCS.values() for ipc in group]
        else:
            ipcs = [i.strip() for i in args.ipcs.split(",") if i.strip()]
        print(f"xhr IPC 检索发现阶段 ({len(ipcs)} 个IPC)...")
        discovered = discover_by_xhr(fc, ipcs, num_per_ipc=args.num_per_ipc)
        # 过滤已存在且有全文的
        new_ids = [pid for pid in discovered
                   if pid not in patents or not patents[pid].get("has_claims")]
        print(f"发现 {len(discovered)} 个专利号, 其中待抓 {len(new_ids)} 个")
        targets = new_ids
        ipc_of = discovered
        # 保存发现清单
        DISCOVER_PATH.write_text(json.dumps({
            "generated_at": datetime.now().isoformat(),
            "patents": targets,
            "ipcs": ipcs,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"发现清单已保存: {DISCOVER_PATH}")
    else:
        if args.query:
            queries = [q.strip() for q in args.query.split(",")]
            queries = [q if "site:" in q else "site:patents.google.com " + q for q in queries]
        else:
            queries = DEFAULT_QUERIES
        print(f"搜索发现阶段 ({len(queries)} 组查询)...")
        discovered = discover(fc, queries)
        # 过滤已存在且有全文的
        new_ids = [pid for pid in discovered
                   if pid not in patents or not patents[pid].get("has_claims")]
        print(f"发现 {len(discovered)} 个专利号, 其中待抓 {len(new_ids)} 个")
        targets = new_ids
        # 保存发现清单
        DISCOVER_PATH.write_text(json.dumps({
            "generated_at": datetime.now().isoformat(),
            "patents": discovered,
            "queries": queries,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"发现清单已保存: {DISCOVER_PATH}")

    if args.discover_only:
        return

    targets = targets[:args.limit]
    print(f"\n本次待抓取: {len(targets)} 篇 (Firecrawl credits 有限, 建议每轮 ≤30)")

    # ── 2. 抓取全文（云端） ───────────────────────────
    parser_client = GooglePatentsClient.__new__(GooglePatentsClient)
    prog = load_progress()
    done, failed = prog["done"], prog["failed"]
    if args.retry_failed:
        todo = [pid for pid in targets if pid not in done]
    else:
        todo = [pid for pid in targets if pid not in done and pid not in failed]

    if args.dry_run:
        for pid in todo:
            print(f"  [计划] {pid} | {patents.get(pid, {}).get('title', '(新)')[:40]}")
        return

    print(f"实际处理: {len(todo)} 篇")
    ok_count = 0
    for i, pid in enumerate(todo, 1):
        try:
            html = fc.scrape_patent_html(pid)
            if not html:
                failed[pid] = {"reason": "Firecrawl无HTML", "at": datetime.now().isoformat()}
                print(f"[{i}/{len(todo)}] {pid} 无HTML (可能credits不足或页面被拒)")
                continue
            patent = parser_client._parse_patent_page(html, pid, f"https://patents.google.com/patent/{pid}")

            entry = patents.get(pid, {"id": pid})
            if patent.title:
                entry["title"] = patent.title
            if patent.abstract:
                entry["summary"] = patent.abstract
            if patent.applicant:
                entry["applicant"] = patent.applicant
            if patent.application_date:
                entry["application_date"] = patent.application_date
            if patent.ipc_codes:
                entry["ipc"] = "; ".join(dict.fromkeys(patent.ipc_codes))
            if not entry.get("ipc") and pid in ipc_of:
                # 检索IPC兜底（xhr 模式：检索式即该批专利的主IPC家族）
                entry["ipc"] = ipc_of[pid].get("ipc", "")
            if not entry.get("applicant") and pid in ipc_of:
                entry["applicant"] = ipc_of[pid].get("assignee", "")
            if not entry.get("application_date") and pid in ipc_of:
                entry["application_date"] = ipc_of[pid].get("filing_date", "")
            if patent.claims:
                entry["claims"] = patent.claims
                entry["has_claims"] = True
            if patent.description:
                entry["description"] = patent.description
                entry["has_description"] = True
            entry["source"] = entry.get("source") or "firecrawl"
            entry["text_source"] = "firecrawl"
            entry["text_fetched_at"] = datetime.now().isoformat()
            entry["crawled_at"] = entry.get("crawled_at") or datetime.now().isoformat()
            patents[pid] = entry

            if entry.get("has_claims"):
                done[pid] = {"at": datetime.now().isoformat()}
                ok_count += 1
                tag = "[全文]" if entry.get("has_description") else "[仅权要]"
                print(f"[{i}/{len(todo)}] {tag} {pid}: {entry.get('title', '')[:30]} ({len(entry.get('claims', ''))}字)")
            else:
                failed[pid] = {"reason": "解析无claims", "at": datetime.now().isoformat()}
                print(f"[{i}/{len(todo)}] {pid} 解析无claims")
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
    print(f"数据库总量: {len(patents)} 篇")
    has_full = sum(1 for p in patents.values() if p.get("has_claims"))
    print(f"有全文: {has_full} 篇")
    empty_ipc = sum(1 for p in patents.values() if not p.get("ipc"))
    print(f"IPC 为空: {empty_ipc} 篇")
    print(f"进度文件: {PROGRESS_PATH} (重跑自动跳过已完成)")


if __name__ == "__main__":
    main()
