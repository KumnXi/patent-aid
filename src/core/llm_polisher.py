"""LLM润色模块

使用大语言模型（DeepSeek等）对自动生成的交底书进行润色，提升可读性和专业性。
"""

import json
from pathlib import Path
from typing import Optional


class LLMPolisher:
    """LLM交底书润色器"""

    def __init__(self, config_path: str = "config/api_config.json"):
        """初始化LLM润色器
        
        Args:
            config_path: API配置文件路径
        """
        self.config = self._load_config(config_path)
        self.llm_config = self.config.get("llm", {})
        self.api_key = self.llm_config.get("api_key", "")
        self.base_url = self.llm_config.get("base_url", "https://api.deepseek.com")
        self.model = self.llm_config.get("model", "deepseek-chat")
        self.max_tokens = self.llm_config.get("max_tokens", 4096)
        self.temperature = self.llm_config.get("temperature", 0.7)
        self.timeout = self.llm_config.get("timeout", 120)
        self.proxy = self.llm_config.get("proxy", "")

    def _load_config(self, config_path: str) -> dict:
        """加载配置"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def is_configured(self) -> bool:
        """检查API是否已配置"""
        return bool(self.api_key and self.api_key.strip())

    def polish(self, disclosure: str, idea: str = "") -> str:
        """润色交底书
        
        Args:
            disclosure: 原始交底书文本
            idea: 技术想法（用于提供上下文）
            
        Returns:
            润色后的交底书文本，如果失败则返回原文本
        """
        if not self.is_configured():
            print("[LLM润色] API Key未配置，跳过润色")
            return disclosure

        try:
            import requests
        except ImportError:
            print("[LLM润色] requests库未安装，跳过润色")
            return disclosure

        # 构建润色prompt
        system_prompt = """你是一位专业的专利代理师，擅长撰写和润色技术交底书。
请对以下技术交底书进行润色，要求：
1. 保持原有技术内容不变，不编造数据
2. 提升语言表达的专业性和流畅性
3. 使用规范的专利术语
4. 确保逻辑清晰、层次分明
5. 保持Markdown格式

请直接输出润色后的完整交底书，不要添加额外说明。"""

        user_prompt = f"请润色以下技术交底书：\n\n{disclosure}"
        
        if idea:
            user_prompt += f"\n\n（技术想法背景：{idea}）"

        # 调用API
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        proxies = {}
        if self.proxy:
            proxies = {"http": self.proxy, "https": self.proxy}

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        try:
            print(f"[LLM润色] 正在调用 {self.model}...")
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
                proxies=proxies,
            )
            
            if response.status_code == 200:
                result = response.json()
                polished = result["choices"][0]["message"]["content"]
                
                # 基本验证：润色后不应太短
                if len(polished) < len(disclosure) * 0.5:
                    print(f"[LLM润色] 警告：润色后文本过短({len(polished)}字)，保留原文")
                    return disclosure
                
                print(f"[LLM润色] 成功！{len(disclosure)}字 → {len(polished)}字")
                return polished
            else:
                print(f"[LLM润色] API错误 {response.status_code}: {response.text[:200]}")
                return disclosure
                
        except requests.exceptions.Timeout:
            print("[LLM润色] 请求超时，保留原文")
            return disclosure
        except requests.exceptions.ConnectionError:
            print("[LLM润色] 连接失败（检查代理），保留原文")
            return disclosure
        except Exception as e:
            print(f"[LLM润色] 异常: {e}，保留原文")
            return disclosure
