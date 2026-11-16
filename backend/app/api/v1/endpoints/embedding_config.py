"""
嵌入模型配置 API
独立于 LLM 配置，专门用于 RAG 系统的嵌入模型
使用 UserConfig.other_config 持久化存储
"""

import asyncio
import json
import time
import uuid
from typing import Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api import deps
from app.models.user import User
from app.models.user_config import UserConfig
from app.core.config import settings

router = APIRouter()


# ============ Schemas ============

class EmbeddingProvider(BaseModel):
    """嵌入模型提供商"""
    id: str
    name: str
    description: str
    models: List[str]
    requires_api_key: bool
    default_model: str


class EmbeddingConfig(BaseModel):
    """嵌入模型配置"""
    provider: str = Field(description="提供商: openai, ollama, azure, cohere, huggingface, jina, qwen")
    model: str = Field(description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API Key (如需要)")
    base_url: Optional[str] = Field(default=None, description="自定义 API 端点")
    dimensions: Optional[int] = Field(default=None, description="向量维度 (某些模型支持)")
    batch_size: int = Field(default=100, description="批处理大小")


class EmbeddingConfigResponse(BaseModel):
    """配置响应"""
    provider: str
    model: str
    api_key: Optional[str] = None  # 返回 API Key
    base_url: Optional[str]
    dimensions: int
    batch_size: int


class TestEmbeddingRequest(BaseModel):
    """测试嵌入请求"""
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    dimension: Optional[int] = None  # 自定义维度（Ollama等场景）
    test_text: str = "这是一段测试文本，用于验证嵌入模型是否正常工作。"


class TestEmbeddingResponse(BaseModel):
    """测试嵌入响应"""
    success: bool
    message: str
    dimensions: Optional[int] = None
    sample_embedding: Optional[List[float]] = None  # 前 5 个维度
    latency_ms: Optional[int] = None


# ============ 提供商配置 ============

EMBEDDING_PROVIDERS: List[EmbeddingProvider] = [
    EmbeddingProvider(
        id="openai",
        name="OpenAI (兼容 DeepSeek/Moonshot/智谱 等)",
        description="OpenAI 官方或兼容 API，填写自定义端点可接入其他服务商",
        models=[
            "text-embedding-3-small",
            "text-embedding-3-large",
            "text-embedding-ada-002",
        ],
        requires_api_key=True,
        default_model="text-embedding-3-small",
    ),
    EmbeddingProvider(
        id="azure",
        name="Azure OpenAI",
        description="Azure 托管的 OpenAI 嵌入模型",
        models=[
            "text-embedding-3-small",
            "text-embedding-3-large",
            "text-embedding-ada-002",
        ],
        requires_api_key=True,
        default_model="text-embedding-3-small",
    ),
    EmbeddingProvider(
        id="ollama",
        name="Ollama (本地)",
        description="本地运行的开源嵌入模型 (使用 /api/embed 端点)",
        models=[
            "nomic-embed-text",
            "mxbai-embed-large",
            "all-minilm",
            "snowflake-arctic-embed",
            "bge-m3",
            "qwen3-embedding",
        ],
        requires_api_key=False,
        default_model="nomic-embed-text",
    ),
    EmbeddingProvider(
        id="cohere",
        name="Cohere",
        description="Cohere Embed v2 API (api.cohere.com/v2)",
        models=[
            "embed-english-v3.0",
            "embed-multilingual-v3.0",
            "embed-english-light-v3.0",
            "embed-multilingual-light-v3.0",
            "embed-v4.0",
        ],
        requires_api_key=True,
        default_model="embed-multilingual-v3.0",
    ),
    EmbeddingProvider(
        id="huggingface",
        name="HuggingFace",
        description="HuggingFace Inference Providers (router.huggingface.co)",
        models=[
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/all-mpnet-base-v2",
            "BAAI/bge-large-zh-v1.5",
            "BAAI/bge-m3",
        ],
        requires_api_key=True,
        default_model="BAAI/bge-m3",
    ),
    EmbeddingProvider(
        id="jina",
        name="Jina AI",
        description="Jina AI 嵌入模型，代码嵌入效果好",
        models=[
            "jina-embeddings-v2-base-code",
            "jina-embeddings-v2-base-en",
            "jina-embeddings-v2-base-zh",
        ],
        requires_api_key=True,
        default_model="jina-embeddings-v2-base-code",
    ),
    EmbeddingProvider(
        id="qwen",
        name="Qwen (DashScope)",
        description="阿里云 DashScope Qwen 嵌入模型，兼容 OpenAI embeddings 接口",
        models=[
            "text-embedding-v4",
            "text-embedding-v3",
            "text-embedding-v2",
        ],
        requires_api_key=True,
        default_model="text-embedding-v4",
    ),
]


# ============ 数据库持久化存储 (异步) ============

EMBEDDING_CONFIG_KEY = "embedding_config"


async def get_embedding_config_from_db(db: AsyncSession, user_id: str) -> EmbeddingConfig:
    """
    从数据库获取嵌入配置（异步）。

    处理流程：
    - 查询用户配置记录
    - 解析 other_config 并读取嵌入配置
    - 若无配置则返回默认值
    """
    # 查询用户配置记录
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user_id)
    )
    # 获取用户配置对象
    user_config = result.scalar_one_or_none()

    # 若存在 other_config 则尝试解析
    if user_config and user_config.other_config:
        try:
            # 解析 other_config
            other_config = json.loads(user_config.other_config) if isinstance(user_config.other_config, str) else user_config.other_config
            # 读取嵌入配置数据
            embedding_data = other_config.get(EMBEDDING_CONFIG_KEY)

            # 若存在嵌入配置则构建对象
            if embedding_data:
                # 组装嵌入配置对象
                config = EmbeddingConfig(
                    provider=embedding_data.get("provider", settings.EMBEDDING_PROVIDER),
                    model=embedding_data.get("model", settings.EMBEDDING_MODEL),
                    api_key=embedding_data.get("api_key"),
                    base_url=embedding_data.get("base_url"),
                    dimensions=embedding_data.get("dimensions"),
                    batch_size=embedding_data.get("batch_size", 100),
                )
                # 记录读取日志
                print(f"[EmbeddingConfig] 读取用户 {user_id} 的嵌入配置: provider={config.provider}, model={config.model}")
                # 返回用户配置
                return config
        except (json.JSONDecodeError, AttributeError) as e:
            # 记录解析失败日志
            print(f"[EmbeddingConfig] 解析用户 {user_id} 配置失败: {e}")

    # 返回默认配置
    print(f"[EmbeddingConfig] 用户 {user_id} 无保存配置，返回默认值")
    return EmbeddingConfig(
        provider=settings.EMBEDDING_PROVIDER,
        model=settings.EMBEDDING_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        batch_size=100,
    )


async def save_embedding_config_to_db(db: AsyncSession, user_id: str, config: EmbeddingConfig) -> None:
    """
    保存嵌入配置到数据库（异步）。

    处理流程：
    - 查询用户配置记录
    - 构建嵌入配置数据
    - 更新或创建配置记录
    - 提交事务
    """
    # 查询用户配置记录
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user_id)
    )
    # 获取用户配置对象
    user_config = result.scalar_one_or_none()

    # 准备嵌入配置数据
    embedding_data = {
        "provider": config.provider,
        "model": config.model,
        "api_key": config.api_key,
        "base_url": config.base_url,
        "dimensions": config.dimensions,
        "batch_size": config.batch_size,
    }

    if user_config:
        # 更新现有配置
        try:
            other_config = json.loads(user_config.other_config) if user_config.other_config else {}
        except (json.JSONDecodeError, TypeError):
            other_config = {}

        # 写入嵌入配置
        other_config[EMBEDDING_CONFIG_KEY] = embedding_data
        # 保存到 other_config 字段
        user_config.other_config = json.dumps(other_config)
        # 🔥 显式标记 other_config 字段已修改，确保 SQLAlchemy 检测到变化
        flag_modified(user_config, "other_config")
    else:
        # 创建新配置
        user_config = UserConfig(
            id=str(uuid.uuid4()),
            user_id=user_id,
            llm_config="{}",
            other_config=json.dumps({EMBEDDING_CONFIG_KEY: embedding_data}),
        )
        # 新配置入库
        db.add(user_config)

    # 提交事务
    await db.commit()
    # 记录保存日志
    print(f"[EmbeddingConfig] 已保存用户 {user_id} 的嵌入配置: provider={config.provider}, model={config.model}")


# ============ API Endpoints ============

@router.get("/providers", response_model=List[EmbeddingProvider])
async def list_embedding_providers(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取可用的嵌入模型提供商列表。

    处理流程：
    - 依赖鉴权
    - 返回静态提供商列表
    """
    # 返回提供商列表
    return EMBEDDING_PROVIDERS


@router.get("/config", response_model=EmbeddingConfigResponse)
async def get_current_config(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取当前嵌入模型配置（从数据库读取）。

    处理流程：
    - 查询数据库配置
    - 计算默认维度
    - 返回配置响应
    """
    # 读取用户配置
    config = await get_embedding_config_from_db(db, current_user.id)

    # 获取维度：优先使用用户配置的维度，否则使用默认值
    dimensions = config.dimensions if config.dimensions else _get_model_dimensions(config.provider, config.model)

    # 返回配置响应
    return EmbeddingConfigResponse(
        provider=config.provider,
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        dimensions=dimensions,
        batch_size=config.batch_size,
    )


@router.put("/config")
async def update_config(
    config: EmbeddingConfig,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    更新嵌入模型配置（持久化到数据库）。

    处理流程：
    - 校验提供商合法性
    - 检查 API Key 要求
    - 保存配置
    """
    # 验证提供商
    provider_ids = [p.id for p in EMBEDDING_PROVIDERS]
    if config.provider not in provider_ids:
        raise HTTPException(status_code=400, detail=f"不支持的提供商: {config.provider}")

    # 获取提供商信息（用于检查 API Key 要求）
    provider = next((p for p in EMBEDDING_PROVIDERS if p.id == config.provider), None)
    # 注意：不再强制验证模型名称，允许用户输入自定义模型

    # 检查 API Key
    if provider and provider.requires_api_key and not config.api_key:
        raise HTTPException(status_code=400, detail=f"{config.provider} 需要 API Key")

    # 保存到数据库
    await save_embedding_config_to_db(db, current_user.id, config)

    # 返回保存结果
    return {"message": "配置已保存", "provider": config.provider, "model": config.model}


@router.post("/test", response_model=TestEmbeddingResponse)
async def test_embedding(
    request: TestEmbeddingRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    测试嵌入模型配置。

    处理流程：
    - 初始化嵌入服务
    - 执行测试嵌入
    - 固定响应时间防止时间侧信道
    - 返回测试结果
    """
    # 固定响应时间，防止 SSRF 时间侧信道攻击
    FIXED_DURATION = 3.0  # 固定响应时间，防止SSRF时间侧信道攻击
    # 记录开始时间
    start_time = time.time()

    try:
        # 延迟导入嵌入服务
        from app.services.rag.embeddings import EmbeddingService

        # 创建嵌入服务实例
        service = EmbeddingService(
            provider=request.provider,
            model=request.model,
            api_key=request.api_key,
            base_url=request.base_url,
            dimension=request.dimension,
            cache_enabled=False,
        )

        # 生成嵌入向量
        embedding = await service.embed(request.test_text)

        # 计算耗时
        elapsed = time.time() - start_time
        # 记录实际延迟
        latency_ms = int(elapsed * 1000)  # 在sleep前计算实际延迟
        # 若耗时不足则补足固定时长
        if elapsed < FIXED_DURATION:
            await asyncio.sleep(FIXED_DURATION - elapsed)
        # 返回成功结果
        return TestEmbeddingResponse(
            success=True,
            message=f"嵌入成功! 维度: {len(embedding)}",
            dimensions=len(embedding),
            sample_embedding=embedding[:5],  # 返回前 5 维
            latency_ms=latency_ms,
        )

    except Exception as e:
        # 发生异常时也同样等待，确保时间特征一致
        # 发生异常时也同样等待，确保时间特征一致
        elapsed = time.time() - start_time
        if elapsed < FIXED_DURATION:
            await asyncio.sleep(FIXED_DURATION - elapsed)

        # 返回失败结果
        return TestEmbeddingResponse(
            success=False,
            message=f"嵌入失败: {str(e)}",
        )


@router.get("/models/{provider}")
async def get_provider_models(
    provider: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    获取指定提供商的模型列表。

    处理流程：
    - 查询提供商信息
    - 校验存在性
    - 返回模型信息
    """
    # 查找提供商信息
    provider_info = next((p for p in EMBEDDING_PROVIDERS if p.id == provider), None)
    # 若提供商不存在则返回 404
    if not provider_info:
        raise HTTPException(status_code=404, detail=f"提供商不存在: {provider}")
    # 返回提供商模型信息
    return {
        "provider": provider,
        "models": provider_info.models,
        "default_model": provider_info.default_model,
        "requires_api_key": provider_info.requires_api_key,
    }


def _get_model_dimensions(provider: str, model: str) -> int:
    """
    获取模型维度。

    处理流程：
    - 通过模型名称查表
    - 若无匹配则返回默认值
    """
    # 模型维度映射表
    dimensions_map = {
        # OpenAI
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,

        # Ollama
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "snowflake-arctic-embed": 1024,
        "bge-m3": 1024,
        "qwen3-embedding": 1024,  # 默认值，8b版本为4096

        # Cohere
        "embed-english-v3.0": 1024,
        "embed-multilingual-v3.0": 1024,
        "embed-english-light-v3.0": 384,
        "embed-multilingual-light-v3.0": 384,
        "embed-v4.0": 1024,

        # HuggingFace
        "sentence-transformers/all-MiniLM-L6-v2": 384,
        "sentence-transformers/all-mpnet-base-v2": 768,
        "BAAI/bge-large-zh-v1.5": 1024,
        "BAAI/bge-m3": 1024,
        "BAAI/bge-small-en-v1.5": 384,
        "BAAI/bge-base-en-v1.5": 768,

        # Jina
        "jina-embeddings-v2-base-code": 768,
        "jina-embeddings-v2-base-en": 768,
        "jina-embeddings-v2-base-zh": 768,
        "jina-embeddings-v2-small-en": 512,

        # Qwen (DashScope)
        "text-embedding-v4": 1024,  # 支持维度: 2048, 1536, 1024(默认), 768, 512, 256, 128, 64
        "text-embedding-v3": 1024,  # 支持维度: 1024(默认), 768, 512, 256, 128, 64
        "text-embedding-v2": 1536,  # 支持维度: 1536
    }

    # 返回模型维度，默认 768
    return dimensions_map.get(model, 768)
