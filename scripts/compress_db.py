"""数据库轻量化压缩工具

将大 JSON 文件压缩为 .gz（loader/rag_engine 已支持透明读取）：
  - data/patent_database/index.json  → index.json.gz（约 108MB → 16MB）
  - data/rag_index/rag_index.json    → rag_index.json.gz（约 69MB → 9MB）
  - data/knowledge_graph/knowledge_graph.json → .gz（约 5MB → 1MB）

用法:
    python scripts/compress_db.py                 # 压缩全部（保留原文件）
    python scripts/compress_db.py --delete        # 压缩后删除原文件（推荐，省磁盘）
    python scripts/compress_db.py --dry-run       # 只显示预计大小
    python scripts/compress_db.py --all           # 含历史备份一并压缩

注意:
    - 删除原文件前请确认 loader 已支持 gz（src/core/database_loader.py 已支持）
    - rag_engine 的 load_index 也会自动检测 gz
"""

import sys
import io
import gzip
import shutil
import argparse
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    ("data/patent_database/index.json", "data/patent_database/index.json.gz"),
    ("data/rag_index/rag_index.json", "data/rag_index/rag_index.json.gz"),
    ("data/knowledge_graph/knowledge_graph.json", "data/knowledge_graph/knowledge_graph.json.gz"),
]

EXTRA = [
    ("data/patent_database/index_backup_20260731.json", "data/patent_database/index_backup_20260731.json.gz"),
]


def compress(src: Path, dst: Path, level: int = 9) -> tuple:
    """压缩文件，返回 (原始大小, 压缩后大小)"""
    raw = src.stat().st_size
    with open(src, "rb") as fin, gzip.open(dst, "wb", compresslevel=level) as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 1024)
    comp = dst.stat().st_size
    return raw, comp


def main():
    parser = argparse.ArgumentParser(description="数据库压缩")
    parser.add_argument("--delete", action="store_true", help="压缩后删除原文件")
    parser.add_argument("--dry-run", action="store_true", help="只显示预计")
    parser.add_argument("--all", action="store_true", help="含历史备份")
    args = parser.parse_args()

    targets = TARGETS + (EXTRA if args.all else [])
    total_saved = 0

    for rel_src, rel_dst in targets:
        src = PROJECT_ROOT / rel_src
        dst = PROJECT_ROOT / rel_dst
        if not src.exists():
            print(f"[跳过] {rel_src} 不存在")
            continue
        raw = src.stat().st_size
        if args.dry_run:
            # 抽样估算压缩率
            with open(src, "rb") as f:
                sample = f.read(min(raw, 5 * 1024 * 1024))
            comp_ratio = len(gzip.compress(sample, 9)) / max(len(sample), 1)
            est = raw * comp_ratio
            print(f"[估算] {rel_src}: {raw/1024/1024:.1f} MB → ~{est/1024/1024:.1f} MB")
            continue
        raw_b, comp_b = compress(src, dst)
        saved = raw_b - comp_b
        total_saved += saved
        print(f"[压缩] {rel_src}: {raw_b/1024/1024:.1f} MB → {comp_b/1024/1024:.1f} MB (省 {saved/1024/1024:.1f} MB)")
        if args.delete:
            src.unlink()
            print(f"  [已删原文件] {rel_src}")

    if not args.dry_run:
        print(f"\n合计节省: {total_saved/1024/1024:.1f} MB")
        print("提示: 删除原文件后，loader/rag_engine 自动读 .gz（已验证支持）")


if __name__ == "__main__":
    main()
