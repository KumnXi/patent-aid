"""epub http 通道深度探测

目的：https 被限 → http 返回 202，探测 202 的响应体/头/重定向，
确认是 JS 挑战、登录跳转还是真实接口可用。

用法: python scripts/epub_http_probe.py
"""

import sys
import io
import json
import time
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

import requests

BASE = "http://epub.cnipa.gov.cn"
OUT_DIR = Path("output/epub_http_probe")
OUT_DIR.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
})


def dump(label, resp):
    print(f"\n--- {label} ---")
    print(f"URL: {resp.url}")
    print(f"HTTP {resp.status_code} | type: {resp.headers.get('Content-Type')} | len: {len(resp.content)}")
    print(f"final URL: {resp.url}")
    body = resp.text[:600]
    print(f"body 前600字: {body!r}")
    return resp


print("=" * 60)
print("1) 首页 GET http")
print("=" * 60)
try:
    r = session.get(BASE + "/", timeout=15, allow_redirects=True)
    dump("首页", r)
    print(f"cookies: {dict(session.cookies)}")
    print(f"Set-Cookie: {r.headers.get('Set-Cookie', '无')}")
except Exception as e:
    print(f"异常: {e}")

print()
print("=" * 60)
print("2) 验证码接口 http")
print("=" * 60)
try:
    r = session.get(BASE + "/rest/checkCode", timeout=15)
    dump("checkCode", r)
    if len(r.content) > 500:
        p = OUT_DIR / "captcha_http.png"
        p.write_bytes(r.content)
        print(f"验证码图片已保存: {p}")
except Exception as e:
    print(f"异常: {e}")

print()
print("=" * 60)
print("3) 搜索接口 http (POST)")
print("=" * 60)
try:
    body = {"searchConditions": [{"key": "关键词", "value": "管道检测机器人"}],
            "pageNum": 1, "pageSize": 10, "searchType": 1}
    r = session.post(BASE + "/rest/api/patent/search", json=body, timeout=20)
    dump("search", r)
    if r.status_code == 200:
        try:
            data = r.json()
            print(f"JSON keys: {list(data.keys())[:10]}")
            print(f"total: {data.get('total')}")
            print(f"records: {len(data.get('records', []))}")
            if data.get("records"):
                rec = data["records"][0]
                print(f"首条: {json.dumps(rec, ensure_ascii=False)[:400]}")
        except Exception as e:
            print(f"非JSON: {e}")
except Exception as e:
    print(f"异常: {e}")

print()
print("=" * 60)
print("4) 详情接口 http")
print("=" * 60)
try:
    r = session.post(BASE + "/rest/api/patent/details", json={"id": "CN105465551B"}, timeout=20)
    dump("details", r)
except Exception as e:
    print(f"异常: {e}")

print()
print("=" * 60)
print("完成。若步骤3/4返回200+JSON，则 http 通道可用，批量脚本改用 http 并兼容 cookie")
print("=" * 60)
