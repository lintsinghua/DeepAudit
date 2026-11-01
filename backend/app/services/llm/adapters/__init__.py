"""
LLM适配器模块

适配器分为两类:
1. LiteLLM 统一适配器 - 支持 OpenAI, Claude, Gemini, DeepSeek, Qwen, Zhipu, Moonshot, Ollama
2. 原生适配器 - 用于 API 格式特殊的提供商: Baidu, MiniMax, Doubao
"""

# LiteLLM 统一适配器
from .litellm_adapter import LiteLLMAdapter

# 原生适配器 (用于 API 格式特殊的提供商)
from .baidu_adapter import BaiduAdapter
from .minimax_adapter import MinimaxAdapter
from .doubao_adapter import DoubaoAdapter
from .lazyllm_adapter import LazyLLMAdapter

__all__ = [
    "LiteLLMAdapter",
    "BaiduAdapter",
    "MinimaxAdapter",
    "DoubaoAdapter",
    "LazyLLMAdapter",
]
