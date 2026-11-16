"""
用户配置API端点
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel
import json

from app.api import deps
from app.db.session import get_db
from app.models.user_config import UserConfig
from app.models.user import User
from app.core.config import settings
from app.core.encryption import encrypt_sensitive_data, decrypt_sensitive_data

router = APIRouter()

# 需要加密的敏感字段列表
SENSITIVE_LLM_FIELDS = [
    'llmApiKey', 'geminiApiKey', 'openaiApiKey', 'claudeApiKey',
    'qwenApiKey', 'deepseekApiKey', 'zhipuApiKey', 'moonshotApiKey',
    'baiduApiKey', 'minimaxApiKey', 'doubaoApiKey'
]
SENSITIVE_OTHER_FIELDS = ['githubToken', 'gitlabToken']


def encrypt_config(config: dict, sensitive_fields: list) -> dict:
    """
    加密配置中的敏感字段。

    处理流程：
    - 复制配置，避免原地修改
    - 遍历敏感字段并加密
    - 返回加密后的配置
    """
    # 复制配置以避免修改原对象
    encrypted = config.copy()
    # 遍历敏感字段
    for field in sensitive_fields:
        # 仅在字段存在且非空时加密
        if field in encrypted and encrypted[field]:
            encrypted[field] = encrypt_sensitive_data(encrypted[field])
    # 返回加密后的配置
    return encrypted


def decrypt_config(config: dict, sensitive_fields: list) -> dict:
    """
    解密配置中的敏感字段。

    处理流程：
    - 复制配置，避免原地修改
    - 遍历敏感字段并解密
    - 返回解密后的配置
    """
    # 复制配置以避免修改原对象
    decrypted = config.copy()
    # 遍历敏感字段
    for field in sensitive_fields:
        # 仅在字段存在且非空时解密
        if field in decrypted and decrypted[field]:
            decrypted[field] = decrypt_sensitive_data(decrypted[field])
    # 返回解密后的配置
    return decrypted


class LLMConfigSchema(BaseModel):
    """LLM配置Schema"""
    llmProvider: Optional[str] = None
    llmApiKey: Optional[str] = None
    llmModel: Optional[str] = None
    llmBaseUrl: Optional[str] = None
    llmTimeout: Optional[int] = None
    llmTemperature: Optional[float] = None
    llmMaxTokens: Optional[int] = None
    llmCustomHeaders: Optional[str] = None

    # Agent超时配置
    llmFirstTokenTimeout: Optional[int] = None  # 首Token超时（秒）
    llmStreamTimeout: Optional[int] = None  # 流式超时（秒）
    agentTimeout: Optional[int] = None  # Agent总超时（秒）
    subAgentTimeout: Optional[int] = None  # 子Agent超时（秒）
    toolTimeout: Optional[int] = None  # 工具执行超时（秒）

    # 平台专用配置
    geminiApiKey: Optional[str] = None
    openaiApiKey: Optional[str] = None
    claudeApiKey: Optional[str] = None
    qwenApiKey: Optional[str] = None
    deepseekApiKey: Optional[str] = None
    zhipuApiKey: Optional[str] = None
    moonshotApiKey: Optional[str] = None
    baiduApiKey: Optional[str] = None
    minimaxApiKey: Optional[str] = None
    doubaoApiKey: Optional[str] = None
    ollamaBaseUrl: Optional[str] = None


class OtherConfigSchema(BaseModel):
    """其他配置Schema"""
    githubToken: Optional[str] = None
    gitlabToken: Optional[str] = None
    maxAnalyzeFiles: Optional[int] = None
    llmConcurrency: Optional[int] = None
    llmGapMs: Optional[int] = None
    outputLanguage: Optional[str] = None


class UserConfigRequest(BaseModel):
    """用户配置请求"""
    llmConfig: Optional[LLMConfigSchema] = None
    otherConfig: Optional[OtherConfigSchema] = None


class UserConfigResponse(BaseModel):
    """用户配置响应"""
    id: str
    user_id: str
    llmConfig: dict
    otherConfig: dict
    created_at: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


def get_default_config() -> dict:
    """
    获取系统默认配置。

    处理流程：
    - 从系统设置读取默认值
    - 组装 LLM 与其他配置
    - 返回默认配置字典
    """
    # 返回系统默认配置
    return {
        "llmConfig": {
            "llmProvider": settings.LLM_PROVIDER,
            "llmApiKey": "",
            "llmModel": settings.LLM_MODEL or "",
            "llmBaseUrl": settings.LLM_BASE_URL or "",
            "llmTimeout": settings.LLM_TIMEOUT * 1000,  # 转换为毫秒
            "llmTemperature": settings.LLM_TEMPERATURE,
            "llmMaxTokens": settings.LLM_MAX_TOKENS,
            "llmCustomHeaders": "",
            # Agent超时配置（秒）
            "llmFirstTokenTimeout": getattr(settings, 'LLM_FIRST_TOKEN_TIMEOUT', 30),
            "llmStreamTimeout": getattr(settings, 'LLM_STREAM_TIMEOUT', 60),
            "agentTimeout": settings.AGENT_TIMEOUT_SECONDS,
            "subAgentTimeout": getattr(settings, 'SUB_AGENT_TIMEOUT_SECONDS', 600),
            "toolTimeout": getattr(settings, 'TOOL_TIMEOUT_SECONDS', 60),
            # 平台专用配置
            "geminiApiKey": settings.GEMINI_API_KEY or "",
            "openaiApiKey": settings.OPENAI_API_KEY or "",
            "claudeApiKey": settings.CLAUDE_API_KEY or "",
            "qwenApiKey": settings.QWEN_API_KEY or "",
            "deepseekApiKey": settings.DEEPSEEK_API_KEY or "",
            "zhipuApiKey": settings.ZHIPU_API_KEY or "",
            "moonshotApiKey": settings.MOONSHOT_API_KEY or "",
            "baiduApiKey": settings.BAIDU_API_KEY or "",
            "minimaxApiKey": settings.MINIMAX_API_KEY or "",
            "doubaoApiKey": settings.DOUBAO_API_KEY or "",
            "ollamaBaseUrl": settings.OLLAMA_BASE_URL or "http://localhost:11434/v1",
        },
        "otherConfig": {
            "githubToken": settings.GITHUB_TOKEN or "",
            "gitlabToken": settings.GITLAB_TOKEN or "",
            "maxAnalyzeFiles": settings.MAX_ANALYZE_FILES,
            "llmConcurrency": settings.LLM_CONCURRENCY,
            "llmGapMs": settings.LLM_GAP_MS,
            "outputLanguage": settings.OUTPUT_LANGUAGE,
        }
    }


@router.get("/defaults")
async def get_default_config_endpoint() -> Any:
    """
    获取系统默认配置（无需认证）。

    处理流程：
    - 调用默认配置构建函数
    - 返回配置结果
    """
    # 返回系统默认配置
    return get_default_config()


@router.get("/me", response_model=UserConfigResponse)
async def get_my_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前用户的配置（合并用户配置和系统默认配置）。

    处理流程：
    - 查询用户配置记录
    - 获取系统默认配置
    - 解密并合并用户配置
    - 返回合并后的配置
    """
    # 查询用户配置记录
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == current_user.id)
    )
    # 获取配置对象
    config = result.scalar_one_or_none()
    # 获取系统默认配置
    default_config = get_default_config()
    # 若用户没有保存配置则返回默认配置
    if not config:
        print(f"[Config] 用户 {current_user.id} 没有保存的配置，返回默认配置")
        # 返回系统默认配置
        return UserConfigResponse(
            id="",
            user_id=current_user.id,
            llmConfig=default_config["llmConfig"],
            otherConfig=default_config["otherConfig"],
            created_at="",
        )
    # 读取用户配置 JSON
    user_llm_config = json.loads(config.llm_config) if config.llm_config else {}
    user_other_config = json.loads(config.other_config) if config.other_config else {}
    # 解密敏感字段
    user_llm_config = decrypt_config(user_llm_config, SENSITIVE_LLM_FIELDS)
    user_other_config = decrypt_config(user_other_config, SENSITIVE_OTHER_FIELDS)
    # 输出调试信息
    print(f"[Config] 用户 {current_user.id} 的保存配置:")
    print(f"  - llmProvider: {user_llm_config.get('llmProvider')}")
    print(f"  - llmApiKey: {'***' + user_llm_config.get('llmApiKey', '')[-4:] if user_llm_config.get('llmApiKey') else '(空)'}")
    print(f"  - llmModel: {user_llm_config.get('llmModel')}")
    # 合并默认配置与用户配置（用户配置优先）
    merged_llm_config = {**default_config["llmConfig"], **user_llm_config}
    merged_other_config = {**default_config["otherConfig"], **user_other_config}
    # 返回合并后的配置
    return UserConfigResponse(
        id=config.id,
        user_id=config.user_id,
        llmConfig=merged_llm_config,
        otherConfig=merged_other_config,
        created_at=config.created_at.isoformat() if config.created_at else "",
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


@router.put("/me", response_model=UserConfigResponse)
async def update_my_config(
    config_in: UserConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新当前用户的配置。

    处理流程：
    - 查询现有配置记录
    - 加密敏感字段
    - 创建或更新配置记录
    - 返回合并后的配置
    """
    # 查询现有配置记录
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == current_user.id)
    )
    # 获取配置对象
    config = result.scalar_one_or_none()
    # 提取待保存的 LLM 配置
    llm_data = config_in.llmConfig.dict(exclude_none=True) if config_in.llmConfig else {}
    # 提取待保存的其他配置
    other_data = config_in.otherConfig.dict(exclude_none=True) if config_in.otherConfig else {}
    # 加密敏感字段
    llm_data_encrypted = encrypt_config(llm_data, SENSITIVE_LLM_FIELDS)
    other_data_encrypted = encrypt_config(other_data, SENSITIVE_OTHER_FIELDS)
    # 若不存在配置记录则创建
    if not config:
        # 创建新配置
        config = UserConfig(
            user_id=current_user.id,
            llm_config=json.dumps(llm_data_encrypted),
            other_config=json.dumps(other_data_encrypted),
        )
        # 写入数据库
        db.add(config)
    else:
        # 更新现有配置
        if config_in.llmConfig:
            existing_llm = json.loads(config.llm_config) if config.llm_config else {}
            # 先解密现有数据，再合并新数据，最后加密
            existing_llm = decrypt_config(existing_llm, SENSITIVE_LLM_FIELDS)
            # 合并新数据
            existing_llm.update(llm_data)  # 使用未加密的新数据合并
            # 重新加密并保存
            config.llm_config = json.dumps(encrypt_config(existing_llm, SENSITIVE_LLM_FIELDS))
        # 更新其他配置
        if config_in.otherConfig:
            existing_other = json.loads(config.other_config) if config.other_config else {}
            # 先解密现有数据，再合并新数据，最后加密
            existing_other = decrypt_config(existing_other, SENSITIVE_OTHER_FIELDS)
            # 合并新数据
            existing_other.update(other_data)  # 使用未加密的新数据合并
            # 重新加密并保存
            config.other_config = json.dumps(encrypt_config(existing_other, SENSITIVE_OTHER_FIELDS))
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(config)
    # 获取系统默认配置并合并（与 get_my_config 保持一致）
    default_config = get_default_config()
    user_llm_config = json.loads(config.llm_config) if config.llm_config else {}
    user_other_config = json.loads(config.other_config) if config.other_config else {}
    # 解密后返回给前端
    user_llm_config = decrypt_config(user_llm_config, SENSITIVE_LLM_FIELDS)
    user_other_config = decrypt_config(user_other_config, SENSITIVE_OTHER_FIELDS)
    # 合并默认配置与用户配置
    merged_llm_config = {**default_config["llmConfig"], **user_llm_config}
    merged_other_config = {**default_config["otherConfig"], **user_other_config}
    # 返回更新后的配置
    return UserConfigResponse(
        id=config.id,
        user_id=config.user_id,
        llmConfig=merged_llm_config,
        otherConfig=merged_other_config,
        created_at=config.created_at.isoformat() if config.created_at else "",
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


@router.delete("/me")
async def delete_my_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    删除当前用户的配置（恢复为默认）。

    处理流程：
    - 查询用户配置记录
    - 删除并提交
    - 返回删除结果
    """
    # 查询用户配置记录
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == current_user.id)
    )
    # 获取配置对象
    config = result.scalar_one_or_none()
    # 若存在配置则删除
    if config:
        await db.delete(config)
        await db.commit()
    # 返回删除结果
    return {"message": "配置已删除"}


class LLMTestRequest(BaseModel):
    """LLM测试请求"""
    provider: str
    apiKey: str
    model: Optional[str] = None
    baseUrl: Optional[str] = None


class LLMTestResponse(BaseModel):
    """LLM测试响应"""
    success: bool
    message: str
    model: Optional[str] = None
    response: Optional[str] = None
    # 调试信息
    debug: Optional[dict] = None


@router.post("/test-llm", response_model=LLMTestResponse)
async def test_llm_connection(
    request: LLMTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    测试 LLM 连接是否正常。

    处理流程：
    - 读取并解密用户配置
    - 计算调试参数与默认值
    - 创建对应适配器并发送测试请求
    - 返回测试结果与调试信息
    """
    # 延迟导入 LLM 相关组件
    from app.services.llm.factory import LLMFactory, NATIVE_ONLY_PROVIDERS
    from app.services.llm.adapters import LiteLLMAdapter, BaiduAdapter, MinimaxAdapter, DoubaoAdapter
    from app.services.llm.types import LLMConfig, LLMProvider, LLMRequest, LLMMessage, DEFAULT_MODELS, DEFAULT_BASE_URLS
    import traceback
    import time
    # 记录开始时间
    start_time = time.time()
    # 获取用户保存的配置
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == current_user.id)
    )
    # 获取配置记录
    user_config_record = result.scalar_one_or_none()
    # 解析用户配置
    saved_llm_config = {}
    saved_other_config = {}
    # 若存在配置则解密字段
    if user_config_record:
        if user_config_record.llm_config:
            saved_llm_config = decrypt_config(
                json.loads(user_config_record.llm_config),
                SENSITIVE_LLM_FIELDS
            )
        if user_config_record.other_config:
            saved_other_config = decrypt_config(
                json.loads(user_config_record.other_config),
                SENSITIVE_OTHER_FIELDS
            )
    # 从保存的配置中获取参数（用于调试显示）
    saved_timeout_ms = saved_llm_config.get('llmTimeout', settings.LLM_TIMEOUT * 1000)
    saved_temperature = saved_llm_config.get('llmTemperature', settings.LLM_TEMPERATURE)
    saved_max_tokens = saved_llm_config.get('llmMaxTokens', settings.LLM_MAX_TOKENS)
    saved_concurrency = saved_other_config.get('llmConcurrency', settings.LLM_CONCURRENCY)
    saved_gap_ms = saved_other_config.get('llmGapMs', settings.LLM_GAP_MS)
    saved_max_files = saved_other_config.get('maxAnalyzeFiles', settings.MAX_ANALYZE_FILES)
    saved_output_lang = saved_other_config.get('outputLanguage', settings.OUTPUT_LANGUAGE)
    # 组装调试信息
    debug_info = {
        "provider": request.provider,
        "model_requested": request.model,
        "base_url_requested": request.baseUrl,
        "api_key_length": len(request.apiKey) if request.apiKey else 0,
        "api_key_prefix": request.apiKey[:8] + "..." if request.apiKey and len(request.apiKey) > 8 else "(empty)",
        # 用户保存的配置参数
        "saved_config": {
            "timeout_ms": saved_timeout_ms,
            "temperature": saved_temperature,
            "max_tokens": saved_max_tokens,
            "concurrency": saved_concurrency,
            "gap_ms": saved_gap_ms,
            "max_analyze_files": saved_max_files,
            "output_language": saved_output_lang,
        },
    }

    try:
        # 解析 provider 映射
        provider_map = {
            'gemini': LLMProvider.GEMINI,
            'openai': LLMProvider.OPENAI,
            'claude': LLMProvider.CLAUDE,
            'qwen': LLMProvider.QWEN,
            'deepseek': LLMProvider.DEEPSEEK,
            'zhipu': LLMProvider.ZHIPU,
            'moonshot': LLMProvider.MOONSHOT,
            'baidu': LLMProvider.BAIDU,
            'minimax': LLMProvider.MINIMAX,
            'doubao': LLMProvider.DOUBAO,
            'ollama': LLMProvider.OLLAMA,
        }

        # 获取匹配的 provider
        provider = provider_map.get(request.provider.lower())
        # 若 provider 不支持则返回失败
        if not provider:
            debug_info["error_type"] = "unsupported_provider"
            return LLMTestResponse(
                success=False,
                message=f"不支持的LLM提供商: {request.provider}",
                debug=debug_info
            )
        # 获取默认模型与默认 Base URL
        model = request.model or DEFAULT_MODELS.get(provider)
        base_url = request.baseUrl or DEFAULT_BASE_URLS.get(provider, "")
        # 测试时使用用户保存的配置参数
        test_timeout = int(saved_timeout_ms / 1000) if saved_timeout_ms else settings.LLM_TIMEOUT
        test_temperature = saved_temperature if saved_temperature is not None else settings.LLM_TEMPERATURE
        test_max_tokens = saved_max_tokens if saved_max_tokens else settings.LLM_MAX_TOKENS
        # 记录调试参数
        debug_info["model_used"] = model
        debug_info["base_url_used"] = base_url
        debug_info["is_native_adapter"] = provider in NATIVE_ONLY_PROVIDERS
        debug_info["test_params"] = {
            "timeout": test_timeout,
            "temperature": test_temperature,
            "max_tokens": test_max_tokens,
        }
        # 打印测试请求日志
        print(f"[LLM Test] 开始测试: provider={provider.value}, model={model}, base_url={base_url}, temperature={test_temperature}, timeout={test_timeout}s, max_tokens={test_max_tokens}")
        # 创建 LLM 配置
        config = LLMConfig(
            provider=provider,
            api_key=request.apiKey,
            model=model,
            base_url=request.baseUrl,
            timeout=test_timeout,
            temperature=test_temperature,
            max_tokens=test_max_tokens,
        )
        # 直接创建新的适配器实例（不使用缓存）
        if provider in NATIVE_ONLY_PROVIDERS:
            native_adapter_map = {
                LLMProvider.BAIDU: BaiduAdapter,
                LLMProvider.MINIMAX: MinimaxAdapter,
                LLMProvider.DOUBAO: DoubaoAdapter,
            }
            adapter = native_adapter_map[provider](config)
            debug_info["adapter_type"] = type(adapter).__name__
        else:
            adapter = LiteLLMAdapter(config)
            debug_info["adapter_type"] = "LiteLLMAdapter"
            # 获取 LiteLLM 实际使用的模型名
            debug_info["litellm_model"] = getattr(adapter, '_get_litellm_model', lambda: model)() if hasattr(adapter, '_get_litellm_model') else model
        # 构建测试请求
        test_request = LLMRequest(
            messages=[
                LLMMessage(role="user", content="Say 'Hello' in one word.")
            ],
            temperature=test_temperature,
            max_tokens=test_max_tokens,
        )
        # 发送测试请求
        print(f"[LLM Test] 发送测试请求...")
        response = await adapter.complete(test_request)
        # 计算耗时
        elapsed_time = time.time() - start_time
        debug_info["elapsed_time_ms"] = round(elapsed_time * 1000, 2)

        # 验证响应内容
        if not response or not response.content:
            # 标记为空响应错误类型
            debug_info["error_type"] = "empty_response"
            # 保存原始响应便于排查
            debug_info["raw_response"] = str(response) if response else None
            # 记录日志
            print(f"[LLM Test] 空响应: {response}")
            # 返回失败结果
            return LLMTestResponse(
                success=False,
                message="LLM 返回空响应，请检查 API Key 和配置",
                debug=debug_info
            )

        # 记录响应长度
        debug_info["response_length"] = len(response.content)
        # 记录 token 使用情况
        debug_info["usage"] = {
            "prompt_tokens": getattr(response, 'prompt_tokens', None),
            "completion_tokens": getattr(response, 'completion_tokens', None),
            "total_tokens": getattr(response, 'total_tokens', None),
        }

        # 输出成功日志
        print(f"[LLM Test] 成功! 响应: {response.content[:50]}... 耗时: {elapsed_time:.2f}s")

        # 返回成功响应
        return LLMTestResponse(
            success=True,
            message=f"连接成功 ({elapsed_time:.2f}s)",
            model=model,
            response=response.content[:100] if response.content else None,
            debug=debug_info
        )

    except Exception as e:
        # 计算耗时
        elapsed_time = time.time() - start_time
        # 解析错误信息
        error_msg = str(e)
        # 获取错误类型
        error_type = type(e).__name__

        # 更新调试信息
        debug_info["elapsed_time_ms"] = round(elapsed_time * 1000, 2)
        debug_info["error_type"] = error_type
        debug_info["error_message"] = error_msg
        debug_info["traceback"] = traceback.format_exc()

        # 提取 LLMError 中的 api_response
        # 提取 LLMError 中的 api_response
        if hasattr(e, 'api_response') and e.api_response:
            debug_info["api_response"] = e.api_response
        if hasattr(e, 'status_code') and e.status_code:
            debug_info["status_code"] = e.status_code

        # 打印失败日志
        print(f"[LLM Test] 失败: {error_type}: {error_msg}")
        print(f"[LLM Test] Traceback:\n{traceback.format_exc()}")

        # 构造更友好的错误信息
        # 提供更友好的错误信息
        friendly_message = error_msg

        # 根据错误关键字分类
        # 优先检查余额不足（因为某些 API 用 429 表示余额不足）
        if any(keyword in error_msg for keyword in ["余额不足", "资源包", "充值", "quota", "insufficient", "balance", "402"]):
            friendly_message = "账户余额不足或配额已用尽，请充值后重试"
            debug_info["error_category"] = "insufficient_balance"
        elif "401" in error_msg or "invalid_api_key" in error_msg.lower() or "incorrect api key" in error_msg.lower():
            friendly_message = "API Key 无效或已过期，请检查后重试"
            debug_info["error_category"] = "auth_invalid_key"
        elif "authentication" in error_msg.lower():
            friendly_message = "认证失败，请检查 API Key 是否正确"
            debug_info["error_category"] = "auth_failed"
        elif "timeout" in error_msg.lower():
            friendly_message = "连接超时，请检查网络或 API 地址是否正确"
            debug_info["error_category"] = "timeout"
        elif "connection" in error_msg.lower() or "connect" in error_msg.lower():
            friendly_message = "无法连接到 API 服务，请检查网络或 API 地址"
            debug_info["error_category"] = "connection"
        elif "rate" in error_msg.lower() and "limit" in error_msg.lower():
            friendly_message = "API 请求频率超限，请稍后重试"
            debug_info["error_category"] = "rate_limit"
        elif "model" in error_msg.lower() and ("not found" in error_msg.lower() or "does not exist" in error_msg.lower()):
            friendly_message = f"模型 '{debug_info.get('model_used', 'unknown')}' 不存在或无权访问"
            debug_info["error_category"] = "model_not_found"
        else:
            debug_info["error_category"] = "unknown"

        # 返回失败响应
        return LLMTestResponse(
            success=False,
            message=friendly_message,
            debug=debug_info
        )


@router.get("/llm-providers")
async def get_llm_providers() -> Any:
    """
    获取支持的 LLM 提供商列表。

    处理流程：
    - 读取系统支持的 provider
    - 组装默认模型与可用模型
    - 返回 provider 列表
    """
    # 延迟导入工厂与常量
    from app.services.llm.factory import LLMFactory
    from app.services.llm.types import LLMProvider, DEFAULT_BASE_URLS
    # 构建 provider 列表
    providers = []
    # 遍历所有支持的 provider
    for provider in LLMFactory.get_supported_providers():
        # 追加 provider 配置信息
        providers.append({
            "id": provider.value,
            "name": provider.value.upper(),
            "defaultModel": LLMFactory.get_default_model(provider),
            "models": LLMFactory.get_available_models(provider),
            "defaultBaseUrl": DEFAULT_BASE_URLS.get(provider, ""),
        })
    # 返回 provider 列表
    return {"providers": providers}
