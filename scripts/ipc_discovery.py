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

# 领域 IPC 分组（来自专利分类调研；管道方向为核心业务，覆盖最全）
DOMAIN_IPCS = {
    "管道检测机器人": [
        "F16L55/26", "F16L55/28", "F16L55/30", "F16L55/32",
        "F16L55/34", "F16L55/36", "F16L55/38", "F16L55/40",
        "F16L55/44", "F16L55/46", "F16L101/10", "F16L101/12",
        "F16L101/16", "F16L101/30", "F16L101/60",
    ],
    "管道无损检测": [
        "G01N27/82", "G01N27/83", "G01N27/87", "G01N27/90",
        "G01N29/04", "G01N29/07", "G01N29/26", "G01N29/44",
        "G01B17/00", "G01B17/02",
    ],
    "管道泄漏检测": [
        "G01M3/02", "G01M3/24", "G01M3/28", "F17D5/02", "F17D5/06",
    ],
    "管内视觉检测": [
        "G01N21/88", "G01N21/89", "G01N21/954",
    ],
    "电力管道巡检": [
        "H02G1/08", "H02G1/02", "H02G9/06", "H02G7/16",
    ],
    "机器人控制": [
        "B25J11/00", "B25J5/00", "B25J9/16", "B25J13/08", "B25J19/02",
    ],
    "电力输配电网络": [
        "H02J3/00", "H02J3/01", "H02J3/06", "H02J3/12",
        "H02J3/18", "H02J3/24", "H02J3/28", "H02J3/32",
        "H02J3/34", "H02J3/36", "H02J3/38", "H02J3/46",
        "H02J13/00", "H02J13/02",
    ],
    "继电保护与故障处理": [
        "H02H1/00", "H02H3/00", "H02H3/04", "H02H3/06",
        "H02H3/08", "H02H3/16", "H02H3/26", "H02H3/28",
        "H02H3/32", "H02H3/38", "H02H5/00", "H02H7/00",
        "H02H7/04", "H02H7/06", "H02H7/16", "H02H7/20",
        "H02H7/22", "H02H7/26", "H02H9/00", "H02H9/02",
    ],
    "储能与新能源": [
        "H02J15/00", "H02J7/00", "H02J7/34", "H01M10/42",
        "H01M10/44", "H01M10/48", "H01M10/0525", "H01M10/052",
        "H02S10/00", "H02S10/10", "H02S20/00", "H02S40/00",
        "H02S40/30", "H02S50/00", "H02S50/10",
    ],
    "电力设备监测与诊断": [
        "G01R31/00", "G01R31/02", "G01R31/08", "G01R31/11",
        "G01R31/12", "G01R31/14", "G01R31/34", "G01R31/40",
        "G01R31/52", "G01R31/54", "G01R31/62", "G01R31/72",
        "G01K1/00", "G01K11/00", "G01K13/00",
    ],
    "变压器与变流设备": [
        "H01F27/00", "H01F27/02", "H01F27/06", "H01F27/08",
        "H01F27/28", "H01F27/32", "H01F30/00", "H01F30/06",
        "H01F38/00", "H01F41/00", "H02M1/00", "H02M1/08",
        "H02M3/00", "H02M3/04", "H02M5/00", "H02M7/00",
        "H02M7/04", "H02M7/12", "H02M7/48",
    ],
    "电机与电气设备": [
        "H02K1/00", "H02K3/00", "H02K5/00", "H02K7/00",
        "H02K9/00", "H02K11/00", "H02K15/00", "H02K16/00",
        "H02K17/00", "H02K19/00", "H02K21/00", "H02P1/00",
        "H02P9/00", "H02P21/00", "H02P23/00", "H02P25/00",
        "H02P27/00", "H02P29/00", "H02K29/00",
    ],
    "电缆与输电线路": [
        "H01B3/00", "H01B7/00", "H01B7/02", "H01B9/00",
        "H01B11/00", "H01B13/00", "H01B17/00", "H01B17/26",
        "H02G1/00", "H02G1/02", "H02G1/08", "H02G3/00",
        "H02G3/02", "H02G3/04", "H02G3/30", "H02G5/00",
        "H02G7/00", "H02G7/02", "H02G7/16", "H02G9/00",
        "H02G9/06", "H02G11/00", "H02G15/00", "H02G15/08",
    ],
    "电力调度与电力市场": [
        "G06Q50/06", "G06Q10/04", "G06Q10/06", "G06Q10/0631",
        "G06Q30/02", "G05B19/00", "G05B19/04", "G05B19/418",
        "G05B13/00", "G05B13/02", "G05B13/04", "G06N3/00",
        "G06N3/02", "G06N3/04", "G06N3/08", "G06N20/00",
        "G06F17/00", "G06F18/00", "G06F18/20",
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
