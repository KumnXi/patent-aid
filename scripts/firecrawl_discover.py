"""Firecrawl 领域发现：搜索专利/论文/报告，拓展文档数据库

原理：
- Google Patents 详情页对 Firecrawl 有 JS 反爬（拿不到全文）
- 但 Firecrawl 的 search 发现能力很强（能找到 Google/WIPO/论文/报告）
- 因此：Firecrawl 负责"发现"，专利全文用 xhr 通道（fast_crawl）抓取入库

产出：
- data/target_patents_firecrawl.json：发现的新专利号（喂给 fast_crawl 抓全文）
- data/knowledge_base/：抓取的非专利资料（论文/报告/综述 markdown）

用法：
    python scripts/firecrawl_discover.py [--query 关键词] [--limit 条数] [--fetch-docs]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.firecrawl import create_firecrawl_client

PROJECT_ROOT = Path(__file__).parent.parent
TARGET_PATH = PROJECT_ROOT / "data" / "target_patents_firecrawl.json"
KB_DIR = PROJECT_ROOT / "data" / "knowledge_base"

# 默认搜索关键词（管道检测 + 电力）
DEFAULT_QUERIES = [
    "管道检测机器人 缺陷识别 专利",
    "管道检测 剩余寿命 评估 专利",
    "海底管道 检测 机器人 专利",
    "燃气管道 泄漏 检测 专利",
    "电力电缆 隧道 巡检 机器人 专利",
]

# 通用专利号：CN / WO（对 URL + 标题 + 描述全量匹配）
PATENT_ID_RE = re.compile(
    r"(CN\s?\d{6,9}\s?[ABU])|(WO\s?\d{4}/\s?\d+)", re.IGNORECASE)


def extract_patent_ids(results: list) -> list:
    """从搜索结果（URL/标题/描述）提取专利号"""
    ids = set()
    for r in results:
        if not isinstance(r, dict):
            continue
        for field in ("url", "title", "description"):
            text = r.get(field, "") or ""
            for m in PATENT_ID_RE.finditer(text):
                pid = (m.group(1) or m.group(2) or "").replace(" ", "").upper()
                if pid:
                    ids.add(pid)
    return sorted(ids)


def main():
    parser = argparse.ArgumentParser(description="Firecrawl 领域发现")
    parser.add_argument("--query", default="", help="搜索关键词（留空用默认多组）")
    parser.add_argument("--limit", type=int, default=10, help="每组返回条数")
    parser.add_argument("--fetch-docs", action="store_true",
                        help="同时抓取非专利文档到 knowledge_base/")
    args = parser.parse_args()

    fc = create_firecrawl_client()
    if not fc.is_available():
        print("Firecrawl 未配置 api_key，请填入 config/api_config.json 的 firecrawl.api_key")
        return

    queries = [args.query] if args.query else DEFAULT_QUERIES
    patent_ids = set()
    doc_links = []

    print("=" * 60)
    print("Firecrawl 领域发现")
    print("=" * 60)
    for q in queries:
        print(f"\n搜索: {q}")
        try:
            results = fc.search(q, limit=args.limit)
            if not results:
                print("  无结果")
                continue
            ids = extract_patent_ids(results)
            patent_ids.update(ids)
            print(f"  结果 {len(results)} 条, 发现专利 {len(ids)} 个")
            for r in results[:args.limit]:
                url = r.get("url", "")
                title = (r.get("title") or "")[:50]
                if url:
                    print(f"    · {title} [{url[:60]}]")
                    if "patents.google" not in url and "patentscope" not in url:
                        doc_links.append({"url": url, "title": title})
        except Exception as e:
            print(f"  失败: {e}")
        time.sleep(1)

    # 输出专利发现（供 fast_crawl 抓全文）
    print(f"\n{'='*60}")
    print(f"发现专利总数: {len(patent_ids)}")
    for pid in sorted(patent_ids):
        print(f"  {pid}")
    TARGET_PATH.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "patents": sorted(patent_ids),
        "queries": queries,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n专利清单已保存: {TARGET_PATH}")
    print(f"  可用 fast_crawl.py 抓取这些专利全文入库（xhr通道）")

    # 可选：抓取文档到知识库
    if args.fetch_docs and doc_links:
        KB_DIR.mkdir(parents=True, exist_ok=True)
        print(f"\n抓取 {len(doc_links)} 篇文档到知识库...")
        for i, doc in enumerate(doc_links, 1):
            try:
                md = fc.scrape_markdown(doc["url"])
                if md and len(md) > 200:
                    name = re.sub(r'[^\w一-鿿\- ]', '', doc["title"] or f"doc{i}")[:40]
                    fname = f"{i:03d}_{name}.md"
                    (KB_DIR / fname).write_text(md, encoding="utf-8")
                    print(f"  ✓ {fname} ({len(md)}字符)")
                else:
                    print(f"  · {doc['title'][:30]} 内容过短，跳过")
            except Exception as e:
                print(f"  ✗ {doc['title'][:30]}: {e}")
            time.sleep(1)
        print(f"\n知识库目录: {KB_DIR}")


if __name__ == "__main__":
    main()
