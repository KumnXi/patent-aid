"""交底书生成历史管理

每次生成的交底书保存到 data/disclosure_history/ 目录：
- {id}.md   交底书全文
- {id}.json 元信息（想法、模式、质检报告、时间）

提供列表/详情/删除接口供 app.py 调用。
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_DIR = PROJECT_ROOT / "data" / "disclosure_history"


def _ensure_dir():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _safe_title(title: str) -> str:
    """生成文件名安全的标题片段"""
    safe = re.sub(r"[^\w\u4e00-\u9fff\-. ]", "", title or "交底书")
    return safe.strip()[:30] or "交底书"


def save_disclosure(idea: str, disclosure: str, mode: str,
                    title: str = None,
                    quality_report: Optional[Dict] = None) -> str:
    """保存一次生成结果

    Args:
        idea: 原始技术想法
        disclosure: 交底书全文
        mode: 生成模式（llm_staged/llm_single/template）
        title: 发明名称
        quality_report: 质检报告（可选）

    Returns:
        历史记录 ID
    """
    _ensure_dir()
    ts = datetime.now()
    record_id = f"{ts.strftime('%Y%m%d_%H%M%S')}_{_safe_title(title)}"

    # 同名冲突时追加序号
    md_path = HISTORY_DIR / f"{record_id}.md"
    n = 1
    while md_path.exists():
        record_id = f"{ts.strftime('%Y%m%d_%H%M%S')}_{_safe_title(title)}_{n}"
        md_path = HISTORY_DIR / f"{record_id}.md"
        n += 1

    md_path.write_text(disclosure, encoding="utf-8")

    meta = {
        "id": record_id,
        "created_at": ts.isoformat(),
        "idea": idea[:500],
        "title": title or "",
        "mode": mode,
        "word_count": len(disclosure.replace(" ", "").replace("\n", "")),
        "quality_report": quality_report,
    }
    (HISTORY_DIR / f"{record_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record_id


def list_history(limit: int = 50) -> List[Dict]:
    """列出历史记录（按时间倒序，不含全文）"""
    _ensure_dir()
    records = []
    for meta_file in HISTORY_DIR.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            records.append(meta)
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return records[:limit]


def get_history(record_id: str) -> Optional[Dict]:
    """获取单条历史记录详情（含全文）"""
    _ensure_dir()
    # 防止路径穿越
    if not re.match(r"^[\w\u4e00-\u9fff\-. ]+$", record_id):
        return None
    md_path = HISTORY_DIR / f"{record_id}.md"
    meta_path = HISTORY_DIR / f"{record_id}.json"
    if not md_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["disclosure"] = md_path.read_text(encoding="utf-8")
        return meta
    except (json.JSONDecodeError, OSError):
        return None


def delete_history(record_id: str) -> bool:
    """删除一条历史记录"""
    _ensure_dir()
    if not re.match(r"^[\w\u4e00-\u9fff\-. ]+$", record_id):
        return False
    deleted = False
    for suffix in [".md", ".json"]:
        path = HISTORY_DIR / f"{record_id}{suffix}"
        if path.exists():
            path.unlink()
            deleted = True
    return deleted
