"""
LazyLLM 适配器
通过 LazyLLM 的 OnlineChatModule 提供统一的大模型接入服务

支持的提供商:
- 通过 LazyLLM 支持的所有在线模型提供商
- 包括: OpenAI, GLM, Qwen, Kimi, SenseNova, DeepSeek, Doubao, Siliconflow, PPIO, AIPing 等
"""

import os
import logging
import lazyllm
import asyncio
from ..base_adapter import BaseLLMAdapter
from ..types import (
    LLMConfig,
    LLMRequest,
    LLMResponse,
    LLMProvider,
    LLMError,
)

logger = logging.getLogger(__name__)


class LazyLLMAdapter(BaseLLMAdapter):
    """LazyLLM 适配器
    
    利用 LazyLLM 的 OnlineChatModule 提供统一的大模型接口
    支持多种在线 LLM 提供商的无缝接入
    """
    
    # DeepAudit Provider 到 LazyLLM source 的映射
    PROVIDER_SOURCE_MAP = {
        LLMProvider.OPENAI: "openai",
        LLMProvider.GEMINI: "gemini",
        LLMProvider.QWEN: "qwen",
        LLMProvider.DEEPSEEK: "deepseek",
        LLMProvider.ZHIPU: "glm",
        LLMProvider.MOONSHOT: "kimi",
        LLMProvider.DOUBAO: "doubao",
        LLMProvider.SILICONFLOW: "siliconflow",
        LLMProvider.MINIMAX: "minimax",
        LLMProvider.SENSENOVA: "sensenova",
        LLMProvider.PPIO: "ppio",
        LLMProvider.AIPING: "aiping",
    }
    
    # API_KEY的格式转换
    PROVIDER_ENV_MAP = {
        LLMProvider.OPENAI: "OPENAI_API_KEY",
        LLMProvider.GEMINI: "GEMINI_API_KEY",
        LLMProvider.QWEN: "QWEN_API_KEY",
        LLMProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
        LLMProvider.ZHIPU: "ZHIPU_API_KEY",
        LLMProvider.MOONSHOT: "MOONSHOT_API_KEY",
        LLMProvider.DOUBAO: "DOUBAO_API_KEY",
        LLMProvider.SILICONFLOW: "SILICONFLOW_API_KEY",
        LLMProvider.MINIMAX: "MINIMAX_API_KEY",
        LLMProvider.SENSENOVA: "SENSENOVA_API_KEY",
        LLMProvider.PPIO: "PPIO_API_KEY",
        LLMProvider.AIPING: "AIPING_API_KEY",
    }
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._lazyllm_module = None
        self._source = self._get_lazyllm_source()
        
    def _get_lazyllm_source(self) -> str:
        """获取 LazyLLM 的 source 名称"""
        source = self.PROVIDER_SOURCE_MAP.get(self.config.provider)
        if not source:
            raise LLMError(
                f"LazyLLM 不支持提供商: {self.config.provider}",
                self.config.provider
            )
        return source
    
    def _setup_environment(self):
        """设置 LazyLLM 所需的环境变量"""
        env_key = f"LAZYLLM_{self._source.upper()}_API_KEY"
        provider_env_key = self.PROVIDER_ENV_MAP.get(self.config.provider)
        candidate_key = os.getenv(provider_env_key) if provider_env_key else None

        if not candidate_key:
            candidate_key = self.config.api_key

        if candidate_key:
            os.environ[env_key] = candidate_key

        # SenseNova 额外 secret_key
        if self.config.provider == LLMProvider.SENSENOVA:
            headers = self.config.custom_headers or {}
            secret_key = headers.get("secret_key") or os.getenv("SENSENOVA_SECRET_KEY")
            if secret_key:
                os.environ["LAZYLLM_SENSENOVA_SECRET_KEY"] = secret_key
    
    def _get_lazyllm_module(self):
        """创建 LazyLLM OnlineChatModule 实例"""
        if self._lazyllm_module is None:
            try:
                self._setup_environment()
                # 创建 OnlineChatModule
                kwargs = {
                    "source": self._source,
                    "stream": False,  # 非流式输出
                }
                
                if self.config.base_url:
                    kwargs["base_url"] = self.config.base_url

                if self.config.model:
                    kwargs["model"] = self.config.model
                self._lazyllm_module = lazyllm.OnlineChatModule(**kwargs)
                logger.info(f"LazyLLM 模块初始化成功: source={self._source}, model={self.config.model}")
                
            except Exception as e:
                raise LLMError(
                    f"LazyLLM 模块初始化失败: {str(e)}",
                    self.config.provider,
                    original_error=e
                )
        
        return self._lazyllm_module
    
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """执行 LLM 推理"""
        try:
            await self.validate_config()
            return await self.retry(lambda: self._send_request(request))
        except Exception as error:
            api_response = getattr(error, 'api_response', None)
            self.handle_error(error, "LazyLLM API 调用失败", api_response=api_response)
    
    async def _send_request(self, request: LLMRequest) -> LLMResponse:
        """发送请求到 LazyLLM"""

        module = self._get_lazyllm_module()
        
        # 构建消息历史
        # LazyLLM 期望的格式: 最后一条消息是 input，之前的是 history
        messages = request.messages
        if not messages:
            raise LLMError("消息列表为空", self.config.provider)
        
        # 分离最后一条用户消息和历史
        user_input = messages[-1].content if messages[-1].role == "user" else ""
        
        # 构建历史记录 (格式: [[user, assistant], [user, assistant], ...])
        history = []
        i = 0
        while i < len(messages) - 1:
            if messages[i].role == "user" and i + 1 < len(messages) and messages[i + 1].role == "assistant":
                history.append([messages[i].content, messages[i + 1].content])
                i += 2
            else:
                i += 1
        
        # 准备调用参数
        call_kwargs = {}
        
        # 添加运行时参数（覆盖静态配置）
        if request.temperature is not None:
            call_kwargs["temperature"] = request.temperature
        elif self.config.temperature is not None:
            call_kwargs["temperature"] = self.config.temperature
            
        if request.max_tokens is not None:
            call_kwargs["max_tokens"] = request.max_tokens
        elif self.config.max_tokens is not None:
            call_kwargs["max_tokens"] = self.config.max_tokens
            
        if request.top_p is not None:
            call_kwargs["top_p"] = request.top_p
        elif self.config.top_p is not None:
            call_kwargs["top_p"] = self.config.top_p
        
        # LazyLLM 的同步调用需要在 executor 中运行
        def _call_lazyllm():
            try:
                result = module(
                    user_input,
                    llm_chat_history=history if history else None,
                    **call_kwargs
                )
                return result
            except Exception as e:
                logger.error(f"LazyLLM 调用失败: {e}")
                raise
        
        # 在线程池中执行同步调用
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _call_lazyllm)
        
        # 解析响应
        if isinstance(result, str):
            content = result
        elif isinstance(result, dict):
            content = result.get("content", str(result))
        else:
            content = str(result)
        
        # 返回基本响应（不包含 usage 信息）
        return LLMResponse(
            content=content,
            model=self.config.model,
            usage=None,  # LazyLLM 的 usage 记录在其内部系统中
            finish_reason="stop"
        )
    
    async def validate_config(self) -> bool:
        """验证配置是否有效"""
        await super().validate_config()
        
        # 检查 LazyLLM 是否支持该提供商
        if self.config.provider not in self.PROVIDER_SOURCE_MAP:
            raise LLMError(
                f"LazyLLM 适配器不支持提供商: {self.config.provider}",
                self.config.provider
            )
        
        return True
    
    @classmethod
    def supports_provider(cls, provider: LLMProvider) -> bool:
        """检查是否支持指定的提供商"""
        return provider in cls.PROVIDER_SOURCE_MAP
    
    async def close(self):
        """关闭适配器"""
        await super().close()
        # LazyLLM 模块的清理（如果需要）
        self._lazyllm_module = None

    