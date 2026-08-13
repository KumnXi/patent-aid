"""CORE 学术论文发现：搜索电力/管道检测方向论文，落知识库并进 RAG

原理：
- 专利库（data/patent_database）覆盖已授权专利，但缺学术前沿研究
- CORE API v3 抓取电力 + 管道检测方向的论文（标题/摘要/元数据）
- 论文落 data/knowledge_base/papers/（markdown）+ papers_index.json（索引）
- --db 时把论文块并入 RAG 索引（source=core_paper），与专利一起检索

产出：
- data/knowledge_base/papers/{id}.md         每篇论文 markdown
- data/knowledge_base/papers_index.json      全部论文索引
- --db 后 RAG 索引含论文块（engine.query() 可检索到）

用法：
    python scripts/paper_discover.py                    # 搜索+落库
    python scripts/paper_discover.py --dry-run          # 只搜索不落库（验证连通）
    python scripts/paper_discover.py --query "virtual power plant" --limit 20
    python scripts/paper_discover.py --db               # 落库后重建 RAG 索引
"""

import argparse
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.paper_search import create_core_client

PROJECT_ROOT = Path(__file__).parent.parent
PAPERS_DIR = PROJECT_ROOT / "data" / "knowledge_base" / "papers"
INDEX_PATH = PROJECT_ROOT / "data" / "knowledge_base" / "papers_index.json"

# 默认搜索关键词（管道检测 + 电力）
DEFAULT_QUERIES = [
    "pipeline inspection robot defect detection",
    "pipeline defect detection deep learning",
    "pipeline remaining useful life assessment",
    "submarine pipeline inspection robot",
    "gas pipeline leak detection sensor",
    "virtual power plant scheduling optimization",
    "power cable tunnel inspection robot",
    "photovoltaic power forecasting",
]


def load_existing_index() -> dict:
    """加载已有论文索引（增量去重用）"""
    if not INDEX_PATH.exists():
        return {"papers": []}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"papers": []}
    except (json.JSONDecodeError, OSError):
        return {"papers": []}


def save_papers(papers: list, queries: list, dry_run: bool = False) -> int:
    """合并保存论文（按 id 去重）到 papers/ 与 papers_index.json

    Args:
        papers: 新检索到的论文列表
        queries: 本次查询词
        dry_run: 只打印不落盘

    Returns:
        新增论文数（非 dry_run 时返回 0 表示仅预览）
    """
    if dry_run:
        print(f"\n[dry-run] 检索到 {len(papers)} 篇（未落盘）")
        return 0

    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_existing_index()
    known = {str(p.get("id")) for p in existing.get("papers", [])}

    added = 0
    for p in papers:
        pid = str(p.get("id"))
        if pid in known:
            continue
        known.add(pid)
        p["source"] = "core_paper"
        p["crawled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        existing["papers"].append(p)
        added += 1

        # 落 markdown
        md = _paper_to_markdown(p)
        (PAPERS_DIR / f"{pid}.md").write_text(md, encoding="utf-8")

    existing["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    existing["source"] = "core"
    existing["count"] = len(existing["papers"])
    existing["queries"] = list(dict.fromkeys(existing.get("queries", []) + queries))
    INDEX_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n新增 {added} 篇，累计 {len(existing['papers'])} 篇")
    return added


def _paper_to_markdown(p: dict) -> str:
    """论文 dict → 知识库 markdown"""
    lines = [f"# {p.get('title', '')}", ""]
    lines.append(f"- 作者: {', '.join(p.get('authors', []) or [])}")
    lines.append(f"- 年份: {p.get('year', '')}")
    lines.append(f"- 期刊/会议: {p.get('venue', '')}")
    lines.append(f"- DOI: {p.get('doi', '')}")
    lines.append(f"- 来源: CORE API v3 (id={p.get('id')})")
    lines.append("")
    lines.append("## 摘要")
    lines.append(p.get("abstract", ""))
    lines.append("")
    return "\n".join(lines)


def rebuild_rag_db():
    """把论文并入 RAG 索引（重建专利索引 + 追加论文块 + 落盘）"""
    print("\n" + "=" * 60)
    print("  重建 RAG 索引（含论文语料）")
    print("=" * 60)
    from src.core import PatentInnovationEngine
    engine = PatentInnovationEngine()
    engine.initialize(force_rebuild=True)   # 重建专利索引，末尾自动追加论文块
    engine.rag_engine.save_index()          # 连同论文块一起落盘
    stats = engine.rag_engine.get_statistics()
    print(f"RAG 索引: {stats['total_chunks']} 块")
    # 抽查：论文能否被检索到
    for q in ["pipeline defect detection", "virtual power plant"]:
        hits = engine.rag_engine.retrieve(q, top_k=3)
        papers = [h for h in hits
                  if h.chunk.metadata.get("source") == "core_paper"]
        print(f"  查询「{q}」: {len(hits)} 命中, 其中论文 {len(papers)} 篇")
        for p in papers[:2]:
            print(f"    · {p.chunk.metadata.get('title', '')[:60]}")


def main():
    parser = argparse.ArgumentParser(description="CORE 学术论文发现")
    parser.add_argument("--query", default="", help="搜索关键词（留空用默认多组）")
    parser.add_argument("--limit", type=int, default=10, help="每组返回条数")
    parser.add_argument("--year-from", type=int, default=0,
                        help="只取该年份及以后（默认不限）")
    parser.add_argument("--dry-run", action="store_true", help="只搜索不落盘")
    parser.add_argument("--db", action="store_true",
                        help="落库后重建 RAG 索引（含论文块）")
    args = parser.parse_args()

    client = create_core_client()
    if not client.is_available():
        print("CORE 未配置 api_key，请填入 config/api_config.json 的 core.api_key")
        return

    queries = [args.query] if args.query else DEFAULT_QUERIES
    all_papers = []
    mode = "dry-run" if args.dry_run else "落库"
    print("=" * 60)
    print(f"CORE 论文发现（{mode}）")
    print("=" * 60)

    for q in queries:
        print(f"\n搜索: {q}")
        try:
            papers = client.search(q, limit=args.limit,
                                   year_from=args.year_from or None)
            if not papers:
                print("  无结果")
                continue
            print(f"  命中 {len(papers)} 篇")
            for p in papers[:args.limit]:
                year = p.get("year") or "?"
                print(f"    · [{year}] {(p.get('title') or '')[:55]}")
            all_papers.extend(papers)
        except Exception as e:
            print(f"  失败: {e}")
        time.sleep(1)  # 限流

    save_papers(all_papers, queries, dry_run=args.dry_run)

    if args.db:
        rebuild_rag_db()


if __name__ == "__main__":
    main()
