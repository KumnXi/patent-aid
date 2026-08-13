"""CORE 学术论文检索客户端（CORE API v3）

用于技术调研升级：抓电力/管道检测方向的学术论文（标题/摘要/元数据），
作为专利数据库之外的补充语料，落 data/knowledge_base/papers/ 并进 RAG 检索。

遵循 src/api 现有客户端模式（读 config、is_available、失败返回 []）。

配置（config/api_config.json）：
```json
"core": {
  "api_key": "你的CORE API Key",
  "base_url": "https://api.core.ac.uk",
  "timeout": 60
}
```

CORE API v3 检索：
    GET https://api.core.ac.uk/v3/search/works?q=<query>&limit=<n>
    Authorization: Bearer <api_key>
    → {"totalHits": n, "results": [{id, title, abstract, authors[], yearPublished,
       venue{name}, doi, urls[], ...}]}
"""

import json
import time
from typing import Dict, List, Optional

import requests

# CORE 返回字段 → 项目统一论文字段 的映射
_FIELD_MAP = {
    "id": "id",
    "title": "title",
    "abstract": "abstract",
    "yearPublished": "year",
    "doi": "doi",
}


def _normalize_paper(raw: Dict) -> Optional[Dict]:
    """CORE 原始记录 → 项目统一字段 {id,title,abstract,authors,year,venue,doi}"""
    pid = raw.get("id")
    if pid is None:
        return None
    title = (raw.get("title") or "").strip()
    if not title:
        return None
    authors = []
    for a in raw.get("authors") or []:
        name = (a.get("name") or "") if isinstance(a, dict) else str(a)
        if name:
            authors.append(name)
    venue_raw = raw.get("venue") or {}
    if isinstance(venue_raw, dict):
        venue = venue_raw.get("name") or ""
    else:
        venue = str(venue_raw) or ""
    return {
        "id": pid,
        "title": title,
        "abstract": (raw.get("abstract") or "").strip(),
        "authors": authors[:8],      # 摘要检索用不到全部作者，保留前 8 位
        "year": raw.get("yearPublished"),
        "venue": venue,
        "doi": raw.get("doi") or "",
    }


class CoreClient:
    """CORE 学术论文检索客户端"""

    def __init__(self, config_path: str = "config/api_config.json"):
        self.config = self._load_config(config_path)
        core = self.config.get("core", {})
        self.api_key: str = (core.get("api_key") or "").strip()
        self.base_url: str = (core.get("base_url")
                              or "https://api.core.ac.uk").rstrip("/")
        self.timeout: int = int(core.get("timeout", 60))

    def is_available(self) -> bool:
        """CORE 是否已配置"""
        return bool(self.api_key and self.api_key.strip()
                    and "你的" not in self.api_key)

    def search(self, query: str, limit: int = 10,
               year_from: int = None) -> List[Dict]:
        """检索学术论文

        Args:
            query: 检索关键词（英文效果更好）
            limit: 返回条数（≤100）
            year_from: 只返回该年份及以后的文章（可选）

        Returns:
            统一论文字段列表，失败返回 []
        """
        if not self.is_available():
            print("[CORE] 未配置 api_key，跳过论文检索")
            return []

        endpoint = f"{self.base_url}/v3/search/works"
        params = {"q": query, "limit": min(limit, 100)}
        if year_from:
            params["yearPublished"] = year_from  # v3 支持该过滤参数
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            resp = requests.get(endpoint, headers=headers, params=params,
                                timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                raw_results = data.get("results") or []
                papers = [_normalize_paper(r) for r in raw_results]
                papers = [p for p in papers if p]
                return papers
            print(f"[CORE] HTTP {resp.status_code}: {resp.text[:200]}")
            return []
        except Exception as e:
            print(f"[CORE] 检索异常: {e}")
            return []

    @staticmethod
    def _load_config(config_path: str) -> dict:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def create_core_client() -> CoreClient:
    """从配置创建客户端"""
    return CoreClient()
