"""CNIPA 专利公布公告批量爬取（免代理、官方免费）

数据流:
  搜索(IPC/关键词) → 著录信息入库 → 详情拿PDF链接 → 下载PDF → 解析全文入库

用法:
    python scripts/cnipa_crawl.py --ipc "F16L55/26"          # 单IPC
    python scripts/cnipa_crawl.py --group 管道检测机器人       # 按领域组
    python scripts/cnipa_crawl.py --all-groups                # 全部领域组
    python scripts/cnipa_crawl.py --query "管道检测机器人"     # 关键词
    python scripts/cnipa_crawl.py --limit 20 --dry-run        # 试跑只搜索
    python scripts/cnipa_crawl.py --skip-fulltext             # 只著录+IPC
    python scripts/cnipa_crawl.py --manual-captcha            # 人工输验证码

前置: pip install ddddocr；先跑 cnipa_probe.py 确认接口结构
"""

import sys
import io
import json
import time
import argparse
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "patent_database" / "index.json"
PROGRESS_PATH = PROJECT_ROOT / "data" / "patent_database" / "cnipa_progress.json"
PDF_DIR = PROJECT_ROOT / "data" / "patent_pdfs"
BASE = "https://epub.cnipa.gov.cn"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": BASE + "/",
    "Origin": BASE,
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}

REQUEST_INTERVAL = 2.0   # 秒/请求（官方源保守限速）
WORKERS = 3              # 并发线程
SAVE_EVERY = 10          # 每 N 篇保存
BACKOFF_LEVELS = [60, 120, 300]
CAPTCHA_RETRY = 3


# ═══════════════════════════════════════════════════════════
# 会话与验证码
# ═══════════════════════════════════════════════════════════

class CnipaSession:
    """带验证码处理与限速的会话"""

    def __init__(self, manual_captcha: bool = False):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.manual_captcha = manual_captcha
        self._lock = threading.Lock()
        self._last = 0.0
        self._ocr = None
        if not manual_captcha:
            try:
                import ddddocr
                self._ocr = ddddocr.DdddOcr(show_ad=False)
            except ImportError:
                print("[警告] ddddocr 未安装，将使用人工验证码模式")
                self.manual_captcha = True

    def wait(self):
        with self._lock:
            now = time.time()
            delta = now - self._last
            if delta < REQUEST_INTERVAL:
                time.sleep(REQUEST_INTERVAL - delta)
            self._last = time.time()

    def _get_captcha(self) -> str:
        """获取并识别验证码"""
        for attempt in range(CAPTCHA_RETRY):
            self.wait()
            resp = self.session.get(BASE + "/rest/checkCode", timeout=20)
            if resp.status_code != 200 or len(resp.content) < 500:
                continue
            img_path = PROJECT_ROOT / "output" / "cnipa_captcha.png"
            img_path.parent.mkdir(exist_ok=True)
            img_path.write_bytes(resp.content)
            if self._ocr is not None:
                code = self._ocr.classification(resp.content)
                if code:
                    return code
            else:
                # 人工输入
                print(f"验证码图片: {img_path.resolve()}")
                code = input("请输入验证码(4位): ").strip()
                if code:
                    return code
        raise RuntimeError("验证码获取/识别失败")

    def post_json(self, endpoint: str, body: dict, captcha_retries: int = CAPTCHA_RETRY) -> dict:
        """POST JSON，遇验证码错误自动重试"""
        for attempt in range(captcha_retries):
            self.wait()
            try:
                resp = self.session.post(BASE + endpoint, json=body, timeout=30)
            except requests.exceptions.RequestException as e:
                if attempt < captcha_retries - 1:
                    time.sleep(5)
                    continue
                raise
            if resp.status_code == 200:
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    raise RuntimeError(f"响应非JSON: {resp.text[:200]}")
            elif resp.status_code in (400, 401, 403):
                # 可能验证码失效，重新获取
                code = self._get_captcha()
                body["captcha"] = code
                continue
            else:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        raise RuntimeError("请求重试耗尽")


# ═══════════════════════════════════════════════════════════
# 数据库
# ═══════════════════════════════════════════════════════════

def load_db():
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db):
    db["metadata"]["updated"] = datetime.now().isoformat()
    db["metadata"]["total_patents"] = len(db["patents"])
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"done": {}, "failed": {}}


def save_progress(prog):
    PROGRESS_PATH.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════
# 全文解析
# ═══════════════════════════════════════════════════════════

def extract_fulltext(pdf_path: Path):
    """从 PDF 提取 权利要求书 / 说明书 文本"""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        text = "".join(page.get_text() for page in doc)
    except ImportError:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        text = "".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        return "", "", str(e)

    claims = ""
    description = ""
    # 找"权利要求书"与"说明书"分界
    m_claims = None
    for marker in ("权利要求书", "权 利 要 求 书"):
        idx = text.find(marker)
        if idx >= 0:
            m_claims = idx
            break
    m_desc = None
    for marker in ("说明书", "说 明 书"):
        idx = text.find(marker)
        if idx >= 0:
            m_desc = idx
            break
    if m_claims is not None and m_desc is not None and m_claims < m_desc:
        claims = text[m_claims:m_desc]
        description = text[m_desc:]
    elif m_claims is not None:
        claims = text[m_claims:]
    elif m_desc is not None:
        description = text[m_desc:]
    else:
        description = text[:30000]
    return claims.strip(), description.strip(), ""


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def collect_ipc_groups():
    """从 ipc_discovery 导入领域组（避免双份清单）"""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from ipc_discovery import DOMAIN_IPCS
    return DOMAIN_IPCS


def build_queries(args) -> list:
    """构建 (查询名, 检索body) 列表"""
    queries = []
    if args.all_groups:
        for group, ipcs in collect_ipc_groups().items():
            for ipc in ipcs:
                queries.append((f"{group}:{ipc}", {
                    "searchConditions": [{"key": "IPC分类号", "value": ipc}],
                    "pageNum": 1, "pageSize": 50, "searchType": 1,
                }))
    elif args.group:
        groups = collect_ipc_groups()
        if args.group not in groups:
            raise SystemExit(f"未知领域组: {args.group}，可选: {list(groups.keys())}")
        for ipc in groups[args.group]:
            queries.append((f"{args.group}:{ipc}", {
                "searchConditions": [{"key": "IPC分类号", "value": ipc}],
                "pageNum": 1, "pageSize": 50, "searchType": 1,
            }))
    elif args.ipc:
        queries.append((args.ipc, {
            "searchConditions": [{"key": "IPC分类号", "value": args.ipc}],
            "pageNum": 1, "pageSize": 50, "searchType": 1,
        }))
    elif args.query:
        queries.append((args.query, {
            "searchConditions": [{"key": "关键词", "value": args.query}],
            "pageNum": 1, "pageSize": 50, "searchType": 1,
        }))
    else:
        raise SystemExit("请指定 --ipc / --group / --all-groups / --query 之一")
    return queries


def search_pages(cnipa: CnipaSession, base_body: dict, max_pages: int):
    """分页搜索，返回专利记录列表"""
    records = []
    for page in range(1, max_pages + 1):
        body = dict(base_body)
        body["pageNum"] = page
        try:
            data = cnipa.post_json("/rest/api/patent/search", body)
        except Exception as e:
            print(f"  搜索第{page}页失败: {e}")
            break
        items = data.get("records", [])
        if not items:
            break
        records.extend(items)
        total = data.get("total", len(items))
        print(f"  第{page}页: {len(items)}条 (累计{len(records)}/{total})")
        if len(records) >= total:
            break
    return records


def parse_record(rec: dict) -> dict:
    """解析搜索结果记录 → 库条目"""
    pid = (rec.get("publicNumber") or rec.get("publicationNumber")
           or rec.get("appNumber") or rec.get("id") or "")
    pid = str(pid).strip()
    if not pid or not pid.startswith("CN"):
        return None
    ipc = rec.get("ipc", "") or rec.get("mainIpc", "") or rec.get("ipcCode", "")
    if isinstance(ipc, list):
        ipc = "; ".join(str(x) for x in ipc)
    entry = {
        "id": pid,
        "title": rec.get("title", "") or rec.get("inventionTitle", "") or "",
        "applicant": rec.get("applicant", "") or rec.get("assignee", "") or "",
        "application_date": rec.get("appDate", "") or rec.get("applicationDate", "") or "",
        "public_date": rec.get("pubDate", "") or rec.get("publicDate", "") or "",
        "ipc": str(ipc),
        "summary": rec.get("abstract", "") or rec.get("summary", "") or "",
        "legal_status": rec.get("legalStatus", "") or rec.get("status", "") or "",
        "source": "cnipa_epub",
        "crawled_at": datetime.now().isoformat(),
        "has_claims": False,
        "has_description": False,
    }
    return entry


def fetch_fulltext(cnipa: CnipaSession, pid: str) -> tuple:
    """下载 PDF 并解析全文，返回 (claims, description, err)"""
    # 详情接口拿 PDF 链接
    try:
        detail = cnipa.post_json("/rest/api/patent/details", {"id": pid})
    except Exception as e:
        return "", "", f"详情失败: {e}"
    # 尝试提取 PDF 链接（多种字段名）
    pdf_url = None
    for key in ("pdfUrl", "pdfPath", "pdf", "attachUrl", "filePath"):
        v = detail.get(key) or (detail.get("data", {}) or {}).get(key, "")
        if v:
            pdf_url = str(v)
            break
    if not pdf_url:
        # 记录本身可能有
        for rec in (detail.get("records") or []):
            for key in ("pdfUrl", "pdfPath", "pdf"):
                if rec.get(key):
                    pdf_url = str(rec[key])
                    break
            if pdf_url:
                break
    if not pdf_url:
        return "", "", "详情无PDF链接"
    if pdf_url.startswith("/"):
        pdf_url = BASE + pdf_url
    try:
        cnipa.wait()
        resp = cnipa.session.get(pdf_url, timeout=60)
        if resp.status_code != 200 or b"%PDF" not in resp.content[:1024]:
            return "", "", f"PDF下载失败 HTTP {resp.status_code}"
        pdf_path = PDF_DIR / f"{pid}.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(resp.content)
        claims, desc, err = extract_fulltext(pdf_path)
        return claims, desc, err
    except Exception as e:
        return "", "", f"PDF异常: {e}"


def main():
    parser = argparse.ArgumentParser(description="CNIPA 批量爬取")
    parser.add_argument("--ipc", default="", help="单IPC")
    parser.add_argument("--group", default="", help="领域组名")
    parser.add_argument("--all-groups", action="store_true", help="全部领域组")
    parser.add_argument("--query", default="", help="关键词")
    parser.add_argument("--max-pages", type=int, default=10, help="每个检索式最多页数")
    parser.add_argument("--limit", type=int, default=0, help="最多处理N篇(0=全部)")
    parser.add_argument("--dry-run", action="store_true", help="只搜索不入库")
    parser.add_argument("--skip-fulltext", action="store_true", help="只著录+IPC不抓全文")
    parser.add_argument("--manual-captcha", action="store_true", help="人工输入验证码")
    global REQUEST_INTERVAL, WORKERS
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    REQUEST_INTERVAL = args.interval
    WORKERS = args.workers

    cnipa = CnipaSession(manual_captcha=args.manual_captcha)
    db = load_db()
    patents = db["patents"]
    prog = load_progress()
    done, failed = prog["done"], prog["failed"]

    print(f"数据库当前: {len(patents)} 篇")
    queries = build_queries(args)
    print(f"待检索式: {len(queries)} 个")

    # ── 1. 搜索发现 ────────────────────────────────────
    discovered = {}
    for qname, body in queries:
        print(f"\n检索: {qname}")
        records = search_pages(cnipa, body, args.max_pages)
        new_cnt = 0
        for rec in records:
            entry = parse_record(rec)
            if not entry:
                continue
            pid = entry["id"]
            if pid not in patents and pid not in discovered:
                discovered[pid] = entry
                new_cnt += 1
        print(f"  → {len(records)} 条记录, 新增 {new_cnt}")

    if args.dry_run:
        print(f"\n[dry-run] 发现新专利 {len(discovered)} 篇，未入库:")
        for pid in list(discovered)[:20]:
            print(f"  {pid} | {discovered[pid]['title'][:40]}")
        return

    targets = list(discovered.items())
    if args.limit > 0:
        targets = targets[:args.limit]
    todo = [(pid, e) for pid, e in targets if pid not in done and pid not in failed]
    print(f"\n待处理: {len(todo)} 篇 (已完成{len(done)}, 失败{len(failed)})")

    # ── 2. 著录入库 + 全文抓取 ─────────────────────────
    stats = {"added": 0, "fulltext": 0, "failed": 0}

    def process(item):
        pid, entry = item
        try:
            if not args.skip_fulltext:
                claims, desc, err = fetch_fulltext(cnipa, pid)
                if claims:
                    entry["claims"] = claims
                    entry["has_claims"] = True
                if desc:
                    entry["description"] = desc
                    entry["has_description"] = True
            return pid, entry, None
        except Exception as e:
            return pid, entry, str(e)

    if args.skip_fulltext:
        for i, item in enumerate(todo, 1):
            pid, entry = item
            patents[pid] = entry
            done[pid] = {"title": entry["title"], "at": datetime.now().isoformat()}
            stats["added"] += 1
            print(f"[{i}/{len(todo)}] {pid} 著录入库: {entry['title'][:30]}")
            if i % SAVE_EVERY == 0 or i == len(todo):
                save_db(db)
                save_progress(prog)
    else:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(process, item): item for item in todo}
            for i, future in enumerate(as_completed(futures), 1):
                pid, entry, err = future.result()
                if err:
                    failed[pid] = {"reason": err[:200], "at": datetime.now().isoformat()}
                    stats["failed"] += 1
                    print(f"[{i}/{len(todo)}] {pid} 失败: {err[:80]}")
                else:
                    patents[pid] = entry
                    done[pid] = {"title": entry["title"], "at": datetime.now().isoformat()}
                    stats["added"] += 1
                    if entry.get("has_claims"):
                        stats["fulltext"] += 1
                    tag = "[全文]" if entry.get("has_claims") else "[著录]"
                    print(f"[{i}/{len(todo)}] {tag} {pid}: {entry['title'][:30]}")
                if i % SAVE_EVERY == 0:
                    save_db(db)
                    save_progress(prog)
                    print(f"  (已保存 {i} 篇)")

    save_db(db)
    save_progress(prog)
    print("\n" + "=" * 50)
    print(f"完成: 新增 {stats['added']} | 全文 {stats['fulltext']} | 失败 {stats['failed']}")
    empty_ipc = sum(1 for p in patents.values() if not p.get("ipc"))
    print(f"数据库总量: {len(patents)} 篇, IPC 为空: {empty_ipc} 篇")


if __name__ == "__main__":
    main()
