"""
动态 Agent 树执行器

实现完整的动态 Agent 树执行逻辑：
- 子 Agent 实际执行
- 并行 Agent 执行
- 结果汇总
- 执行状态追踪
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from .state import AgentState, AgentStatus
from .registry import agent_registry
from .message import message_bus, MessageType
from ..config import get_agent_config

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """执行模式"""
    SEQUENTIAL = "sequential"  # 顺序执行
    PARALLEL = "parallel"      # 并行执行
    ADAPTIVE = "adaptive"      # 自适应（根据任务类型决定）


@dataclass
class ExecutionTask:
    """执行任务"""
    agent_id: str
    agent_type: str
    task: str
    context: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # 优先级，数字越大优先级越高
    dependencies: List[str] = field(default_factory=list)  # 依赖的其他任务 ID
    
    # 执行状态
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    total_agents: int = 0
    completed_agents: int = 0
    failed_agents: int = 0
    
    # 汇总的发现
    all_findings: List[Dict[str, Any]] = field(default_factory=list)
    
    # 各 Agent 的结果
    agent_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # 执行统计
    total_duration_ms: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    
    # 错误信息
    errors: List[str] = field(default_factory=list)


class DynamicAgentExecutor:
    """
    动态 Agent 树执行器
    
    负责：
    1. 管理 Agent 的创建和执行
    2. 处理并行执行和依赖关系
    3. 汇总执行结果
    4. 处理错误和超时
    """
    
    def __init__(
        self,
        llm_service,
        tools: Dict[str, Any],
        event_emitter=None,
        max_parallel: int = 5,
        default_timeout: Optional[int] = None,
    ):
        """
        初始化执行器
        
        Args:
            llm_service: LLM 服务
            tools: 可用工具
            event_emitter: 事件发射器
            max_parallel: 最大并行 Agent 数
            default_timeout: 默认超时时间（秒）
        """
        self.llm_service = llm_service
        self.tools = tools
        self.event_emitter = event_emitter
        self.max_parallel = max_parallel
        self.default_timeout = (
            default_timeout if default_timeout is not None
            else get_agent_config().sub_agent_timeout_seconds
        )
        
        # 执行状态
        self._tasks: Dict[str, ExecutionTask] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_parallel)
        
        # 取消标志
        self._cancelled = False
    
    def cancel(self):
        """取消所有执行"""
        self._cancelled = True
        
        # 取消所有运行中的任务
        for task_id, task in self._running_tasks.items():
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled task: {task_id}")
    
    @property
    def is_cancelled(self) -> bool:
        return self._cancelled
    
    async def execute_agent(
        self,
        agent_class,
        agent_config: Dict[str, Any],
        input_data: Dict[str, Any],
        parent_id: Optional[str] = None,
        knowledge_modules: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行单个 Agent
        
        Args:
            agent_class: Agent 类
            agent_config: Agent 配置
            input_data: 输入数据
            parent_id: 父 Agent ID
            knowledge_modules: 知识模块列表
            
        Returns:
            Agent 执行结果
        """
        if self._cancelled:
            return {"success": False, "error": "Execution cancelled"}
        
        async with self._semaphore:
            try:
                # 创建 Agent 实例
                agent = agent_class(
                    llm_service=self.llm_service,
                    tools=self.tools,
                    event_emitter=self.event_emitter,
                    parent_id=parent_id,
                    knowledge_modules=knowledge_modules,
                    **agent_config,
                )
                
                # 执行 Agent
                start_time = time.time()
                result = await asyncio.wait_for(
                    agent.run(input_data),
                    timeout=self.default_timeout,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                
                return {
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                    "agent_id": agent.agent_id,
                    "iterations": result.iterations,
                    "tokens_used": result.tokens_used,
                    "tool_calls": result.tool_calls,
                    "duration_ms": duration_ms,
                    "handoff": result.handoff.to_dict() if result.handoff else None,
                }
                
            except asyncio.TimeoutError:
                logger.error(f"Agent execution timed out")
                return {"success": False, "error": "Execution timed out"}
            except asyncio.CancelledError:
                logger.info(f"Agent execution cancelled")
                return {"success": False, "error": "Execution cancelled"}
            except Exception as e:
                logger.error(f"Agent execution failed: {e}", exc_info=True)
                return {"success": False, "error": str(e)}
    
    async def execute_parallel(
        self,
        tasks: List[ExecutionTask],
        agent_factory: Callable[[ExecutionTask], Awaitable[Dict[str, Any]]],
    ) -> ExecutionResult:
        """
        并行执行多个 Agent 任务
        
        Args:
            tasks: 任务列表
            agent_factory: Agent 工厂函数，接收任务返回执行结果
            
        Returns:
            汇总的执行结果
        """
        if not tasks:
            return ExecutionResult(success=True)
        
        start_time = time.time()
        
        # 按优先级排序
        sorted_tasks = sorted(tasks, key=lambda t: t.priority, reverse=True)
        
        # 分离有依赖和无依赖的任务
        independent_tasks = [t for t in sorted_tasks if not t.dependencies]
        dependent_tasks = [t for t in sorted_tasks if t.dependencies]
        
        # 存储任务
        for task in sorted_tasks:
            self._tasks[task.agent_id] = task
        
        result = ExecutionResult(
            success=True,
            total_agents=len(tasks),
        )
        
        # 先执行无依赖的任务
        if independent_tasks:
            await self._execute_task_batch(independent_tasks, agent_factory, result)
        
        # 然后执行有依赖的任务
        for task in dependent_tasks:
            if self._cancelled:
                break
            
            # 等待依赖完成
            await self._wait_for_dependencies(task)
            
            # 执行任务
            await self._execute_single_task(task, agent_factory, result)
        
        # 计算总时长
        result.total_duration_ms = int((time.time() - start_time) * 1000)
        
        # 判断整体成功状态
        result.success = result.failed_agents == 0
        
        return result
    
    async def _execute_task_batch(
        self,
        tasks: List[ExecutionTask],
        agent_factory: Callable[[ExecutionTask], Awaitable[Dict[str, Any]]],
        result: ExecutionResult,
    ):
        """执行一批任务"""
        async_tasks = []
        
        for task in tasks:
            if self._cancelled:
                break
            
            async_task = asyncio.create_task(
                self._execute_single_task(task, agent_factory, result)
            )
            self._running_tasks[task.agent_id] = async_task
            async_tasks.append(async_task)
        
        # 等待所有任务完成
        if async_tasks:
            await asyncio.gather(*async_tasks, return_exceptions=True)
    
    async def _execute_single_task(
        self,
        task: ExecutionTask,
        agent_factory: Callable[[ExecutionTask], Awaitable[Dict[str, Any]]],
        result: ExecutionResult,
    ):
        """执行单个任务"""
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        
        try:
            # 调用工厂函数执行 Agent
            agent_result = await agent_factory(task)
            
            task.finished_at = datetime.now(timezone.utc)
            task.result = agent_result
            
            if agent_result.get("success"):
                task.status = "completed"
                result.completed_agents += 1
                
                # 收集发现
                findings = agent_result.get("data", {}).get("findings", [])
                result.all_findings.extend(findings)
                
                # 统计
                result.total_tokens += agent_result.get("tokens_used", 0)
                result.total_tool_calls += agent_result.get("tool_calls", 0)
            else:
                task.status = "failed"
                task.error = agent_result.get("error")
                result.failed_agents += 1
                result.errors.append(f"{task.agent_id}: {task.error}")
            
            # 保存结果
            result.agent_results[task.agent_id] = agent_result
            
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.finished_at = datetime.now(timezone.utc)
            result.failed_agents += 1
            result.errors.append(f"{task.agent_id}: {str(e)}")
            logger.error(f"Task {task.agent_id} failed: {e}", exc_info=True)
        
        finally:
            # 清理运行中的任务
            self._running_tasks.pop(task.agent_id, None)
    
    async def _wait_for_dependencies(self, task: ExecutionTask):
        """等待任务的依赖完成"""
        for dep_id in task.dependencies:
            dep_task = self._tasks.get(dep_id)
            if not dep_task:
                continue
            
            # 等待依赖任务完成
            while dep_task.status in ["pending", "running"]:
                if self._cancelled:
                    return
                await asyncio.sleep(0.1)
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """获取执行摘要"""
        return {
            "total_tasks": len(self._tasks),
            "completed": sum(1 for t in self._tasks.values() if t.status == "completed"),
            "failed": sum(1 for t in self._tasks.values() if t.status == "failed"),
            "pending": sum(1 for t in self._tasks.values() if t.status == "pending"),
            "running": sum(1 for t in self._tasks.values() if t.status == "running"),
            "tasks": {
                tid: {
                    "status": t.status,
                    "agent_type": t.agent_type,
                    "error": t.error,
                }
                for tid, t in self._tasks.items()
            },
        }


class SubAgentExecutor:
    """
    子 Agent 执行器
    
    专门用于从父 Agent 创建和执行子 Agent
    """
    
    def __init__(
        self,
        parent_agent,
        llm_service,
        tools: Dict[str, Any],
        event_emitter=None,
    ):
        self.parent_agent = parent_agent
        self.llm_service = llm_service
        self.tools = tools
        self.event_emitter = event_emitter
        
        self._child_agents: Dict[str, Any] = {}
        self._executor = DynamicAgentExecutor(
            llm_service=llm_service,
            tools=tools,
            event_emitter=event_emitter,
        )
    
    async def create_and_run_sub_agent(
        self,
        agent_type: str,
        task: str,
        context: Dict[str, Any] = None,
        knowledge_modules: List[str] = None,
    ) -> Dict[str, Any]:
        """
        创建并运行子 Agent
        
        Args:
            agent_type: Agent 类型 (analysis, verification, specialist)
            task: 任务描述
            context: 任务上下文
            knowledge_modules: 知识模块
            
        Returns:
            子 Agent 执行结果
        """
        from ..agents import AnalysisAgent, VerificationAgent
        
        # 根据类型选择 Agent 类
        agent_class_map = {
            "analysis": AnalysisAgent,
            "verification": VerificationAgent,
        }
        
        agent_class = agent_class_map.get(agent_type)
        if not agent_class:
            return {"success": False, "error": f"Unknown agent type: {agent_type}"}
        
        # 准备输入数据
        input_data = {
            "task": task,
            "task_context": context or {},
            "project_info": context.get("project_info", {}) if context else {},
            "config": context.get("config", {}) if context else {},
        }
        
        # 如果父 Agent 有 handoff，传递给子 Agent
        if hasattr(self.parent_agent, "_incoming_handoff") and self.parent_agent._incoming_handoff:
            input_data["parent_handoff"] = self.parent_agent._incoming_handoff.to_dict()
        
        # 执行子 Agent
        result = await self._executor.execute_agent(
            agent_class=agent_class,
            agent_config={},
            input_data=input_data,
            parent_id=self.parent_agent.agent_id,
            knowledge_modules=knowledge_modules,
        )
        
        # 记录子 Agent
        if result.get("agent_id"):
            self._child_agents[result["agent_id"]] = result
        
        return result
    
    async def run_parallel_sub_agents(
        self,
        sub_agent_configs: List[Dict[str, Any]],
    ) -> ExecutionResult:
        """
        并行运行多个子 Agent
        
        Args:
            sub_agent_configs: 子 Agent 配置列表
                [{"agent_type": "analysis", "task": "...", "context": {...}, "knowledge_modules": [...]}]
                
        Returns:
            汇总的执行结果
        """
        tasks = []
        
        for i, config in enumerate(sub_agent_configs):
            task = ExecutionTask(
                agent_id=f"sub_{self.parent_agent.agent_id}_{i}",
                agent_type=config.get("agent_type", "analysis"),
                task=config.get("task", ""),
                context=config.get("context", {}),
                priority=config.get("priority", 0),
                dependencies=config.get("dependencies", []),
            )
            tasks.append(task)
        
        async def agent_factory(task: ExecutionTask) -> Dict[str, Any]:
            return await self.create_and_run_sub_agent(
                agent_type=task.agent_type,
                task=task.task,
                context=task.context,
                knowledge_modules=task.context.get("knowledge_modules"),
            )
        
        return await self._executor.execute_parallel(tasks, agent_factory)
    
    def get_child_results(self) -> Dict[str, Dict[str, Any]]:
        """获取所有子 Agent 的结果"""
        return self._child_agents.copy()
    
    def get_all_findings(self) -> List[Dict[str, Any]]:
        """获取所有子 Agent 发现的漏洞"""
        findings = []
        for result in self._child_agents.values():
            if result.get("success") and result.get("data"):
                findings.extend(result["data"].get("findings", []))
        return findings
