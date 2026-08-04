"""IPC 分类号领域发现（构建完整专利库的方法）

用 Google Patents 的 IPC 检索做领域全量发现，替代 CNIPA FTP 的"按 IPC 圈定"功能
（CNIPA FTP 慢且不稳定，本脚本完全绕开它）：

1. 对每个领域 IPC，分页检索 Google Patents 的中国专利（每页50条，默认取300条）
2. 合并去重，得到领域目标专利清单
3. 与本地数据库对比，报告"已有 vs 新增"
4. 目标清单保存到 data/target_patents.json，可直接喂给 fast_crawl.py 抓全文

用法: D:/Anaconda3/envs/mathmodel/python.exe scripts/ipc_discovery.py [每IPC页数]
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
TARGET_PATH = project_root / "data" / "target_patents.json"
PAGE_SIZE = 50
PAGES_PER_IPC = int(sys.argv[1]) if len(sys.argv) > 1 else 6  # 默认每个IPC取300条
SEARCH_INTERVAL = 3  # 检索间隔（秒）

# 领域 IPC 分组（来自专利分类调研）
DOMAIN_IPCS = {
    "管道检测机器人": [
        "F16L55/26", "F16L55/28", "F16L55/30", "F16L55/32",
        "F16L55/34", "F16L55/40", "F16L55/44", "F16L101/30",
    ],
    "电力管道巡检": [
        "H02G1/08", "H02G1/02", "H02G9/06", "H02G7/16",
    ],
    "机器人控制": [
        "B25J11/00", "B25J5/00", "B25J9/16", "B25J19/02",
    ],
    "管道检测感知": [
        "G01N21/954", "G01N29/04", "G01R31/08", "G01R31/12",
    ],
    "电力系统": [
        "H02J3/00", "H02J3/38", "H02J13/00", "G01R21/00",
    ],
}


def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def discover(google, db, pages_per_ipc=PAGES_PER_IPC):
    """按 IPC 分页检索，返回 领域->专利ID 清单

    每个 IPC 结束时增量保存到 target_patents.json，中断不丢数据。
    """
    # 从已有增量文件恢复进度
    existing = set(db["patents"].keys())
    found = {}  # ipc -> [ids]
    all_ids = set()
    if TARGET_PATH.exists():
        try:
            old = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
            found = old.get("by_ipc", {})
            all_ids.update(old.get("new_to_crawl", []))
            all_ids.update(old.get("missing_full_text", []))
            print(f"  恢复进度: {len(found)} 个IPC已发现")
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    def save():
        TARGET_PATH.parent.mkdir(exist_ok=True)
        new_ids = sorted(all_ids - existing)
        missing_full = sorted(
            pid for pid in (all_ids & existing)
            if not db["patents"].get(pid, {}).get("has_claims")
        )
        target = {
            "generated_at": datetime.now().isoformat(),
            "total_discovered": len(all_ids),
            "new_to_crawl": new_ids,
            "missing_full_text": missing_full,
            "by_ipc": {k: v for k, v in found.items()},
            "domain_ipcs": DOMAIN_IPCS,
        }
        TARGET_PATH.write_text(
            json.dumps(target, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    for group, ipcs in DOMAIN_IPCS.items():
        print(f"\n=== {group} ({len(ipcs)} 个IPC) ===")
        for ipc in ipcs:
            # 已发现过的 IPC 跳过（增量恢复）
            if ipc in found:
                unique = found[ipc]
                all_ids.update(unique)
                print(f"  {ipc}: {len(unique)} 篇 [已缓存]")
                continue

            ids = []
            for page in range(pages_per_ipc):
                try:
                    batch = google.search_patents(
                        f"({ipc})", num_results=PAGE_SIZE, country="CN", page=page
                    )
                    if not batch:
                        break
                    ids.extend(batch)
                except Exception as e:
                    print(f"  {ipc} page{page} 失败: {e}")
                    break
                time.sleep(SEARCH_INTERVAL)
            unique = list(dict.fromkeys(ids))  # 去重保序
            found[ipc] = unique
            all_ids.update(unique)
            print(f"  {ipc}: 发现 {len(unique)} 篇")
            save()  # 增量保存

    return found, all_ids


def main():
    print(f"[{datetime.now():%H:%M:%S}] IPC 领域发现启动 "
          f"(每IPC取{PAGES_PER_IPC}页×{PAGE_SIZE}条)")

    google = create_client_from_config()
    if not google.check_proxy():
        print("错误: 代理不可用，请确认 Clash 已启动")
        return

    db = load_db()
    existing = set(db["patents"].keys())
    print(f"本地数据库: {len(existing)} 篇")

    found, all_ids = discover(google, db)

    # 汇总
    new_ids = sorted(all_ids - existing)
    existing_ids = sorted(all_ids & existing)
    missing_full = sorted(
        pid for pid in existing_ids
        if not db["patents"].get(pid, {}).get("has_claims")
    )

    print(f"\n{'='*50}")
    print(f"领域发现完成")
    print(f"  发现专利总数: {len(all_ids)} 篇 (去重后)")
    print(f"  已在库中:     {len(existing_ids)} 篇")
    print(f"  新增可抓取:   {len(new_ids)} 篇")
    print(f"  在库但缺全文: {len(missing_full)} 篇")
    print(f"{'='*50}")
    print(f"\n目标清单已保存: {TARGET_PATH}")
    print(f"\n下一步: 用 fast_crawl.py 抓取这些专利全文")
    print(f"  D:/Anaconda3/envs/mathmodel/python.exe scripts/fast_crawl.py")


if __name__ == "__main__":
    main()
