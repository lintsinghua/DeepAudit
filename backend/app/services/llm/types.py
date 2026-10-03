"""
LLM服务类型定义
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


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
    SILICONFLOW = "siliconflow"  # SiliconFlow
    SENSENOVA = "sensenova"  # SenseNova
    AIPING = "aiping"        # AI PING
    PPIO = "ppio"            # PPIO AI


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
    LLMProvider.SILICONFLOW: "deepseek-ai/DeepSeek-V3.2",
    LLMProvider.SENSENOVA: "SenseChat-5",
    LLMProvider.AIPING: "DeepSeek-V3.2",
    LLMProvider.PPIO: "deepseek/deepseek-v3.2",
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
    LLMProvider.SENSENOVA: "https://api.sensenova.com/v1",
    LLMProvider.SILICONFLOW: "https://api.siliconflow.cn/v1",
    LLMProvider.AIPING: "https://api.aiping.cloud/v1",
    LLMProvider.PPIO: "https://api.ppio.ai/v1",
}






