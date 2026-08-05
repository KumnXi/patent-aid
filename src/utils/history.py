"""交底书生成历史管理

每次生成的交底书保存到 data/disclosure_history/ 目录：
- {id}.md.enc    交底书全文（AES 加密，Fernet）
- {id}.json.enc  元信息（想法、模式、质检报告、时间，加密）
- 兼容旧的 {id}.md / {id}.json 明文（读取时自动识别）

加密密钥保存在 data/.secret.key（首次自动生成，勿泄露/丢失，丢失则历史不可恢复）。

安全：get_history/delete_history 使用 _is_safe_id() 严格校验 record_id，
      拒绝路径穿越字符（\\ / ..），并验证解析后文件仍在 HISTORY_DIR 内。
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HISTORY_DIR = PROJECT_ROOT / "data" / "disclosure_history"
KEY_PATH = PROJECT_ROOT / "data" / ".secret.key"


def _ensure_dir():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════
# 加解密
# ═══════════════════════════════════════════════════════════

def _get_key() -> bytes:
    """获取或创建 Fernet 密钥（存 data/.secret.key）"""
    if not KEY_PATH.exists():
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEY_PATH.write_bytes(Fernet.generate_key())
        # 限制权限（POSIX 有效；Windows 尽力）
        try:
            KEY_PATH.chmod(0o600)
        except OSError:
            pass
    return KEY_PATH.read_bytes()


def _encrypt_text(text: str) -> bytes:
    return Fernet(_get_key()).encrypt(text.encode("utf-8"))


def _decrypt_token(token: bytes) -> str:
    return Fernet(_get_key()).decrypt(token).decode("utf-8")


def _read_text(path: Path) -> str:
    """读取历史文件：.enc 直接解密；明文路径优先 .enc，否则读明文"""
    if str(path).endswith(".enc"):
        # 本身就是加密文件 → 直接解密
        try:
            return _decrypt_token(path.read_bytes())
        except (InvalidToken, OSError):
            return ""
    enc = path.with_suffix(path.suffix + ".enc")
    if enc.exists():
        try:
            return _decrypt_token(enc.read_bytes())
        except (InvalidToken, OSError):
            return ""  # 密钥不匹配/损坏
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _write_text(path: Path, text: str):
    """写入历史文件（加密到 .enc）"""
    _ensure_dir()
    enc = path.with_suffix(path.suffix + ".enc")
    enc.write_bytes(_encrypt_text(text))


def _delete_file(path: Path):
    """删除文件（含加密/明文两种形态）"""
    for p in (path, path.with_suffix(path.suffix + ".enc")):
        if p.exists():
            p.unlink()


def _safe_title(title: str) -> str:
    """生成文件名安全的标题片段"""
    safe = re.sub(r"[^\w一-鿿\-. ]", "", title or "交底书")
    return safe.strip()[:30] or "交底书"


def _is_safe_id(record_id: str) -> bool:
    """检查 record_id 是否合法且无路径穿越

    合法格式：YYYYMMDD_HHMMSS_{标题}（字母/数字/中文/下划线/连字符/点/空格）。
    拒绝反斜杠、正斜杠、.. 等路径穿越字符，并验证解析后文件仍在 HISTORY_DIR 内。
    """
    if not re.match(r"^[\d]{8}_[\d]{6}_[\w一-鿿\-. ]+$", record_id):
        return False
    # 拒绝任何路径分隔符
    if "\\" in record_id or "/" in record_id or ".." in record_id:
        return False
    # 解析后确认文件落在 HISTORY_DIR 内，防止符号链接等绕过
    for suffix in [".md", ".json"]:
        resolved = (HISTORY_DIR / f"{record_id}{suffix}").resolve()
        if not str(resolved).startswith(str(HISTORY_DIR.resolve())):
            return False
    return True


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
    while _file_exists(md_path):
        record_id = f"{ts.strftime('%Y%m%d_%H%M%S')}_{_safe_title(title)}_{n}"
        md_path = HISTORY_DIR / f"{record_id}.md"
        n += 1

    _write_text(md_path, disclosure)

    meta = {
        "id": record_id,
        "created_at": ts.isoformat(),
        "idea": idea[:500],
        "title": title or "",
        "mode": mode,
        "word_count": len(disclosure.replace(" ", "").replace("\n", "")),
        "quality_report": quality_report,
    }
    _write_text(HISTORY_DIR / f"{record_id}.json",
                json.dumps(meta, ensure_ascii=False, indent=2))
    return record_id


def _file_exists(path: Path) -> bool:
    """检查文件是否存在（含加密形态）"""
    return path.exists() or path.with_suffix(path.suffix + ".enc").exists()


def _iter_history_files():
    """遍历历史记录文件（加密 .json.enc + 兼容旧明文 .json）"""
    seen = set()
    for enc in HISTORY_DIR.glob("*.json.enc"):
        yield enc
        seen.add(enc.stem)  # {id}.json.enc → stem 为 {id}.json
    for plain in HISTORY_DIR.glob("*.json"):
        if plain.stem not in seen:
            yield plain


def list_history(limit: int = 50) -> List[Dict]:
    """列出历史记录（按时间倒序，不含全文）"""
    _ensure_dir()
    records = []
    for meta_file in _iter_history_files():
        try:
            text = _read_text(meta_file)
            if not text:
                continue
            meta = json.loads(text)
            records.append(meta)
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return records[:limit]


def get_history(record_id: str) -> Optional[Dict]:
    """获取单条历史记录详情（含全文）"""
    _ensure_dir()
    if not _is_safe_id(record_id):
        return None
    md_path = HISTORY_DIR / f"{record_id}.md"
    meta_path = HISTORY_DIR / f"{record_id}.json"
    if not _file_exists(md_path) or not _file_exists(meta_path):
        return None
    try:
        meta = json.loads(_read_text(meta_path))
        meta["disclosure"] = _read_text(md_path)
        return meta
    except (json.JSONDecodeError, OSError):
        return None


def delete_history(record_id: str) -> bool:
    """删除一条历史记录"""
    _ensure_dir()
    if not _is_safe_id(record_id):
        return False
    deleted = False
    for suffix in [".md", ".json"]:
        _delete_file(HISTORY_DIR / f"{record_id}{suffix}")
        # 若明文/加密存在则视为已删除
        if _file_exists(HISTORY_DIR / f"{record_id}{suffix}"):
            continue
        deleted = True
    return deleted


def migrate_legacy() -> int:
    """把旧的明文历史（.md/.json）迁移为加密存储（.enc）

    Returns:
        迁移的记录数
    """
    migrated = 0
    for suffix in [".md", ".json"]:
        for plain in HISTORY_DIR.glob(f"*{suffix}"):
            if not plain.exists():
                continue
            enc = plain.with_suffix(plain.suffix + ".enc")
            if enc.exists():
                continue  # 已加密
            try:
                _write_text(plain, plain.read_text(encoding="utf-8"))
            except OSError:
                continue
            migrated += 1
            # 迁移成功后删除明文
            try:
                plain.unlink()
            except OSError:
                pass
    return migrated
