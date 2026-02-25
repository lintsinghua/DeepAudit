"""
LiteLLM 统一适配器
支持通过 LiteLLM 调用多个 LLM 提供商，使用统一的 OpenAI 兼容格式

增强功能:
- Prompt Caching: 为支持的 LLM（如 Claude）添加缓存标记
- 智能重试: 指数退避重试策略
- 流式输出: 支持逐 token 返回
"""

import logging
from typing import Dict, Any, Optional, List
from ..base_adapter import BaseLLMAdapter
from ..types import (
    LLMConfig,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    LLMProvider,
    LLMError,
    DEFAULT_BASE_URLS,
)
from ..prompt_cache import prompt_cache_manager, estimate_tokens

logger = logging.getLogger(__name__)


class LiteLLMAdapter(BaseLLMAdapter):
    """
    LiteLLM 统一适配器
    
    支持的提供商:
    - OpenAI (openai/gpt-4o-mini)
    - Claude (anthropic/claude-3-5-sonnet-20241022)
    - Gemini (gemini/gemini-1.5-flash)
    - DeepSeek (deepseek/deepseek-chat)
    - Qwen (qwen/qwen-turbo) - 通过 OpenAI 兼容模式
    - Zhipu (zhipu/glm-4-flash) - 通过 OpenAI 兼容模式
    - Moonshot (moonshot/moonshot-v1-8k) - 通过 OpenAI 兼容模式
    - Ollama (ollama/llama3)
    """

    # LiteLLM 模型前缀映射
    PROVIDER_PREFIX_MAP = {
        LLMProvider.OPENAI: "openai",
        LLMProvider.CLAUDE: "anthropic",
        LLMProvider.GEMINI: "gemini",
        LLMProvider.DEEPSEEK: "deepseek",
        LLMProvider.QWEN: "openai",  # 使用 OpenAI 兼容模式
        LLMProvider.ZHIPU: "openai",  # 使用 OpenAI 兼容模式
        LLMProvider.MOONSHOT: "openai",  # 使用 OpenAI 兼容模式
        LLMProvider.OLLAMA: "ollama",
    }

    # 需要自定义 base_url 的提供商
    CUSTOM_BASE_URL_PROVIDERS = {
        LLMProvider.QWEN,
        LLMProvider.ZHIPU,
        LLMProvider.MOONSHOT,
        LLMProvider.DEEPSEEK,
    }

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._litellm_model = self._get_litellm_model()
        self._api_base = self._get_api_base()

    def _get_litellm_model(self) -> str:
        """获取 LiteLLM 格式的模型名称
        
        对于使用第三方 OpenAI 兼容 API（如 SiliconFlow）的情况：
        - 如果用户设置了自定义 base_url，且模型名包含 / (如 Qwen/Qwen3-8B)
        - 需要将其转换为 openai/Qwen/Qwen3-8B 格式
        - 因为 LiteLLM 只认识 openai 作为有效前缀
        """
        provider = self.config.provider
        model = self.config.model

        # 检查模型名是否已经包含前缀
        if "/" in model:
            # 提取第一部分作为可能的 provider 前缀
            prefix_part = model.split("/")[0].lower()
            
            # LiteLLM 认识的有效 provider 前缀列表
            valid_litellm_prefixes = [
                "openai", "anthropic", "gemini", "deepseek", "ollama",
                "azure", "huggingface", "together", "groq", "mistral",
                "anyscale", "replicate", "bedrock", "vertex_ai", "cohere",
                "sagemaker", "palm", "ai21", "nlp_cloud", "aleph_alpha",
                "petals", "baseten", "vllm", "cloudflare", "xinference"
            ]
            
            # 如果前缀是 LiteLLM 认识的，直接返回
            if prefix_part in valid_litellm_prefixes:
                return model
            
            # 如果用户设置了自定义 base_url，将其视为 OpenAI 兼容 API
            # 例如 SiliconFlow 使用模型名 "Qwen/Qwen3-8B"
            if self.config.base_url:
                logger.debug(f"使用自定义 base_url，将模型 {model} 视为 OpenAI 兼容格式")
                return f"openai/{model}"
            
            # 对于没有自定义 base_url 的情况，尝试使用 provider 的前缀
            prefix = self.PROVIDER_PREFIX_MAP.get(provider, "openai")
            return f"{prefix}/{model}"

        # 获取 provider 前缀
        prefix = self.PROVIDER_PREFIX_MAP.get(provider, "openai")
        
        return f"{prefix}/{model}"

    def _extract_api_response(self, error: Exception) -> Optional[str]:
        """从异常中提取 API 服务器返回的原始响应信息"""
        error_str = str(error)

        # 尝试提取 JSON 格式的错误信息
        import re
        import json

        # 匹配 {'error': {...}} 或 {"error": {...}} 格式
        json_pattern = r"\{['\"]error['\"]:\s*\{[^}]+\}\}"
        match = re.search(json_pattern, error_str)
        if match:
            try:
                # 将单引号替换为双引号以便 JSON 解析
                json_str = match.group().replace("'", '"')
                error_obj = json.loads(json_str)
                if 'error' in error_obj:
                    err = error_obj['error']
                    code = err.get('code', '')
                    message = err.get('message', '')
                    return f"[{code}] {message}" if code else message
            except Exception:
                pass

        # 尝试提取 message 字段
        message_pattern = r"['\"]message['\"]:\s*['\"]([^'\"]+)['\"]"
        match = re.search(message_pattern, error_str)
        if match:
            return match.group(1)

        # 尝试从 litellm 异常中获取原始消息
        if hasattr(error, 'message'):
            return error.message
        if hasattr(error, 'llm_provider'):
            # litellm 异常通常包含原始错误信息
            return error_str.split(' - ')[-1] if ' - ' in error_str else None

        return None

    def _get_api_base(self) -> Optional[str]:
        """获取 API 基础 URL"""
        # 优先使用用户配置的 base_url
        if self.config.base_url:
            return self.config.base_url

        # 对于需要自定义 base_url 的提供商，使用默认值
        if self.config.provider in self.CUSTOM_BASE_URL_PROVIDERS:
            return DEFAULT_BASE_URLS.get(self.config.provider)

        # Ollama 使用本地地址
        if self.config.provider == LLMProvider.OLLAMA:
            return DEFAULT_BASE_URLS.get(LLMProvider.OLLAMA, "http://localhost:11434")

        return None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """使用 LiteLLM 发送请求"""
        try:
            await self.validate_config()
            return await self.retry(lambda: self._send_request(request))
        except Exception as error:
            self.handle_error(error, f"LiteLLM ({self.config.provider.value}) API调用失败")

    async def _send_request(self, request: LLMRequest) -> LLMResponse:
        """发送请求到 LiteLLM"""
        import litellm
        
        # 启用 LiteLLM 调试模式以获取更详细的错误信息
        # 注释掉下一行可关闭调试模式
        # litellm._turn_on_debug()
        
        # 禁用 LiteLLM 的缓存，确保每次都实际调用 API
        litellm.cache = None
        
        # 禁用 LiteLLM 自动添加的 reasoning_effort 参数
        # 这可以防止模型名称被错误解析为 effort 参数
        litellm.drop_params = True
        
        # 构建消息
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        # 🔥 Prompt Caching: 为支持的 LLM 添加缓存标记
        cache_enabled = False
        if self.config.provider == LLMProvider.CLAUDE:
            # 估算系统提示词 token 数
            system_tokens = 0
            for msg in messages:
                if msg.get("role") == "system":
                    system_tokens += estimate_tokens(msg.get("content", ""))
            
            messages, cache_enabled = prompt_cache_manager.process_messages(
                messages=messages,
                model=self.config.model,
                provider=self.config.provider.value,
                system_prompt_tokens=system_tokens,
            )
            
            if cache_enabled:
                logger.debug(f"🔥 Prompt Caching enabled for {self.config.model}")

        # 构建请求参数
        kwargs: Dict[str, Any] = {
            "model": self._litellm_model,
            "messages": messages,
            "temperature": request.temperature if request.temperature is not None else self.config.temperature,
            "max_tokens": request.max_tokens if request.max_tokens is not None else self.config.max_tokens,
        }

        # Claude 不允许同时传 temperature 和 top_p
        if self.config.provider != LLMProvider.CLAUDE:
            kwargs["top_p"] = request.top_p if request.top_p is not None else self.config.top_p

        # 设置 API Key
        if self.config.api_key and self.config.api_key != "ollama":
            kwargs["api_key"] = self.config.api_key

        # 设置 API Base URL
        if self._api_base:
            kwargs["api_base"] = self._api_base
            logger.debug(f"🔗 使用自定义 API Base: {self._api_base}")

        # 设置超时
        kwargs["timeout"] = self.config.timeout

        # 对于 OpenAI 提供商，添加额外参数
        if self.config.provider == LLMProvider.OPENAI:
            kwargs["frequency_penalty"] = self.config.frequency_penalty
            kwargs["presence_penalty"] = self.config.presence_penalty

        try:
            # 调用 LiteLLM
            response = await litellm.acompletion(**kwargs)
        except litellm.exceptions.AuthenticationError as e:
            api_response = self._extract_api_response(e)
            raise LLMError(f"API Key 无效或已过期", self.config.provider, 401, api_response=api_response)
        except litellm.exceptions.RateLimitError as e:
            error_msg = str(e)
            api_response = self._extract_api_response(e)
            # 区分"余额不足"和"频率超限"
            if any(keyword in error_msg for keyword in ["余额不足", "资源包", "充值", "quota", "insufficient", "balance"]):
                raise LLMError(f"账户余额不足或配额已用尽，请充值后重试", self.config.provider, 402, api_response=api_response)
            raise LLMError(f"API 调用频率超限，请稍后重试", self.config.provider, 429, api_response=api_response)
        except litellm.exceptions.APIConnectionError as e:
            api_response = self._extract_api_response(e)
            raise LLMError(f"无法连接到 API 服务", self.config.provider, api_response=api_response)
        except litellm.exceptions.APIError as e:
            api_response = self._extract_api_response(e)
            raise LLMError(f"API 错误", self.config.provider, getattr(e, 'status_code', None), api_response=api_response)
        except Exception as e:
            # 捕获其他异常并重新抛出
            error_msg = str(e)
            api_response = self._extract_api_response(e)
            if "invalid_api_key" in error_msg.lower() or "incorrect api key" in error_msg.lower():
                raise LLMError(f"API Key 无效", self.config.provider, 401, api_response=api_response)
            elif "authentication" in error_msg.lower():
                raise LLMError(f"认证失败", self.config.provider, 401, api_response=api_response)
            elif any(keyword in error_msg for keyword in ["余额不足", "资源包", "充值", "quota", "insufficient", "balance"]):
                raise LLMError(f"账户余额不足或配额已用尽", self.config.provider, 402, api_response=api_response)
            raise

        # 解析响应
        if not response:
            raise LLMError("API 返回空响应", self.config.provider)
            
        choice = response.choices[0] if response.choices else None
        if not choice:
            raise LLMError("API响应格式异常: 缺少choices字段", self.config.provider)

        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = LLMUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )
            
            # 🔥 更新 Prompt Cache 统计
            if cache_enabled and hasattr(response.usage, "cache_creation_input_tokens"):
                prompt_cache_manager.update_stats(
                    cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0),
                    cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
                    total_input_tokens=response.usage.prompt_tokens or 0,
                )

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage=usage,
            finish_reason=choice.finish_reason,
        )

    async def stream_complete(self, request: LLMRequest):
        """
        流式调用 LLM，逐 token 返回

        Yields:
            dict: {"type": "token", "content": str} 或 {"type": "done", "content": str, "usage": dict}
        """
        import litellm

        await self.validate_config()

        litellm.cache = None
        litellm.drop_params = True

        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

        # 🔥 估算输入 token 数量（用于在无法获取真实 usage 时进行估算）
        input_tokens_estimate = sum(
            estimate_tokens(msg["content"], self.config.model) for msg in messages
        )

        kwargs = {
            "model": self._litellm_model,
            "messages": messages,
            "temperature": request.temperature if request.temperature is not None else self.config.temperature,
            "max_tokens": request.max_tokens if request.max_tokens is not None else self.config.max_tokens,
            "stream": True,  # 启用流式输出
        }

        # Claude 不允许同时传 temperature 和 top_p
        if self.config.provider != LLMProvider.CLAUDE:
            kwargs["top_p"] = request.top_p if request.top_p is not None else self.config.top_p

        # 🔥 对于支持的模型，请求在流式输出中包含 usage 信息
        # OpenAI API 支持 stream_options
        if self.config.provider in [LLMProvider.OPENAI, LLMProvider.DEEPSEEK]:
            kwargs["stream_options"] = {"include_usage": True}

        if self.config.api_key and self.config.api_key != "ollama":
            kwargs["api_key"] = self.config.api_key

        if self._api_base:
            kwargs["api_base"] = self._api_base

        kwargs["timeout"] = self.config.timeout

        accumulated_content = ""
        final_usage = None  # 🔥 存储最终的 usage 信息
        chunk_count = 0  # 🔥 跟踪 chunk 数量

        try:
            response = await litellm.acompletion(**kwargs)

            async for chunk in response:
                chunk_count += 1

                # 🔥 检查是否有 usage 信息（某些 API 会在最后的 chunk 中包含）
                if hasattr(chunk, "usage") and chunk.usage:
                    final_usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                        "total_tokens": chunk.usage.total_tokens or 0,
                    }
                    logger.debug(f"Got usage from chunk: {final_usage}")

                if not chunk.choices:
                    # 🔥 某些模型可能发送没有 choices 的 chunk（如心跳）
                    continue

                delta = chunk.choices[0].delta
                content = getattr(delta, "content", "") or ""
                finish_reason = chunk.choices[0].finish_reason

                if content:
                    accumulated_content += content
                    yield {
                        "type": "token",
                        "content": content,
                        "accumulated": accumulated_content,
                    }
                # 🔥 ENHANCED: 处理没有 content 但也没有 finish_reason 的情况
                # 某些模型（如智谱 GLM）可能在某些 chunk 中不返回内容

                if finish_reason:
                    # 流式完成
                    # 🔥 如果没有从 chunk 获取到 usage，进行估算
                    if not final_usage:
                        output_tokens_estimate = estimate_tokens(
                            accumulated_content, self.config.model
                        )
                        final_usage = {
                            "prompt_tokens": input_tokens_estimate,
                            "completion_tokens": output_tokens_estimate,
                            "total_tokens": input_tokens_estimate + output_tokens_estimate,
                        }
                        logger.debug(f"Estimated usage: {final_usage}")

                    # 🔥 ENHANCED: 如果累积内容为空但有 finish_reason，记录警告
                    if not accumulated_content:
                        logger.warning(f"Stream completed with no content after {chunk_count} chunks, finish_reason={finish_reason}")

                    yield {
                        "type": "done",
                        "content": accumulated_content,
                        "usage": final_usage,
                        "finish_reason": finish_reason,
                    }
                    break

            # 🔥 ENHANCED: 如果循环结束但没有收到 finish_reason，也需要返回 done
            if accumulated_content:
                logger.warning(f"Stream ended without finish_reason, returning accumulated content ({len(accumulated_content)} chars)")
                if not final_usage:
                    output_tokens_estimate = estimate_tokens(
                        accumulated_content, self.config.model
                    )
                    final_usage = {
                        "prompt_tokens": input_tokens_estimate,
                        "completion_tokens": output_tokens_estimate,
                        "total_tokens": input_tokens_estimate + output_tokens_estimate,
                    }
                yield {
                    "type": "done",
                    "content": accumulated_content,
                    "usage": final_usage,
                    "finish_reason": "complete",
                }

        except litellm.exceptions.RateLimitError as e:
            # 速率限制错误 - 需要特殊处理
            logger.error(f"Stream rate limit error: {e}")
            error_msg = str(e)
            # 区分"余额不足"和"频率超限"
            if any(keyword in error_msg.lower() for keyword in ["余额不足", "资源包", "充值", "quota", "exceeded", "billing"]):
                error_type = "quota_exceeded"
                user_message = "API 配额已用尽，请检查账户余额或升级计划"
            else:
                error_type = "rate_limit"
                # 尝试从错误消息中提取重试时间
                import re
                retry_match = re.search(r"retry\s*(?:in|after)\s*(\d+(?:\.\d+)?)\s*s", error_msg, re.IGNORECASE)
                retry_seconds = float(retry_match.group(1)) if retry_match else 60
                user_message = f"API 调用频率超限，建议等待 {int(retry_seconds)} 秒后重试"

            output_tokens_estimate = estimate_tokens(
                accumulated_content, self.config.model
            ) if accumulated_content else 0
            yield {
                "type": "error",
                "error_type": error_type,
                "error": error_msg,
                "user_message": user_message,
                "accumulated": accumulated_content,
                "usage": {
                    "prompt_tokens": input_tokens_estimate,
                    "completion_tokens": output_tokens_estimate,
                    "total_tokens": input_tokens_estimate + output_tokens_estimate,
                } if accumulated_content else None,
            }

        except litellm.exceptions.AuthenticationError as e:
            # 认证错误 - API Key 无效
            logger.error(f"Stream authentication error: {e}")
            yield {
                "type": "error",
                "error_type": "authentication",
                "error": str(e),
                "user_message": "API Key 无效或已过期，请检查配置",
                "accumulated": accumulated_content,
                "usage": None,
            }

        except litellm.exceptions.APIConnectionError as e:
            # 连接错误 - 网络问题
            logger.error(f"Stream connection error: {e}")
            yield {
                "type": "error",
                "error_type": "connection",
                "error": str(e),
                "user_message": "无法连接到 API 服务，请检查网络连接",
                "accumulated": accumulated_content,
                "usage": None,
            }

        except Exception as e:
            # 其他错误 - 检查是否是包装的速率限制错误
            error_msg = str(e)
            logger.error(f"Stream error: {e}")

            # 检查是否是包装的速率限制错误（如 ServiceUnavailableError 包装 RateLimitError）
            is_rate_limit = any(keyword in error_msg.lower() for keyword in [
                "ratelimiterror", "rate limit", "429", "resource_exhausted",
                "quota exceeded", "too many requests"
            ])

            if is_rate_limit:
                # 按速率限制错误处理
                import re
                # 检查是否是配额用尽
                if any(keyword in error_msg.lower() for keyword in ["quota", "exceeded", "billing"]):
                    error_type = "quota_exceeded"
                    user_message = "API 配额已用尽，请检查账户余额或升级计划"
                else:
                    error_type = "rate_limit"
                    retry_match = re.search(r"retry\s*(?:in|after)\s*(\d+(?:\.\d+)?)\s*s", error_msg, re.IGNORECASE)
                    retry_seconds = float(retry_match.group(1)) if retry_match else 60
                    user_message = f"API 调用频率超限，建议等待 {int(retry_seconds)} 秒后重试"
            else:
                error_type = "unknown"
                user_message = "LLM 调用发生错误，请重试"

            output_tokens_estimate = estimate_tokens(
                accumulated_content, self.config.model
            ) if accumulated_content else 0
            yield {
                "type": "error",
                "error_type": error_type,
                "error": error_msg,
                "user_message": user_message,
                "accumulated": accumulated_content,
                "usage": {
                    "prompt_tokens": input_tokens_estimate,
                    "completion_tokens": output_tokens_estimate,
                    "total_tokens": input_tokens_estimate + output_tokens_estimate,
                } if accumulated_content else None,
            }

    async def validate_config(self) -> bool:
        """验证配置"""
        # Ollama 不需要 API Key
        if self.config.provider == LLMProvider.OLLAMA:
            if not self.config.model:
                raise LLMError("未指定 Ollama 模型", LLMProvider.OLLAMA)
            return True

        # 其他提供商需要 API Key
        if not self.config.api_key:
            raise LLMError(
                f"API Key未配置 ({self.config.provider.value})",
                self.config.provider,
            )

        # check for placeholder keys
        if "sk-your-" in self.config.api_key or "***" in self.config.api_key:
             raise LLMError(
                f"无效的 API Key (使用了占位符): {self.config.api_key[:10]}...",
                self.config.provider,
                401
            )

        if not self.config.model:
            raise LLMError(
                f"未指定模型 ({self.config.provider.value})",
                self.config.provider,
            )

        return True

    @classmethod
    def supports_provider(cls, provider: LLMProvider) -> bool:
        """检查是否支持指定的提供商"""
        return provider in cls.PROVIDER_PREFIX_MAP
