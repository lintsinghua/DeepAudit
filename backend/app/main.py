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
        r = redis.from_url(redis_url)
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
    启动时初始化数据库（创建默认账户等）
    """
    logger.info("DeepAudit 后端服务启动中...")

    # 初始化数据库（创建默认账户）
    # 注意：需要先运行 alembic upgrade head 创建表结构
    try:
        async with AsyncSessionLocal() as db:
            await init_db(db)
        logger.info("  - 数据库初始化完成")
    except Exception as e:
        if settings.ENVIRONMENT == "production":
            # Bootstrap also disables legacy default credentials: fail closed.
            raise
        # 表不存在时静默跳过，等待用户运行数据库迁移
        error_msg = str(e)
        if "does not exist" in error_msg or "UndefinedTableError" in error_msg:
            logger.info("数据库表未创建，请先运行: alembic upgrade head")
        else:
            logger.warning(f"数据库初始化跳过: {e}")

    logger.info("审计任务通过持久化队列交由独立 worker 执行")

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

from app.core.upload_limit import UploadLimitMiddleware
app.add_middleware(UploadLimitMiddleware)

# Same-origin deployments need no CORS entries; cross-origin clients are explicit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).rstrip("/") for origin in settings.BACKEND_CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
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


@app.get("/ready")
async def readiness():
    from fastapi.responses import JSONResponse
    from sqlalchemy import select
    from app.models.audit_job import AuditJob
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(select(AuditJob.id).limit(1))
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
