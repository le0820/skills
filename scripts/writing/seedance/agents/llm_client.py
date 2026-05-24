"""LLM客户端 - 统一的LLM调用接口

支持OpenAI和Anthropic两种provider，提供重试机制和错误处理。
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """LLM提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class LLMConfig:
    """LLM配置"""
    provider: LLMProvider = LLMProvider.OPENAI
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 8192
    timeout: float = 60.0
    max_retries: int = 2
    retry_delay: float = 5.0

    @classmethod
    def from_env(cls, prefix: str = "SEEDANCE") -> 'LLMConfig':
        """从环境变量加载配置

        Args:
            prefix: 环境变量前缀，如 SEEDANCE 或 INKOS

        Returns:
            LLMConfig实例
        """
        provider_str = os.getenv(f"{prefix}_LLM_PROVIDER", "openai")
        try:
            provider = LLMProvider(provider_str)
        except ValueError:
            provider = LLMProvider.OPENAI

        return cls(
            provider=provider,
            base_url=os.getenv(f"{prefix}_LLM_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv(f"{prefix}_LLM_API_KEY", ""),
            model=os.getenv(f"{prefix}_LLM_MODEL", "gpt-4o"),
            temperature=float(os.getenv(f"{prefix}_LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv(f"{prefix}_LLM_MAX_TOKENS", "8192")),
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.getenv("MAX_RETRIES", "2")),
            retry_delay=float(os.getenv("RETRY_DELAY_SECONDS", "5"))
        )


class LLMError(Exception):
    """LLM调用错误"""
    def __init__(self, message: str, provider: str, model: str):
        super().__init__(message)
        self.provider = provider
        self.model = model


class LLMClient:
    """统一的LLM调用客户端

    支持OpenAI和Anthropic两种provider，提供：
    - 异步调用
    - 重试机制
    - 错误处理
    - JSON输出解析

    Example:
        config = LLMConfig.from_env("SEEDANCE")
        client = LLMClient(config)
        response = await client.generate("请写一个故事大纲")
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        """初始化客户端

        Args:
            config: LLM配置，为None时从环境变量加载
        """
        self.config = config or LLMConfig.from_env("SEEDANCE")
        self._client = None

    async def _get_client(self):
        """获取或创建HTTP客户端"""
        if self._client is None:
            if self.config.provider == LLMProvider.OPENAI:
                import openai
                self._client = openai.AsyncOpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                    timeout=self.config.timeout
                )
            elif self.config.provider == LLMProvider.ANTHROPIC:
                import anthropic
                self._client = anthropic.AsyncAnthropic(
                    api_key=self.config.api_key,
                    timeout=self.config.timeout
                )
        return self._client

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None,
                       response_format: Optional[Dict[str, str]] = None) -> str:
        """生成文本响应

        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（仅OpenAI支持）

        Returns:
            生成的文本

        Raises:
            LLMError: 调用失败
        """
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                client = await self._get_client()

                if self.config.provider == LLMProvider.OPENAI:
                    response = await client.chat.completions.create(
                        model=self.config.model,
                        messages=[
                            {"role": "system", "content": system_prompt or ""},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=temp,
                        max_tokens=tokens,
                        response_format=response_format
                    )
                    return response.choices[0].message.content

                elif self.config.provider == LLMProvider.ANTHROPIC:
                    response = await client.messages.create(
                        model=self.config.model,
                        max_tokens=tokens,
                        temperature=temp,
                        system=system_prompt or "",
                        messages=[
                            {"role": "user", "content": prompt}
                        ]
                    )
                    return response.content[0].text

            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries:
                    logger.warning(f"LLM call failed (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(self.config.retry_delay)
                else:
                    logger.error(f"LLM call failed after all retries: {e}")
                    raise LLMError(
                        message=str(e),
                        provider=self.config.provider.value,
                        model=self.config.model
                    )

        raise last_error

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None,
                            temperature: Optional[float] = None) -> Dict[str, Any]:
        """生成JSON格式响应

        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            temperature: 温度参数

        Returns:
            解析后的JSON对象

        Raises:
            LLMError: 调用失败
            json.JSONDecodeError: JSON解析失败
        """
        # 添加JSON格式要求
        json_prompt = f"""{prompt}

请以JSON格式输出，确保输出是有效的JSON。"""

        if self.config.provider == LLMProvider.OPENAI:
            # OpenAI支持response_format
            response = await self.generate(
                json_prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                response_format={"type": "json_object"}
            )
        else:
            # Anthropic不支持response_format，依赖prompt
            response = await self.generate(
                json_prompt,
                system_prompt=system_prompt,
                temperature=temperature
            )

        # 提取JSON部分（处理可能的markdown代码块）
        json_str = response.strip()
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.startswith("```"):
            json_str = json_str[3:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
        json_str = json_str.strip()

        return json.loads(json_str)

    async def close(self):
        """关闭客户端连接"""
        if self._client:
            await self._client.close()
            self._client = None
