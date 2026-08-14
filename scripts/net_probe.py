"""免代理专利数据源连通性诊断

测各候选源从当前网络的可达性（不依赖代理）：
  1. epub.cnipa.gov.cn        CNIPA公布公告(HTTP+HTTPS)
  2. www.cnipa.gov.cn         CNIPA官网
  3. api.firecrawl.dev        Firecrawl云端(已有key)
  4. patents.google.com       Google Patents(预期被墙,对照)
  5. www.patentscope.wipo.int WIPO Patentscope
  6. worldwide.espacenet.com  EPO Espacenet
  7. www.soopat.com           SooPAT
用法: python scripts/net_probe.py
"""

import sys
import io
import time
import socket
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

import requests

TARGETS = [
    ("CNIPA公布公告", "https://epub.cnipa.gov.cn", 8),
    ("CNIPA公布公告-http", "http://epub.cnipa.gov.cn", 8),
    ("CNIPA官网", "https://www.cnipa.gov.cn", 8),
    ("Firecrawl", "https://api.firecrawl.dev", 8),
    ("GooglePatents", "https://patents.google.com", 8),
    ("WIPO", "https://patentscope.wipo.int", 8),
    ("Espacenet", "https://worldwide.espacenet.com", 8),
    ("SooPAT", "https://www.soopat.com", 8),
]


def check(url: str, timeout: int):
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                         allow_redirects=True)
        return f"HTTP {r.status_code} ({len(r.content)//1024}KB)"
    except requests.exceptions.ConnectTimeout:
        return "连接超时"
    except requests.exceptions.ConnectionError as e:
        return f"连接失败: {str(e)[:60]}"
    except Exception as e:
        return f"异常: {str(e)[:60]}"


def dns(host: str):
    try:
        ip = socket.gethostbyname(host)
        return ip
    except Exception as e:
        return f"DNS失败: {str(e)[:40]}"


print("=" * 60)
print("DNS 解析检查")
print("=" * 60)
for name, url, _ in TARGETS:
    host = url.split("/")[2]
    print(f"  {name:18s} {host:35s} → {dns(host)}")

print()
print("=" * 60)
print("HTTP 连通性检查 (直连, 无代理)")
print("=" * 60)
for name, url, t in TARGETS:
    print(f"  {name:18s} {url}")
    print(f"    → {check(url, t)}")
    time.sleep(0.5)
