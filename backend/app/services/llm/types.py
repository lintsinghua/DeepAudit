"""
LLM服务类型定义
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from urllib.parse import urlsplit

from app.core.config import settings


class LLMProvider(str, Enum):
    """支持的LLM提供商类型"""
    GEMINI = "gemini"        # Google Gemini
    OPENAI = "openai"        # OpenAI (GPT系列)
    CLAUDE = "claude"        # Anthropic Claude
    QWEN = "qwen"            # 阿里云通义千问
    DEEPSEEK = "deepseek"    # DeepSeek
    ZHIPU = "zhipu"          # 智谱AI (GLM系列)
    MOONSHOT = "moonshot"    # 月之暗面 Kimi
    BAIDU = "baidu"          # 百度文心一言
    MINIMAX = "minimax"      # MiniMax
    DOUBAO = "doubao"        # 字节豆包
    OLLAMA = "ollama"        # Ollama 本地大模型


@dataclass
class LLMConfig:
    """LLM配置"""
    provider: LLMProvider
    api_key: str
    model: str
    base_url: Optional[str] = None
    timeout: int = 150
    temperature: float = 0.2
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0
    presence_penalty: float = 0
    custom_headers: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.base_url = trusted_model_endpoint(self.base_url)
        if self.model:
            validate_model_name(self.model)


@dataclass
class LLMMessage:
    """LLM请求消息"""
    role: str  # 'system', 'user', 'assistant'
    content: str


@dataclass
class LLMRequest:
    """LLM请求参数"""
    messages: List[LLMMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stream: bool = False


@dataclass
class LLMUsage:
    """Token使用统计"""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    """LLM响应"""
    content: str
    model: Optional[str] = None
    usage: Optional[LLMUsage] = None
    finish_reason: Optional[str] = None


class LLMError(Exception):
    """LLM错误"""
    def __init__(
        self,
        message: str,
        provider: Optional[LLMProvider] = None,
        status_code: Optional[int] = None,
        original_error: Optional[Any] = None,
        api_response: Optional[str] = None
    ):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.original_error = original_error
        self.api_response = api_response  # API 服务器返回的原始错误信息


# 各平台默认模型 (2025年最新推荐)
DEFAULT_MODELS: Dict[LLMProvider, str] = {
    LLMProvider.GEMINI: "gemini-3-pro",
    LLMProvider.OPENAI: "gpt-5",
    LLMProvider.CLAUDE: "claude-sonnet-4.5",
    LLMProvider.QWEN: "qwen3-max-instruct",
    LLMProvider.DEEPSEEK: "deepseek-v3.1-terminus",
    LLMProvider.ZHIPU: "glm-4.6",
    LLMProvider.MOONSHOT: "kimi-k2",
    LLMProvider.BAIDU: "ernie-4.5",
    LLMProvider.MINIMAX: "minimax-m2",
    LLMProvider.DOUBAO: "doubao-1.6-pro",
    LLMProvider.OLLAMA: "llama3.3-70b",
}


# 各平台API端点
DEFAULT_BASE_URLS: Dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "https://api.openai.com/v1",
    LLMProvider.QWEN: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    LLMProvider.DEEPSEEK: "https://api.deepseek.com",
    LLMProvider.ZHIPU: "https://open.bigmodel.cn/api/paas/v4",
    LLMProvider.MOONSHOT: "https://api.moonshot.cn/v1",
    LLMProvider.BAIDU: "https://aip.baidubce.com/rpc/2.0/ai_custom/v1",
    LLMProvider.MINIMAX: "https://api.minimax.chat/v1",
    LLMProvider.DOUBAO: "https://ark.cn-beijing.volces.com/api/v3",
    LLMProvider.OLLAMA: "http://localhost:11434/v1",
    LLMProvider.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
    LLMProvider.CLAUDE: "https://api.anthropic.com/v1",
}


EMBEDDING_BASE_URLS = {
    "openai": DEFAULT_BASE_URLS[LLMProvider.OPENAI],
    "ollama": "http://localhost:11434",
    "cohere": "https://api.cohere.com/v2",
    "huggingface": "https://router.huggingface.co",
    "jina": "https://api.jina.ai/v1",
    "qwen": DEFAULT_BASE_URLS[LLMProvider.QWEN],
}


def validate_model_name(model: str) -> str:
    if any(not re.fullmatch(r"[A-Za-z0-9_:.@+-]+", part) or part in (".", "..")
           for part in model.split("/")):
        raise ValueError("模型名称格式无效")
    return model


def trusted_model_endpoint(value: Optional[str]) -> Optional[str]:
    """Require an exact built-in or operator-configured service base, including its path."""
    if not value:
        return value
    allowed = (*DEFAULT_BASE_URLS.values(), *EMBEDDING_BASE_URLS.values(),
               settings.LLM_BASE_URL, settings.OPENAI_BASE_URL, settings.OLLAMA_BASE_URL,
               settings.EMBEDDING_BASE_URL, *settings.MODEL_ALLOWED_ENDPOINTS.split(","))
    candidate = value.rstrip("/")
    if candidate in {item.strip().rstrip("/") for item in allowed if item}:
        url = urlsplit(candidate)
        if (url.scheme in {"http", "https"} and url.hostname and url.username is None
                and not url.query and not url.fragment and "\\" not in candidate
                and not any(ord(c) <= 32 or ord(c) == 127 for c in candidate)):
            return candidate
    raise ValueError("模型服务地址未获部署者授权，请检查地址或联系管理员")
