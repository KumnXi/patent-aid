"""CNIPA 专利公布公告 epub 接口探测脚本

四步探测，每步独立容错：
  ① 验证码: GET /rest/checkCode → ddddocr 识别
  ② 搜索:   POST /rest/api/patent/search（多组参数变体试探）
  ③ 详情:   POST /rest/api/patent/details
  ④ PDF:    从详情提取 PDF 链接 → 下载 → pymupdf 解析

用法: python scripts/cnipa_probe.py
前置: pip install ddddocr（清华镜像）
"""

import sys
import io
import json
import time
import argparse
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

import requests

BASE = "https://epub.cnipa.gov.cn"
OUT_DIR = Path("output/cnipa_probe")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": BASE + "/",
    "Origin": BASE,
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}


def section(title):
    print("\n" + "=" * 60)
    print("  " + title)
    print("=" * 60)


def try_ddddocr(img_path: Path):
    """尝试用 ddddocr 识别验证码"""
    try:
        import ddddocr
        ocr = ddddocr.DdddOcr(show_ad=False)
        with open(img_path, "rb") as f:
            res = ocr.classification(f.read())
        return res
    except ImportError:
        return None


def main():
    parser = argparse.ArgumentParser(description="CNIPA epub 探测")
    parser.add_argument("--keyword", default="管道检测机器人", help="搜索关键词")
    parser.add_argument("--ipc", default="F16L55/26", help="IPC检索式")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    results = {}

    # ── ① 验证码 ─────────────────────────────────────────
    section("步骤1: 验证码获取与识别")
    try:
        resp = session.get(BASE + "/rest/checkCode", timeout=20)
        ctype = resp.headers.get("Content-Type", "?")
        print(f"HTTP {resp.status_code}, content-type: {ctype}")
        if resp.status_code == 200 and len(resp.content) > 500:
            img_path = OUT_DIR / "captcha.png"
            img_path.write_bytes(resp.content)
            print(f"验证码图片已保存: {img_path} ({len(resp.content)} 字节)")
            code = try_ddddocr(img_path)
            if code:
                print(f"ddddocr 识别结果: {code!r}")
                results["captcha"] = {"ok": True, "ocr": code}
            else:
                print("[提示] ddddocr 未安装或识别失败，请人工查看图片")
                print(f"  图片路径: {img_path.resolve()}")
                results["captcha"] = {"ok": True, "ocr": None}
        else:
            print(f"[警告] 验证码获取异常: {resp.text[:200]}")
            results["captcha"] = {"ok": False, "reason": resp.text[:200]}
    except Exception as e:
        print(f"[失败] 验证码步骤异常: {e}")
        results["captcha"] = {"ok": False, "reason": str(e)}

    # ── ② 搜索接口（多组参数变体） ───────────────────────
    section("步骤2: 搜索接口探测")
    search_bodies = [
        {"searchConditions": [{"key": "关键词", "value": args.keyword}], "pageNum": 1, "pageSize": 10, "searchType": 1, "order": "申请日", "orderDir": "desc"},
        {"searchConditions": [{"key": "关键词", "oper": "=", "value": args.keyword}], "pageNum": 1, "pageSize": 10, "searchType": 1},
        {"searchConditions": [{"key": "关键词", "oper": "like", "value": args.keyword}], "pageNum": 1, "pageSize": 10},
        {"q": args.keyword, "pageNum": 1, "pageSize": 10},
        {"searchConditions": [{"key": "IPC分类号", "value": args.ipc}], "pageNum": 1, "pageSize": 10, "searchType": 1},
        {"searchConditions": [{"key": "IPC", "value": args.ipc}], "pageNum": 1, "pageSize": 10},
        {"searchConditions": [{"key": "公开（公告）号", "value": "CN105465551B"}], "pageNum": 1, "pageSize": 10},
    ]
    for i, body in enumerate(search_bodies, 1):
        try:
            resp = session.post(BASE + "/rest/api/patent/search", json=body, timeout=25)
            text = resp.text[:400]
            print(f"[变体{i}] HTTP {resp.status_code}: {text}")
            if resp.status_code == 200 and resp.text.strip().startswith(("{", "[")):
                try:
                    data = resp.json()
                    total = data.get("total", data.get("count", "?"))
                    print(f"  → total={total}, keys={list(data.keys())[:10]}")
                    if i in (1, 2, 3) and "search" not in results:
                        results["search"] = {"ok": True, "body_idx": i, "total": total, "keys": list(data.keys())[:10]}
                    elif "search_ipc" not in results:
                        results["search_ipc"] = {"ok": True, "body_idx": i, "total": total}
                except json.JSONDecodeError:
                    print("  → 返回非 JSON")
            elif resp.status_code in (400, 403, 500):
                print("  [提示] 可能需要验证码 cookie 或参数格式不对")
        except Exception as e:
            print(f"[变体{i}] 异常: {e}")
        time.sleep(1.5)

    # ── ③ 详情接口 ───────────────────────────────────────
    section("步骤3: 详情接口探测")
    detail_bodies = [
        {"id": "CN105465551B"},
        {"publicNumber": "CN105465551B"},
        {"searchConditions": [{"key": "公开（公告）号", "value": "CN105465551B"}]},
    ]
    for i, body in enumerate(detail_bodies, 1):
        try:
            resp = session.post(BASE + "/rest/api/patent/details", json=body, timeout=25)
            print(f"[变体{i}] HTTP {resp.status_code}: {resp.text[:300]}")
            if resp.status_code == 200 and "detail" not in results:
                results["detail"] = {"ok": True, "body_idx": i, "sample": resp.text[:300]}
                break
        except Exception as e:
            print(f"[变体{i}] 异常: {e}")
        time.sleep(1.5)

    # ── ④ PDF 全文探测 ───────────────────────────────────
    section("步骤4: PDF 下载与解析探测")
    pdf_candidates = [
        BASE + "/rest/patent/pdf/CN105465551B",
        BASE + "/rest/patent/pdf?id=CN105465551B",
        BASE + "/Datas/att/CN105465551B.pdf",
    ]
    for url in pdf_candidates:
        try:
            resp = session.get(url, timeout=30)
            ctype = resp.headers.get("Content-Type", "?")
            print(f"GET {url} → HTTP {resp.status_code}, type={ctype}, size={len(resp.content)}")
            if resp.status_code == 200 and b"%PDF" in resp.content[:1024]:
                pdf_path = OUT_DIR / "sample.pdf"
                pdf_path.write_bytes(resp.content)
                print(f"PDF 已下载: {pdf_path} ({len(resp.content)} 字节)")
                try:
                    import fitz
                    doc = fitz.open(str(pdf_path))
                    text = doc[0].get_text()[:300]
                    print(f"pymupdf 解析成功, {doc.page_count} 页, 首页文本: {text!r}")
                    results["pdf"] = {"ok": True, "url": url, "pages": doc.page_count}
                except ImportError:
                    import pypdf
                    reader = pypdf.PdfReader(str(pdf_path))
                    print(f"pypdf 解析成功, {len(reader.pages)} 页")
                    results["pdf"] = {"ok": True, "url": url, "pages": len(reader.pages)}
                break
        except Exception as e:
            print(f"  异常: {e}")
        time.sleep(1.5)

    # ── 汇总 ──────────────────────────────────────────────
    section("探测汇总")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok_steps = sum(1 for v in results.values() if isinstance(v, dict) and v.get("ok"))
    print(f"\n通过步骤: {ok_steps}/4")
    if not results.get("captcha", {}).get("ok"):
        print("[下一步] 验证码不通 → 检查网络/UA/接口地址")
    if results.get("search", {}).get("ok"):
        idx = results["search"].get("body_idx")
        print(f"[下一步] 搜索通 → 用变体 {idx} 作为批量脚本模板")
    else:
        print("[下一步] 搜索不通 → 把本输出贴给助手，按实际响应迭代")


if __name__ == "__main__":
    main()
