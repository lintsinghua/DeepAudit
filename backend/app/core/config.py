"""
模块说明：核心配置与安全组件：config。
"""

from typing import List, Union, Optional
from pydantic import AnyHttpUrl, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "DeepAudit"
    API_V1_STR: str = "/api/v1"
    
    # SECURITY
    SECRET_KEY: str = "changethis_in_production_to_a_long_random_string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    
    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # POSTGRES
    POSTGRES_SERVER: str = "db"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "deepaudit"
    DATABASE_URL: str | None = None

    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: str | None, values: dict[str, any]) -> str:
        if isinstance(v, str):
            return v
        return str(f"postgresql+asyncpg://{values.get('POSTGRES_USER')}:{values.get('POSTGRES_PASSWORD')}@{values.get('POSTGRES_SERVER')}/{values.get('POSTGRES_DB')}")

    # LLM配置
    LLM_PROVIDER: str = "openai"  # gemini, openai, claude, qwen, deepseek, zhipu, moonshot, baidu, minimax, doubao, ollama
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: Optional[str] = None  # 不指定时使用provider的默认模型
    LLM_BASE_URL: Optional[str] = None  # 自定义API端点（如中转站）
    LLM_TIMEOUT: int = 150  # 超时时间（秒）
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096

    # Agent 流式超时配置（秒）
    LLM_FIRST_TOKEN_TIMEOUT: int = 30  # 等待首个Token的超时时间
    LLM_STREAM_TIMEOUT: int = 60  # 流式输出中两个Token之间的超时时间
    SUB_AGENT_TIMEOUT_SECONDS: int = 600  # 子Agent超时时间（10分钟）
    TOOL_TIMEOUT_SECONDS: int = 60  # 工具执行默认超时时间
    
    # 各LLM提供商的API Key配置（兼容单独配置）
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None
    QWEN_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    ZHIPU_API_KEY: Optional[str] = None
    MOONSHOT_API_KEY: Optional[str] = None
    BAIDU_API_KEY: Optional[str] = None  # 格式: api_key:secret_key
    MINIMAX_API_KEY: Optional[str] = None
    DOUBAO_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: Optional[str] = "http://localhost:11434/v1"
    
    # GitHub配置
    GITHUB_TOKEN: Optional[str] = None
    
    # GitLab配置
    GITLAB_TOKEN: Optional[str] = None
    
    # Gitea配置
    GITEA_TOKEN: Optional[str] = None
    
    # 扫描配置
    MAX_ANALYZE_FILES: int = 0  # 最大分析文件数，0表示无限制
    MAX_FILE_SIZE_BYTES: int = 200 * 1024  # 最大文件大小 200KB
    LLM_CONCURRENCY: int = 3  # LLM并发数
    LLM_GAP_MS: int = 2000  # LLM请求间隔（毫秒）
    
    # ZIP文件存储配置
    ZIP_STORAGE_PATH: str = "./uploads/zip_files"  # ZIP文件存储目录
    
    # 输出语言配置 - 支持 zh-CN（中文）和 en-US（英文）
    OUTPUT_LANGUAGE: str = "zh-CN"
    
    # ============ Agent 模块配置 ============

    # 嵌入模型配置（独立于 LLM 配置）
    EMBEDDING_PROVIDER: str = "openai"  # openai, azure, ollama, cohere, huggingface, jina, qwen
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: Optional[str] = None  # 嵌入模型专用 API Key（留空则使用 LLM_API_KEY）
    EMBEDDING_BASE_URL: Optional[str] = None  # 嵌入模型专用 Base URL（留空使用提供商默认地址）
    
    # 向量数据库配置
    VECTOR_DB_PATH: str = "./data/vector_db"  # 向量数据库持久化目录

    # SSH配置
    SSH_CONFIG_PATH: str = "./data/ssh"  # SSH配置目录（存储known_hosts等）
    SSH_CLONE_TIMEOUT: int = 300  # SSH克隆超时时间（秒）
    SSH_TEST_TIMEOUT: int = 15  # SSH测试连接超时时间（秒）
    SSH_CONNECT_TIMEOUT: int = 10  # SSH连接超时时间（秒）
    
    # Agent 配置
    AGENT_MAX_ITERATIONS: int = 50  # Agent 最大迭代次数
    AGENT_TOKEN_BUDGET: int = 100000  # Agent Token 预算
    AGENT_TIMEOUT_SECONDS: int = 1800  # Agent 超时时间（30分钟）
    
    # 沙箱配置（必须）
    SANDBOX_IMAGE: str = "deepaudit/sandbox:latest"  # 沙箱 Docker 镜像
    SANDBOX_MEMORY_LIMIT: str = "512m"  # 沙箱内存限制
    SANDBOX_CPU_LIMIT: float = 1.0  # 沙箱 CPU 限制
    SANDBOX_TIMEOUT: int = 60  # 沙箱命令超时（秒）
    SANDBOX_NETWORK_MODE: str = "none"  # 沙箱网络模式 (none, bridge)
    SANDBOX_CAP_DROP: str = "SYS_ADMIN,NET_ADMIN,SYS_PTRACE,SYS_RAWIO,SYS_MODULE,SYS_BOOT,MKNOD,AUDIT_WRITE,AUDIT_CONTROL,SETFCAP,MAC_OVERRIDE,MAC_ADMIN"  # 丢弃的 Linux 能力，逗号分隔，设置 ALL 丢弃全部
    SANDBOX_NO_NEW_PRIVILEGES: bool = True  # 禁止提权，某些环境可能需要关闭
    
    # RAG 配置
    RAG_CHUNK_SIZE: int = 1500  # 代码块大小（Token）
    RAG_CHUNK_OVERLAP: int = 50  # 代码块重叠（Token）
    RAG_TOP_K: int = 10  # 检索返回数量

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"  # 忽略额外的环境变量（如 VITE_* 前端变量）


settings = Settings()
