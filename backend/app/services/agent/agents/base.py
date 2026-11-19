"""
Agent 基类
定义 Agent 的基本接口和通用功能

核心原则：
1. LLM 是 Agent 的大脑，全程参与决策
2. Agent 之间通过 TaskHandoff 传递结构化上下文
3. 事件分为流式事件（前端展示）和持久化事件（数据库记录）
4. 支持动态Agent树和专业知识模块
5. 完整的状态管理和Agent间通信
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import asyncio
import json
import logging
import uuid

from ..core.state import AgentState, AgentStatus
from ..core.registry import agent_registry
from ..core.message import message_bus, MessageType, AgentMessage

logger = logging.getLogger(__name__)


class AgentType(Enum):
    """Agent 类型"""
    ORCHESTRATOR = "orchestrator"
    RECON = "recon"
    ANALYSIS = "analysis"
    VERIFICATION = "verification"


class AgentPattern(Enum):
    """Agent 运行模式"""
    REACT = "react"                    # 反应式：思考-行动-观察循环
    PLAN_AND_EXECUTE = "plan_execute"  # 计划执行：先规划后执行


@dataclass
class AgentConfig:
    """Agent 配置"""
    name: str
    agent_type: AgentType
    pattern: AgentPattern = AgentPattern.REACT
    
    # LLM 配置
    model: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 8192
    
    # 执行限制
    max_iterations: int = 20
    timeout_seconds: int = 600
    
    # 工具配置
    tools: List[str] = field(default_factory=list)
    
    # 系统提示词
    system_prompt: Optional[str] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    
    # 执行统计
    iterations: int = 0
    tool_calls: int = 0
    tokens_used: int = 0
    duration_ms: int = 0
    
    # 中间结果
    intermediate_steps: List[Dict[str, Any]] = field(default_factory=list)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 🔥 协作信息 - Agent 传递给下一个 Agent 的结构化信息
    handoff: Optional["TaskHandoff"] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "handoff": self.handoff.to_dict() if self.handoff else None,
        }


@dataclass
class TaskHandoff:
    """
    任务交接协议 - Agent 之间传递的结构化信息
    
    设计原则：
    1. 包含足够的上下文让下一个 Agent 理解前序工作
    2. 提供明确的建议和关注点
    3. 可直接转换为 LLM 可理解的 prompt
    """
    # 基本信息
    from_agent: str
    to_agent: str
    
    # 工作摘要
    summary: str
    work_completed: List[str] = field(default_factory=list)
    
    # 关键发现和洞察
    key_findings: List[Dict[str, Any]] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    
    # 建议和关注点
    suggested_actions: List[Dict[str, Any]] = field(default_factory=list)
    attention_points: List[str] = field(default_factory=list)
    priority_areas: List[str] = field(default_factory=list)
    
    # 上下文数据
    context_data: Dict[str, Any] = field(default_factory=dict)
    
    # 置信度
    confidence: float = 0.8
    
    # 时间戳
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "summary": self.summary,
            "work_completed": self.work_completed,
            "key_findings": self.key_findings,
            "insights": self.insights,
            "suggested_actions": self.suggested_actions,
            "attention_points": self.attention_points,
            "priority_areas": self.priority_areas,
            "context_data": self.context_data,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskHandoff":
        return cls(
            from_agent=data.get("from_agent", ""),
            to_agent=data.get("to_agent", ""),
            summary=data.get("summary", ""),
            work_completed=data.get("work_completed", []),
            key_findings=data.get("key_findings", []),
            insights=data.get("insights", []),
            suggested_actions=data.get("suggested_actions", []),
            attention_points=data.get("attention_points", []),
            priority_areas=data.get("priority_areas", []),
            context_data=data.get("context_data", {}),
            confidence=data.get("confidence", 0.8),
        )
    
    def to_prompt_context(self) -> str:
        """
        转换为 LLM 可理解的上下文格式
        这是关键！让 LLM 能够理解前序 Agent 的工作
        """
        lines = [
            f"## 来自 {self.from_agent} Agent 的任务交接",
            "",
            f"### 工作摘要",
            self.summary,
            "",
        ]
        
        if self.work_completed:
            lines.append("### 已完成的工作")
            for work in self.work_completed:
                lines.append(f"- {work}")
            lines.append("")
        
        if self.key_findings:
            lines.append("### 关键发现")
            for i, finding in enumerate(self.key_findings[:15], 1):
                severity = finding.get("severity", "medium")
                title = finding.get("title", "Unknown")
                file_path = finding.get("file_path", "")
                lines.append(f"{i}. [{severity.upper()}] {title}")
                if file_path:
                    lines.append(f"   位置: {file_path}:{finding.get('line_start', '')}")
                if finding.get("description"):
                    lines.append(f"   描述: {finding['description'][:100]}")
            lines.append("")
        
        if self.insights:
            lines.append("### 洞察和分析")
            for insight in self.insights:
                lines.append(f"- {insight}")
            lines.append("")
        
        if self.suggested_actions:
            lines.append("### 建议的下一步行动")
            for action in self.suggested_actions:
                action_type = action.get("type", "general")
                description = action.get("description", "")
                priority = action.get("priority", "medium")
                lines.append(f"- [{priority.upper()}] {action_type}: {description}")
            lines.append("")
        
        if self.attention_points:
            lines.append("### ⚠️ 需要特别关注")
            for point in self.attention_points:
                lines.append(f"- {point}")
            lines.append("")
        
        if self.priority_areas:
            lines.append("### 优先分析区域")
            for area in self.priority_areas:
                lines.append(f"- {area}")
        
        return "\n".join(lines)


class BaseAgent(ABC):
    """
    Agent 基类
    
    核心原则：
    1. LLM 是 Agent 的大脑，全程参与决策
    2. 所有日志应该反映 LLM 的思考过程
    3. 工具调用是 LLM 的决策结果
    
    协作原则：
    1. 通过 TaskHandoff 接收前序 Agent 的上下文
    2. 执行完成后生成 TaskHandoff 传递给下一个 Agent
    3. 洞察和发现应该结构化记录
    
    动态Agent树：
    1. 支持动态创建子Agent
    2. Agent间通过消息总线通信
    3. 完整的状态管理和生命周期
    """
    
    def __init__(
        self,
        config: AgentConfig,
        llm_service,
        tools: Dict[str, Any],
        event_emitter=None,
        parent_id: Optional[str] = None,
        knowledge_modules: Optional[List[str]] = None,
    ):
        """
        初始化 Agent
        
        Args:
            config: Agent 配置
            llm_service: LLM 服务
            tools: 可用工具字典
            event_emitter: 事件发射器
            parent_id: 父Agent ID（用于动态Agent树）
            knowledge_modules: 要加载的知识模块
        """
        self.config = config
        self.llm_service = llm_service
        self.tools = tools
        self.event_emitter = event_emitter
        self.parent_id = parent_id
        self.knowledge_modules = knowledge_modules or []
        
        # 🔥 生成唯一ID
        self._agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        
        # 🔥 增强的状态管理
        self._state = AgentState(
            agent_id=self._agent_id,
            agent_name=config.name,
            agent_type=config.agent_type.value,
            parent_id=parent_id,
            max_iterations=config.max_iterations,
            knowledge_modules=self.knowledge_modules,
        )
        
        # 运行状态（保持向后兼容）
        self._iteration = 0
        self._total_tokens = 0
        self._tool_calls = 0
        self._cancelled = False

        # 获取超时配置
        self._timeout_config = self._get_timeout_config()
        
        # 🔥 协作状态
        self._incoming_handoff: Optional[TaskHandoff] = None
        self._insights: List[str] = []  # 收集的洞察
        self._work_completed: List[str] = []  # 完成的工作记录
        
        # 🔥 是否已注册到注册表
        self._registered = False
        
        # 🔥 加载知识模块到系统提示词
        if self.knowledge_modules:
            self._load_knowledge_modules()
    
    def _register_to_registry(self, task: Optional[str] = None) -> None:
        """注册到Agent注册表（延迟注册，在run时调用）"""
        logger.debug(f"[AgentTree] _register_to_registry 被调用: {self.config.name} (id={self._agent_id}, parent={self.parent_id}, _registered={self._registered})")
        
        if self._registered:
            logger.debug(f"[AgentTree] {self.config.name} 已注册，跳过 (id={self._agent_id})")
            return
        
        logger.debug(f"[AgentTree] 正在注册 Agent: {self.config.name} (id={self._agent_id}, parent={self.parent_id})")
        
        agent_registry.register_agent(
            agent_id=self._agent_id,
            agent_name=self.config.name,
            agent_type=self.config.agent_type.value,
            task=task or self._state.task or "Initializing",
            parent_id=self.parent_id,
            agent_instance=self,
            state=self._state,
            knowledge_modules=self.knowledge_modules,
        )
        
        # 创建消息队列
        message_bus.create_queue(self._agent_id)
        self._registered = True
        
        tree = agent_registry.get_agent_tree()
        logger.debug(f"[AgentTree] Agent 注册完成: {self.config.name}, 当前树节点数: {len(tree['nodes'])}")
    
    def set_parent_id(self, parent_id: str) -> None:
        """设置父Agent ID（在调度时调用）"""
        self.parent_id = parent_id
        self._state.parent_id = parent_id
    
    def _load_knowledge_modules(self) -> None:
        """加载知识模块到系统提示词"""
        if not self.knowledge_modules:
            return

        try:
            from ..knowledge import knowledge_loader

            enhanced_prompt = knowledge_loader.build_system_prompt_with_modules(
                self.config.system_prompt or "",
                self.knowledge_modules,
            )
            self.config.system_prompt = enhanced_prompt

            logger.info(f"[{self.name}] Loaded knowledge modules: {self.knowledge_modules}")
        except Exception as e:
            logger.warning(f"Failed to load knowledge modules: {e}")

    def _get_timeout_config(self) -> Dict[str, int]:
        """
        获取超时配置（秒）

        优先级：用户配置 > 环境变量默认值

        Returns:
            包含各种超时配置的字典
        """
        from app.core.config import settings

        # 尝试从 llm_service 获取用户配置的超时值
        if hasattr(self.llm_service, 'get_agent_timeout_config'):
            return self.llm_service.get_agent_timeout_config()

        # 回退到环境变量默认值
        return {
            'llm_first_token_timeout': getattr(settings, 'LLM_FIRST_TOKEN_TIMEOUT', 30),
            'llm_stream_timeout': getattr(settings, 'LLM_STREAM_TIMEOUT', 60),
            'agent_timeout': getattr(settings, 'AGENT_TIMEOUT_SECONDS', 1800),
            'sub_agent_timeout': getattr(settings, 'SUB_AGENT_TIMEOUT_SECONDS', 600),
            'tool_timeout': getattr(settings, 'TOOL_TIMEOUT_SECONDS', 60),
        }
    
    @property
    def name(self) -> str:
        return self.config.name
    
    @property
    def agent_id(self) -> str:
        return self._agent_id
    
    @property
    def state(self) -> AgentState:
        return self._state
    
    @property
    def agent_type(self) -> AgentType:
        return self.config.agent_type
    
    # ============ Agent间消息处理 ============
    
    def check_messages(self) -> List[AgentMessage]:
        """
        检查并处理收到的消息
        
        Returns:
            未读消息列表
        """
        messages = message_bus.get_messages(
            self._agent_id,
            unread_only=True,
            mark_as_read=True,
        )
        
        for msg in messages:
            # 处理消息
            if msg.from_agent == "user":
                # 用户消息直接添加到对话历史
                self._state.add_message("user", msg.content)
            else:
                # Agent间消息使用XML格式
                self._state.add_message("user", msg.to_xml())
            
            # 如果在等待状态，恢复执行
            if self._state.is_waiting_for_input():
                self._state.resume_from_waiting()
                agent_registry.update_agent_status(self._agent_id, "running")
        
        return messages
    
    def has_pending_messages(self) -> bool:
        """检查是否有待处理的消息"""
        return message_bus.has_unread_messages(self._agent_id)
    
    def send_message_to_parent(
        self,
        content: str,
        message_type: MessageType = MessageType.INFORMATION,
    ) -> None:
        """向父Agent发送消息"""
        if self.parent_id:
            message_bus.send_message(
                from_agent=self._agent_id,
                to_agent=self.parent_id,
                content=content,
                message_type=message_type,
            )
    
    def send_message_to_agent(
        self,
        target_id: str,
        content: str,
        message_type: MessageType = MessageType.INFORMATION,
    ) -> None:
        """向指定Agent发送消息"""
        message_bus.send_message(
            from_agent=self._agent_id,
            to_agent=target_id,
            content=content,
            message_type=message_type,
        )
    
    # ============ 生命周期管理 ============
    
    def on_start(self) -> None:
        """Agent开始执行时调用"""
        self._state.start()
        agent_registry.update_agent_status(self._agent_id, "running")
    
    def on_complete(self, result: Dict[str, Any]) -> None:
        """Agent完成时调用"""
        self._state.set_completed(result)
        agent_registry.update_agent_status(self._agent_id, "completed", result)
        
        # 向父Agent报告完成
        if self.parent_id:
            message_bus.send_completion_report(
                from_agent=self._agent_id,
                to_agent=self.parent_id,
                summary=result.get("summary", "Task completed"),
                findings=result.get("findings", []),
                success=True,
            )
    
    def on_error(self, error: str) -> None:
        """Agent出错时调用"""
        self._state.set_failed(error)
        agent_registry.update_agent_status(self._agent_id, "failed", {"error": error})
    
    @abstractmethod
    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        执行 Agent 任务
        
        Args:
            input_data: 输入数据
            
        Returns:
            Agent 执行结果
        """
        pass
    
    def cancel(self):
        """取消执行"""
        self._cancelled = True
        logger.info(f"[{self.name}] Cancel requested")
    
        # 🔥 外部取消检查回调
        self._cancel_callback = None

    def set_cancel_callback(self, callback) -> None:
        """设置外部取消检查回调"""
        self._cancel_callback = callback

    @property
    def is_cancelled(self) -> bool:
        """检查是否已取消（包含内部标志和外部回调）"""
        if self._cancelled:
            return True
        # 检查外部回调
        if self._cancel_callback and self._cancel_callback():
            self._cancelled = True
            logger.info(f"[{self.name}] Detected cancellation from callback")
            return True
        return False
    
    # ============ 协作方法 ============
    
    def receive_handoff(self, handoff: TaskHandoff):
        """
        接收来自前序 Agent 的任务交接
        
        Args:
            handoff: 任务交接对象
        """
        self._incoming_handoff = handoff
        logger.info(
            f"[{self.name}] Received handoff from {handoff.from_agent}: "
            f"{handoff.summary[:50]}..."
        )
    
    def get_handoff_context(self) -> str:
        """
        获取交接上下文（用于构建 LLM prompt）
        
        Returns:
            格式化的上下文字符串
        """
        if not self._incoming_handoff:
            return ""
        return self._incoming_handoff.to_prompt_context()
    
    def add_insight(self, insight: str):
        """记录洞察"""
        self._insights.append(insight)
    
    def record_work(self, work: str):
        """记录完成的工作"""
        self._work_completed.append(work)
    
    def create_handoff(
        self,
        to_agent: str,
        summary: str,
        key_findings: List[Dict[str, Any]] = None,
        suggested_actions: List[Dict[str, Any]] = None,
        attention_points: List[str] = None,
        priority_areas: List[str] = None,
        context_data: Dict[str, Any] = None,
    ) -> TaskHandoff:
        """
        创建任务交接
        
        Args:
            to_agent: 目标 Agent
            summary: 工作摘要
            key_findings: 关键发现
            suggested_actions: 建议的行动
            attention_points: 需要关注的点
            priority_areas: 优先分析区域
            context_data: 上下文数据
            
        Returns:
            TaskHandoff 对象
        """
        return TaskHandoff(
            from_agent=self.name,
            to_agent=to_agent,
            summary=summary,
            work_completed=self._work_completed.copy(),
            key_findings=key_findings or [],
            insights=self._insights.copy(),
            suggested_actions=suggested_actions or [],
            attention_points=attention_points or [],
            priority_areas=priority_areas or [],
            context_data=context_data or {},
        )
    
    def build_prompt_with_handoff(self, base_prompt: str) -> str:
        """
        构建包含交接上下文的 prompt
        
        Args:
            base_prompt: 基础 prompt
            
        Returns:
            增强后的 prompt
        """
        handoff_context = self.get_handoff_context()
        if not handoff_context:
            return base_prompt
        
        return f"""{base_prompt}

---
## 前序 Agent 交接信息

{handoff_context}

---
请基于以上来自前序 Agent 的信息，结合你的专业能力开展工作。
"""
    
    # ============ 核心事件发射方法 ============
    
    async def emit_event(
        self,
        event_type: str,
        message: str,
        **kwargs
    ):
        """发射事件"""
        if self.event_emitter:
            from ..event_manager import AgentEventData
            
            # 准备 metadata
            metadata = kwargs.get("metadata", {}) or {}
            if "agent_name" not in metadata:
                metadata["agent_name"] = self.name
            
            # 分离已知字段和未知字段
            known_fields = {
                "phase", "tool_name", "tool_input", "tool_output", 
                "tool_duration_ms", "finding_id", "tokens_used"
            }
            
            event_kwargs = {}
            for k, v in kwargs.items():
                if k in known_fields:
                    event_kwargs[k] = v
                elif k != "metadata":
                    # 将未知字段放入 metadata
                    metadata[k] = v
            
            await self.event_emitter.emit(AgentEventData(
                event_type=event_type,
                message=message,
                metadata=metadata,
                **event_kwargs
            ))
    
    # ============ LLM 思考相关事件 ============
    
    async def emit_thinking(self, message: str):
        """发射 LLM 思考事件"""
        await self.emit_event("thinking", message)
    
    async def emit_llm_start(self, iteration: int):
        """发射 LLM 开始思考事件"""
        await self.emit_event(
            "llm_start",
            f"[{self.name}] 第 {iteration} 轮迭代开始",
            metadata={"iteration": iteration}
        )
    
    async def emit_llm_thought(self, thought: str, iteration: int):
        """发射 LLM 思考内容事件 - 这是核心！展示 LLM 在想什么"""
        # 截断过长的思考内容
        display_thought = thought[:500] + "..." if len(thought) > 500 else thought
        await self.emit_event(
            "llm_thought",
            f"[{self.name}] 思考: {display_thought}",
            metadata={
                "thought": thought,
                "iteration": iteration,
            }
        )
    
    async def emit_thinking_start(self):
        """发射开始思考事件（流式输出用）"""
        await self.emit_event("thinking_start", "开始思考...")
    
    async def emit_thinking_token(self, token: str, accumulated: str):
        """发射思考 token 事件（流式输出用）"""
        await self.emit_event(
            "thinking_token",
            "",  # 不需要 message，前端从 metadata 获取
            metadata={
                "token": token,
                "accumulated": accumulated,
            }
        )
    
    async def emit_thinking_end(self, full_response: str):
        """发射思考结束事件（流式输出用）"""
        await self.emit_event(
            "thinking_end",
            "思考完成",
            metadata={"accumulated": full_response}
        )
    
    async def emit_llm_decision(self, decision: str, reason: str = ""):
        """发射 LLM 决策事件 - 展示 LLM 做了什么决定"""
        await self.emit_event(
            "llm_decision",
            f"[{self.name}] 决策: {decision}" + (f" ({reason})" if reason else ""),
            metadata={
                "decision": decision,
                "reason": reason,
            }
        )
    
    async def emit_llm_complete(self, result_summary: str, tokens_used: int):
        """发射 LLM 完成事件"""
        await self.emit_event(
            "llm_complete",
            f"[{self.name}] 完成: {result_summary} (消耗 {tokens_used} tokens)",
            metadata={
                "tokens_used": tokens_used,
            }
        )
    
    async def emit_llm_action(self, action: str, action_input: Dict):
        """发射 LLM 动作决策事件"""
        await self.emit_event(
            "llm_action",
            f"[{self.name}] 执行动作: {action}",
            metadata={
                "action": action,
                "action_input": action_input,
            }
        )
    
    async def emit_llm_observation(self, observation: str):
        """发射 LLM 观察事件"""
        # 截断过长的观察结果
        display_obs = observation[:300] + "..." if len(observation) > 300 else observation
        await self.emit_event(
            "llm_observation",
            f"[{self.name}] 观察结果: {display_obs}",
            metadata={
                "observation": observation[:2000],  # 限制存储长度
            }
        )
    
    # ============ 工具调用相关事件 ============
    
    async def emit_tool_call(self, tool_name: str, tool_input: Dict):
        """发射工具调用事件"""
        await self.emit_event(
            "tool_call",
            f"[{self.name}] 调用工具: {tool_name}",
            tool_name=tool_name,
            tool_input=tool_input,
        )
    
    async def emit_tool_result(self, tool_name: str, result: str, duration_ms: int):
        """发射工具结果事件"""
        # 🔥 修复：确保 result 不为 None，避免显示 "None" 字符串
        safe_result = result if result and result != "None" else ""
        tool_output_dict = {"result": safe_result[:2000] if safe_result else ""}  # 截断长输出
        await self.emit_event(
            "tool_result",
            f"[{self.name}] 工具 {tool_name} 完成 ({duration_ms}ms)",
            tool_name=tool_name,
            tool_output=tool_output_dict,
            tool_duration_ms=duration_ms,
        )
    
    # ============ 发现相关事件 ============

    async def emit_finding(self, title: str, severity: str, vuln_type: str, file_path: str = "", is_verified: bool = False):
        """发射漏洞发现事件"""
        import uuid
        finding_id = str(uuid.uuid4())

        # 🔥 使用 EventManager.emit_finding 发送正确的事件类型
        if self.event_emitter and hasattr(self.event_emitter, 'emit_finding'):
            await self.event_emitter.emit_finding(
                finding_id=finding_id,
                title=title,
                severity=severity,
                vulnerability_type=vuln_type,
                is_verified=is_verified,
            )
        else:
            # 回退：使用通用事件发射
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢",
            }.get(severity.lower(), "⚪")

            event_type = "finding_verified" if is_verified else "finding_new"
            await self.emit_event(
                event_type,
                f"{severity_emoji} [{self.name}] 发现漏洞: [{severity.upper()}] {title}\n   类型: {vuln_type}\n   位置: {file_path}",
                metadata={
                    "id": finding_id,
                    "title": title,
                    "severity": severity,
                    "vulnerability_type": vuln_type,
                    "file_path": file_path,
                    "is_verified": is_verified,
                }
            )
    
    # ============ 通用工具方法 ============
    
    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            **kwargs: 工具参数
            
        Returns:
            工具执行结果
        """
        tool = self.tools.get(tool_name)
        if not tool:
            logger.warning(f"Tool not found: {tool_name}")
            return None
        
        self._tool_calls += 1
        await self.emit_tool_call(tool_name, kwargs)
        
        import time
        start = time.time()
        
        result = await tool.execute(**kwargs)
        
        duration_ms = int((time.time() - start) * 1000)
        await self.emit_tool_result(tool_name, str(result.data)[:500], duration_ms)
        
        return result
    
    async def call_llm(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        调用 LLM
        
        Args:
            messages: 消息列表
            tools: 可用工具描述

        Returns:
            LLM 响应
        """
        self._iteration += 1

        try:
            # 🔥 不传递 temperature 和 max_tokens，让 LLMService 使用用户配置
            response = await self.llm_service.chat_completion(
                messages=messages,
                tools=tools,
            )

            if response.get("usage"):
                self._total_tokens += response["usage"].get("total_tokens", 0)

            return response

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    def get_tool_descriptions(self) -> List[Dict[str, Any]]:
        """获取工具描述（用于 LLM）"""
        descriptions = []
        
        for name, tool in self.tools.items():
            if name.startswith("_"):
                continue
            
            desc = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                }
            }
            
            # 添加参数 schema
            if hasattr(tool, 'args_schema') and tool.args_schema:
                desc["function"]["parameters"] = tool.args_schema.schema()
            
            descriptions.append(desc)
        
        return descriptions
    
    def get_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        return {
            "agent": self.name,
            "type": self.agent_type.value,
            "iterations": self._iteration,
            "tool_calls": self._tool_calls,
            "tokens_used": self._total_tokens,
        }
    
    # ============ Memory Compression ============
    
    def compress_messages_if_needed(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 100000,
    ) -> List[Dict[str, str]]:
        """
        如果消息历史过长，自动压缩
        
        Args:
            messages: 消息列表
            max_tokens: 最大token数
            
        Returns:
            压缩后的消息列表
        """
        from ...llm.memory_compressor import MemoryCompressor
        
        compressor = MemoryCompressor(max_total_tokens=max_tokens)
        
        if compressor.should_compress(messages):
            logger.info(f"[{self.name}] Compressing conversation history...")
            compressed = compressor.compress_history(messages)
            logger.info(f"[{self.name}] Compressed {len(messages)} -> {len(compressed)} messages")
            return compressed
        
        return messages
    
    # ============ 统一的流式 LLM 调用 ============

    async def stream_llm_call(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        auto_compress: bool = True,
    ) -> Tuple[str, int]:
        """
        统一的流式 LLM 调用方法

        所有 Agent 共用此方法，避免重复代码

        Args:
            messages: 消息列表
            temperature: 温度（None 时使用用户配置）
            max_tokens: 最大 token 数（None 时使用用户配置）
            auto_compress: 是否自动压缩过长的消息历史

        Returns:
            (完整响应内容, token数量)
        """
        # 🔥 自动压缩过长的消息历史
        if auto_compress:
            messages = self.compress_messages_if_needed(messages)

        accumulated = ""
        total_tokens = 0

        # 🔥 在开始 LLM 调用前检查取消
        if self.is_cancelled:
            logger.info(f"[{self.name}] Cancelled before LLM call")
            return "", 0

        logger.info(f"[{self.name}] 🚀 Starting stream_llm_call, emitting thinking_start...")
        await self.emit_thinking_start()
        logger.info(f"[{self.name}] ✅ thinking_start emitted, starting LLM stream...")

        try:
            # 获取流式迭代器（传入 None 时使用用户配置）
            stream = self.llm_service.chat_completion_stream(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            # 兼容不同版本的 python async generator
            iterator = stream.__aiter__()

            import time
            first_token_received = False
            last_activity = time.time()

            while True:
                # 检查取消
                if self.is_cancelled:
                    logger.info(f"[{self.name}] Cancelled during LLM streaming loop")
                    break
                
                try:
                    # 🔥 使用用户配置的超时时间
                    # 第一个 token 使用首Token超时，后续 token 使用流式超时
                    first_token_timeout = float(self._timeout_config.get('llm_first_token_timeout', 30))
                    stream_timeout = float(self._timeout_config.get('llm_stream_timeout', 60))
                    timeout = first_token_timeout if not first_token_received else stream_timeout

                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)

                    last_activity = time.time()
                    
                    if chunk["type"] == "token":
                        first_token_received = True
                        token = chunk["content"]
                        # 🔥 累积 content，确保 accumulated 变量更新
                        # 注意：某些 adapter 返回的 chunk["accumulated"] 可能已经包含了累积值，
                        # 但为了安全起见，如果不一致，我们自己累积
                        if "accumulated" in chunk:
                            accumulated = chunk["accumulated"]
                        else:
                            # 如果 adapter 没返回 accumulated，我们自己拼
                            # 注意：如果是 token 类型，content 是增量
                            # 如果 accumulated 被覆盖了，需要小心。
                            # 实际上 service.py 中 chat_completion_stream 保证了 accumulated 存在
                            # 这里我们信任 service 层的 accumulated
                            pass

                        # Double check if accumulated is empty but we have token
                        if not accumulated and token:
                            accumulated += token # Fallback

                        await self.emit_thinking_token(token, accumulated)
                        # 🔥 CRITICAL: 让出控制权给事件循环，让 SSE 有机会发送事件
                        await asyncio.sleep(0)

                    elif chunk["type"] == "keepalive":
                        first_token_received = True
                        last_activity = time.time()

                    elif chunk["type"] == "done":
                        accumulated = chunk["content"]
                        if chunk.get("usage"):
                            total_tokens = chunk["usage"].get("total_tokens", 0)
                        # 🔥 记录推理模型的 reasoning 统计
                        reasoning = chunk.get("reasoning_content", "")
                        reasoning_tokens_est = chunk.get("reasoning_tokens", 0)
                        if reasoning:
                            logger.debug(f"[{self.name}] reasoning_content: {len(reasoning)} chars, ~{reasoning_tokens_est} tokens")
                        break

                    elif chunk["type"] == "error":
                        accumulated = chunk.get("accumulated", "")
                        error_msg = chunk.get("error", "Unknown error")
                        error_type = chunk.get("error_type", "unknown")
                        user_message = chunk.get("user_message", error_msg)
                        logger.error(f"[{self.name}] Stream error ({error_type}): {error_msg}")

                        if chunk.get("usage"):
                            total_tokens = chunk["usage"].get("total_tokens", 0)

                        # 使用特殊前缀标记 API 错误，让调用方能够识别
                        # 格式：[API_ERROR:error_type] user_message
                        if error_type in ("rate_limit", "quota_exceeded", "authentication", "connection"):
                            accumulated = f"[API_ERROR:{error_type}] {user_message}"
                        elif not accumulated:
                            accumulated = f"[系统错误: {error_msg}] 请重新思考并输出你的决策。"
                        break

                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    timeout_type = "First Token" if not first_token_received else "Stream"
                    logger.error(f"[{self.name}] LLM {timeout_type} Timeout ({timeout}s)")
                    error_msg = f"LLM 响应超时 ({timeout_type}, {timeout}s)"
                    await self.emit_event("error", error_msg)
                    if not accumulated:
                         accumulated = f"[超时错误: {timeout}s 无响应] 请尝试简化请求或重试。"
                    break
                    
        except asyncio.CancelledError:
            logger.info(f"[{self.name}] LLM call cancelled")
            raise
        except Exception as e:
            # 🔥 增强异常处理，避免吞掉错误
            logger.error(f"[{self.name}] Unexpected error in stream_llm_call: {e}", exc_info=True)
            await self.emit_event("error", f"LLM 调用错误: {str(e)}")
            accumulated = f"[LLM调用错误: {str(e)}] 请重试。"
        finally:
            await self.emit_thinking_end(accumulated)
        
        # 🔥 记录空响应警告，帮助调试
        if not accumulated or not accumulated.strip():
            logger.warning(f"[{self.name}] Empty LLM response returned (total_tokens: {total_tokens})")
        
        return accumulated, total_tokens
    
    async def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        """
        统一的工具执行方法 - 支持取消和超时

        Args:
            tool_name: 工具名称
            tool_input: 工具参数

        Returns:
            工具执行结果字符串
        """
        # 🔥 在执行工具前检查取消
        if self.is_cancelled:
            return "⚠️ 任务已取消"

        tool = self.tools.get(tool_name)

        if not tool:
            return f"错误: 工具 '{tool_name}' 不存在。可用工具: {list(self.tools.keys())}"

        try:
            self._tool_calls += 1
            await self.emit_tool_call(tool_name, tool_input)

            import time
            start = time.time()

            # 🔥 根据工具类型设置不同的超时时间
            tool_timeouts = {
                "semgrep_scan": 120,      # 外部扫描工具需要更长时间
                "bandit_scan": 90,
                "gitleaks_scan": 60,
                "npm_audit": 90,
                "safety_scan": 60,
                "kunlun_scan": 180,
                "osv_scanner": 60,
                "trufflehog_scan": 90,
                "sandbox_exec": 60,
                "php_test": 30,
                "command_injection_test": 30,
                "sql_injection_test": 30,
                "xss_test": 30,
            }
            # 🔥 使用用户配置的默认工具超时时间
            default_tool_timeout = self._timeout_config.get('tool_timeout', 60)
            timeout = tool_timeouts.get(tool_name, default_tool_timeout)

            # 🔥 使用 asyncio.wait_for 添加超时控制，同时支持取消
            async def execute_with_cancel_check():
                """包装工具执行，定期检查取消状态"""
                # 创建工具执行任务
                execute_task = asyncio.create_task(tool.execute(**tool_input))

                try:
                    # 使用循环定期检查取消状态
                    while not execute_task.done():
                        if self.is_cancelled:
                            execute_task.cancel()
                            try:
                                await execute_task
                            except asyncio.CancelledError:
                                pass
                            raise asyncio.CancelledError("任务已取消")

                        # 等待任务完成或超时检查间隔
                        try:
                            return await asyncio.wait_for(
                                asyncio.shield(execute_task),
                                timeout=0.5  # 每0.5秒检查一次取消状态
                            )
                        except asyncio.TimeoutError:
                            continue  # 继续循环检查

                    return await execute_task
                except asyncio.CancelledError:
                    if not execute_task.done():
                        execute_task.cancel()
                    raise

            try:
                result = await asyncio.wait_for(
                    execute_with_cancel_check(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                duration_ms = int((time.time() - start) * 1000)
                await self.emit_tool_result(tool_name, f"超时 ({timeout}s)", duration_ms)
                return f"⚠️ 工具 '{tool_name}' 执行超时 ({timeout}秒)，请尝试其他方法或减小操作范围。"
            except asyncio.CancelledError:
                duration_ms = int((time.time() - start) * 1000)
                await self.emit_tool_result(tool_name, "已取消", duration_ms)
                return "⚠️ 任务已取消"

            duration_ms = int((time.time() - start) * 1000)
            # 🔥 修复：确保传递有意义的结果字符串，避免 "None"
            result_preview = str(result.data)[:200] if result.data is not None else (result.error[:200] if result.error else "")
            await self.emit_tool_result(tool_name, result_preview, duration_ms)

            # 🔥 工具执行后再次检查取消
            if self.is_cancelled:
                return "⚠️ 任务已取消"

            if result.success:
                output = str(result.data)

                # 包含 metadata 中的额外信息
                if result.metadata:
                    if "issues" in result.metadata:
                        output += f"\n\n发现的问题:\n{json.dumps(result.metadata['issues'], ensure_ascii=False, indent=2)}"
                    if "findings" in result.metadata:
                        output += f"\n\n发现:\n{json.dumps(result.metadata['findings'][:10], ensure_ascii=False, indent=2)}"

                # 截断过长输出
                if len(output) > 6000:
                    output = output[:6000] + f"\n\n... [输出已截断，共 {len(str(result.data))} 字符]"
                return output
            else:
                # 🔥 输出详细的错误信息，包括原始错误
                error_msg = f"""⚠️ 工具执行失败

**工具**: {tool_name}
**参数**: {json.dumps(tool_input, ensure_ascii=False, indent=2) if tool_input else '无'}
**错误**: {result.error}

请根据错误信息调整参数或尝试其他方法。"""
                return error_msg

        except asyncio.CancelledError:
            logger.info(f"[{self.name}] Tool '{tool_name}' execution cancelled")
            return "⚠️ 任务已取消"
        except Exception as e:
            import traceback
            logger.error(f"Tool execution error: {e}")
            # 🔥 输出完整的原始错误信息，包括堆栈跟踪
            error_msg = f"""❌ 工具执行异常

**工具**: {tool_name}
**参数**: {json.dumps(tool_input, ensure_ascii=False, indent=2) if tool_input else '无'}
**错误类型**: {type(e).__name__}
**错误信息**: {str(e)}
**堆栈跟踪**:
```
{traceback.format_exc()}
```

请分析错误原因，可能需要：
1. 检查参数格式是否正确
2. 尝试使用其他工具
3. 如果是权限或资源问题，跳过该操作"""
            return error_msg
    
    def get_tools_description(self) -> str:
        """生成工具描述文本（用于 prompt）"""
        tools_info = []
        for name, tool in self.tools.items():
            if name.startswith("_"):
                continue
            desc = f"- {name}: {getattr(tool, 'description', 'No description')}"
            tools_info.append(desc)
        return "\n".join(tools_info)
