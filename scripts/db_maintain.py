"""专利数据库治理脚本

功能：
1. 字段规范化（日期、IPC、申请人、摘要提取）
2. 同族去重（A/B 版本保留 B 版）
3. 标题近似重复检测（相似度 > 0.85，生成报告供人工确认）
4. 质量报告输出

用法：
    python scripts/db_maintain.py            # 规范化 + 同族去重 + 报告（自动写回）
    python scripts/db_maintain.py --dry-run  # 只分析不写回
    python scripts/db_maintain.py --remove-similar  # 额外删除标题近似重复（谨慎）

建议先备份：脚本会自动创建备份。
"""

import json
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "patent_database" / "index.json"
REPORT_PATH = PROJECT_ROOT / "data" / "patent_database" / "quality_report.json"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def title_bigrams(title: str) -> set:
    """标题中文 bigram 集合"""
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]+", title))
    grams = {chinese[i:i + 2] for i in range(len(chinese) - 1)}
    grams.update(re.findall(r"[A-Za-z0-9]{2,}", title.lower()))
    return grams


def similarity(a: str, b: str) -> float:
    """bigram Jaccard 相似度"""
    ga, gb = title_bigrams(a), title_bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def normalize_date(raw) -> str:
    """规范化日期为 YYYY-MM-DD，失败返回空串"""
    s = str(raw or "").strip()
    if DATE_RE.match(s):
        return s
    # YYYYMMDD（BigQuery 格式）
    if re.match(r"^\d{8}$", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # YYYY年MM月DD日
    m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def normalize_ipc(raw) -> list:
    """IPC 统一为字符串列表"""
    if not raw:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = re.split(r"[;；,，、\s]+", str(raw))
    return sorted({i.strip() for i in items if i.strip()})


def extract_abstract(description: str) -> str:
    """从说明书提取摘要（首个实质性段落，限 300 字）"""
    if not description:
        return ""
    # 去掉常见开头标记
    text = re.sub(r"^说明书\s*", "", description.strip())
    text = re.sub(r"^(技术领域|背景技术)\s*", "", text.strip())
    # 取第一个超过 50 字的段落
    for para in re.split(r"\n+", text):
        para = para.strip()
        if len(para) >= 50:
            return para[:300]
    return text[:300] if text else ""


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def main():
    dry_run = "--dry-run" in sys.argv
    remove_similar = "--remove-similar" in sys.argv

    with open(DB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    patents = data.get("patents", {})
    print(f"数据库加载完成: {len(patents)} 篇")

    # ── 1. 字段规范化 ─────────────────────────────
    stats = {"date_fixed": 0, "date_invalid": 0, "ipc_normalized": 0,
             "applicant_trimmed": 0, "abstract_added": 0}

    for pid, p in patents.items():
        # 日期
        new_date = normalize_date(p.get("application_date"))
        if new_date != (p.get("application_date") or ""):
            p["application_date"] = new_date
            stats["date_fixed"] += 1
        if not new_date:
            stats["date_invalid"] += 1

        # IPC
        new_ipc = normalize_ipc(p.get("ipc"))
        if new_ipc != p.get("ipc"):
            p["ipc"] = new_ipc
            stats["ipc_normalized"] += 1

        # 申请人
        applicant = str(p.get("applicant") or "").strip()
        if applicant != p.get("applicant"):
            p["applicant"] = applicant
            stats["applicant_trimmed"] += 1

        # 摘要
        if not p.get("abstract") and p.get("description"):
            abstract = extract_abstract(p["description"])
            if abstract:
                p["abstract"] = abstract
                stats["abstract_added"] += 1

    print(f"\n[规范化] 日期修正:{stats['date_fixed']} 无效日期:{stats['date_invalid']} "
          f"IPC规范:{stats['ipc_normalized']} 申请人清洗:{stats['applicant_trimmed']} "
          f"摘要补充:{stats['abstract_added']}")

    # ── 2. 同族去重（A/B 版保留 B）────────────────
    family_groups = {}
    for pid in patents:
        base = re.sub(r"[ABU]\d*$", "", pid)  # CN1234567A → CN1234567
        family_groups.setdefault(base, []).append(pid)

    family_removed = []
    for base, pids in family_groups.items():
        if len(pids) < 2:
            continue
        # 优先保留 B 版 > U 版 > A 版；数据更全的优先
        def rank(pid):
            p = patents[pid]
            content_score = bool(p.get("claims")) + bool(p.get("description"))
            suffix = "B" if pid.endswith("B") else ("U" if pid.endswith("U") else "A")
            return ({"B": 2, "U": 1, "A": 0}[suffix], content_score)
        pids.sort(key=rank, reverse=True)
        keep, dups = pids[0], pids[1:]
        for dup in dups:
            family_removed.append({"removed": dup, "kept": keep,
                                   "reason": "同族A/B版本"})
            if not dry_run:
                del patents[dup]

    print(f"[同族去重] 移除 {len(family_removed)} 篇（保留 B/U 版或数据更全者）")
    for item in family_removed[:10]:
        print(f"  - {item['removed']} → 保留 {item['kept']}")

    # ── 3. 标题近似重复检测 ───────────────────────
    pids = list(patents.keys())
    similar_pairs = []
    for i in range(len(pids)):
        ti = patents[pids[i]].get("title", "")
        if not ti:
            continue
        for j in range(i + 1, len(pids)):
            tj = patents[pids[j]].get("title", "")
            if not tj:
                continue
            sim = similarity(ti, tj)
            if sim > 0.85:
                similar_pairs.append({
                    "patent_a": pids[i], "title_a": ti,
                    "patent_b": pids[j], "title_b": tj,
                    "similarity": round(sim, 3),
                })

    print(f"[近似重复] 发现 {len(similar_pairs)} 对标题相似度>0.85")
    for pair in similar_pairs[:10]:
        print(f"  - {pair['patent_a']} vs {pair['patent_b']} "
              f"(sim={pair['similarity']})")

    if remove_similar and not dry_run:
        # 每对保留数据更全的一篇
        removed_similar = set()
        for pair in similar_pairs:
            a, b = pair["patent_a"], pair["patent_b"]
            if a in removed_similar or b in removed_similar:
                continue
            pa, pb = patents.get(a), patents.get(b)
            if not pa or not pb:
                continue
            sa = bool(pa.get("claims")) + bool(pa.get("description"))
            sb = bool(pb.get("claims")) + bool(pb.get("description"))
            victim = b if sa >= sb else a
            del patents[victim]
            removed_similar.add(victim)
        print(f"[近似去重] 额外移除 {len(removed_similar)} 篇")
    elif similar_pairs and not remove_similar:
        print("  （如需删除请加 --remove-similar 参数）")

    # ── 4. 质量报告 ──────────────────────────────
    ipc_counter = Counter()
    year_counter = Counter()
    applicant_counter = Counter()
    with_claims = with_desc = with_abstract = 0

    for p in patents.values():
        if p.get("claims"):
            with_claims += 1
        if p.get("description"):
            with_desc += 1
        if p.get("abstract"):
            with_abstract += 1
        for ipc in (p.get("ipc") or []):
            ipc_counter[ipc.split("/")[0]] += 1  # 统计到小类
        date = p.get("application_date") or ""
        if date:
            year_counter[date[:4]] += 1
        if p.get("applicant"):
            applicant_counter[p["applicant"]] += 1

    total = len(patents)
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_patents": total,
        "coverage": {
            "claims": round(with_claims / total * 100, 1) if total else 0,
            "description": round(with_desc / total * 100, 1) if total else 0,
            "abstract": round(with_abstract / total * 100, 1) if total else 0,
        },
        "normalization": stats,
        "family_dedup": family_removed,
        "similar_title_pairs": similar_pairs,
        "ipc_distribution": dict(ipc_counter.most_common(20)),
        "year_distribution": dict(sorted(year_counter.items())),
        "top_applicants": dict(applicant_counter.most_common(20)),
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[质量报告] 已输出到 {REPORT_PATH.name}")

    # ── 5. 写回（原子写入）────────────────────────
    if dry_run:
        print("\n[dry-run] 未写回数据库")
        return

    data["patents"] = patents
    data["metadata"]["total_patents"] = total
    data["metadata"]["updated"] = datetime.now().isoformat()
    data["metadata"]["last_maintenance"] = datetime.now().isoformat()

    tmp_path = DB_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    shutil.move(str(tmp_path), str(DB_PATH))
    print(f"[写回完成] 数据库现有 {total} 篇")


if __name__ == "__main__":
    main()
