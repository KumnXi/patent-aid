"""专利并发快速爬取（替代 slow_crawl）

相比 slow_crawl.py 的改进：
- 并发抓取详情（默认 4 线程），网络延迟被并发覆盖
- 全局节流 1 秒/篇（共享 RateLimiter），避免 429 限流
- 保留渐进退避：连续失败时自动冷却 60→120→300 秒
- 保留批量保存（主线程单写，线程安全）

实测节奏：4 线程 + 1s 节流 ≈ 每分钟 ~50 篇（slow_crawl 约 4 篇/分钟）。

用法: D:/Anaconda3/envs/mathmodel/python.exe scripts/fast_crawl.py
"""

import sys, io, json, time, threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.api.google_patents import create_client_from_config

DB_PATH = project_root / "data" / "patent_database" / "index.json"
MAX_FETCH = 200     # 本次最多抓取数量
WORKERS = 4         # 并发线程数
MIN_INTERVAL = 1.0  # 全局请求间隔（秒）
SAVE_EVERY = 10     # 每 N 篇保存一次

# 渐进退避策略
BACKOFF_LEVELS = [60, 120, 300]  # 连续失败时: 1分钟→2分钟→5分钟
CONSECUTIVE_FAIL_TRIGGER = 5     # 连续失败 N 篇触发冷却

# 电力行业关键词
ELECTRICAL_KEYWORDS = ["配电", "继电", "光伏", "变压器", "输电", "变电",
                       "微电网", "电缆", "储能", "虚拟电厂", "无功", "负荷"]


# ═══════════════════════════════════════════════════════════
# 并发基础设施
# ═══════════════════════════════════════════════════════════

class RateLimiter:
    """全局请求节流器（线程安全）"""

    def __init__(self, min_interval: float):
        self._lock = threading.Lock()
        self._min = min_interval
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.time()
            delta = now - self._last
            if delta < self._min:
                time.sleep(self._min - delta)
            self._last = time.time()


# 每个线程独立的 client（requests.Session 非线程安全，必须分开）
_thread_local = threading.local()


def _get_client():
    if not hasattr(_thread_local, "client"):
        _thread_local.client = create_client_from_config()
    return _thread_local.client


def fetch_one(rate_limiter: RateLimiter, pid: str, category: str):
    """带全局节流的单篇抓取（供线程池调用）"""
    rate_limiter.wait()
    client = _get_client()
    try:
        patent = client.get_patent_detail(pid)
        return pid, category, patent, None
    except Exception as e:
        return pid, category, None, str(e)


# ═══════════════════════════════════════════════════════════
# 数据库
# ═══════════════════════════════════════════════════════════

def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    db["metadata"]["updated"] = datetime.now().isoformat()
    db["metadata"]["total_patents"] = len(db["patents"])
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def classify(query: str) -> str:
    """根据搜索关键词自动分类"""
    return "electrical" if any(k in query for k in ELECTRICAL_KEYWORDS) else "pipeline_robot"


def apply_result(db, pid, category, patent):
    """把抓取结果写入数据库（主线程单写）"""
    if patent and patent.claims:
        entry = db["patents"].get(pid, {"id": pid})
        entry.update({
            "id": pid,
            "title": patent.title or "",
            "applicant": patent.applicant or "",
            "application_date": patent.application_date or "",
            "ipc": "; ".join(patent.ipc_codes[:3]) if patent.ipc_codes else "",
            "summary": patent.abstract or "",
            "legal_status": patent.legal_status or "",
            "claims": patent.claims,
            "description": patent.description or "",
            "has_claims": True,
            "has_description": bool(patent.description),
            "crawled_at": datetime.now().isoformat(),
            "source": "fast_crawl",
            "category": category,
            "text_source": "google_patents",
        })
        db["patents"][pid] = entry
        return True
    else:
        if patent and patent.title:
            entry = db["patents"].get(pid, {"id": pid})
            entry.update({
                "id": pid, "title": patent.title or "",
                "applicant": patent.applicant or "",
                "ipc": "; ".join(patent.ipc_codes[:3]) if patent.ipc_codes else "",
                "category": category, "has_claims": False,
                "has_description": False,
                "crawled_at": datetime.now().isoformat(),
                "source": "fast_crawl",
            })
            db["patents"][pid] = entry
        return False


# ═══════════════════════════════════════════════════════════
# 搜索
# ═══════════════════════════════════════════════════════════

def collect_targets(google, db, queries, max_fetch):
    """搜索并去重，返回待抓取列表"""
    to_fetch = []
    seen = set()
    for q in queries:
        print(f"[{datetime.now():%H:%M:%S}] 搜索: {q}")
        try:
            ids = google.search_patents(q, num_results=25, country="CN")
            new_count = 0
            for pid in ids:
                if pid not in seen and (pid not in db["patents"] or not db["patents"][pid].get("has_claims")):
                    seen.add(pid)
                    to_fetch.append((pid, classify(q)))
                    new_count += 1
            print(f"  找到 {len(ids)} 篇, 新增 {new_count}")
        except Exception as e:
            print(f"  失败: {e}")
        time.sleep(2)
        if len(to_fetch) >= max_fetch:
            break
    return to_fetch[:max_fetch]


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def main():
    print(f"[{datetime.now():%H:%M:%S}] 并发爬取启动 "
          f"(线程{WORKERS}, 节流{MIN_INTERVAL}s, 上限{MAX_FETCH}篇)")

    google = create_client_from_config()
    if not google.check_proxy():
        print("错误: 代理不可用，请确认 Clash 已启动")
        return

    db = load_db()
    print(f"  当前数据库: {len(db['patents'])} 篇")

    queries = [
        "配电网 故障隔离 自愈", "继电保护 整定计算 方法",
        "虚拟电厂 需求响应 调度", "分布式光伏 并网 逆变器",
        "电力变压器 状态监测 故障诊断", "输电线路 覆冰 在线监测",
        "智能变电站 保护 自动化", "微电网 能量管理 优化调度",
        "电力电缆 故障测距 定位", "储能系统 电池管理 协调控制",
        "电力系统 暂态稳定 控制", "无功补偿 电压调节",
        "管道检测机器人 缺陷识别", "管道巡检机器人 深度学习",
        "管道 裂纹检测 超声", "pipeline inspection robot",
    ]

    to_fetch = collect_targets(google, db, queries, MAX_FETCH)
    print(f"\n[{datetime.now():%H:%M:%S}] 待抓取: {len(to_fetch)} 篇\n")

    rate_limiter = RateLimiter(MIN_INTERVAL)
    success = 0
    failed = 0
    consecutive_fail = 0
    backoff_idx = 0
    dirty = False

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_one, rate_limiter, pid, cat)
                   for pid, cat in to_fetch}

        for i, future in enumerate(as_completed(futures), 1):
            # 限流冷却
            if consecutive_fail >= CONSECUTIVE_FAIL_TRIGGER:
                wait = BACKOFF_LEVELS[min(backoff_idx, len(BACKOFF_LEVELS) - 1)]
                print(f"\n[{datetime.now():%H:%M:%S}] 连续失败{consecutive_fail}篇，"
                      f"冷却 {wait}秒 (第{backoff_idx+1}级)")
                time.sleep(wait)
                backoff_idx += 1
                consecutive_fail = 0

            try:
                pid, category, patent, err = future.result()
            except Exception as e:
                pid, category, patent, err = "?", "", None, str(e)

            if err:
                failed += 1
                consecutive_fail += 1
                print(f"[{datetime.now():%H:%M:%S}] [{i}/{len(to_fetch)}] {pid} 异常: {err}")
                continue

            ok = apply_result(db, pid, category, patent)
            if ok:
                success += 1
                consecutive_fail = 0
                backoff_idx = 0
                print(f"[{datetime.now():%H:%M:%S}] [{i}/{len(to_fetch)}] {pid} "
                      f"OK: {(patent.title or '')[:25]}... ({len(patent.claims)}字)")
            else:
                failed += 1
                consecutive_fail += 1
                print(f"[{datetime.now():%H:%M:%S}] [{i}/{len(to_fetch)}] {pid} FAIL")

            # 批量保存
            if success and (success % SAVE_EVERY == 0 or i == len(to_fetch)):
                save_db(db)
                dirty = False
            else:
                dirty = True

    if dirty:
        save_db(db)

    print(f"\n{'='*50}")
    print(f"[{datetime.now():%H:%M:%S}] 完成!")
    total_done = success + failed
    rate = (success / total_done * 100) if total_done else 0
    print(f"  成功: {success} | 失败: {failed} | 成功率: {rate:.0f}%")
    print(f"  数据库总量: {len(db['patents'])} 篇")
    has_claims = sum(1 for p in db['patents'].values() if p.get('has_claims'))
    print(f"  有全文: {has_claims} 篇")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
