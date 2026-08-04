"""文本嵌入客户端（向量检索用）

封装 DashScope/OpenAI 兼容 Embedding API 的调用逻辑。
当前默认使用阿里云 text-embedding-v3（8K 上下文，支持自定义维度）。

配置位置 config/api_config.json:
```json
{
  "embedding": {
    "provider": "dashscope",
    "api_key": "你的DashScope API Key",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "text-embedding-v3",
    "dimensions": 1024,
    "batch_size": 25,
    "proxy": ""
  }
}
```

无 API Key 或调用失败时，调用方应优雅降级（RAG 引擎回退到 TF-IDF）。
"""

import json
import time
from typing import List, Optional

import requests


class EmbeddingClient:
    """通用 Embedding 客户端（OpenAI 兼容 /embeddings 接口）"""

    def __init__(self, config_path: str = "config/api_config.json"):
        self.config = self._load_config(config_path)
        emb = self.config.get("embedding", {})
        self.api_key: str = emb.get("api_key", "")
        self.base_url: str = emb.get(
            "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self.model: str = emb.get("model", "text-embedding-v3")
        self.dimensions: int = int(emb.get("dimensions", 0) or 0)
        self.batch_size: int = int(emb.get("batch_size", 25))
        self.timeout: int = int(emb.get("timeout", 60))
        self.proxy: str = emb.get("proxy", "")

    def is_available(self) -> bool:
        """检查嵌入服务是否可用（API Key 已配置）"""
        return bool(self.api_key and self.api_key.strip())

    def embed(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文本（自动分批）

        Args:
            texts: 文本列表

        Returns:
            与输入等长的向量列表；某批失败则整批跳过（返回该批为空）

        Raises:
            EmbeddingError: 所有批次都失败或未配置 key 时抛出
        """
        if not self.is_available():
            raise EmbeddingError("Embedding API Key 未配置，请在 config/api_config.json 填写 embedding.api_key")
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        proxies = self._get_proxies()

        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            batch_idx = list(range(start, start + len(batch)))
            vectors = self._embed_batch(batch, proxies)
            if vectors is not None:
                for idx, vec in zip(batch_idx, vectors):
                    results[idx] = vec

        failed = [i for i, r in enumerate(results) if r is None]
        if failed:
            raise EmbeddingError(f"嵌入失败 {len(failed)}/{len(texts)} 条")

        return results  # type: ignore[return-value]

    def _embed_batch(self, texts: List[str], proxies: dict) -> Optional[List[List[float]]]:
        """调用单批嵌入接口（带重试与限流退避）"""
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # dimensions 仅对 OpenAI text-embedding-3 系列有效；
        # bge-m3 等开源模型固定 1024 维，传了会报参数无效
        payload = {
            "model": self.model,
            "input": texts,
        }
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions

        for attempt in range(3):
            try:
                resp = requests.post(
                    url, headers=headers, json=payload,
                    timeout=self.timeout, proxies=proxies,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
                    return [it["embedding"] for it in items]
                elif resp.status_code == 429:
                    wait = (attempt + 1) * 10
                    print(f"[Embedding] 限流(429)，等待{wait}秒后重试...")
                    time.sleep(wait)
                else:
                    print(f"[Embedding] API 错误 {resp.status_code}: {resp.text[:200]}")
                    return None
            except requests.exceptions.Timeout:
                print(f"[Embedding] 超时，重试({attempt+1}/3)...")
            except requests.exceptions.ConnectionError as e:
                print(f"[Embedding] 连接失败（请检查代理）: {e}")
                return None
            except Exception as e:
                print(f"[Embedding] 未知错误: {e}")
                return None
        print("[Embedding] 批次重试耗尽，跳过该批")
        return None

    # ─── 内部方法 ───────────────────────────────────────────

    @staticmethod
    def _load_config(config_path: str) -> dict:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _get_proxies(self) -> dict:
        if self.proxy:
            return {"http": self.proxy, "https": self.proxy}
        return {}


class EmbeddingError(Exception):
    """Embedding 调用异常"""
    pass
