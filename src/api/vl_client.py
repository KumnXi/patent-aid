"""DashScope 多模态 VL 客户端（图片/文字理解）

给 DeepSeek 纯文本后端补上"眼睛"：把图片转成文字描述/结构化字段。
遵循 src/api 现有客户端模式（读 config、is_available、失败降级返回 None）。

配置（config/api_config.json）：
```json
"dashscope": {
  "api_key": "sk-...",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "model": "qwen-vl-max",
  "timeout": 90
}
```
key 回退：环境变量 DASHSCOPE_API_KEY（~/.claude/settings.json 已配置）。

注意：本项目主 LLM 是 DeepSeek（纯文本接口 LLMClient.chat()），
vl_client 专用于"看图"，产出必须是文字（供 DeepSeek 或生成链路消费），
不能把图像块塞给 LLMClient.chat()。
"""

import base64
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image


class VLClient:
    """DashScope 视觉语言模型客户端（OpenAI 兼容接口）"""

    # 大图自动压缩到长边不超过该值（VL 接口有图片大小限制）
    MAX_SIDE = 2048

    def __init__(self, config_path: str = "config/api_config.json"):
        self.config = self._load_config(config_path)
        ds = self.config.get("dashscope", {})
        self.api_key: str = (ds.get("api_key") or "").strip() or \
            os.environ.get("DASHSCOPE_API_KEY", "").strip()
        self.base_url: str = (
            ds.get("base_url")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self.model: str = ds.get("model", "qwen-vl-max")
        self.timeout: int = int(ds.get("timeout", 90))

    def is_available(self) -> bool:
        """DashScope 是否已配置（key 形如 sk-xxx）"""
        return bool(self.api_key and "sk-" in self.api_key)

    def chat_with_image(self, image_path: str, prompt: str,
                        max_tokens: int = 1024, temperature: float = 0.3) -> Optional[str]:
        """看图问答：图片 → 文字回答

        Args:
            image_path: 本地图片路径
            prompt: 对图片的提问/指令
            max_tokens: 回答最大 token 数

        Returns:
            模型文字回答，失败返回 None
        """
        if not self.is_available():
            print("[VL] 未配置 dashscope api_key，跳过看图")
            return None

        data_url = self._image_to_data_url(image_path)
        if not data_url:
            return None

        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            "max_tokens": max_tokens,
            "temperature": temperature,
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
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    return content
                print(f"[VL] 响应无内容: {str(data)[:200]}")
                return None
            print(f"[VL] HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        except Exception as e:
            print(f"[VL] 调用异常: {e}")
            return None

    def _image_to_data_url(self, image_path: str) -> Optional[str]:
        """读取图片并转为 base64 data URL（自动压缩长边 ≤ MAX_SIDE）"""
        try:
            img = Image.open(image_path)
            img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > self.MAX_SIDE:
                ratio = self.MAX_SIDE / max(w, h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/png;base64,{b64}"
        except Exception as e:
            print(f"[VL] 图片读取失败 {image_path}: {e}")
            return None

    @staticmethod
    def _load_config(config_path: str) -> dict:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def create_vl_client() -> VLClient:
    """从配置创建 VL 客户端"""
    return VLClient()
