import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.api import api_router
from app.db.session import AsyncSessionLocal
from app.db.init_db import init_db

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 禁用 uvicorn access log 和 LiteLLM INFO 日志
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)


async def check_agent_services():
    """检查 Agent 必须服务的可用性"""
    issues = []

    # 检查 Docker/沙箱服务
    try:
        import docker
        client = docker.from_env()
        client.ping()
        logger.info("  - Docker 服务可用")
    except ImportError:
        issues.append("Docker Python 库未安装 (pip install docker)")
    except Exception as e:
        issues.append(f"Docker 服务不可用: {e}")

    # 检查 Redis 连接（可选警告）
    try:
        import redis
        import os
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, password=os.environ.get("REDIS_PASSWORD") or None)
        r.ping()
        logger.info("  - Redis 服务可用")
    except ImportError:
        logger.warning("  - Redis Python 库未安装，部分功能可能受限")
    except Exception as e:
        logger.warning(f"  - Redis 服务连接失败: {e}")

    return issues


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    启动时检查旧版演示凭据并初始化系统模板
    """
    logger.info("DeepAudit 后端服务启动中...")

    # 先完成凭据升级，再开始接受请求。
    async with AsyncSessionLocal() as db:
        await init_db(db)

    # 检查 Agent 服务
    logger.info("检查 Agent 核心服务...")
    issues = await check_agent_services()
    if issues:
        logger.warning("=" * 50)
        logger.warning("Agent 服务检查发现问题:")
        for issue in issues:
            logger.warning(f"  - {issue}")
        logger.warning("部分功能可能不可用，请检查配置")
        logger.warning("=" * 50)
    else:
        logger.info("  - Agent 核心服务检查通过")

    logger.info("=" * 50)
    logger.info("DeepAudit 后端服务已启动")
    logger.info(f"API 文档: http://localhost:8000/docs")
    logger.info("=" * 50)

    yield

    logger.info("DeepAudit 后端服务已关闭")


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Configure CORS - Allow all origins in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "message": "Welcome to DeepAudit API",
        "docs": "/docs",
    }
