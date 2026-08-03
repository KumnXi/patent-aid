"""数据库去重与质量评分工具

功能:
1. 检测并合并重复专利（基于标题相似度 + 专利号去重）
2. 对每篇专利的文本质量打分（完整性、清晰度、长度）
3. 输出质量报告

使用方式:
    D:/Anaconda3/envs/mathmodel/python.exe scripts/db_quality.py
"""

import sys
import io
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / "data" / "patent_database" / "index.json"


def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    db["metadata"]["updated"] = datetime.now().isoformat()
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════
# 1. 去重检测
# ═══════════════════════════════════════════════════════

def normalize_title(title: str) -> str:
    """标题归一化：去除专利号前缀、空格、标点"""
    if not title:
        return ""
    # 去除常见前缀
    title = re.sub(r'^CN\d+[A-Z]\s*[-–]\s*', '', title)
    # 去除尾部 " - Google Patents" 等
    title = re.sub(r'\s*-\s*(Google Patents|专利)$', '', title)
    # 去除空白
    title = re.sub(r'\s+', '', title)
    return title.lower()


def detect_duplicates(db: dict) -> list:
    """检测重复专利
    
    Returns:
        重复组列表，每组包含重复的专利ID
    """
    # 策略1: 标题完全相同
    title_groups = defaultdict(list)
    for pid, patent in db["patents"].items():
        norm_title = normalize_title(patent.get("title", ""))
        if norm_title:
            title_groups[norm_title].append(pid)
    
    duplicates = []
    for norm_title, pids in title_groups.items():
        if len(pids) > 1:
            duplicates.append({
                "title": norm_title,
                "patents": pids,
                "reason": "标题完全相同"
            })
    
    return duplicates


def merge_duplicates(db: dict, duplicates: list) -> dict:
    """合并重复专利（保留信息最完整的）
    
    Returns:
        合并统计
    """
    removed = []
    
    for dup in duplicates:
        pids = dup["patents"]
        patents = [(pid, db["patents"].get(pid, {})) for pid in pids]
        
        # 评分：选择信息最完整的保留
        scores = []
        for pid, p in patents:
            score = 0
            if p.get("claims"): score += 3
            if p.get("description"): score += 3
            if p.get("has_claims"): score += 1
            if p.get("has_description"): score += 1
            if p.get("ipc"): score += 1
            if p.get("summary"): score += 1
            scores.append((score, pid))
        
        # 按分数降序，保留第一个
        scores.sort(reverse=True)
        keep_pid = scores[0][1]
        
        for score, pid in scores[1:]:
            removed.append(pid)
            # 合并信息到保留的专利
            keep_patent = db["patents"][keep_pid]
            merge_patent = db["patents"][pid]
            for key in ["claims", "description", "ipc", "summary"]:
                if not keep_patent.get(key) and merge_patent.get(key):
                    keep_patent[key] = merge_patent[key]
            
            del db["patents"][pid]
    
    return {"removed": len(removed), "removed_ids": removed}


# ═══════════════════════════════════════════════════════
# 2. 质量评分
# ═══════════════════════════════════════════════════════

def score_patent(patent: dict) -> dict:
    """对单篇专利评分
    
    评分维度:
    - 完整性 (0-40): 有权利要求+说明书+摘要+IPC
    - 文本长度 (0-30): 权利要求和说明书的长度
    - 清晰度 (0-30): 无乱码、有结构
    """
    scores = {}
    
    # 完整性 (0-40)
    completeness = 0
    if patent.get("claims"): completeness += 15
    if patent.get("description"): completeness += 15
    if patent.get("summary"): completeness += 5
    if patent.get("ipc"): completeness += 5
    scores["completeness"] = completeness
    
    # 文本长度 (0-30)
    claims_len = len(patent.get("claims", ""))
    desc_len = len(patent.get("description", ""))
    length_score = 0
    if claims_len > 500: length_score += 10
    elif claims_len > 100: length_score += 5
    if desc_len > 2000: length_score += 10
    elif desc_len > 500: length_score += 5
    if claims_len > 2000: length_score += 5
    if desc_len > 5000: length_score += 5
    scores["text_length"] = min(length_score, 30)
    
    # 清晰度 (0-30)
    clarity = 0
    claims_text = patent.get("claims", "")
    desc_text = patent.get("description", "")
    
    # 检查乱码（连续非中文非ASCII字符）
    garbled = bool(re.search(r'[\x80-\xff]{5,}', claims_text + desc_text))
    if not garbled:
        clarity += 15
    else:
        clarity -= 10
    
    # 检查结构（有"权利要求"、"步骤"等关键词）
    structure_keywords = ["权利要求", "步骤", "所述", "其特征在于", "实施例"]
    structure_count = sum(1 for kw in structure_keywords if kw in claims_text + desc_text)
    clarity += min(structure_count * 3, 15)
    
    scores["clarity"] = max(clarity, 0)
    
    # 总分
    scores["total"] = scores["completeness"] + scores["text_length"] + scores["clarity"]
    
    # 等级
    total = scores["total"]
    if total >= 80:
        scores["grade"] = "A"
    elif total >= 60:
        scores["grade"] = "B"
    elif total >= 40:
        scores["grade"] = "C"
    else:
        scores["grade"] = "D"
    
    return scores


def run_quality_analysis(db: dict) -> dict:
    """运行完整质量分析"""
    all_scores = {}
    grade_dist = defaultdict(int)
    
    for pid, patent in db["patents"].items():
        scores = score_patent(patent)
        all_scores[pid] = scores
        grade_dist[scores["grade"]] += 1
    
    # 统计
    total = len(all_scores)
    avg_score = sum(s["total"] for s in all_scores.values()) / max(total, 1)
    
    # 按等级排序的差专利
    worst = sorted(all_scores.items(), key=lambda x: x[1]["total"])[:10]
    
    return {
        "total_patents": total,
        "average_score": round(avg_score, 1),
        "grade_distribution": dict(grade_dist),
        "worst_patents": [(pid, s["total"], s["grade"]) for pid, s in worst],
        "all_scores": all_scores,
    }


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  数据库去重与质量评分")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    db = load_db()
    total = len(db["patents"])
    print(f"\n数据库: {total} 篇专利\n")
    
    # ── 去重 ──
    print("--- 1. 去重检测 ---")
    duplicates = detect_duplicates(db)
    
    if duplicates:
        print(f"发现 {len(duplicates)} 组重复:")
        for dup in duplicates[:5]:
            print(f"  标题: {dup['title'][:40]}... 专利: {dup['patents']}")
        
        result = merge_duplicates(db, duplicates)
        print(f"\n合并结果: 移除 {result['removed']} 篇重复")
        if result["removed_ids"]:
            for pid in result["removed_ids"][:5]:
                print(f"  移除: {pid}")
        
        save_db(db)
        print("数据库已更新")
    else:
        print("未发现重复专利")
    
    # ── 质量评分 ──
    print(f"\n--- 2. 质量评分 ---")
    analysis = run_quality_analysis(db)
    
    print(f"总专利: {analysis['total_patents']}")
    print(f"平均分: {analysis['average_score']}")
    print(f"等级分布:")
    for grade in ["A", "B", "C", "D"]:
        count = analysis["grade_distribution"].get(grade, 0)
        pct = count / max(analysis["total_patents"], 1) * 100
        bar = "█" * int(pct / 5)
        print(f"  {grade}: {count:4d} ({pct:5.1f}%) {bar}")
    
    print(f"\n最低分专利:")
    for pid, score, grade in analysis["worst_patents"][:5]:
        title = db["patents"].get(pid, {}).get("title", "")[:30]
        print(f"  [{grade} {score}分] {pid}: {title}")
    
    # ── 保存评分 ──
    scores_file = project_root / "data" / "patent_database" / "quality_scores.json"
    # 保存精简版（不保存all_scores避免文件太大）
    save_data = {
        "generated_at": datetime.now().isoformat(),
        "total_patents": analysis["total_patents"],
        "average_score": analysis["average_score"],
        "grade_distribution": analysis["grade_distribution"],
        "worst_patents": analysis["worst_patents"],
    }
    with open(scores_file, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n评分已保存: {scores_file}")
    
    # 将评分写入每篇专利的字段
    for pid, scores in analysis["all_scores"].items():
        if pid in db["patents"]:
            db["patents"][pid]["quality_score"] = scores["total"]
            db["patents"][pid]["quality_grade"] = scores["grade"]
    save_db(db)
    print("质量评分已写入数据库")
    
    print(f"\n{'='*60}")
    print(f"完成! 去重: {len(duplicates)}组, 平均质量: {analysis['average_score']}分")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
