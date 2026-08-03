"""
Google BigQuery 专利数据批量获取

从 Google Patents Public Data 数据集中精准筛选电力/管道方向中国专利。

使用方式:
  方式1 (推荐): 在 BigQuery 网页端运行下方 SQL，导出 JSON 后运行:
    python scripts/bigquery_patents.py --import exported.json

  方式2 (自动化): 配置 Google Cloud 凭证后直接运行:
    set GOOGLE_APPLICATION_CREDENTIALS=path/to/service_account.json
    python scripts/bigquery_patents.py --query

注意:
- 免费额度: 每月 1TB 查询量，单次查询约扫描 ~1TB（全表扫描）
- 新账号有 $300 免费试用额度（90天）
- 超出额度需绑定信用卡才能继续查询
- 数据集字段为嵌套结构，必须用 UNNEST 展开
"""

import sys, io, json, argparse, time
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / "data" / "patent_database" / "index.json"
EXPORT_DIR = project_root / "data" / "bigquery_exports"

# ═══════════════════════════════════════════════════════════
# SQL 查询模板 - 精准筛选电力 + 管道方向
# ═══════════════════════════════════════════════════════════

# 注意: patents-public-data.patents.publications 表使用嵌套结构
# - title_localized / abstract_localized / claims_localized 是 ARRAY<STRUCT<text, language>>
# - ipc 是 ARRAY<STRUCT<code, inventive, first, tree>>
# - filing_date / publication_date 是 INT64 (格式: 20180101)
# 必须用 UNNEST 或子查询展开

POWER_SQL = """
SELECT
  p.publication_number,
  p.filing_date,
  p.publication_date,
  p.assignee,
  (SELECT t.text FROM UNNEST(p.title_localized) t WHERE t.language = 'zh' LIMIT 1) AS title,
  (SELECT ab.text FROM UNNEST(p.abstract_localized) ab WHERE ab.language = 'zh' LIMIT 1) AS abstract,
  (SELECT cl.text FROM UNNEST(p.claims_localized) cl LIMIT 1) AS claims
FROM `patents-public-data.patents.publications` p
WHERE
  p.country_code = 'CN'
  AND EXISTS (
    SELECT 1 FROM UNNEST(p.ipc) i
    WHERE i.code LIKE 'H02J%'    -- 电力网络/配电/调度
       OR i.code LIKE 'H02H%'    -- 继电保护
       OR i.code LIKE 'H02B%'    -- 配电设备/变电站
       OR i.code LIKE 'H02G%'    -- 电缆/输电线路
       OR i.code LIKE 'H02S%'    -- 光伏发电
       OR i.code LIKE 'H02M%'    -- 电力变换/逆变器
  )
  AND p.filing_date >= 20180101
LIMIT 1000
"""

PIPELINE_SQL = """
SELECT
  p.publication_number,
  p.filing_date,
  p.publication_date,
  p.assignee,
  (SELECT t.text FROM UNNEST(p.title_localized) t WHERE t.language = 'zh' LIMIT 1) AS title,
  (SELECT ab.text FROM UNNEST(p.abstract_localized) ab WHERE ab.language = 'zh' LIMIT 1) AS abstract,
  (SELECT cl.text FROM UNNEST(p.claims_localized) cl LIMIT 1) AS claims
FROM `patents-public-data.patents.publications` p
WHERE
  p.country_code = 'CN'
  AND EXISTS (
    SELECT 1 FROM UNNEST(p.title_localized) t
    WHERE t.text LIKE '%管道%检测%'
       OR t.text LIKE '%管道%机器人%'
       OR t.text LIKE '%管道%巡检%'
  )
  AND p.filing_date >= 20150101
LIMIT 500
"""


def query_bigquery(sql: str, label: str):
    """通过 BigQuery SDK 执行查询"""
    try:
        from google.cloud import bigquery
    except ImportError:
        print("错误: 需要安装 google-cloud-bigquery")
        print("  pip install google-cloud-bigquery")
        return None

    try:
        client = bigquery.Client()
    except Exception as e:
        print(f"错误: BigQuery 认证失败: {e}")
        print("\n请配置认证:")
        print("  方式1: set GOOGLE_APPLICATION_CREDENTIALS=path/to/key.json")
        print("  方式2: gcloud auth application-default login")
        return None

    print(f"[{datetime.now():%H:%M:%S}] 执行查询: {label}")
    print(f"  SQL 长度: {len(sql)} 字符")

    query_job = client.query(sql)
    results = query_job.result()  # 等待完成

    rows = []
    for row in results:
        rows.append(dict(row))

    print(f"  获取 {len(rows)} 条结果")
    return rows


def import_json(file_path: str):
    """导入从 BigQuery 网页端导出的 JSON 文件"""
    path = Path(file_path)
    if not path.exists():
        print(f"错误: 文件不存在 {file_path}")
        return None

    print(f"读取: {path.name} ({path.stat().st_size / 1024 / 1024:.1f}MB)")

    with open(path, "r", encoding="utf-8") as f:
        # BigQuery 导出的 JSON 可能是每行一个对象（JSONL）或数组
        content = f.read().strip()
        if content.startswith("["):
            rows = json.loads(content)
        else:
            # JSONL 格式
            rows = [json.loads(line) for line in content.split("\n") if line.strip()]

    print(f"  解析 {len(rows)} 条记录")
    return rows


def merge_to_database(rows: list):
    """将 BigQuery 结果合并到现有数据库"""
    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    existing = set(db["patents"].keys())
    added = 0
    skipped = 0

    for row in rows:
        # 标准化专利号
        pub_num = row.get("publication_number", "")
        if not pub_num:
            continue

        # BigQuery 格式: CN-117977607-B → CN117977607B
        pid = pub_num.replace("-", "")

        if pid in existing:
            skipped += 1
            continue

        # 构建专利条目
        title = row.get("title", "") or ""
        if isinstance(title, list):
            title = title[0] if title else ""

        abstract = row.get("abstract", "") or ""
        if isinstance(abstract, list):
            abstract = abstract[0] if abstract else ""

        claims = row.get("claims", "") or ""
        if isinstance(claims, list):
            claims = "\n".join(claims)

        # assignee 是 ARRAY<STRING>
        assignee = row.get("assignee", "") or ""
        if isinstance(assignee, list):
            assignee = "; ".join(assignee[:3]) if assignee else ""

        # filing_date / publication_date 是 INT64 (20180101)
        filing_date = str(row.get("filing_date", "") or "")
        pub_date = str(row.get("publication_date", "") or "")

        # 从 claims 内容推断 IPC（BigQuery 精简版不直接返回 ipc）
        ipc = ""

        entry = {
            "id": pid,
            "title": title,
            "applicant": assignee,
            "application_date": filing_date,
            "publication_date": pub_date,
            "ipc": ipc,
            "summary": abstract,
            "claims": claims,
            "has_claims": bool(claims and len(claims) > 50),
            "has_description": False,
            "crawled_at": datetime.now().isoformat(),
            "source": "bigquery",
            "category": "electrical",  # BigQuery SQL 已按电力IPC过滤
            "text_source": "bigquery_patents_public_data",
        }

        db["patents"][pid] = entry
        added += 1

    # 更新元数据
    db["metadata"]["updated"] = datetime.now().isoformat()
    db["metadata"]["total_patents"] = len(db["patents"])

    # 保存
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 50}")
    print(f"导入完成!")
    print(f"  新增: {added} 篇")
    print(f"  跳过(已存在): {skipped} 篇")
    print(f"  数据库总量: {len(db['patents'])} 篇")
    has_claims = sum(1 for p in db["patents"].values() if p.get("has_claims"))
    print(f"  有权利要求: {has_claims} 篇")
    print(f"{'=' * 50}")


def main():
    parser = argparse.ArgumentParser(description="BigQuery 专利数据获取")
    parser.add_argument("--query", action="store_true", help="直接执行 BigQuery 查询")
    parser.add_argument("--import", dest="import_file", help="导入导出的 JSON 文件")
    parser.add_argument("--sql", action="store_true", help="仅打印 SQL（用于网页端）")
    args = parser.parse_args()

    if args.sql:
        print("=" * 60)
        print("电力行业专利 SQL (复制到 BigQuery 网页端运行):")
        print("=" * 60)
        print(POWER_SQL)
        print("\n" + "=" * 60)
        print("管道检测机器人专利 SQL:")
        print("=" * 60)
        print(PIPELINE_SQL)
        print("\n导出方式: 运行后点击 '保存结果' → 'JSON 下载'")
        return

    if args.import_file:
        rows = import_json(args.import_file)
        if rows:
            merge_to_database(rows)
        return

    if args.query:
        all_rows = []

        # 查询电力方向
        rows = query_bigquery(POWER_SQL, "电力行业 (H02J/H02H/H02B/H02G/H02S)")
        if rows:
            all_rows.extend(rows)

        time.sleep(2)

        # 查询管道方向
        rows = query_bigquery(PIPELINE_SQL, "管道检测机器人")
        if rows:
            all_rows.extend(rows)

        if all_rows:
            # 保存原始数据
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            export_file = EXPORT_DIR / f"bigquery_{datetime.now():%Y%m%d_%H%M%S}.json"
            with open(export_file, "w", encoding="utf-8") as f:
                json.dump(all_rows, f, ensure_ascii=False)
            print(f"\n原始数据已保存: {export_file}")

            # 导入数据库
            merge_to_database(all_rows)
        return

    # 默认: 打印帮助
    parser.print_help()
    print("\n快速开始:")
    print("  1. python scripts/bigquery_patents.py --sql")
    print("     → 复制 SQL 到 https://console.cloud.google.com/bigquery 运行")
    print("     → 导出 JSON 文件")
    print("  2. python scripts/bigquery_patents.py --import 导出文件.json")
    print("     → 自动导入数据库")


if __name__ == "__main__":
    main()
