"""
Agent 协作工具

提供动态Agent创建、通信和管理功能
"""

import logging
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from .base import AgentTool, ToolResult
from ..core.registry import agent_registry
from ..core.message import message_bus, MessageType, MessagePriority

logger = logging.getLogger(__name__)


class CreateAgentInput(BaseModel):
    """创建Agent输入参数"""
    name: str = Field(..., description="Agent名称")
    task: str = Field(..., description="任务描述")
    agent_type: str = Field(
        default="specialist",
        description="Agent类型: analysis(分析), verification(验证), specialist(专家)"
    )
    knowledge_modules: Optional[str] = Field(
        default=None,
        description="知识模块，逗号分隔，最多5个。如: sql_injection,xss,authentication"
    )
    inherit_context: bool = Field(
        default=True,
        description="是否继承父Agent的上下文"
    )
    execute_immediately: bool = Field(
        default=False,
        description="是否立即执行子Agent（否则只创建不执行）"
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="传递给子Agent的上下文数据"
    )


class CreateSubAgentTool(AgentTool):
    """
    创建子Agent工具
    
    允许Agent动态创建专业化的子Agent来处理特定任务。
    子Agent可以加载特定的知识模块，专注于特定领域。
    
    支持两种模式：
    1. 仅创建：创建Agent但不执行，后续可以批量执行
    2. 立即执行：创建并立即执行Agent，等待结果返回
    """
    
    def __init__(
        self,
        parent_agent_id: str,
        llm_service=None,
        tools: Dict[str, Any] = None,
        event_emitter=None,
    ):
        super().__init__()
        self.parent_agent_id = parent_agent_id
        self.llm_service = llm_service
        self.tools = tools or {}
        self.event_emitter = event_emitter
        
        # 子Agent执行器（延迟初始化）
        self._sub_executor = None
    
    def _get_executor(self):
        """获取子Agent执行器"""
        if self._sub_executor is None and self.llm_service:
            from ..core.executor import SubAgentExecutor
            # 需要获取父Agent实例
            parent_agent = agent_registry.get_agent(self.parent_agent_id)
            if parent_agent:
                self._sub_executor = SubAgentExecutor(
                    parent_agent=parent_agent,
                    llm_service=self.llm_service,
                    tools=self.tools,
                    event_emitter=self.event_emitter,
                )
        return self._sub_executor
    
    @property
    def name(self) -> str:
        return "create_sub_agent"
    
    @property
    def description(self) -> str:
        return """创建专业化的子Agent来处理特定任务。

使用场景：
1. 发现需要深入分析的特定漏洞类型
2. 需要专业知识来验证某个发现
3. 任务过于复杂需要分解

参数:
- name: Agent名称（如 "SQL注入专家"）
- task: 具体任务描述
- agent_type: Agent类型 (analysis/verification/specialist)
- knowledge_modules: 知识模块，逗号分隔（如 "sql_injection,database_security"）
- inherit_context: 是否继承当前上下文
- execute_immediately: 是否立即执行（默认false，仅创建）
- context: 传递给子Agent的上下文数据

注意：每个Agent最多加载5个知识模块。"""
    
    @property
    def args_schema(self):
        return CreateAgentInput
    
    async def _execute(
        self,
        name: str,
        task: str,
        agent_type: str = "specialist",
        knowledge_modules: Optional[str] = None,
        inherit_context: bool = True,
        execute_immediately: bool = False,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> ToolResult:
        """创建子Agent"""
        
        if not name or not name.strip():
            return ToolResult(success=False, error="Agent名称不能为空")
        
        if not task or not task.strip():
            return ToolResult(success=False, error="任务描述不能为空")
        
        # 解析知识模块
        modules = []
        if knowledge_modules:
            modules = [m.strip() for m in knowledge_modules.split(",") if m.strip()]
            if len(modules) > 5:
                return ToolResult(
                    success=False,
                    error="知识模块数量不能超过5个"
                )
        
        # 验证知识模块（如果有）
        if modules:
            from ..knowledge import knowledge_loader
            validation = knowledge_loader.validate_modules(modules)
            if validation["invalid"]:
                available = knowledge_loader.get_all_module_names()
                return ToolResult(
                    success=False,
                    error=f"无效的知识模块: {validation['invalid']}。可用模块: {', '.join(available)}"
                )
        
        # 生成Agent ID
        from ..core.state import _generate_agent_id
        agent_id = _generate_agent_id()
        
        # 注册到注册表
        node = agent_registry.register_agent(
            agent_id=agent_id,
            agent_name=name.strip(),
            agent_type=agent_type,
            task=task.strip(),
            parent_id=self.parent_agent_id,
            knowledge_modules=modules,
        )
        
        # 创建消息队列
        message_bus.create_queue(agent_id)
        
        logger.info(f"Created sub-agent: {name} ({agent_id}), parent: {self.parent_agent_id}")
        
        # 如果需要立即执行
        if execute_immediately:
            executor = self._get_executor()
            if executor:
                # 准备上下文
                exec_context = context or {}
                exec_context["knowledge_modules"] = modules
                
                # 执行子Agent
                exec_result = await executor.create_and_run_sub_agent(
                    agent_type=agent_type if agent_type in ["analysis", "verification"] else "analysis",
                    task=task.strip(),
                    context=exec_context,
                    knowledge_modules=modules,
                )
                
                # 更新注册表状态
                if exec_result.get("success"):
                    agent_registry.update_agent_status(agent_id, "completed", exec_result)
                else:
                    agent_registry.update_agent_status(agent_id, "failed", {"error": exec_result.get("error")})
                
                return ToolResult(
                    success=exec_result.get("success", False),
                    data={
                        "message": f"子Agent '{name}' 已执行完成" if exec_result.get("success") else f"子Agent '{name}' 执行失败",
                        "agent_id": agent_id,
                        "execution_result": exec_result,
                        "findings": exec_result.get("data", {}).get("findings", []) if exec_result.get("success") else [],
                    },
                    error=exec_result.get("error"),
                    metadata=node,
                )
            else:
                logger.warning("SubAgentExecutor not available, agent created but not executed")
        
        return ToolResult(
            success=True,
            data={
                "message": f"子Agent '{name}' 已创建",
                "agent_id": agent_id,
                "agent_info": {
                    "id": agent_id,
                    "name": name,
                    "type": agent_type,
                    "task": task[:100],
                    "knowledge_modules": modules,
                    "parent_id": self.parent_agent_id,
                    "status": "created",
                }
            },
            metadata=node,
        )


class SendMessageInput(BaseModel):
    """发送消息输入参数"""
    target_agent_id: str = Field(..., description="目标Agent ID")
    message: str = Field(..., description="消息内容")
    message_type: str = Field(
        default="information",
        description="消息类型: query(查询), instruction(指令), information(信息)"
    )
    priority: str = Field(
        default="normal",
        description="优先级: low, normal, high, urgent"
    )


class SendMessageTool(AgentTool):
    """
    发送消息工具
    
    向其他Agent发送消息，实现Agent间通信
    """
    
    def __init__(self, sender_agent_id: str):
        super().__init__()
        self.sender_agent_id = sender_agent_id
    
    @property
    def name(self) -> str:
        return "send_message"
    
    @property
    def description(self) -> str:
        return """向其他Agent发送消息。

使用场景：
1. 向子Agent发送指令
2. 向父Agent报告进展
3. 请求其他Agent提供信息

参数:
- target_agent_id: 目标Agent的ID
- message: 消息内容
- message_type: 消息类型 (query/instruction/information)
- priority: 优先级 (low/normal/high/urgent)"""
    
    @property
    def args_schema(self):
        return SendMessageInput
    
    async def _execute(
        self,
        target_agent_id: str,
        message: str,
        message_type: str = "information",
        priority: str = "normal",
        **kwargs
    ) -> ToolResult:
        """发送消息"""
        
        if not target_agent_id:
            return ToolResult(success=False, error="目标Agent ID不能为空")
        
        if not message or not message.strip():
            return ToolResult(success=False, error="消息内容不能为空")
        
        # 检查目标Agent是否存在
        target_node = agent_registry.get_agent_node(target_agent_id)
        if not target_node:
            return ToolResult(
                success=False,
                error=f"目标Agent '{target_agent_id}' 不存在"
            )
        
        # 转换消息类型
        try:
            msg_type = MessageType(message_type)
        except ValueError:
            msg_type = MessageType.INFORMATION
        
        try:
            msg_priority = MessagePriority(priority)
        except ValueError:
            msg_priority = MessagePriority.NORMAL
        
        # 发送消息
        sent_message = message_bus.send_message(
            from_agent=self.sender_agent_id,
            to_agent=target_agent_id,
            content=message.strip(),
            message_type=msg_type,
            priority=msg_priority,
        )
        
        return ToolResult(
            success=True,
            data={
                "message": f"消息已发送到 '{target_node['name']}'",
                "message_id": sent_message.id,
                "target_agent": {
                    "id": target_agent_id,
                    "name": target_node["name"],
                    "status": target_node["status"],
                }
            },
            metadata=sent_message.to_dict(),
        )


class ViewAgentGraphTool(AgentTool):
    """
    查看Agent图工具
    
    查看当前的Agent树结构和状态
    """
    
    def __init__(self, current_agent_id: str):
        super().__init__()
        self.current_agent_id = current_agent_id
    
    @property
    def name(self) -> str:
        return "view_agent_graph"
    
    @property
    def description(self) -> str:
        return """查看当前的Agent树结构和状态。

显示：
- 所有Agent及其层级关系
- 每个Agent的状态和任务
- 加载的知识模块"""
    
    @property
    def args_schema(self):
        return None
    
    async def _execute(self, **kwargs) -> ToolResult:
        """查看Agent图"""
        
        tree_view = agent_registry.get_agent_tree_view()
        stats = agent_registry.get_statistics()
        
        return ToolResult(
            success=True,
            data={
                "graph_structure": tree_view,
                "summary": stats,
                "current_agent_id": self.current_agent_id,
            },
        )


class WaitForMessageTool(AgentTool):
    """
    等待消息工具
    
    让Agent进入等待状态，等待其他Agent的消息
    """
    
    def __init__(self, agent_id: str, agent_state=None):
        super().__init__()
        self.agent_id = agent_id
        self.agent_state = agent_state
    
    @property
    def name(self) -> str:
        return "wait_for_message"
    
    @property
    def description(self) -> str:
        return """进入等待状态，等待其他Agent或用户的消息。

使用场景：
1. 等待子Agent完成任务并报告
2. 等待用户提供更多信息
3. 等待其他Agent的协作响应

参数:
- reason: 等待原因"""
    
    @property
    def args_schema(self):
        return None
    
    async def _execute(
        self,
        reason: str = "等待消息",
        **kwargs
    ) -> ToolResult:
        """进入等待状态"""
        
        # 更新Agent状态
        if self.agent_state:
            self.agent_state.enter_waiting_state(reason)
        
        # 更新注册表
        agent_registry.update_agent_status(self.agent_id, "waiting")
        
        return ToolResult(
            success=True,
            data={
                "status": "waiting",
                "message": f"Agent正在等待: {reason}",
                "agent_id": self.agent_id,
                "resume_conditions": [
                    "收到其他Agent的消息",
                    "收到用户消息",
                    "等待超时",
                ],
            },
        )


class AgentFinishInput(BaseModel):
    """Agent完成输入参数"""
    result_summary: str = Field(..., description="结果摘要")
    findings: Optional[List[str]] = Field(default=None, description="发现列表")
    success: bool = Field(default=True, description="是否成功")
    recommendations: Optional[List[str]] = Field(default=None, description="建议列表")


class AgentFinishTool(AgentTool):
    """
    Agent完成工具
    
    子Agent完成任务后调用，向父Agent报告结果
    """
    
    def __init__(self, agent_id: str, agent_state=None):
        super().__init__()
        self.agent_id = agent_id
        self.agent_state = agent_state
    
    @property
    def name(self) -> str:
        return "agent_finish"
    
    @property
    def description(self) -> str:
        return """完成当前Agent的任务并向父Agent报告。

只有子Agent才能使用此工具。根Agent应使用finish_scan。

参数:
- result_summary: 结果摘要
- findings: 发现列表
- success: 是否成功完成
- recommendations: 建议列表"""
    
    @property
    def args_schema(self):
        return AgentFinishInput
    
    async def _execute(
        self,
        result_summary: str,
        findings: Optional[List[str]] = None,
        success: bool = True,
        recommendations: Optional[List[str]] = None,
        **kwargs
    ) -> ToolResult:
        """完成Agent任务"""
        
        # 获取父Agent ID
        parent_id = agent_registry.get_parent(self.agent_id)
        
        if not parent_id:
            return ToolResult(
                success=False,
                error="此工具只能由子Agent使用。根Agent请使用finish_scan。"
            )
        
        # 更新状态
        result = {
            "summary": result_summary,
            "findings": findings or [],
            "success": success,
            "recommendations": recommendations or [],
        }
        
        agent_registry.update_agent_status(
            self.agent_id,
            "completed" if success else "failed",
            result,
        )
        
        if self.agent_state:
            self.agent_state.set_completed(result)
        
        # 向父Agent发送完成报告
        message_bus.send_completion_report(
            from_agent=self.agent_id,
            to_agent=parent_id,
            summary=result_summary,
            findings=[{"description": f} for f in (findings or [])],
            success=success,
        )
        
        agent_node = agent_registry.get_agent_node(self.agent_id)
        
        return ToolResult(
            success=True,
            data={
                "agent_completed": True,
                "parent_notified": True,
                "completion_summary": {
                    "agent_id": self.agent_id,
                    "agent_name": agent_node["name"] if agent_node else "Unknown",
                    "success": success,
                    "findings_count": len(findings or []),
                }
            },
        )


class RunSubAgentsInput(BaseModel):
    """批量执行子Agent输入参数"""
    agent_ids: List[str] = Field(..., description="要执行的Agent ID列表")
    parallel: bool = Field(default=True, description="是否并行执行")


class RunSubAgentsTool(AgentTool):
    """
    批量执行子Agent工具
    
    执行已创建的子Agent，支持并行执行
    """
    
    def __init__(
        self,
        parent_agent_id: str,
        llm_service=None,
        tools: Dict[str, Any] = None,
        event_emitter=None,
    ):
        super().__init__()
        self.parent_agent_id = parent_agent_id
        self.llm_service = llm_service
        self.tools = tools or {}
        self.event_emitter = event_emitter
    
    @property
    def name(self) -> str:
        return "run_sub_agents"
    
    @property
    def description(self) -> str:
        return """批量执行已创建的子Agent。

使用场景：
1. 创建多个子Agent后批量执行
2. 并行执行多个分析任务

参数:
- agent_ids: 要执行的Agent ID列表
- parallel: 是否并行执行（默认true）"""
    
    @property
    def args_schema(self):
        return RunSubAgentsInput
    
    async def _execute(
        self,
        agent_ids: List[str],
        parallel: bool = True,
        **kwargs
    ) -> ToolResult:
        """批量执行子Agent"""
        
        if not agent_ids:
            return ToolResult(success=False, error="Agent ID列表不能为空")
        
        # 验证所有Agent存在且是当前Agent的子Agent
        valid_agents = []
        for aid in agent_ids:
            node = agent_registry.get_agent_node(aid)
            if not node:
                continue
            if node.get("parent_id") != self.parent_agent_id:
                continue
            if node.get("status") not in ["created", "pending"]:
                continue
            valid_agents.append(node)
        
        if not valid_agents:
            return ToolResult(
                success=False,
                error="没有找到可执行的子Agent"
            )
        
        # 构建执行任务
        from ..core.executor import DynamicAgentExecutor, ExecutionTask
        
        executor = DynamicAgentExecutor(
            llm_service=self.llm_service,
            tools=self.tools,
            event_emitter=self.event_emitter,
        )
        
        tasks = []
        for node in valid_agents:
            task = ExecutionTask(
                agent_id=node["id"],
                agent_type=node["type"],
                task=node["task"],
                context={
                    "knowledge_modules": node.get("knowledge_modules", []),
                },
            )
            tasks.append(task)
        
        # 定义Agent工厂函数
        async def agent_factory(task: ExecutionTask) -> Dict[str, Any]:
            from ..agents import AnalysisAgent, VerificationAgent
            
            agent_class_map = {
                "analysis": AnalysisAgent,
                "verification": VerificationAgent,
                "specialist": AnalysisAgent,  # 默认使用分析Agent
                "poc_writer": None,  # 动态导入
            }
            if task.agent_type == "poc_writer":
                from ..agents.smart_contract_poc_writer import PoCWriterAgent
                agent_class_map["poc_writer"] = PoCWriterAgent
            
            agent_class = agent_class_map.get(task.agent_type, AnalysisAgent)
            
            return await executor.execute_agent(
                agent_class=agent_class,
                agent_config={},
                input_data={
                    "task": task.task,
                    "task_context": task.context,
                },
                parent_id=self.parent_agent_id,
                knowledge_modules=task.context.get("knowledge_modules"),
            )
        
        # 执行
        if parallel:
            result = await executor.execute_parallel(tasks, agent_factory)
        else:
            # 顺序执行
            result = await executor.execute_parallel(tasks, agent_factory)
        
        return ToolResult(
            success=result.success,
            data={
                "message": f"执行完成: {result.completed_agents}/{result.total_agents} 成功",
                "total_agents": result.total_agents,
                "completed": result.completed_agents,
                "failed": result.failed_agents,
                "findings_count": len(result.all_findings),
                "findings": result.all_findings[:20],  # 限制返回数量
                "duration_ms": result.total_duration_ms,
                "tokens_used": result.total_tokens,
            },
            error="; ".join(result.errors) if result.errors else None,
            metadata={
                "agent_results": {
                    aid: {
                        "success": r.get("success"),
                        "findings_count": len(r.get("data", {}).get("findings", [])) if r.get("success") else 0,
                    }
                    for aid, r in result.agent_results.items()
                }
            },
        )


class CollectSubAgentResultsTool(AgentTool):
    """
    收集子Agent结果工具
    
    收集所有子Agent的执行结果和发现
    """
    
    def __init__(self, parent_agent_id: str):
        super().__init__()
        self.parent_agent_id = parent_agent_id
    
    @property
    def name(self) -> str:
        return "collect_sub_agent_results"
    
    @property
    def description(self) -> str:
        return """收集所有子Agent的执行结果。

返回：
- 所有子Agent的状态
- 汇总的发现列表
- 执行统计"""
    
    @property
    def args_schema(self):
        return None
    
    async def _execute(self, **kwargs) -> ToolResult:
        """收集子Agent结果"""
        
        # 获取所有子Agent
        children = agent_registry.get_children(self.parent_agent_id)
        
        if not children:
            return ToolResult(
                success=True,
                data={
                    "message": "没有子Agent",
                    "children_count": 0,
                    "findings": [],
                }
            )
        
        all_findings = []
        completed = 0
        failed = 0
        running = 0
        
        child_summaries = []
        
        for child_id in children:
            node = agent_registry.get_agent_node(child_id)
            if not node:
                continue
            
            status = node.get("status", "unknown")
            
            if status == "completed":
                completed += 1
                # 收集发现
                result = node.get("result", {})
                if isinstance(result, dict):
                    findings = result.get("findings", [])
                    if isinstance(findings, list):
                        all_findings.extend(findings)
            elif status == "failed":
                failed += 1
            elif status == "running":
                running += 1
            
            child_summaries.append({
                "id": child_id,
                "name": node.get("name"),
                "type": node.get("type"),
                "status": status,
                "findings_count": len(node.get("result", {}).get("findings", [])) if node.get("result") else 0,
            })
        
        return ToolResult(
            success=True,
            data={
                "message": f"收集完成: {completed} 完成, {failed} 失败, {running} 运行中",
                "children_count": len(children),
                "completed": completed,
                "failed": failed,
                "running": running,
                "total_findings": len(all_findings),
                "findings": all_findings,
                "children": child_summaries,
            },
        )
