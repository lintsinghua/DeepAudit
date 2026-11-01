"""
Agent 审计任务模型
支持 AI Agent 自主漏洞挖掘和验证
"""

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import (
    Column, String, Integer, Float, Text, Boolean, 
    DateTime, ForeignKey, Enum as SQLEnum, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from .project import Project


class AgentTaskStatus:
    """Agent 任务状态"""
    PENDING = "pending"           # 等待执行
    INITIALIZING = "initializing" # 初始化中
    RUNNING = "running"           # 运行中
    PLANNING = "planning"         # 规划阶段
    INDEXING = "indexing"         # 索引阶段
    ANALYZING = "analyzing"       # 分析阶段
    VERIFYING = "verifying"       # 验证阶段
    REPORTING = "reporting"       # 报告生成
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 已取消
    PAUSED = "paused"             # 已暂停


class AgentTaskPhase:
    """Agent 执行阶段"""
    PLANNING = "planning"
    INDEXING = "indexing"
    RECONNAISSANCE = "reconnaissance"
    ANALYSIS = "analysis"
    VERIFICATION = "verification"
    REPORTING = "reporting"


class AgentTask(Base):
    """Agent 审计任务"""
    __tablename__ = "agent_tasks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    # 任务基本信息
    name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    task_type = Column(String(50), default="agent_audit")
    
    # 任务配置
    audit_scope = Column(JSON, nullable=True)  # 审计范围配置
    target_vulnerabilities = Column(JSON, nullable=True)  # 目标漏洞类型
    verification_level = Column(String(50), default="sandbox")  # analysis_only, sandbox, generate_poc
    
    # 分支信息（仓库项目）
    branch_name = Column(String(255), nullable=True)
    
    # 排除模式
    exclude_patterns = Column(JSON, nullable=True)
    
    # 文件范围
    target_files = Column(JSON, nullable=True)  # 指定扫描的文件列表
    
    # LLM 配置
    llm_config = Column(JSON, nullable=True)  # LLM 配置
    
    # Agent 配置
    agent_config = Column(JSON, nullable=True)  # Agent 特定配置
    max_iterations = Column(Integer, default=50)  # 最大迭代次数
    token_budget = Column(Integer, default=100000)  # Token 预算
    timeout_seconds = Column(Integer, default=1800)  # 超时时间（秒）
    
    # 状态
    status = Column(String(20), default=AgentTaskStatus.PENDING)
    current_phase = Column(String(50), nullable=True)
    current_step = Column(String(255), nullable=True)  # 当前执行步骤描述
    error_message = Column(Text, nullable=True)
    
    # 进度统计
    total_files = Column(Integer, default=0)
    indexed_files = Column(Integer, default=0)
    analyzed_files = Column(Integer, default=0)  # 实际扫描过的文件数
    files_with_findings = Column(Integer, default=0)  # 有漏洞发现的文件数
    total_chunks = Column(Integer, default=0)  # 代码块总数
    
    # Agent 统计
    total_iterations = Column(Integer, default=0)  # Agent 迭代次数
    tool_calls_count = Column(Integer, default=0)  # 工具调用次数
    tokens_used = Column(Integer, default=0)  # 已使用 Token 数
    
    # 发现统计
    findings_count = Column(Integer, default=0)  # 发现总数
    verified_count = Column(Integer, default=0)  # 已验证数
    false_positive_count = Column(Integer, default=0)  # 误报数
    
    # 严重程度统计
    critical_count = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    medium_count = Column(Integer, default=0)
    low_count = Column(Integer, default=0)
    
    # 质量评分
    quality_score = Column(Float, default=0.0)
    security_score = Column(Float, default=0.0)
    
    # 审计计划
    audit_plan = Column(JSON, nullable=True)  # Agent 生成的审计计划
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # 创建者
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    
    # 关联关系
    project = relationship("Project", back_populates="agent_tasks")
    events = relationship("AgentEvent", back_populates="task", cascade="all, delete-orphan", order_by="AgentEvent.created_at")
    findings = relationship("AgentFinding", back_populates="task", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<AgentTask {self.id} - {self.status}>"
    
    @property
    def progress_percentage(self) -> float:
        """计算进度百分比"""
        if self.status == AgentTaskStatus.COMPLETED:
            return 100.0
        if self.status in [AgentTaskStatus.FAILED, AgentTaskStatus.CANCELLED]:
            return 0.0
        
        phase_weights = {
            AgentTaskPhase.PLANNING: 5,
            AgentTaskPhase.INDEXING: 15,
            AgentTaskPhase.RECONNAISSANCE: 10,
            AgentTaskPhase.ANALYSIS: 50,
            AgentTaskPhase.VERIFICATION: 15,
            AgentTaskPhase.REPORTING: 5,
        }
        
        completed_weight = 0
        current_found = False
        
        for phase, weight in phase_weights.items():
            if phase == self.current_phase:
                current_found = True
                # 估算当前阶段进度
                if phase == AgentTaskPhase.INDEXING and self.total_files > 0:
                    completed_weight += weight * (self.indexed_files / self.total_files)
                elif phase == AgentTaskPhase.ANALYSIS and self.total_files > 0:
                    completed_weight += weight * (self.analyzed_files / self.total_files)
                else:
                    completed_weight += weight * 0.5
                break
            elif not current_found:
                completed_weight += weight
        
        return min(completed_weight, 99.0)


class AgentEventType:
    """Agent 事件类型"""
    # 系统事件
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"
    TASK_CANCEL = "task_cancel"
    
    # 阶段事件
    PHASE_START = "phase_start"
    PHASE_COMPLETE = "phase_complete"
    
    # Agent 思考
    THINKING = "thinking"
    PLANNING = "planning"
    DECISION = "decision"
    
    # 工具调用
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    
    # RAG 相关
    RAG_QUERY = "rag_query"
    RAG_RESULT = "rag_result"
    
    # 发现相关
    FINDING_NEW = "finding_new"
    FINDING_UPDATE = "finding_update"
    FINDING_VERIFIED = "finding_verified"
    FINDING_FALSE_POSITIVE = "finding_false_positive"
    
    # 沙箱相关
    SANDBOX_START = "sandbox_start"
    SANDBOX_EXEC = "sandbox_exec"
    SANDBOX_RESULT = "sandbox_result"
    SANDBOX_ERROR = "sandbox_error"
    
    # 进度
    PROGRESS = "progress"
    
    # 日志
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"


class AgentEvent(Base):
    """Agent 执行事件（用于实时日志和回放）"""
    __tablename__ = "agent_events"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # 事件信息
    event_type = Column(String(50), nullable=False, index=True)
    phase = Column(String(50), nullable=True)
    
    # 事件内容
    message = Column(Text, nullable=True)
    
    # 工具调用相关
    tool_name = Column(String(100), nullable=True)
    tool_input = Column(JSON, nullable=True)
    tool_output = Column(JSON, nullable=True)
    tool_duration_ms = Column(Integer, nullable=True)  # 工具执行时长（毫秒）
    
    # 关联的发现
    finding_id = Column(String(36), nullable=True)
    
    # Token 消耗
    tokens_used = Column(Integer, default=0)
    
    # 元数据
    event_metadata = Column(JSON, nullable=True)
    
    # 序号（用于排序）
    sequence = Column(Integer, default=0, index=True)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # 关联关系
    task = relationship("AgentTask", back_populates="events")
    
    def __repr__(self):
        return f"<AgentEvent {self.event_type} - {self.message[:50] if self.message else ''}>"
    
    def to_sse_dict(self) -> dict:
        """转换为 SSE 事件格式"""
        return {
            "id": self.id,
            "type": self.event_type,
            "phase": self.phase,
            "message": self.message,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
            "tool_duration_ms": self.tool_duration_ms,
            "finding_id": self.finding_id,
            "tokens_used": self.tokens_used,
            "metadata": self.event_metadata,
            "sequence": self.sequence,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
        }


class VulnerabilitySeverity:
    """漏洞严重程度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class VulnerabilityType:
    """漏洞类型"""
    SQL_INJECTION = "sql_injection"
    NOSQL_INJECTION = "nosql_injection"
    XSS = "xss"
    COMMAND_INJECTION = "command_injection"
    CODE_INJECTION = "code_injection"
    PATH_TRAVERSAL = "path_traversal"
    FILE_INCLUSION = "file_inclusion"
    SSRF = "ssrf"
    XXE = "xxe"
    DESERIALIZATION = "deserialization"
    AUTH_BYPASS = "auth_bypass"
    IDOR = "idor"
    SENSITIVE_DATA_EXPOSURE = "sensitive_data_exposure"
    HARDCODED_SECRET = "hardcoded_secret"
    WEAK_CRYPTO = "weak_crypto"
    RACE_CONDITION = "race_condition"
    BUSINESS_LOGIC = "business_logic"
    MEMORY_CORRUPTION = "memory_corruption"
    OTHER = "other"


class FindingStatus:
    """发现状态"""
    NEW = "new"               # 新发现
    ANALYZING = "analyzing"   # 分析中
    VERIFIED = "verified"     # 已验证
    FALSE_POSITIVE = "false_positive"  # 误报
    NEEDS_REVIEW = "needs_review"      # 需要人工审核
    FIXED = "fixed"           # 已修复
    WONT_FIX = "wont_fix"     # 不修复
    DUPLICATE = "duplicate"   # 重复


class AgentFinding(Base):
    """Agent 发现的漏洞"""
    __tablename__ = "agent_findings"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # 漏洞基本信息
    vulnerability_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    
    # 位置信息
    file_path = Column(String(500), nullable=True, index=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    column_start = Column(Integer, nullable=True)
    column_end = Column(Integer, nullable=True)
    function_name = Column(String(255), nullable=True)
    class_name = Column(String(255), nullable=True)
    
    # 代码片段
    code_snippet = Column(Text, nullable=True)
    code_context = Column(Text, nullable=True)  # 更多上下文
    
    # 数据流信息
    source = Column(Text, nullable=True)  # 污点源
    sink = Column(Text, nullable=True)    # 危险函数
    dataflow_path = Column(JSON, nullable=True)  # 数据流路径
    
    # 验证信息
    status = Column(String(30), default=FindingStatus.NEW, index=True)
    verdict = Column(String(30), nullable=True, index=True)  # confirmed / likely / uncertain / false_positive
    is_verified = Column(Boolean, default=False)
    verification_method = Column(Text, nullable=True)
    verification_result = Column(JSON, nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    # PoC
    has_poc = Column(Boolean, default=False)
    poc_code = Column(Text, nullable=True)
    poc_description = Column(Text, nullable=True)
    poc_steps = Column(JSON, nullable=True)  # 复现步骤
    
    # 修复建议
    suggestion = Column(Text, nullable=True)
    fix_code = Column(Text, nullable=True)
    fix_description = Column(Text, nullable=True)
    references = Column(JSON, nullable=True)  # 参考链接 CWE, OWASP 等
    
    # AI 解释
    ai_explanation = Column(Text, nullable=True)
    ai_confidence = Column(Float, nullable=True)  # AI 置信度 0-1
    
    # XAI (可解释AI)
    xai_what = Column(Text, nullable=True)
    xai_why = Column(Text, nullable=True)
    xai_how = Column(Text, nullable=True)
    xai_impact = Column(Text, nullable=True)
    
    # 关联规则
    matched_rule_code = Column(String(100), nullable=True)
    matched_pattern = Column(Text, nullable=True)
    
    # CVSS 评分（可选）
    cvss_score = Column(Float, nullable=True)
    cvss_vector = Column(String(100), nullable=True)
    
    # 元数据
    finding_metadata = Column(JSON, nullable=True)
    tags = Column(JSON, nullable=True)
    
    # 去重标识
    fingerprint = Column(String(64), nullable=True, index=True)  # 用于去重的指纹
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关联关系
    task = relationship("AgentTask", back_populates="findings")
    
    def __repr__(self):
        return f"<AgentFinding {self.vulnerability_type} - {self.severity} - {self.file_path}>"
    
    def generate_fingerprint(self) -> str:
        """生成去重指纹"""
        import hashlib
        components = [
            self.vulnerability_type or "",
            self.file_path or "",
            str(self.line_start or 0),
            self.function_name or "",
            (self.code_snippet or "")[:200],
        ]
        content = "|".join(components)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "vulnerability_type": self.vulnerability_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "code_snippet": self.code_snippet,
            "status": self.status,
            "is_verified": self.is_verified,
            "has_poc": self.has_poc,
            "poc_code": self.poc_code,
            "suggestion": self.suggestion,
            "fix_code": self.fix_code,
            "ai_explanation": self.ai_explanation,
            "ai_confidence": self.ai_confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentCheckpoint(Base):
    """
    Agent 检查点
    
    用于持久化 Agent 状态，支持：
    - 任务恢复
    - 状态回滚
    - 执行历史追踪
    """
    __tablename__ = "agent_checkpoints"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Agent 信息
    agent_id = Column(String(50), nullable=False, index=True)
    agent_name = Column(String(255), nullable=False)
    agent_type = Column(String(50), nullable=False)
    parent_agent_id = Column(String(50), nullable=True)
    
    # 状态数据（JSON 序列化的 AgentState）
    state_data = Column(Text, nullable=False)
    
    # 执行状态
    iteration = Column(Integer, default=0)
    status = Column(String(30), nullable=False)
    
    # 统计信息
    total_tokens = Column(Integer, default=0)
    tool_calls = Column(Integer, default=0)
    findings_count = Column(Integer, default=0)
    
    # 检查点类型
    checkpoint_type = Column(String(30), default="auto")  # auto, manual, error, final
    checkpoint_name = Column(String(255), nullable=True)
    
    # 元数据
    checkpoint_metadata = Column(JSON, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    def __repr__(self):
        return f"<AgentCheckpoint {self.agent_id} - iter {self.iteration}>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "parent_agent_id": self.parent_agent_id,
            "iteration": self.iteration,
            "status": self.status,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "findings_count": self.findings_count,
            "checkpoint_type": self.checkpoint_type,
            "checkpoint_name": self.checkpoint_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentTreeNode(Base):
    """
    Agent 树节点
    
    记录动态 Agent 树的结构，用于：
    - 可视化 Agent 树
    - 追踪 Agent 间关系
    - 分析执行流程
    """
    __tablename__ = "agent_tree_nodes"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Agent 信息
    agent_id = Column(String(50), nullable=False, unique=True, index=True)
    agent_name = Column(String(255), nullable=False)
    agent_type = Column(String(50), nullable=False)
    
    # 树结构
    parent_agent_id = Column(String(50), nullable=True, index=True)
    depth = Column(Integer, default=0)  # 树深度
    
    # 任务信息
    task_description = Column(Text, nullable=True)
    knowledge_modules = Column(JSON, nullable=True)
    
    # 执行状态
    status = Column(String(30), default="created")
    
    # 执行结果
    result_summary = Column(Text, nullable=True)
    findings_count = Column(Integer, default=0)
    
    # 统计
    iterations = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    tool_calls = Column(Integer, default=0)
    duration_ms = Column(Integer, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f"<AgentTreeNode {self.agent_name} ({self.agent_id})>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "parent_agent_id": self.parent_agent_id,
            "depth": self.depth,
            "task_description": self.task_description,
            "knowledge_modules": self.knowledge_modules,
            "status": self.status,
            "result_summary": self.result_summary,
            "findings_count": self.findings_count,
            "iterations": self.iterations,
            "tokens_used": self.tokens_used,
            "tool_calls": self.tool_calls,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
