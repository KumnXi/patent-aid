"""Firecrawl 爬取客户端（Google Patents 备用通道）

Firecrawl (https://firecrawl.dev) 是网页转结构化数据的爬取服务，
带数据中心代理池，可绕开单 IP 被 Google 限流（503）的问题。

本项目用途：当 google_patents.py 的 xhr/HTML 抓取失败（503/封IP）时，
用它抓取专利页 HTML，复用现有解析逻辑。

配置（config/api_config.json）：
```json
"firecrawl": {
  "api_key": "你的Firecrawl API Key",
  "base_url": "https://api.firecrawl.dev"
}
```

注意：Firecrawl 免费档约 500 credits/月，一个专利页消耗数个 credits，
仅作备用通道，不要作主力爬取。
"""

import json
from pathlib import Path
from typing import Optional

import requests


class FirecrawlClient:
    """Firecrawl 网页抓取客户端"""

    def __init__(self, config_path: str = "config/api_config.json"):
        self.config = self._load_config(config_path)
        fc = self.config.get("firecrawl", {})
        self.api_key: str = fc.get("api_key", "")
        self.base_url: str = fc.get("base_url", "https://api.firecrawl.dev").rstrip("/")
        self.timeout: int = int(fc.get("timeout", 60))

    def is_available(self) -> bool:
        """Firecrawl 是否已配置"""
        return bool(self.api_key and self.api_key.strip()
                    and "你的" not in self.api_key)

    def scrape_patent_html(self, patent_id: str) -> Optional[str]:
        """抓取 Google Patents 专利页 HTML

        Args:
            patent_id: 专利号（如 CN117977607B）

        Returns:
            专利页 HTML，失败返回 None
        """
        if not self.is_available():
            print("[Firecrawl] 未配置 api_key，跳过")
            return None

        url = f"https://patents.google.com/patent/{patent_id}/zh"
        endpoint = f"{self.base_url}/v1/scrape"

        payload = {
            "url": url,
            "formats": ["html"],
            "onlyMainContent": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(endpoint, headers=headers, json=payload,
                                 timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("data", {}).get("html"):
                    return data["data"]["html"]
                # 无 html，尝试 markdown
                if data.get("data", {}).get("markdown"):
                    print(f"[Firecrawl] {patent_id} 返回markdown而非html")
                    return None
                print(f"[Firecrawl] {patent_id} 响应无html内容")
                return None
            else:
                print(f"[Firecrawl] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"[Firecrawl] 抓取异常: {e}")
            return None

    @staticmethod
    def _load_config(config_path: str) -> dict:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def create_firecrawl_client() -> FirecrawlClient:
    """从配置创建客户端"""
    return FirecrawlClient()
