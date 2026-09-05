import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentTaskCreate(BaseModel):
    """创建 Agent 任务请求"""

    project_id: str = Field(..., description="项目 ID")
    name: Optional[str] = Field(None, description="任务名称")
    description: Optional[str] = Field(None, description="任务描述")

    # 审计配置
    audit_scope: Optional[dict] = Field(None, description="审计范围")
    target_vulnerabilities: Optional[List[str]] = Field(
        default=["sql_injection", "xss", "command_injection", "path_traversal", "ssrf"],
        description="目标漏洞类型",
    )
    verification_level: str = Field(
        "sandbox", description="验证级别: analysis_only, sandbox, generate_poc"
    )

    # 分支
    branch_name: Optional[str] = Field(None, description="分支名称")

    # 排除模式
    exclude_patterns: Optional[List[str]] = Field(
        default=["node_modules", "__pycache__", ".git", "*.min.js"], description="排除模式"
    )

    # 文件范围
    target_files: Optional[List[str]] = Field(None, description="指定扫描的文件")

    # Agent 配置
    max_iterations: int = Field(50, ge=1, le=200, description="最大迭代次数")
    timeout_seconds: int = Field(1800, ge=60, le=7200, description="超时时间（秒）")


class AgentTaskResponse(BaseModel):
    """Agent 任务响应 - 包含所有前端需要的字段"""

    id: str
    project_id: str
    name: Optional[str]
    description: Optional[str]
    task_type: str = "agent_audit"
    status: str
    current_phase: Optional[str]
    current_step: Optional[str] = None

    # 进度统计
    total_files: int = 0
    indexed_files: int = 0
    analyzed_files: int = 0
    total_chunks: int = 0

    # Agent 统计
    total_iterations: int = 0
    tool_calls_count: int = 0
    tokens_used: int = 0

    # 发现统计（兼容两种命名）
    findings_count: int = 0
    total_findings: int = 0  # 兼容字段
    verified_count: int = 0
    verified_findings: int = 0  # 兼容字段
    false_positive_count: int = 0

    # 严重程度统计
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    # 评分
    quality_score: float = 0.0
    security_score: Optional[float] = None

    # 进度百分比
    progress_percentage: float = 0.0

    # 时间
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 配置
    audit_scope: Optional[dict] = None
    target_vulnerabilities: Optional[List[str]] = None
    verification_level: Optional[str] = None
    exclude_patterns: Optional[List[str]] = None
    target_files: Optional[List[str]] = None

    # 错误信息
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class AgentEventResponse(BaseModel):
    """Agent 事件响应"""

    id: str
    task_id: str
    event_type: str
    phase: Optional[str]
    message: Optional[str] = None
    sequence: int
    # 🔥 ORM 字段名是 created_at，序列化为 timestamp
    created_at: datetime = Field(serialization_alias="timestamp")

    # 工具相关字段
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Dict[str, Any]] = None
    tool_duration_ms: Optional[int] = None

    # 其他字段
    progress_percent: Optional[float] = None
    finding_id: Optional[str] = None
    tokens_used: Optional[int] = None
    # 🔥 ORM 字段名是 event_metadata，序列化为 metadata
    event_metadata: Optional[Dict[str, Any]] = Field(default=None, serialization_alias="metadata")

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
        "by_alias": True,  # 🔥 关键：确保序列化时使用别名
    }


class AgentFindingResponse(BaseModel):
    """Agent 发现响应"""

    id: str
    task_id: str
    vulnerability_type: str
    severity: str
    title: str
    description: Optional[str]
    file_path: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    code_snippet: Optional[str]

    is_verified: bool
    # 🔥 FIX: Map from ai_confidence in ORM, make Optional with default
    confidence: Optional[float] = Field(default=0.5, validation_alias="ai_confidence")
    status: str

    suggestion: Optional[str] = None
    poc: Optional[dict] = None

    created_at: datetime

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,  # Allow both 'confidence' and 'ai_confidence'
    }


class TaskSummaryResponse(BaseModel):
    """任务摘要响应"""

    task_id: str
    status: str
    security_score: Optional[int]

    total_findings: int
    verified_findings: int

    severity_distribution: Dict[str, int]
    vulnerability_types: Dict[str, int]

    duration_seconds: Optional[int]
    phases_completed: List[str]


class AgentTreeNodeResponse(BaseModel):
    """Agent 树节点响应"""

    id: str
    agent_id: str
    agent_name: str
    agent_type: str
    parent_agent_id: Optional[str] = None
    depth: int = 0
    task_description: Optional[str] = None
    knowledge_modules: Optional[List[str]] = None
    status: str = "created"
    result_summary: Optional[str] = None
    findings_count: int = 0
    iterations: int = 0
    tokens_used: int = 0
    tool_calls: int = 0
    duration_ms: Optional[int] = None
    children: List["AgentTreeNodeResponse"] = []

    class Config:
        from_attributes = True


class AgentTreeResponse(BaseModel):
    """Agent 树响应"""

    task_id: str
    root_agent_id: Optional[str] = None
    total_agents: int = 0
    running_agents: int = 0
    completed_agents: int = 0
    failed_agents: int = 0
    total_findings: int = 0
    nodes: List[AgentTreeNodeResponse] = []


class CheckpointResponse(BaseModel):
    """检查点响应"""

    id: str
    agent_id: str
    agent_name: str
    agent_type: str
    iteration: int
    status: str
    total_tokens: int = 0
    tool_calls: int = 0
    findings_count: int = 0
    checkpoint_type: str = "auto"
    checkpoint_name: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True
