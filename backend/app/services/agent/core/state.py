"""
Agent 状态管理模块

提供完整的Agent状态管理，支持：
- 完整的生命周期管理
- 状态序列化和持久化
- 暂停和恢复
- 动态Agent树结构
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def _generate_agent_id() -> str:
    """生成唯一的Agent ID"""
    return f"agent_{uuid.uuid4().hex[:8]}"


class AgentStatus(str, Enum):
    """Agent 运行状态"""
    CREATED = "created"          # 已创建，未开始
    RUNNING = "running"          # 运行中
    WAITING = "waiting"          # 等待中（等待消息或输入）
    PAUSED = "paused"            # 已暂停
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    STOPPED = "stopped"          # 被停止
    STOPPING = "stopping"        # 正在停止


class AgentState(BaseModel):
    """
    Agent 状态模型
    
    包含Agent执行所需的所有状态信息，支持：
    - 完整的生命周期管理
    - 状态序列化和持久化
    - 暂停和恢复
    - 动态Agent树结构
    """
    
    # ============ 基本信息 ============
    agent_id: str = Field(default_factory=_generate_agent_id)
    agent_name: str = "DeepAudit Agent"
    agent_type: str = "generic"  # recon, analysis, verification, specialist
    parent_id: Optional[str] = None  # 父Agent ID（用于动态Agent树）
    
    # ============ 任务信息 ============
    task: str = ""
    task_context: Dict[str, Any] = Field(default_factory=dict)
    inherited_context: Dict[str, Any] = Field(default_factory=dict)  # 从父Agent继承的上下文
    
    # ============ 知识模块 ============
    knowledge_modules: List[str] = Field(default_factory=list)  # 加载的知识模块名称
    
    # ============ 执行状态 ============
    status: AgentStatus = AgentStatus.CREATED
    iteration: int = 0
    max_iterations: int = 50
    
    # ============ 对话历史 ============
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    system_prompt: str = ""
    
    # ============ 执行记录 ============
    actions_taken: List[Dict[str, Any]] = Field(default_factory=list)
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    
    # ============ 发现列表 ============
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    
    # ============ 时间戳 ============
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    last_updated: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    
    # ============ 等待状态 ============
    waiting_for_input: bool = False
    waiting_start_time: Optional[datetime] = None
    waiting_reason: str = ""
    waiting_timeout_seconds: int = 600  # 10分钟超时
    
    # ============ 最终结果 ============
    final_result: Optional[Dict[str, Any]] = None
    
    # ============ 统计信息 ============
    total_tokens: int = 0
    tool_calls: int = 0
    
    # ============ 标志位 ============
    stop_requested: bool = False
    max_iterations_warning_sent: bool = False
    # ============ PoC / 沙箱交互状态 ============
    poc_code: Optional[str] = None
    sandbox_logs: Dict[str, Any] = Field(default_factory=dict)
    poc_attempts: int = 0
    
    class Config:
        use_enum_values = True
    
    # ============ 状态管理方法 ============
    
    def start(self) -> None:
        """开始执行"""
        self.status = AgentStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._update_timestamp()
    
    def increment_iteration(self) -> None:
        """增加迭代次数"""
        self.iteration += 1
        self._update_timestamp()
    
    def set_completed(self, final_result: Optional[Dict[str, Any]] = None) -> None:
        """标记为完成"""
        self.status = AgentStatus.COMPLETED
        self.final_result = final_result
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self._update_timestamp()
    
    def set_failed(self, error: str) -> None:
        """标记为失败"""
        self.status = AgentStatus.FAILED
        self.add_error(error)
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self._update_timestamp()
    
    def request_stop(self) -> None:
        """请求停止"""
        self.stop_requested = True
        self.status = AgentStatus.STOPPING
        self._update_timestamp()
    
    def set_stopped(self) -> None:
        """标记为已停止"""
        self.status = AgentStatus.STOPPED
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self._update_timestamp()
    
    # ============ 等待状态管理 ============
    
    def enter_waiting_state(self, reason: str = "等待消息") -> None:
        """进入等待状态"""
        self.waiting_for_input = True
        self.waiting_start_time = datetime.now(timezone.utc)
        self.waiting_reason = reason
        self.status = AgentStatus.WAITING
        self._update_timestamp()
    
    def resume_from_waiting(self, new_task: Optional[str] = None) -> None:
        """从等待状态恢复"""
        self.waiting_for_input = False
        self.waiting_start_time = None
        self.waiting_reason = ""
        self.stop_requested = False
        self.status = AgentStatus.RUNNING
        if new_task:
            self.task = new_task
        self._update_timestamp()
    
    def has_waiting_timeout(self) -> bool:
        """检查等待是否超时"""
        if not self.waiting_for_input or not self.waiting_start_time:
            return False
        
        if self.stop_requested or self.status in [AgentStatus.COMPLETED, AgentStatus.FAILED]:
            return False
        
        elapsed = (datetime.now(timezone.utc) - self.waiting_start_time).total_seconds()
        return elapsed > self.waiting_timeout_seconds
    
    def is_waiting_for_input(self) -> bool:
        """是否在等待输入"""
        return self.waiting_for_input
    
    # ============ 执行控制 ============
    
    def should_stop(self) -> bool:
        """是否应该停止"""
        return (
            self.stop_requested or 
            self.status in [AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.STOPPED] or
            self.has_reached_max_iterations()
        )
    
    def has_reached_max_iterations(self) -> bool:
        """是否达到最大迭代次数"""
        return self.iteration >= self.max_iterations
    
    def is_approaching_max_iterations(self, threshold: float = 0.85) -> bool:
        """是否接近最大迭代次数"""
        return self.iteration >= int(self.max_iterations * threshold)
    
    # ============ 消息管理 ============
    
    def add_message(self, role: str, content: Any) -> None:
        """添加消息"""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._update_timestamp()
    
    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """获取对话历史（不含时间戳，用于LLM调用）"""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages]
    
    # ============ 执行记录 ============
    
    def add_action(self, action: Dict[str, Any]) -> None:
        """记录执行的动作"""
        self.actions_taken.append({
            "iteration": self.iteration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
        })
        self.tool_calls += 1
        self._update_timestamp()
    
    def add_observation(self, observation: Dict[str, Any]) -> None:
        """记录观察结果"""
        self.observations.append({
            "iteration": self.iteration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "observation": observation,
        })
        self._update_timestamp()
    
    def add_error(self, error: str) -> None:
        """记录错误"""
        self.errors.append(f"Iteration {self.iteration}: {error}")
        self._update_timestamp()
    
    def add_finding(self, finding: Dict[str, Any]) -> None:
        """添加发现"""
        finding["discovered_at"] = datetime.now(timezone.utc).isoformat()
        finding["discovered_by"] = self.agent_id
        self.findings.append(finding)
        self._update_timestamp()
    
    # ============ 上下文管理 ============
    
    def update_context(self, key: str, value: Any) -> None:
        """更新任务上下文"""
        self.task_context[key] = value
        self._update_timestamp()
    
    def inherit_context(self, parent_context: Dict[str, Any]) -> None:
        """继承父Agent的上下文"""
        self.inherited_context = parent_context.copy()
        self._update_timestamp()
    
    # ============ 统计和摘要 ============
    
    def add_tokens(self, tokens: int) -> None:
        """添加token使用量"""
        self.total_tokens += tokens
        self._update_timestamp()
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """获取执行摘要"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "parent_id": self.parent_id,
            "task": self.task,
            "status": self.status,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "findings_count": len(self.findings),
            "errors_count": len(self.errors),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self._calculate_duration(),
            "knowledge_modules": self.knowledge_modules,
        }
    
    def _calculate_duration(self) -> Optional[float]:
        """计算执行时长"""
        if not self.started_at:
            return None
        
        end_time = self.finished_at or datetime.now(timezone.utc).isoformat()
        start = datetime.fromisoformat(self.started_at.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        return (end - start).total_seconds()
    
    def _update_timestamp(self) -> None:
        """更新最后修改时间"""
        self.last_updated = datetime.now(timezone.utc).isoformat()
