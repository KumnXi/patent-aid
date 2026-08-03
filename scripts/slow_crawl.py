"""
专利定向爬取（电力 + 管道检测机器人）

策略：
- 每篇间隔15秒（正常），被限流时渐进退避 60→120→300秒
- 搜索间隔8秒，每次最多抓100篇
- 每5篇批量保存一次，减少IO
- 启动时检测限流状态，自动等待冷却

用法: D:/Anaconda3/envs/mathmodel/python.exe scripts/slow_crawl.py
"""

import sys, io, json, time
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.api.google_patents import create_client_from_config

DB_PATH = project_root / "data" / "patent_database" / "index.json"
MAX_FETCH = 100      # 本次最多抓取数量
INTERVAL = 15        # 正常间隔（秒）- 从30降到15
SEARCH_INTERVAL = 8  # 搜索间隔（秒）
SAVE_EVERY = 5       # 每N篇保存一次

# 渐进退避策略
BACKOFF_LEVELS = [60, 120, 300]  # 连续失败时: 1分钟→2分钟→5分钟

# 电力行业关键词
ELECTRICAL_KEYWORDS = ["配电","继电","光伏","变压器","输电","变电","微电网","电缆","储能","虚拟电厂","无功","负荷"]


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


def main():
    print(f"[{datetime.now():%H:%M:%S}] 专利爬取启动 (间隔{INTERVAL}s, 上限{MAX_FETCH}篇)")

    google = create_client_from_config()
    if not google.check_proxy():
        print("错误: 代理不可用，请确认 Clash 已启动")
        return

    db = load_db()
    print(f"  当前数据库: {len(db['patents'])} 篇")

    # ━━━ 搜索阶段 ━━━
    queries = [
        # 电力行业
        "配电网 故障隔离 自愈",
        "继电保护 整定计算 方法",
        "虚拟电厂 需求响应 调度",
        "分布式光伏 并网 逆变器",
        "电力变压器 状态监测 故障诊断",
        "输电线路 覆冰 在线监测",
        "智能变电站 保护 自动化",
        "微电网 能量管理 优化调度",
        "电力电缆 故障测距 定位",
        "储能系统 电池管理 协调控制",
        "电力系统 暂态稳定 控制",
        "无功补偿 电压调节",
        # 管道检测机器人
        "管道检测机器人 缺陷识别",
        "管道巡检机器人 深度学习",
        "管道 裂纹检测 超声",
        "pipeline inspection robot",
    ]

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
        time.sleep(SEARCH_INTERVAL)

    to_fetch = to_fetch[:MAX_FETCH]
    print(f"\n[{datetime.now():%H:%M:%S}] 待抓取: {len(to_fetch)} 篇")
    print(f"  策略: 间隔{INTERVAL}s, 退避{'/'.join(map(str,BACKOFF_LEVELS))}s\n")

    # ━━━ 抓取阶段 ━━━
    success = 0
    failed = 0
    consecutive_fail = 0
    backoff_idx = 0
    dirty = False  # 是否有未保存的数据

    for i, (pid, category) in enumerate(to_fetch):
        # 渐进退避
        if consecutive_fail >= 3:
            wait = BACKOFF_LEVELS[min(backoff_idx, len(BACKOFF_LEVELS)-1)]
            print(f"\n[{datetime.now():%H:%M:%S}] 限流冷却 {wait}秒... (第{backoff_idx+1}级)")
            time.sleep(wait)
            backoff_idx += 1
            consecutive_fail = 0

        print(f"[{datetime.now():%H:%M:%S}] [{i+1}/{len(to_fetch)}] {pid}", end=" ")

        try:
            patent = google.get_patent_detail(pid)
        except Exception as e:
            patent = None
            print(f"异常: {e}")

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
                "source": "slow_crawl",
                "category": category,
                "text_source": "google_patents",
            })
            db["patents"][pid] = entry
            success += 1
            consecutive_fail = 0
            backoff_idx = 0  # 成功后重置退避等级
            dirty = True
            print(f"OK: {patent.title[:25]}... ({len(patent.claims)}字)")
        else:
            failed += 1
            consecutive_fail += 1
            if patent and patent.title:
                entry = db["patents"].get(pid, {"id": pid})
                entry.update({
                    "id": pid, "title": patent.title or "",
                    "applicant": patent.applicant or "",
                    "ipc": "; ".join(patent.ipc_codes[:3]) if patent.ipc_codes else "",
                    "category": category, "has_claims": False,
                    "has_description": False,
                    "crawled_at": datetime.now().isoformat(),
                    "source": "slow_crawl",
                })
                db["patents"][pid] = entry
                dirty = True
            print("FAIL")

        # 批量保存
        if dirty and (success % SAVE_EVERY == 0 or i == len(to_fetch) - 1):
            save_db(db)
            dirty = False

        # 间隔
        if i < len(to_fetch) - 1:
            time.sleep(INTERVAL)

    # 最终保存
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
