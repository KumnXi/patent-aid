"""LLM 调用客户端

封装 DeepSeek/OpenAI 兼容 API 的通用调用逻辑。
支持代理、超时、重试，供交底书生成和润色等模块复用。
"""

import json
import time
from typing import Optional

import requests


class LLMClient:
    """通用 LLM 调用客户端（兼容 OpenAI API 格式）"""

    def __init__(self, config_path: str = "config/api_config.json"):
        self.config = self._load_config(config_path)
        llm = self.config.get("llm", {})
        self.api_key: str = llm.get("api_key", "")
        self.base_url: str = llm.get("base_url", "https://api.deepseek.com")
        self.model: str = llm.get("model", "deepseek-chat")
        self.max_tokens: int = llm.get("max_tokens", 4096)
        self.temperature: float = llm.get("temperature", 0.7)
        self.timeout: int = llm.get("timeout", 120)
        self.proxy: str = llm.get("proxy", "")

    # ─── 公共方法 ───────────────────────────────────────────

    def is_available(self) -> bool:
        """检查 LLM 是否可用（API Key 已配置）"""
        return bool(self.api_key and self.api_key.strip())

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """调用 LLM 进行对话

        Args:
            system_prompt: 系统提示词（角色/格式/约束）
            user_prompt: 用户消息
            max_tokens: 最大生成 token 数（覆盖默认值）
            temperature: 采样温度（覆盖默认值）

        Returns:
            LLM 生成的文本

        Raises:
            LLMError: 调用失败时抛出
        """
        if not self.is_available():
            raise LLMError("API Key 未配置，请在 config/api_config.json 中填写 llm.api_key")

        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        proxies = self._get_proxies()

        last_error = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                    proxies=proxies,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if not content or not content.strip():
                        raise LLMError("LLM 返回空内容")
                    return content
                elif resp.status_code == 429:
                    # 限流，等待后重试
                    wait = (attempt + 1) * 10
                    print(f"[LLM] 限流(429)，等待{wait}秒后重试...")
                    time.sleep(wait)
                    last_error = LLMError(f"API 限流: {resp.status_code}")
                else:
                    raise LLMError(
                        f"API 错误 {resp.status_code}: {resp.text[:300]}"
                    )
            except requests.exceptions.Timeout:
                last_error = LLMError("请求超时")
                print(f"[LLM] 超时，重试({attempt+1}/3)...")
            except requests.exceptions.ConnectionError as e:
                last_error = LLMError(f"连接失败（请检查代理）: {e}")
                print(f"[LLM] 连接失败: {e}")
                break  # 连接错误不重试
            except LLMError:
                raise
            except Exception as e:
                last_error = LLMError(f"未知错误: {e}")
                break

        raise last_error or LLMError("LLM 调用失败")

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


class LLMError(Exception):
    """LLM 调用异常"""
    pass
