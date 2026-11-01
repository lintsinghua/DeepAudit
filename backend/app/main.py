"""
模块说明：应用模块：main。
"""

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
    """
    检查 Agent 依赖服务的可用性。

    处理流程：
    - 检查 Docker 客户端与守护进程
    - 检查 Redis 连接可用性
    - 返回所有不可用项
    """
    # 存放不可用服务的提示信息
    issues = []

    # 检查 Docker/沙箱服务
    try:
        # 延迟导入，避免未安装时直接报错
        import docker
        # 创建 Docker 客户端
        client = docker.from_env()
        # 发送 ping 以验证可用性
        client.ping()
        # 记录服务可用
        logger.info("  - Docker 服务可用")
    except ImportError:
        # Docker 客户端库未安装
        issues.append("Docker Python 库未安装 (pip install docker)")
    except Exception as e:
        # Docker 服务不可用或连接异常
        issues.append(f"Docker 服务不可用: {e}")

    # 检查 Redis 连接（可选警告）
    try:
        # 延迟导入，避免未安装时直接报错
        import redis
        # 读取环境变量
        import os
        # 获取 Redis 连接地址
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        # 创建 Redis 客户端
        r = redis.from_url(redis_url)
        # 发送 ping 验证连接
        r.ping()
        # 记录服务可用
        logger.info("  - Redis 服务可用")
    except ImportError:
        # Redis 客户端库未安装
        logger.warning("  - Redis Python 库未安装，部分功能可能受限")
    except Exception as e:
        # Redis 服务连接失败
        logger.warning(f"  - Redis 服务连接失败: {e}")

    # 返回不可用服务列表
    return issues


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。

    处理流程：
    - 启动时初始化数据库
    - 检查 Agent 依赖服务
    - 输出启动日志
    - 关闭时输出关闭日志
    """
    # 记录启动日志
    logger.info("DeepAudit 后端服务启动中...")

    # 初始化数据库（创建默认账户）
    # 注意：需要先运行 alembic upgrade head 创建表结构
    try:
        # 打开异步数据库会话
        async with AsyncSessionLocal() as db:
            # 执行初始化逻辑
            await init_db(db)
        # 记录初始化完成
        logger.info("  - 数据库初始化完成")
    except Exception as e:
        # 解析异常信息
        # 表不存在时静默跳过，等待用户运行数据库迁移
        error_msg = str(e)
        # 若表不存在则提示迁移
        if "does not exist" in error_msg or "UndefinedTableError" in error_msg:
            logger.info("数据库表未创建，请先运行: alembic upgrade head")
        else:
            # 其他异常仅记录警告
            logger.warning(f"数据库初始化跳过: {e}")

    # 检查 Agent 服务
    logger.info("检查 Agent 核心服务...")
    # 执行服务检查
    issues = await check_agent_services()
    # 如果存在问题则输出详细信息
    if issues:
        # 打印分隔线
        logger.warning("=" * 50)
        # 打印问题标题
        logger.warning("Agent 服务检查发现问题:")
        # 逐条输出问题
        for issue in issues:
            logger.warning(f"  - {issue}")
        # 输出提醒信息
        logger.warning("部分功能可能不可用，请检查配置")
        # 打印分隔线
        logger.warning("=" * 50)
    else:
        # 记录检查通过
        logger.info("  - Agent 核心服务检查通过")

    # 输出启动信息
    logger.info("=" * 50)
    logger.info("DeepAudit 后端服务已启动")
    logger.info(f"API 文档: http://localhost:8000/docs")
    logger.info("=" * 50)
    logger.info("演示账户: demo@example.com / demo123")
    logger.info("=" * 50)

    # 交出控制权给应用运行
    yield

    # 记录关闭日志
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
    """
    健康检查接口。

    处理流程：
    - 直接返回固定状态
    """
    # 返回健康状态
    return {"status": "ok"}


@app.get("/")
async def root():
    """
    根路径接口。

    处理流程：
    - 返回欢迎信息与文档入口
    """
    # 返回 API 欢迎信息
    return {
        "message": "Welcome to DeepAudit API",
        "docs": "/docs",
        "demo_account": {
            "email": "demo@example.com",
            "password": "demo123"
        }
    }
