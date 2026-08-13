"""检索质量抽查：数据库搭建后验证 RAG 对核心领域查询的命中质量

用法: python scripts/check_retrieval.py
"""

import sys
import io
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.rag_engine import RAGEngine

# 核心业务查询（管道 + 电力）
QUERIES = [
    "管道缺陷检测与识别",
    "管道机器人行走机构",
    "管道泄漏检测",
    "焊缝缺陷超声检测",
    "高压电缆隧道巡检机器人",
    "虚拟电厂调度与负荷预测",
    "配电网故障定位与自愈",
    "储能系统电池均衡管理",
    "变压器状态监测与故障诊断",
    "继电保护整定计算方法",
]


def main():
    rag = RAGEngine(str(ROOT / "data" / "rag_index"))
    rag.load_index()
    stats = rag.get_statistics()
    print("=" * 70)
    print(f"RAG 索引: {stats['total_chunks']} 文档块 / {stats['patents_indexed']} 专利")
    print("=" * 70)

    total_hits = 0
    for q in QUERIES:
        results = rag.retrieve(q, top_k=5)
        # 统计 top5 中标题/文本包含查询关键词的命中数
        hits = 0
        print(f"\n查询: {q}")
        for r in results:
            c = r.chunk
            title = (c.metadata.get("title", "") if isinstance(c.metadata, dict) else "") or ""
            text = (c.text or "")[:80].replace("\n", " ")
            score = r.score
            # 简单相关性判断：标题或正文含查询词
            related = any(k in (title + text) for k in q[:4].split()) or any(k in (title + text) for k in q)
            if related:
                hits += 1
            mark = "✓" if related else "·"
            print(f"  [{score:.3f}] {mark} {c.patent_id} {c.section_type} {title[:36]}")
        total_hits += hits
        print(f"  → 相关命中 {hits}/5")

    print("\n" + "=" * 70)
    print(f"总相关命中: {total_hits}/{len(QUERIES) * 5}")
    print("=" * 70)


if __name__ == "__main__":
    main()
