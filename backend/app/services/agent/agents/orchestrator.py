"""
Orchestrator Agent (编排层) - LLM 驱动版

LLM 是真正的大脑，全程参与决策！
- LLM 决定下一步做什么
- LLM 决定调度哪个子 Agent
- LLM 决定何时完成
- LLM 根据中间结果动态调整策略

类型: Autonomous Agent with Dynamic Planning
"""

import asyncio
import json
import logging
import os
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .base import BaseAgent, AgentConfig, AgentResult, AgentType, AgentPattern, TaskHandoff
from ..json_parser import AgentJsonParser
from ..prompts import MULTI_AGENT_RULES, CORE_SECURITY_PRINCIPLES

logger = logging.getLogger(__name__)


ORCHESTRATOR_SYSTEM_PROMPT = """你是 DeepAudit 的编排 Agent，负责**自主**协调整个安全审计流程。

## 你的角色
你是整个审计流程的**大脑**，不是一个机械执行者。你需要：
1. 自主思考和决策
2. 根据观察结果动态调整策略
3. 决定何时调用哪个子 Agent
4. 判断何时审计完成

## 你可以调度的子 Agent
1. **recon**: 信息收集 Agent - 分析项目结构、技术栈、入口点
2. **analysis**: 分析 Agent - 深度代码审计、漏洞检测
3. **verification**: 验证 Agent - 验证发现的漏洞、生成 PoC

## 你可以使用的操作

### 1. 调度子 Agent
```
Action: dispatch_agent
Action Input: {"agent": "recon|analysis|verification", "task": "具体任务描述", "context": "任务上下文"}
```

### 2. 汇总发现
```
Action: summarize
Action Input: {"findings": [...], "analysis": "你的分析"}
```

### 3. 完成审计
```
Action: finish
Action Input: {"conclusion": "审计结论", "findings": [...], "recommendations": [...]}
```

## 工作方式
每一步，你需要：

1. **Thought**: 分析当前状态，思考下一步应该做什么
   - 目前收集到了什么信息？
   - 还需要了解什么？
   - 应该深入分析哪些地方？
   - 有什么发现需要验证？

2. **Action**: 选择一个操作
3. **Action Input**: 提供操作参数

## 输出格式
每一步必须严格按照以下格式：

```
Thought: [你的思考过程]
Action: [dispatch_agent|summarize|finish]
Action Input: [JSON 参数]
```

## 审计策略建议
- 先用 recon Agent 了解项目全貌（只需调度一次）
- 根据 recon 结果，让 analysis Agent 重点审计高风险区域
- 发现可疑漏洞后，用 verification Agent 验证
- 随时根据新发现调整策略，不要机械执行
- 当你认为审计足够全面时，选择 finish

## 重要原则
1. **你是大脑，不是执行器** - 每一步都要思考
2. **动态调整** - 根据发现调整策略
3. **主动决策** - 不要等待，主动推进
4. **质量优先** - 宁可深入分析几个真实漏洞，不要浅尝辄止
5. **避免重复** - 每个 Agent 通常只需要调度一次，如果结果不理想，尝试其他 Agent 或直接完成审计

## 处理子 Agent 结果
- 子 Agent 返回的 Observation 包含它们的分析结果
- 即使结果看起来不完整，也要基于已有信息继续推进
- 不要反复调度同一个 Agent 期望得到不同结果
- 如果 recon 完成后，应该调度 analysis 进行深度分析
- 如果 analysis 完成后有发现，可以调度 verification 验证
- 如果没有更多工作要做，使用 finish 结束审计

现在，基于项目信息开始你的审计工作！"""


@dataclass
class AgentStep:
    """执行步骤"""
    thought: str
    action: str
    action_input: Dict[str, Any]
    observation: Optional[str] = None
    sub_agent_result: Optional[AgentResult] = None


class OrchestratorAgent(BaseAgent):
    """
    编排 Agent - LLM 驱动版
    
    LLM 全程参与决策：
    1. LLM 思考当前状态
    2. LLM 决定下一步操作
    3. 执行操作，获取结果
    4. LLM 分析结果，决定下一步
    5. 重复直到 LLM 决定完成
    """
    
    def __init__(
        self,
        llm_service,
        tools: Dict[str, Any],
        event_emitter=None,
        sub_agents: Optional[Dict[str, BaseAgent]] = None,
        tracer=None,
    ):
        # 组合增强的系统提示词，注入多Agent协作规则和核心安全原则
        full_system_prompt = f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n{CORE_SECURITY_PRINCIPLES}\n\n{MULTI_AGENT_RULES}"
        
        config = AgentConfig(
            name="Orchestrator",
            agent_type=AgentType.ORCHESTRATOR,
            pattern=AgentPattern.REACT,  # 改为 ReAct 模式！
            max_iterations=20,
            system_prompt=full_system_prompt,
        )
        super().__init__(config, llm_service, tools, event_emitter)
        
        self.sub_agents = sub_agents or {}
        self._conversation_history: List[Dict[str, str]] = []
        self._steps: List[AgentStep] = []
        self._all_findings: List[Dict] = []
        
        # 🔥 Tracer 遥测支持
        self.tracer = tracer

        # 🔥 存储运行时上下文，用于传递给子 Agent
        self._runtime_context: Dict[str, Any] = {}

        # 🔥 跟踪已调度的 Agent 任务，避免重复调度
        self._dispatched_tasks: Dict[str, int] = {}  # agent_name -> dispatch_count

        # 🔥 保存各个 Agent 的完整结果，用于传递给后续 Agent
        self._agent_results: Dict[str, Dict[str, Any]] = {}  # agent_name -> full result data

        # 🔥 保存各个 Agent 返回的 TaskHandoff，用于 Agent 间通信
        self._agent_handoffs: Dict[str, TaskHandoff] = {}  # agent_name -> TaskHandoff
    
    def register_sub_agent(self, name: str, agent: BaseAgent):
        """注册子 Agent"""
        self.sub_agents[name] = agent
    
    def cancel(self):
        """
        取消执行 - 同时取消所有子 Agent
        
        重写父类方法，确保取消信号传播到所有子 Agent
        """
        self._cancelled = True
        logger.info(f"[{self.name}] Cancel requested, propagating to {len(self.sub_agents)} sub-agents")
        
        # 🔥 传播取消信号到所有子 Agent
        for name, agent in self.sub_agents.items():
            if hasattr(agent, 'cancel'):
                agent.cancel()
                logger.info(f"[{self.name}] Cancelled sub-agent: {name}")
    
    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        执行编排任务 - LLM 全程参与！
        
        Args:
            input_data: {
                "project_info": 项目信息,
                "config": 审计配置,
                "project_root": 项目根目录,
                "task_id": 任务ID,
            }
        """
        import time
        start_time = time.time()
        
        project_info = input_data.get("project_info", {})
        config = input_data.get("config", {})
        
        # 🔥 保存运行时上下文，用于传递给子 Agent
        self._runtime_context = {
            "project_info": project_info,
            "config": config,
            "project_root": input_data.get("project_root", project_info.get("root", ".")),
            "task_id": input_data.get("task_id"),
        }
        
        # 构建初始消息
        initial_message = self._build_initial_message(project_info, config)
        
        # 初始化对话历史
        self._conversation_history = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": initial_message},
        ]
        
        self._steps = []
        self._all_findings = []
        self._agent_results = {}  # 🔥 重置 Agent 结果缓存
        self._agent_handoffs = {}  # 🔥 重置 Agent handoff 缓存
        final_result = None
        error_message = None  # 🔥 跟踪错误信息
        
        await self.emit_thinking("🧠 Orchestrator Agent 启动，LLM 开始自主编排决策...")
        
        try:
            for iteration in range(self.config.max_iterations):
                if self.is_cancelled:
                    break
                
                self._iteration = iteration + 1
                
                # 🔥 再次检查取消标志（在LLM调用之前）
                if self.is_cancelled:
                    await self.emit_thinking("🛑 任务已取消，停止执行")
                    break
                
                # 调用 LLM 进行思考和决策（流式输出）
                try:
                    llm_output, tokens_this_round = await self.stream_llm_call(
                        self._conversation_history,
                        # 🔥 不传递 temperature 和 max_tokens，使用用户配置
                    )
                except asyncio.CancelledError:
                    logger.info(f"[{self.name}] LLM call cancelled")
                    break
                
                self._total_tokens += tokens_this_round
                
                # 🔥 检测空响应
                if not llm_output or not llm_output.strip():
                    logger.warning(f"[{self.name}] Empty LLM response")
                    empty_retry_count = getattr(self, '_empty_retry_count', 0) + 1
                    self._empty_retry_count = empty_retry_count
                    if empty_retry_count >= 5:  # 🔥 增加重试次数到5次
                        logger.error(f"[{self.name}] Too many empty responses, stopping")
                        error_message = "连续收到空响应，停止编排"
                        await self.emit_event("error", error_message)
                        break

                    # 🔥 添加短暂延迟，避免快速重试
                    await asyncio.sleep(1.0)

                    # 🔥 更详细的重试提示
                    retry_prompt = f"""收到空响应（第 {empty_retry_count} 次）。请严格按照以下格式输出你的决策：

Thought: [你对当前审计状态的思考]
Action: [dispatch_agent|summarize|finish]
Action Input: {{"参数": "值"}}

当前可调度的子 Agent: {list(self.sub_agents.keys())}
当前已收集发现: {len(self._all_findings)} 个

请立即输出你的下一步决策。"""

                    self._conversation_history.append({
                        "role": "user",
                        "content": retry_prompt,
                    })
                    continue
                
                # 重置空响应计数器
                self._empty_retry_count = 0

                # 🔥 检查是否是 API 错误（而非格式错误）
                if llm_output.startswith("[API_ERROR:"):
                    # 提取错误类型和消息
                    match = re.match(r"\[API_ERROR:(\w+)\]\s*(.*)", llm_output)
                    if match:
                        error_type = match.group(1)
                        error_message = match.group(2)

                        if error_type == "rate_limit":
                            # 速率限制 - 等待后重试
                            api_retry_count = getattr(self, '_api_retry_count', 0) + 1
                            self._api_retry_count = api_retry_count
                            if api_retry_count >= 3:
                                logger.error(f"[{self.name}] Too many rate limit errors, stopping")
                                await self.emit_event("error", f"API 速率限制重试次数过多: {error_message}")
                                break
                            logger.warning(f"[{self.name}] Rate limit hit, waiting before retry ({api_retry_count}/3)")
                            await self.emit_event("warning", f"API 速率限制，等待后重试 ({api_retry_count}/3)")
                            await asyncio.sleep(30)  # 等待 30 秒后重试
                            continue

                        elif error_type == "quota_exceeded":
                            # 配额用尽 - 终止任务
                            logger.error(f"[{self.name}] API quota exceeded: {error_message}")
                            await self.emit_event("error", f"API 配额已用尽: {error_message}")
                            break

                        elif error_type == "authentication":
                            # 认证错误 - 终止任务
                            logger.error(f"[{self.name}] API authentication error: {error_message}")
                            await self.emit_event("error", f"API 认证失败: {error_message}")
                            break

                        elif error_type == "connection":
                            # 连接错误 - 重试
                            api_retry_count = getattr(self, '_api_retry_count', 0) + 1
                            self._api_retry_count = api_retry_count
                            if api_retry_count >= 3:
                                logger.error(f"[{self.name}] Too many connection errors, stopping")
                                await self.emit_event("error", f"API 连接错误重试次数过多: {error_message}")
                                break
                            logger.warning(f"[{self.name}] Connection error, retrying ({api_retry_count}/3)")
                            await self.emit_event("warning", f"API 连接错误，重试中 ({api_retry_count}/3)")
                            await asyncio.sleep(5)  # 等待 5 秒后重试
                            continue

                # 重置 API 重试计数器（成功获取响应后）
                self._api_retry_count = 0

                # 解析 LLM 的决策
                step = self._parse_llm_response(llm_output)
                
                if not step:
                    # LLM 输出格式不正确，提示重试
                    format_retry_count = getattr(self, '_format_retry_count', 0) + 1
                    self._format_retry_count = format_retry_count
                    if format_retry_count >= 3:
                        logger.error(f"[{self.name}] Too many format errors, stopping")
                        error_message = "连续格式错误，停止编排"
                        await self.emit_event("error", error_message)
                        break
                    await self.emit_llm_decision("格式错误", "需要重新输出")
                    self._conversation_history.append({
                        "role": "assistant",
                        "content": llm_output,
                    })
                    self._conversation_history.append({
                        "role": "user",
                        "content": "请按照规定格式输出：Thought + Action + Action Input",
                    })
                    continue
                
                # 重置格式重试计数器
                self._format_retry_count = 0
                
                self._steps.append(step)
                
                # 🔥 发射 LLM 思考内容事件 - 展示编排决策的思考过程
                if step.thought:
                    await self.emit_llm_thought(step.thought, iteration + 1)
                
                # 添加 LLM 响应到历史
                self._conversation_history.append({
                    "role": "assistant",
                    "content": llm_output,
                })
                
                # 执行 LLM 决定的操作
                if step.action == "finish":
                    # 🔥 LLM 决定完成审计
                    await self.emit_llm_decision("完成审计", "LLM 判断审计已充分完成")
                    await self.emit_llm_complete(
                        f"编排完成，发现 {len(self._all_findings)} 个漏洞",
                        self._total_tokens
                    )
                    final_result = step.action_input
                    break
                
                elif step.action == "dispatch_agent":
                    # 🔥 LLM 决定调度子 Agent
                    agent_name = step.action_input.get("agent", "unknown")
                    task_desc = step.action_input.get("task", "")
                    await self.emit_llm_decision(
                        f"调度 {agent_name} Agent",
                        f"任务: {task_desc[:100]}"
                    )
                    await self.emit_llm_action("dispatch_agent", step.action_input)
                    
                    observation = await self._dispatch_agent(step.action_input)
                    step.observation = observation
                    
                    # 🔥 子 Agent 执行完成后检查取消状态
                    if self.is_cancelled:
                        logger.info(f"[{self.name}] Cancelled after sub-agent dispatch")
                        break
                    
                    # 🔥 发射观察事件
                    await self.emit_llm_observation(observation)
                    
                elif step.action == "summarize":
                    # LLM 要求汇总
                    await self.emit_llm_decision("汇总发现", "LLM 请求查看当前发现汇总")
                    observation = self._summarize_findings()
                    step.observation = observation
                    await self.emit_llm_observation(observation)
                    
                else:
                    observation = f"未知操作: {step.action}，可用操作: dispatch_agent, summarize, finish"
                    await self.emit_llm_decision("未知操作", observation)
                
                # 添加观察结果到历史
                self._conversation_history.append({
                    "role": "user",
                    "content": f"Observation:\n{step.observation}",
                })
            
            # 生成最终结果
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 🔥 如果被取消，返回取消结果
            if self.is_cancelled:
                await self.emit_event(
                    "info",
                    f"🛑 Orchestrator 已取消: {len(self._all_findings)} 个发现, {self._iteration} 轮决策"
                )
                return AgentResult(
                    success=False,
                    error="任务已取消",
                    data={
                        "findings": self._all_findings,
                        "steps": [
                            {
                                "thought": s.thought,
                                "action": s.action,
                                "action_input": s.action_input,
                                "observation": s.observation[:500] if s.observation else None,
                            }
                            for s in self._steps
                        ],
                    },
                    iterations=self._iteration,
                    tool_calls=self._tool_calls,
                    tokens_used=self._total_tokens,
                    duration_ms=duration_ms,
                )
            
            # 🔥 如果有错误，返回失败结果
            if error_message:
                await self.emit_event(
                    "error",
                    f"❌ Orchestrator 失败: {error_message}"
                )
                return AgentResult(
                    success=False,
                    error=error_message,
                    data={
                        "findings": self._all_findings,
                        "steps": [
                            {
                                "thought": s.thought,
                                "action": s.action,
                                "action_input": s.action_input,
                                "observation": s.observation[:500] if s.observation else None,
                            }
                            for s in self._steps
                        ],
                    },
                    iterations=self._iteration,
                    tool_calls=self._tool_calls,
                    tokens_used=self._total_tokens,
                    duration_ms=duration_ms,
                )
            
            await self.emit_event(
                "info",
                f"🎯 Orchestrator 完成: {len(self._all_findings)} 个发现, {self._iteration} 轮决策"
            )

            # 🔥 CRITICAL: Log final findings count before returning
            logger.info(f"[Orchestrator] Final result: {len(self._all_findings)} findings collected")
            if len(self._all_findings) == 0:
                logger.warning(f"[Orchestrator] ⚠️ No findings collected! Dispatched agents: {list(self._dispatched_tasks.keys())}, Iterations: {self._iteration}")
            for i, f in enumerate(self._all_findings[:5]):  # Log first 5 for debugging
                logger.debug(f"[Orchestrator] Finding {i+1}: {f.get('title', 'N/A')} - {f.get('vulnerability_type', 'N/A')}")

            return AgentResult(
                success=True,
                data={
                    "findings": self._all_findings,
                    "summary": final_result or self._generate_default_summary(),
                    "steps": [
                        {
                            "thought": s.thought,
                            "action": s.action,
                            "action_input": s.action_input,
                            "observation": s.observation[:500] if s.observation else None,
                        }
                        for s in self._steps
                    ],
                },
                iterations=self._iteration,
                tool_calls=self._tool_calls,
                tokens_used=self._total_tokens,
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            logger.error(f"Orchestrator failed: {e}", exc_info=True)
            return AgentResult(
                success=False,
                error=str(e),
            )
    
    def _build_initial_message(
        self,
        project_info: Dict[str, Any],
        config: Dict[str, Any],
    ) -> str:
        """构建初始消息"""
        structure = project_info.get('structure', {})
        
        # 🔥 检查是否是限定范围的审计
        scope_limited = structure.get('scope_limited', False)
        scope_message = structure.get('scope_message', '')
        
        msg = f"""请开始对以下项目进行安全审计。

## 项目信息
- 名称: {project_info.get('name', 'unknown')}
- 语言: {project_info.get('languages', [])}
- 文件数量: {project_info.get('file_count', 0)}
"""
        
        # 🔥 根据是否限定范围显示不同的结构信息
        if scope_limited:
            msg += f"""
## ⚠️ 审计范围限定
**{scope_message}**

### 目标文件列表
"""
            for f in structure.get('files', []):
                msg += f"- {f}\n"
            
            if structure.get('directories'):
                msg += f"""
### 相关目录
{structure.get('directories', [])}
"""
        else:
            msg += f"""
## 目录结构
{json.dumps(structure, ensure_ascii=False, indent=2)}
"""
        
        # 🔥 如果配置了 target_files，也明确显示
        target_files = config.get('target_files', [])
        if target_files:
            msg += f"""
## ⚠️ 重要提示
用户指定了 **{len(target_files)}** 个目标文件进行审计。
请确保你的分析集中在这些指定的文件上，不要浪费时间分析其他文件。
"""
        
        msg += f"""
## 用户配置
- 目标漏洞: {config.get('target_vulnerabilities', ['all'])}
- 验证级别: {config.get('verification_level', 'sandbox')}
- 排除模式: {config.get('exclude_patterns', [])}

## 可用子 Agent
{', '.join(self.sub_agents.keys()) if self.sub_agents else '(暂无子 Agent)'}

请开始你的审计工作。首先思考应该如何开展，然后决定第一步做什么。"""
        
        return msg
    
    def _parse_llm_response(self, response: str) -> Optional[AgentStep]:
        """解析 LLM 响应"""
        # 🔥 v2.1: 预处理 - 移除 Markdown 格式标记（LLM 有时会输出 **Action:** 而非 Action:）
        cleaned_response = response
        cleaned_response = re.sub(r'\*\*Action:\*\*', 'Action:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Action Input:\*\*', 'Action Input:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Thought:\*\*', 'Thought:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Observation:\*\*', 'Observation:', cleaned_response)

        # 提取 Thought
        thought_match = re.search(r'Thought:\s*(.*?)(?=Action:|$)', cleaned_response, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else ""

        # 提取 Action
        action_match = re.search(r'Action:\s*(\w+)', cleaned_response)
        if not action_match:
            return None
        action = action_match.group(1).strip()

        # 提取 Action Input
        input_match = re.search(r'Action Input:\s*(.*?)(?=Thought:|Observation:|$)', cleaned_response, re.DOTALL)
        if not input_match:
            return None

        input_text = input_match.group(1).strip()
        # 移除 markdown 代码块
        input_text = re.sub(r'```json\s*', '', input_text)
        input_text = re.sub(r'```\s*', '', input_text)

        # 使用增强的 JSON 解析器
        action_input = AgentJsonParser.parse(
            input_text,
            default={"raw": input_text}
        )

        return AgentStep(
            thought=thought,
            action=action,
            action_input=action_input,
        )
    
    async def _dispatch_agent(self, params: Dict[str, Any]) -> str:
        """调度子 Agent"""
        agent_name = params.get("agent", "")
        task = params.get("task", "")
        context = params.get("context", "")
        
        logger.debug(f"[Orchestrator] _dispatch_agent 被调用: agent_name='{agent_name}', task='{task[:50]}...'")
        
        # 🔥 尝试大小写不敏感匹配
        agent = self.sub_agents.get(agent_name)
        if not agent:
            # 尝试小写匹配
            agent_name_lower = agent_name.lower()
            agent = self.sub_agents.get(agent_name_lower)
            if agent:
                agent_name = agent_name_lower
                logger.debug(f"[Orchestrator] 使用小写匹配: {agent_name}")
        
        if not agent:
            available = list(self.sub_agents.keys())
            logger.warning(f"[Orchestrator] Agent '{agent_name}' 不存在，可用: {available}")
            return f"错误: Agent '{agent_name}' 不存在。可用的 Agent: {available}"
        
        # 🔥 检查是否重复调度同一个 Agent
        dispatch_count = self._dispatched_tasks.get(agent_name, 0)
        if dispatch_count >= 2:
            return f"""## ⚠️ 重复调度警告

你已经调度 {agent_name} Agent {dispatch_count} 次了。

如果之前的调度没有返回有用的结果，请考虑：
1. 尝试调度其他 Agent（如 analysis 或 verification）
2. 使用 finish 操作结束审计并汇总已有发现
3. 提供更具体的任务描述

当前已收集的发现数量: {len(self._all_findings)}
"""
        
        self._dispatched_tasks[agent_name] = dispatch_count + 1
        
        # 🔥 设置父 Agent ID 并注册到注册表（动态 Agent 树）
        logger.debug(f"[Orchestrator] 准备调度 {agent_name} Agent, agent._registered={agent._registered}")
        agent.set_parent_id(self._agent_id)
        logger.debug(f"[Orchestrator] 设置 parent_id 完成，准备注册 {agent_name}")
        agent._register_to_registry(task=task)
        logger.debug(f"[Orchestrator] {agent_name} 注册完成，agent._registered={agent._registered}")
        
        await self.emit_event(
            "dispatch",
            f"📤 调度 {agent_name} Agent: {task[:100]}...",
            agent=agent_name,
            task=task,
        )
        
        self._tool_calls += 1
        
        try:
            # 🔥 构建子 Agent 输入 - 传递完整的运行时上下文
            project_info = self._runtime_context.get("project_info", {}).copy()
            # 确保 project_info 包含 root 路径
            if "root" not in project_info:
                project_info["root"] = self._runtime_context.get("project_root", ".")

            # 🔥 FIX: 构建完整的 previous_results，包含所有已执行 Agent 的结果
            previous_results = {
                "findings": self._all_findings,  # 传递已收集的发现
            }

            # 🔥 将之前 Agent 的完整结果传递给后续 Agent
            for prev_agent, prev_data in self._agent_results.items():
                previous_results[prev_agent] = {"data": prev_data}

            # 🔥 构建 TaskHandoff - Agent 间的结构化通信协议
            handoff = self._build_handoff_for_agent(agent_name, task, context)

            sub_input = {
                "task": task,
                "task_context": context,
                "project_info": project_info,
                "config": self._runtime_context.get("config", {}),
                "project_root": self._runtime_context.get("project_root", "."),
                "previous_results": previous_results,
                "handoff": handoff.to_dict() if handoff else None,  # 🔥 传递 TaskHandoff
            }

            # 🔥 执行子 Agent 前检查取消状态
            if self.is_cancelled:
                return f"## {agent_name} Agent 执行取消\n\n任务已被用户取消"

            # 🔥 执行子 Agent - 支持取消和超时
            # 使用用户配置的子Agent超时时间
            default_sub_agent_timeout = self._timeout_config.get('sub_agent_timeout', 600)
            # 设置子 Agent 超时（根据 Agent 类型，recon稍短）
            agent_timeouts = {
                "recon": min(300, default_sub_agent_timeout),  # recon 通常较快
                "analysis": default_sub_agent_timeout,
                "verification": default_sub_agent_timeout,
            }
            timeout = agent_timeouts.get(agent_name, default_sub_agent_timeout)

            async def run_with_cancel_check():
                """包装子 Agent 执行，定期检查取消状态"""
                run_task = asyncio.create_task(agent.run(sub_input))
                try:
                    while not run_task.done():
                        if self.is_cancelled:
                            # 🔥 传播取消到子 Agent
                            logger.info(f"[{self.name}] Cancelling sub-agent {agent_name} due to parent cancel")
                            if hasattr(agent, 'cancel'):
                                agent.cancel()
                            run_task.cancel()
                            try:
                                await run_task
                            except asyncio.CancelledError:
                                pass
                            raise asyncio.CancelledError("任务已取消")

                        # Use asyncio.wait to poll without cancelling the task
                        done, pending = await asyncio.wait(
                            [run_task],
                            timeout=0.5,
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        if run_task in done:
                            return run_task.result()
                        # If not done, continue loop
                        continue

                    return await run_task
                except asyncio.CancelledError:
                    # 🔥 确保子任务被取消
                    if not run_task.done():
                        if hasattr(agent, 'cancel'):
                            agent.cancel()
                        run_task.cancel()
                        try:
                            await run_task
                        except asyncio.CancelledError:
                            pass
                    raise

            try:
                result = await asyncio.wait_for(
                    run_with_cancel_check(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"[{self.name}] Sub-agent {agent_name} timed out after {timeout}s")
                return f"## {agent_name} Agent 执行超时\n\n子 Agent 执行超过 {timeout} 秒，已强制终止。请尝试更具体的任务或使用其他 Agent。"
            except asyncio.CancelledError:
                logger.info(f"[{self.name}] Sub-agent {agent_name} was cancelled")
                return f"## {agent_name} Agent 执行取消\n\n任务已被用户取消"

            # 🔥 执行后再次检查取消状态
            if self.is_cancelled:
                return f"## {agent_name} Agent 执行中断\n\n任务已被用户取消"

            # 🔥 处理子 Agent 结果 - 不同 Agent 返回不同的数据结构
            # 🔥 DEBUG: 添加诊断日志
            logger.info(f"[Orchestrator] Processing {agent_name} result: success={result.success}, data_type={type(result.data).__name__}, data_keys={list(result.data.keys()) if isinstance(result.data, dict) else 'N/A'}")

            if result.success and result.data:
                data = result.data

                # 🔥 FIX: 保存 Agent 的完整结果，供后续 Agent 使用
                self._agent_results[agent_name] = data
                logger.info(f"[Orchestrator] Saved {agent_name} result with keys: {list(data.keys())}")

                # 🔥 保存 Agent 返回的 handoff，用于传递给后续 Agent
                if result.handoff:
                    if not hasattr(self, '_agent_handoffs'):
                        self._agent_handoffs = {}
                    self._agent_handoffs[agent_name] = result.handoff
                    logger.info(
                        f"[Orchestrator] Saved {agent_name} handoff: "
                        f"summary={result.handoff.summary[:50]}..."
                    )

                # 🔥 CRITICAL FIX: 收集发现 - 支持多种字段名
                # findings 字段通常来自 Analysis/Verification Agent
                # initial_findings 来自 Recon Agent
                raw_findings = data.get("findings", [])
                logger.info(f"[Orchestrator] {agent_name} returned data with {len(raw_findings)} findings in 'findings' field")

                # 🔥 ENHANCED: Also check for initial_findings (from Recon) - 改进逻辑
                # 即使 findings 为空列表，也检查 initial_findings
                if "initial_findings" in data:
                    initial = data.get("initial_findings", [])
                    logger.info(f"[Orchestrator] {agent_name} has {len(initial)} initial_findings, types: {[type(f).__name__ for f in initial[:3]]}")
                    for f in initial:
                        if isinstance(f, dict):
                            # 🔥 Normalize finding format - 处理 Recon 返回的格式
                            normalized = self._normalize_finding(f)
                            if normalized not in raw_findings:
                                raw_findings.append(normalized)
                                logger.info(f"[Orchestrator] Added dict finding from initial_findings")
                        elif isinstance(f, str) and f.strip():
                            # 🔥 FIX: Convert string finding to dict format instead of skipping
                            # Recon Agent 有时候会返回字符串格式的发现
                            # 尝试从字符串中提取文件路径（格式如 "app.py:36 - 描述"）
                            file_path = ""
                            line_start = 0
                            if ":" in f:
                                parts = f.split(":", 1)
                                potential_file = parts[0].strip()
                                # 检查是否像文件路径
                                if "." in potential_file and "/" not in potential_file[:3]:
                                    file_path = potential_file
                                    # 尝试提取行号
                                    if len(parts) > 1:
                                        remaining = parts[1].strip()
                                        line_match = remaining.split()[0] if remaining else ""
                                        if line_match.isdigit():
                                            line_start = int(line_match)

                            string_finding = {
                                "title": f[:100] if len(f) > 100 else f,
                                "description": f,
                                "file_path": file_path,
                                "line_start": line_start,
                                "severity": "medium",  # 默认中等严重度，Analysis 会重新评估
                                "vulnerability_type": "potential_issue",
                                "source": "recon",
                                "needs_verification": True,
                                "confidence": 0.5,  # 较低置信度，需要进一步分析
                            }
                            logger.info(f"[Orchestrator] Converted string finding to dict: {f[:80]}... (file={file_path}, line={line_start})")
                            raw_findings.append(string_finding)
                else:
                    logger.info(f"[Orchestrator] {agent_name} has no 'initial_findings' key in data")

                # 🔥 Also check high_risk_areas from Recon for potential findings
                if agent_name == "recon" and "high_risk_areas" in data:
                    high_risk = data.get("high_risk_areas", [])
                    logger.info(f"[Orchestrator] {agent_name} identified {len(high_risk)} high risk areas")
                    # 🔥 FIX: 将 high_risk_areas 也转换为发现
                    for area in high_risk:
                        if isinstance(area, str) and area.strip():
                            # 尝试从描述中提取文件路径和漏洞类型
                            file_path = ""
                            line_start = 0
                            vuln_type = "potential_issue"

                            # 🔥 FIX: 改进文件路径提取逻辑
                            # 格式1: "file.py:36 - 描述" -> 提取 file.py 和 36
                            # 格式2: "描述性文本" -> 不提取文件路径
                            if ":" in area:
                                parts = area.split(":", 1)
                                potential_file = parts[0].strip()
                                # 只有当 parts[0] 看起来像文件路径时才提取
                                # 文件路径通常包含 . 且没有空格（或只在结尾有扩展名）
                                # 🔥 FIX: 放宽文件路径校验 - 不再限制扩展名，只要像文件路径就提取
                                if ("." in potential_file and
                                    " " not in potential_file and
                                    len(potential_file) < 100 and
                                    not potential_file.endswith("/")):
                                    file_path = potential_file
                                    # 尝试提取行号
                                    if len(parts) > 1:
                                        remaining = parts[1].strip()
                                        line_match = remaining.split()[0] if remaining else ""
                                        if line_match.isdigit():
                                            line_start = int(line_match)

                            # 推断漏洞类型
                            area_lower = area.lower()
                            if "command" in area_lower or "命令" in area_lower or "subprocess" in area_lower:
                                vuln_type = "command_injection"
                            elif "sql" in area_lower:
                                vuln_type = "sql_injection"
                            elif "xss" in area_lower:
                                vuln_type = "xss"
                            elif "path" in area_lower or "traversal" in area_lower or "路径" in area_lower:
                                vuln_type = "path_traversal"
                            elif "ssrf" in area_lower:
                                vuln_type = "ssrf"
                            elif "secret" in area_lower or "密钥" in area_lower or "key" in area_lower:
                                vuln_type = "hardcoded_secret"

                            high_risk_finding = {
                                "title": area[:100] if len(area) > 100 else area,
                                "description": area,
                                "file_path": file_path,
                                "line_start": line_start,
                                "severity": "high",  # 高风险区域默认高严重度
                                "vulnerability_type": vuln_type,
                                "source": "recon_high_risk",
                                "needs_verification": True,
                                "confidence": 0.6,
                            }
                            raw_findings.append(high_risk_finding)
                            logger.info(f"[Orchestrator] Converted high_risk_area to finding: {area[:60]}... (file={file_path}, type={vuln_type})")

                # 🔥 初始化 valid_findings，确保后续代码可以访问
                valid_findings = []

                if raw_findings:
                    # 只添加字典格式的发现
                    valid_findings = [f for f in raw_findings if isinstance(f, dict)]

                    logger.info(f"[Orchestrator] {agent_name} returned {len(valid_findings)} valid findings")

                    # 🔥 ENHANCED: Merge findings with better deduplication
                    for new_f in valid_findings:
                        # Normalize the finding first
                        normalized_new = self._normalize_finding(new_f)
                        if not normalized_new:
                            continue

                        # Create fingerprint for deduplication (file + description similarity)
                        new_file = normalized_new.get("file_path", "").lower().strip()
                        new_desc = (normalized_new.get("description", "") or "").lower()[:100]
                        new_type = (normalized_new.get("vulnerability_type", "") or "").lower()
                        new_line = normalized_new.get("line_start") or normalized_new.get("line", 0)

                        # Check if exists (more flexible matching)
                        found = False
                        for i, existing_f in enumerate(self._all_findings):
                            existing_file = (existing_f.get("file_path", "") or existing_f.get("file", "")).lower().strip()
                            existing_desc = (existing_f.get("description", "") or "").lower()[:100]
                            existing_type = (existing_f.get("vulnerability_type", "") or existing_f.get("type", "")).lower()
                            existing_line = existing_f.get("line_start") or existing_f.get("line", 0)

                            # Match if same file AND (same line OR similar description OR same vulnerability type)
                            same_file = new_file and existing_file and (
                                new_file == existing_file or
                                new_file.endswith(existing_file) or
                                existing_file.endswith(new_file)
                            )
                            same_line = new_line and existing_line and new_line == existing_line
                            similar_desc = new_desc and existing_desc and (
                                new_desc in existing_desc or existing_desc in new_desc
                            )
                            same_type = new_type and existing_type and (
                                new_type == existing_type or
                                (new_type in existing_type) or (existing_type in new_type)
                            )

                            # 🔥 Match criteria for same-file findings
                            if same_file and (same_line or similar_desc or same_type):
                                match_found = True
                            elif same_type and same_line and not same_file:
                                # 🔥 FIX: Only allow cross-file matching when:
                                # 1. new_file is garbage ("?"/empty) and descriptions still match
                                # 2. One path is a prefix of the other ("src/foo.py" vs "foo.py")
                                # Do NOT merge when existing_file is garbage - that would lose the real path.
                                new_is_garbage = not new_file or new_file == "?"
                                prefix_match = (
                                    new_file.endswith("/" + existing_file) or
                                    existing_file.endswith("/" + new_file)
                                )
                                if (new_is_garbage and similar_desc) or prefix_match:
                                    match_found = True
                                    logger.info(f"[Orchestrator] Matched by type+line despite file mismatch: {new_file} vs {existing_file}")
                                else:
                                    match_found = False
                            else:
                                match_found = False

                            if match_found:
                                # Update existing with new info (e.g. verification results)
                                # 🔥 FIX: Smart merge - don't overwrite good data with empty values
                                merged = dict(existing_f)  # Start with existing data
                                for key, value in normalized_new.items():
                                    # Only overwrite if new value is meaningful
                                    if value is not None and value != "" and value != 0:
                                        merged[key] = value
                                    elif key not in merged or merged[key] is None:
                                        # Fill in missing fields even with empty values
                                        merged[key] = value

                                # Keep the better title
                                if normalized_new.get("title") and len(normalized_new.get("title", "")) > len(existing_f.get("title", "")):
                                    merged["title"] = normalized_new["title"]
                                # Keep verified status if either is verified
                                if existing_f.get("is_verified") or normalized_new.get("is_verified"):
                                    merged["is_verified"] = True
                                # 🔥 FIX: Preserve non-zero line numbers
                                if existing_f.get("line_start") and not normalized_new.get("line_start"):
                                    merged["line_start"] = existing_f["line_start"]
                                # 🔥 FIX: Preserve vulnerability_type
                                if existing_f.get("vulnerability_type") and not normalized_new.get("vulnerability_type"):
                                    merged["vulnerability_type"] = existing_f["vulnerability_type"]

                                self._all_findings[i] = merged
                                found = True
                                logger.info(f"[Orchestrator] Merged finding: {new_file}:{merged.get('line_start', 0)} ({merged.get('vulnerability_type', '')})")
                                break

                        if not found:
                            self._all_findings.append(normalized_new)
                            logger.info(f"[Orchestrator] Added new finding: {new_file}:{new_line} ({new_type})")

                    logger.info(f"[Orchestrator] Total findings now: {len(self._all_findings)}")
                else:
                    logger.info(f"[Orchestrator] {agent_name} returned no findings")
                
                await self.emit_event(
                    "dispatch_complete",
                    f"✅ {agent_name} Agent 完成",
                    agent=agent_name,
                    findings_count=len(self._all_findings),  # 🔥 Use total findings count
                )
                
                # 🔥 根据 Agent 类型构建不同的观察结果
                if agent_name == "recon":
                    # Recon Agent 返回项目信息
                    observation = f"""## Recon Agent 执行结果

**状态**: 成功
**迭代次数**: {result.iterations}
**耗时**: {result.duration_ms}ms

### 项目结构
{json.dumps(data.get('project_structure', {}), ensure_ascii=False, indent=2)}

### 技术栈
- 语言: {data.get('tech_stack', {}).get('languages', [])}
- 框架: {data.get('tech_stack', {}).get('frameworks', [])}
- 数据库: {data.get('tech_stack', {}).get('databases', [])}

### 入口点 ({len(data.get('entry_points', []))} 个)
"""
                    for i, ep in enumerate(data.get('entry_points', [])[:10]):
                        if isinstance(ep, dict):
                            observation += f"{i+1}. [{ep.get('type', 'unknown')}] {ep.get('file', '')}:{ep.get('line', '')}\n"
                    
                    observation += f"""
### 高风险区域
{data.get('high_risk_areas', [])}

### 初步发现 ({len(data.get('initial_findings', []))} 个)
"""
                    for finding in data.get('initial_findings', [])[:5]:
                        if isinstance(finding, str):
                            observation += f"- {finding}\n"
                        elif isinstance(finding, dict):
                            observation += f"- {finding.get('title', finding)}\n"
                    
                else:
                    # Analysis/Verification Agent 返回漏洞发现
                    observation = f"""## {agent_name} Agent 执行结果

**状态**: 成功
**发现数量**: {len(valid_findings)}
**迭代次数**: {result.iterations}
**耗时**: {result.duration_ms}ms

### 发现摘要
"""
                    for i, f in enumerate(valid_findings[:10]):
                        if not isinstance(f, dict):
                            continue
                        observation += f"""
{i+1}. [{f.get('severity', 'unknown')}] {f.get('title', 'Unknown')}
   - 类型: {f.get('vulnerability_type', 'unknown')}
   - 文件: {f.get('file_path', 'unknown')}
   - 描述: {f.get('description', '')[:200]}...
"""

                    if len(valid_findings) > 10:
                        observation += f"\n... 还有 {len(valid_findings) - 10} 个发现"
                
                if data.get("summary"):
                    observation += f"\n\n### Agent 总结\n{data['summary']}"
                
                return observation
            else:
                return f"## {agent_name} Agent 执行失败\n\n错误: {result.error}"
                
        except Exception as e:
            logger.error(f"Sub-agent dispatch failed: {e}", exc_info=True)
            return f"## 调度失败\n\n错误: {str(e)}"

    def _validate_file_path(self, file_path: str) -> bool:
        """
        🔥 v2.1: 验证文件路径是否真实存在

        Args:
            file_path: 相对或绝对文件路径（可能包含行号，如 "app.py:36"）

        Returns:
            bool: 文件是否存在
        """
        if not file_path or not file_path.strip():
            return False

        # 获取项目根目录
        project_root = self._runtime_context.get("project_root", "")
        if not project_root:
            # 没有项目根目录时，无法验证，返回 True 以避免误判
            return True

        # 清理路径（移除可能的行号）
        clean_path = file_path.split(":")[0].strip() if ":" in file_path else file_path.strip()

        # 尝试相对路径
        full_path = os.path.join(project_root, clean_path)
        if os.path.isfile(full_path):
            return True

        # 尝试绝对路径
        if os.path.isabs(clean_path) and os.path.isfile(clean_path):
            return True

        return False

    def _normalize_finding(self, finding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        标准化发现格式

        不同 Agent 可能返回不同格式的发现，这个方法将它们标准化为统一格式

        🔥 v2.1: 添加文件路径验证，返回 None 表示发现无效（幻觉）
        """
        normalized = dict(finding)  # 复制原始数据

        # 🔥 处理 location 字段 -> file_path + line_start
        if "location" in normalized and "file_path" not in normalized:
            location = normalized["location"]
            if isinstance(location, str) and ":" in location:
                parts = location.split(":")
                normalized["file_path"] = parts[0]
                try:
                    normalized["line_start"] = int(parts[1])
                except (ValueError, IndexError):
                    pass
            elif isinstance(location, str):
                normalized["file_path"] = location

        # 🔥 处理 file 字段 -> file_path
        if "file" in normalized and "file_path" not in normalized:
            normalized["file_path"] = normalized["file"]

        # 🔥 处理 line 字段 -> line_start
        if "line" in normalized and "line_start" not in normalized:
            normalized["line_start"] = normalized["line"]

        # 🔥 处理 type 字段 -> vulnerability_type
        if "type" in normalized and "vulnerability_type" not in normalized:
            # 不是所有 type 都是漏洞类型，比如 "Vulnerability" 只是标记
            type_val = normalized["type"]
            if type_val and type_val.lower() not in ["vulnerability", "finding", "issue"]:
                normalized["vulnerability_type"] = type_val
            elif "description" in normalized:
                # 尝试从描述中推断漏洞类型
                desc = normalized["description"].lower()
                if "command injection" in desc or "rce" in desc or "system(" in desc:
                    normalized["vulnerability_type"] = "command_injection"
                elif "sql injection" in desc or "sqli" in desc:
                    normalized["vulnerability_type"] = "sql_injection"
                elif "xss" in desc or "cross-site scripting" in desc:
                    normalized["vulnerability_type"] = "xss"
                elif "path traversal" in desc or "directory traversal" in desc:
                    normalized["vulnerability_type"] = "path_traversal"
                elif "ssrf" in desc:
                    normalized["vulnerability_type"] = "ssrf"
                elif "xxe" in desc:
                    normalized["vulnerability_type"] = "xxe"
                else:
                    normalized["vulnerability_type"] = "other"

        # 🔥 确保 severity 字段存在且为小写
        if "severity" in normalized:
            normalized["severity"] = str(normalized["severity"]).lower()
        else:
            normalized["severity"] = "medium"

        # 🔥 处理 risk 字段 -> severity
        if "risk" in normalized and "severity" not in normalized:
            normalized["severity"] = str(normalized["risk"]).lower()

        # 🔥 生成 title 如果不存在
        if "title" not in normalized:
            vuln_type = normalized.get("vulnerability_type", "Unknown")
            file_path = normalized.get("file_path", "")
            if file_path:
                import os
                normalized["title"] = f"{vuln_type.replace('_', ' ').title()} in {os.path.basename(file_path)}"
            else:
                normalized["title"] = f"{vuln_type.replace('_', ' ').title()} Vulnerability"

        # 🔥 处理 code 字段 -> code_snippet
        if "code" in normalized and "code_snippet" not in normalized:
            normalized["code_snippet"] = normalized["code"]

        # 🔥 处理 recommendation -> suggestion
        if "recommendation" in normalized and "suggestion" not in normalized:
            normalized["suggestion"] = normalized["recommendation"]

        # 🔥 处理 impact -> 添加到 description
        if "impact" in normalized and normalized.get("description"):
            if "impact" not in normalized["description"].lower():
                normalized["description"] += f"\n\nImpact: {normalized['impact']}"

        # 🔥 v2.1: 验证文件路径存在性
        file_path = normalized.get("file_path", "")
        if file_path and not self._validate_file_path(file_path):
            logger.warning(
                f"[Orchestrator] 🚫 过滤幻觉发现: 文件不存在 '{file_path}' "
                f"(title: {normalized.get('title', 'N/A')[:50]})"
            )
            return None  # 返回 None 表示发现无效

        return normalized

    def _summarize_findings(self) -> str:
        """汇总当前发现"""
        if not self._all_findings:
            return "目前还没有发现任何漏洞。"
        
        # 统计
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        type_counts = {}
        
        for f in self._all_findings:
            if not isinstance(f, dict):
                continue
                
            sev = f.get("severity", "low")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            
            vtype = f.get("vulnerability_type", "other")
            type_counts[vtype] = type_counts.get(vtype, 0) + 1
        
        summary = f"""## 当前发现汇总

**总计**: {len(self._all_findings)} 个漏洞

### 严重程度分布
- Critical: {severity_counts['critical']}
- High: {severity_counts['high']}
- Medium: {severity_counts['medium']}
- Low: {severity_counts['low']}

### 漏洞类型分布
"""
        for vtype, count in type_counts.items():
            summary += f"- {vtype}: {count}\n"
        
        summary += "\n### 详细列表\n"
        for i, f in enumerate(self._all_findings):
            if isinstance(f, dict):
                summary += f"{i+1}. [{f.get('severity')}] {f.get('title')} ({f.get('file_path')})\n"
        
        return summary
    
    def _generate_default_summary(self) -> Dict[str, Any]:
        """生成默认摘要"""
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        
        for f in self._all_findings:
            if isinstance(f, dict):
                sev = f.get("severity", "low")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        return {
            "total_findings": len(self._all_findings),
            "severity_distribution": severity_counts,
            "conclusion": "审计完成（未通过 LLM 生成结论）",
        }
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self._conversation_history

    def get_steps(self) -> List[AgentStep]:
        """获取执行步骤"""
        return self._steps

    def _build_handoff_for_agent(
        self,
        target_agent: str,
        task: str,
        context: str,
    ) -> Optional[TaskHandoff]:
        """
        为目标 Agent 构建 TaskHandoff

        根据目标 Agent 类型，从之前的 Agent 结果中提取相关信息，
        构建结构化的任务交接协议。

        优先使用前序 Agent 返回的 handoff（如果存在），否则从 _agent_results 构建。

        Args:
            target_agent: 目标 Agent 名称 (recon/analysis/verification)
            task: 任务描述
            context: 任务上下文

        Returns:
            TaskHandoff 对象，如果没有前序信息则返回 None
        """
        # 🔥 如果是第一个 Agent (recon)，没有前序信息
        if target_agent == "recon" and not self._agent_results:
            return None

        # 🔥 优先使用前序 Agent 返回的 handoff
        # Analysis Agent 需要 Recon 的 handoff
        if target_agent == "analysis" and "recon" in self._agent_handoffs:
            recon_handoff = self._agent_handoffs["recon"]
            logger.info(f"[Orchestrator] Using Recon's handoff for Analysis Agent")
            # 更新目标 Agent
            return TaskHandoff(
                from_agent=recon_handoff.from_agent,
                to_agent=target_agent,
                summary=recon_handoff.summary,
                work_completed=recon_handoff.work_completed,
                key_findings=recon_handoff.key_findings,
                insights=recon_handoff.insights,
                suggested_actions=recon_handoff.suggested_actions,
                attention_points=recon_handoff.attention_points,
                priority_areas=recon_handoff.priority_areas,
                context_data=recon_handoff.context_data,
                confidence=recon_handoff.confidence,
            )

        # Verification Agent 需要 Analysis 的 handoff（也可能需要 Recon 的信息）
        if target_agent == "verification" and "analysis" in self._agent_handoffs:
            analysis_handoff = self._agent_handoffs["analysis"]
            logger.info(f"[Orchestrator] Using Analysis's handoff for Verification Agent")

            # 合并 Recon 的上下文信息（如果有）
            context_data = dict(analysis_handoff.context_data)
            if "recon" in self._agent_handoffs:
                recon_handoff = self._agent_handoffs["recon"]
                context_data["recon_tech_stack"] = recon_handoff.context_data.get("tech_stack", {})
                context_data["recon_entry_points"] = recon_handoff.context_data.get("entry_points", [])

            return TaskHandoff(
                from_agent=analysis_handoff.from_agent,
                to_agent=target_agent,
                summary=analysis_handoff.summary,
                work_completed=analysis_handoff.work_completed,
                key_findings=analysis_handoff.key_findings,
                insights=analysis_handoff.insights,
                suggested_actions=analysis_handoff.suggested_actions,
                attention_points=analysis_handoff.attention_points,
                priority_areas=analysis_handoff.priority_areas,
                context_data=context_data,
                confidence=analysis_handoff.confidence,
            )

        # 🔥 如果没有前序 Agent 的 handoff，从 _agent_results 构建（回退逻辑）
        logger.info(f"[Orchestrator] Building handoff from _agent_results for {target_agent}")

        # 🔥 收集工作摘要和关键发现
        work_completed = []
        key_findings = []
        insights = []
        suggested_actions = []
        attention_points = []
        priority_areas = []
        context_data = {}

        # 从 Recon 结果构建 handoff（给 Analysis）
        if target_agent == "analysis" and "recon" in self._agent_results:
            recon_data = self._agent_results["recon"]

            work_completed.append("完成项目信息收集和技术栈识别")

            # 提取技术栈信息
            tech_stack = recon_data.get("tech_stack", {})
            if tech_stack:
                work_completed.append(
                    f"识别技术栈: {', '.join(tech_stack.get('languages', []))} / "
                    f"{', '.join(tech_stack.get('frameworks', []))}"
                )
                context_data["tech_stack"] = tech_stack

            # 提取入口点
            entry_points = recon_data.get("entry_points", [])
            if entry_points:
                work_completed.append(f"发现 {len(entry_points)} 个入口点")
                context_data["entry_points"] = entry_points[:20]  # 限制数量
                for ep in entry_points[:10]:
                    if isinstance(ep, dict):
                        attention_points.append(
                            f"[{ep.get('type', 'unknown')}] {ep.get('file', '')}:{ep.get('line', '')}"
                        )

            # 提取高风险区域
            high_risk_areas = recon_data.get("high_risk_areas", [])
            if high_risk_areas:
                insights.append(f"发现 {len(high_risk_areas)} 个高风险区域需要重点分析")
                priority_areas.extend(high_risk_areas[:15])

            # 提取初步发现
            initial_findings = recon_data.get("initial_findings", [])
            if initial_findings:
                for f in initial_findings[:10]:
                    if isinstance(f, dict):
                        key_findings.append(f)
                        suggested_actions.append({
                            "action": "deep_analysis",
                            "target": f.get("file_path", ""),
                            "reason": f.get("title", "需要深入分析")
                        })

            # 推荐的工具
            recommended_tools = recon_data.get("recommended_tools", {})
            if recommended_tools:
                context_data["recommended_tools"] = recommended_tools

        # 从 Analysis 结果构建 handoff（给 Verification）
        elif target_agent == "verification":
            # 先添加 Recon 的信息（如果有）
            if "recon" in self._agent_results:
                recon_data = self._agent_results["recon"]
                context_data["tech_stack"] = recon_data.get("tech_stack", {})
                context_data["entry_points"] = recon_data.get("entry_points", [])[:10]

            # 添加 Analysis 的信息
            if "analysis" in self._agent_results:
                analysis_data = self._agent_results["analysis"]

                work_completed.append("完成代码深度分析")

                findings = analysis_data.get("findings", [])
                if findings:
                    work_completed.append(f"发现 {len(findings)} 个潜在漏洞")

                    # 按严重程度排序，优先验证高危漏洞
                    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
                    sorted_findings = sorted(
                        findings,
                        key=lambda x: severity_order.get(x.get("severity", "low"), 3)
                    )

                    for f in sorted_findings[:15]:
                        if isinstance(f, dict):
                            key_findings.append(f)
                            suggested_actions.append({
                                "action": "verify",
                                "target": f.get("file_path", ""),
                                "vulnerability_type": f.get("vulnerability_type", "unknown"),
                                "priority": "high" if f.get("severity") in ["critical", "high"] else "normal"
                            })

                    # 统计严重程度分布
                    severity_counts = {}
                    for f in findings:
                        sev = f.get("severity", "unknown")
                        severity_counts[sev] = severity_counts.get(sev, 0) + 1

                    insights.append(
                        f"漏洞分布: Critical={severity_counts.get('critical', 0)}, "
                        f"High={severity_counts.get('high', 0)}, "
                        f"Medium={severity_counts.get('medium', 0)}, "
                        f"Low={severity_counts.get('low', 0)}"
                    )

            # 也包含已有的发现（可能来自多个 Agent）
            if self._all_findings:
                context_data["all_findings"] = self._all_findings[:20]

        # 如果没有任何工作记录，说明没有前序信息
        if not work_completed and not key_findings:
            return None

        # 构建 TaskHandoff
        summary = f"任务: {task[:100]}"
        if work_completed:
            summary = f"前序工作已完成: {', '.join(work_completed[:3])}"

        return TaskHandoff(
            from_agent="Orchestrator",
            to_agent=target_agent,
            summary=summary,
            work_completed=work_completed,
            key_findings=key_findings,
            insights=insights,
            suggested_actions=suggested_actions,
            attention_points=attention_points,
            priority_areas=priority_areas,
            context_data=context_data,
            confidence=0.85,
        )
