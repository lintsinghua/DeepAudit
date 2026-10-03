"""
LLM工厂类 - 统一创建和管理LLM适配器

使用 LiteLLM 作为主要适配器，支持大多数 LLM 提供商。
对于 API 格式特殊的提供商（百度、MiniMax、豆包），使用原生适配器。
"""

from typing import Dict, List
from .types import LLMConfig, LLMProvider, DEFAULT_MODELS
from .base_adapter import BaseLLMAdapter
from .adapters import (
    LiteLLMAdapter,
    BaiduAdapter,
    MinimaxAdapter,
    DoubaoAdapter,
    LazyLLMAdapter,
)


# 必须使用原生适配器的提供商（API 格式特殊）
NATIVE_ONLY_PROVIDERS = {
    LLMProvider.BAIDU,
    LLMProvider.MINIMAX,
    LLMProvider.DOUBAO,
}


class LLMFactory:
    """LLM工厂类"""

    _adapters: Dict[str, BaseLLMAdapter] = {}

    @classmethod
    def create_adapter(cls, config: LLMConfig) -> BaseLLMAdapter:
        """创建LLM适配器实例"""
        cache_key = cls._get_cache_key(config)

        # 从缓存中获取
        if cache_key in cls._adapters:
            return cls._adapters[cache_key]

        # 创建新的适配器实例
        adapter = cls._instantiate_adapter(config)

        # 缓存实例
        cls._adapters[cache_key] = adapter

        return adapter

    @classmethod
    def _instantiate_adapter(cls, config: LLMConfig) -> BaseLLMAdapter:
        """根据提供商类型实例化适配器
        
        优先级策略:
        1. 必须使用原生适配器的提供商（API 格式特殊）
        2. LiteLLM 支持的提供商
        3. LazyLLM 支持的提供商
        4. 不支持的提供商
        """
        # 如果未指定模型，使用默认模型
        if not config.model:
            config.model = DEFAULT_MODELS.get(config.provider, "gpt-4o-mini")

        # 对于必须使用原生适配器的提供商
        if config.provider in NATIVE_ONLY_PROVIDERS:
            return cls._create_native_adapter(config)

        # 其他提供商优先使用 LiteLLM
        if LiteLLMAdapter.supports_provider(config.provider):
            return LiteLLMAdapter(config)
        
        # 使用 LazyLLM 适配器
        if LazyLLMAdapter.supports_provider(config.provider):
            return LazyLLMAdapter(config)

        # 不支持的提供商
        raise ValueError(f"不支持的LLM提供商: {config.provider}")

    @classmethod
    def _create_native_adapter(cls, config: LLMConfig) -> BaseLLMAdapter:
        """创建原生适配器（仅用于 API 格式特殊的提供商）"""
        native_adapter_map = {
            LLMProvider.BAIDU: BaiduAdapter,
            LLMProvider.MINIMAX: MinimaxAdapter,
            LLMProvider.DOUBAO: DoubaoAdapter,
        }

        adapter_class = native_adapter_map.get(config.provider)
        if not adapter_class:
            raise ValueError(f"不支持的原生适配器提供商: {config.provider}")

        return adapter_class(config)

    @classmethod
    def _get_cache_key(cls, config: LLMConfig) -> str:
        """生成缓存键"""
        api_key_prefix = config.api_key[:8] if config.api_key else "no-key"
        return f"{config.provider.value}:{config.model}:{api_key_prefix}"

    @classmethod
    def clear_cache(cls) -> None:
        """清除缓存"""
        cls._adapters.clear()

    @classmethod
    def get_supported_providers(cls) -> List[LLMProvider]:
        """获取支持的提供商列表"""
        return list(LLMProvider)

    @classmethod
    def get_default_model(cls, provider: LLMProvider) -> str:
        """获取提供商的默认模型"""
        return DEFAULT_MODELS.get(provider, "gpt-4o-mini")

    @classmethod
    def get_available_models(cls, provider: LLMProvider) -> List[str]:
        """获取提供商的可用模型列表 (2025年最新)"""
        models = {
            LLMProvider.GEMINI: [
                "gemini-3-pro",
                "gemini-3.0-deep-think",
                "gemini-2.5-flash",
                "gemini-2.5-pro",
                "gemini-2.5-flash-lite",
                "gemini-2.5-flash-live-api",
                "veo-3.1",
                "veo-3.1-fast",
            ],
            LLMProvider.OPENAI: [
                "gpt-5",
                "gpt-5.1",
                "gpt-5.1-instant",
                "gpt-5.1-codex-max",
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4.5",
                "o4-mini",
                "o3",
                "o3-mini",
                "gpt-oss-120b",
                "gpt-oss-20b",
            ],
            LLMProvider.CLAUDE: [
                "claude-opus-4.5",
                "claude-sonnet-4.5",
                "claude-haiku-4.5",
                "claude-sonnet-4",
                "claude-opus-4",
                "claude-3.7-sonnet",
                "claude-3.5-sonnet",
                "claude-3.5-haiku",
                "claude-3-opus",
            ],
            LLMProvider.QWEN: [
                "qwen3-max-instruct",
                "qwen3-235b-a22b",
                "qwen3-turbo",
                "qwen3-32b",
                "qwen3-4b",
                "qwen3-embedding-8b",
                "qwen-image",
                "qwen-vl",
                "qwen-audio",
            ],
            LLMProvider.DEEPSEEK: [
                "deepseek-v3.1-terminus",
                "deepseek-r1-70b",
                "deepseek-r1-zero",
                "deepseek-v3.2-exp",
                "deepseek-chat",
                "deepseek-reasoner",
                "deepseek-ocr",
            ],
            LLMProvider.ZHIPU: [
                "glm-4.6",
                "glm-4.6-reap-218b",
                "glm-4.5",
                "glm-4.5v",
                "glm-4.5-air-106b",
                "glm-4-flash",
                "glm-4v-flash",
                "glm-4.1v-thinking",
            ],
            LLMProvider.MOONSHOT: [
                "kimi-k2",
                "kimi-k2-thinking",
                "kimi-k2-instruct-0905",
                "kimi-k1.5",
                "kimi-vl",
                "kimi-dev-72b",
                "kimi-researcher",
                "kimi-linear",
            ],
            LLMProvider.BAIDU: [
                "ernie-4.5",
                "ernie-4.5-21b-a3b-thinking",
                "ernie-4.0-8k",
                "ernie-3.5-8k",
                "ernie-vl",
            ],
            LLMProvider.MINIMAX: [
                "minimax-m2",
                "minimax-01-text",
                "minimax-01-vl",
                "minimax-m1",
                "speech-2.6",
                "hailuo-02",
                "music-1.5",
            ],
            LLMProvider.DOUBAO: [
                "doubao-1.6-pro",
                "doubao-1.5-pro",
                "doubao-seed-code",
                "doubao-seed-1.6",
                "doubao-vision-language",
            ],
            LLMProvider.OLLAMA: [
                "llama3.3-70b",
                "qwen3-8b",
                "gemma3-27b",
                "dolphin-3.0-llama3.1-8b",
                "cogito-v1",
                "deepseek-r1",
                "gpt-oss-120b",
                "llama3.1-405b",
                "mistral-nemo",
                "phi-3",
            ],
        }
        return models.get(provider, [])
