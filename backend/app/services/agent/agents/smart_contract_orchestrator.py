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

ORCHESTRATOR_SYSTEM_PROMPT = """你是 DeepAudit 的智能合约审计编排 Agent，负责**自主**协调整个 Web3 安全审计的生命周期。

## 你的角色
你是整个智能合约审计流程的**战略大脑**，不是一个机械执行者。你需要：
1. 自主思考和决策
2. 协调多 Agent 协作：从代码侦察、漏洞挖掘，到 PoC 编写与沙箱动态验证的完整闭环
3. 根据观察结果动态调整审计策略
4. 判断何时审计完成，并输出最终带有真实资金损失证明的高确信度报告

## 你可以调度的子 Agent
1. **recon**: 情报侦察 Agent - 负责下载链上合约源码，分析 Solidity 项目结构、依赖库和核心入口点。
2. **analysis**: 漏洞挖掘 Agent - 深度代码审计，通过 RAG 知识库匹配重入、溢出、访问控制等漏洞，并提出具体的攻击思路。
3. **verification**: 漏洞利用与验证 Agent - 接收攻击思路，自主编写 Foundry PoC 攻击脚本 (`Verification.t.sol`)。它会在沙箱中自行完成“编译-报错-修复-执行”的闭环，最终返回真实的 Profit（获利）和 Gas 消耗数据。

## 你可以使用的操作

### 1. 调度子 Agent
```
Action: dispatch_agent
Action Input: {"agent": "recon|analysis|verification", "task": "具体任务描述", "context": "上游Agent提供的任务上下文或前置数据"}
```

### 2. 汇总发现
```
Action: summarize
Action Input: {"findings": [...], "analysis": "当前审计进度分析"}
```

### 3. 完成审计
```
Action: finish
Action Input: {"conclusion": "最终审计结论", "verified_vulnerabilities": [...], "unverified_vulnerabilities": [...]}
```

## 智能合约审计工作流 (标准闭环)
1. **启动**：首先调度 `recon`，获取目标合约的物理源码和结构概览。
2. **挖掘**：将 `recon` 返回的核心合约与入口点交给 `analysis` 进行深度漏洞挖掘。
3. **利用与验证**：将 `analysis` 发现的每一个潜在漏洞和“攻击思路”交给 `verification`。`verification` Agent 会自行完成代码编写、沙箱测试与修复，你只需等待它的最终验证战报。

## 工作方式
每一步，你需要输出：

```
Thought: [分析当前状态，思考目前收集到了什么？还需要调度哪个 Agent？]
Action: [dispatch_agent|summarize|finish]
Action Input: [JSON 格式的参数]
```

🚨 警告：输出完 Action Input 后，**必须立刻停止输出！绝对禁止你自己生成 Observation！** 系统的执行引擎会自动执行工具，并将真实的 Observation 返回给你。如果你自己编造 Observation，任务将被直接判定失败。

## 审计策略与重要原则
1. **你是大脑，不是执行器** - 每一步都要基于当前的 Observation 思考。
2. **标准调度顺序** - 先用 `recon` 了解项目全貌（通常只需调度一次）；再根据结果让 `analysis` 重点审计；发现可疑漏洞后，立刻让 `verification` 进行沙箱验证。
3. **主动决策与动态调整** - 不要机械执行。如果一个方向没有发现，主动调整策略或结束审计。
4. **质量优先** - 宁可深入分析并验证出几个真实的致命漏洞，也不要浅尝辄止地报告大量误报。
5. **避免重复** - 如果 `verification` 明确报告某个漏洞由于防御机制无法被利用（执行回滚/未获利），**不要**再次派发给它，直接将该漏洞标记为误报并继续分析下一个。

## 处理子 Agent 结果
- 子 Agent 返回的 Observation 包含它们的执行结果与发现。
- 即使结果看起来不完整，也要基于已有信息继续推进。
- 如果 `recon` 找不到相关文件，说明可能地址错误或项目为空，可以直接结束审计。
- 当所有的漏洞都经过了 `verification` 验证，或者确认没有更多高危区域需要检查时，使用 `finish` 结束审计。

记住：**无 PoC 不漏洞**。你的最终目标是通过合理的调度，拿到带有真实 `Profit`（获利金额）证明的漏洞战果报告！"""


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
        # 组合增强的系统提示词，注入核心安全原则
        full_system_prompt = f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n{CORE_SECURITY_PRINCIPLES}\n\n{MULTI_AGENT_RULES}"
        
        config = AgentConfig(
            name="Orchestrator",
            agent_type=AgentType.ORCHESTRATOR,
            pattern=AgentPattern.REACT,
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
        
        # 🔥 新增：动态覆盖 Orchestrator 的最大迭代次数
        if "max_iterations" in config:
            self.config.max_iterations = config["max_iterations"]
            logger.info(f"[Orchestrator] 动态调整最大迭代次数为: {self.config.max_iterations}")

        # 🔥 保存运行时上下文，用于传递给子 Agent
        self._runtime_context = {
            "project_info": project_info,
            "config": config,
            "project_root": input_data.get("project_root", project_info.get("root", ".")),
            "task_id": input_data.get("task_id"),
        }
        
        # 构建初始消息，注入项目基本信息和用户配置
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
        """构建初始消息 (注入 Web3 链上或本地审计上下文)"""
        import json
        
        target_address = config.get("target_address", [])
        chain = config.get("chain", "mainnet")  # 默认mainnet
        
        structure = project_info.get("structure", {})
        scope_limited = structure.get("scope_limited", False)
        scope_message = structure.get("scope_message", "")
        
        msg = f"请开始对智能合约进行安全审计。\n\n"
        
        # 场景 1：链上地址审计 (首选)
        if target_address:
            msg += f"## 审计目标 (链上资产)\n"
            msg += "- 目标合约列表:\n"
            # 直接遍历列表，生成干净的 Markdown 格式
            for addr in target_address:
                msg += f"  * {addr}\n"
            msg += f"- 所在链: {chain}\n\n"
            msg += "🚨 **重要提示**：这是链上智能合约！你的第一步**必须**是调度 `recon` Agent，让它去链上下载该地址的源码到本地沙箱！\n"
        # 注意：这里我们刻意向大模型隐藏了那个空的 project_info！
            
        # 场景 2：本地代码库/ZIP包审计
        else:
            msg += f"## 审计目标 (本地代码库)\n"
            msg += f"- 项目名称: {project_info.get('name', 'Unknown')}\n"
            msg += f"- 项目目录: {project_info.get('root', '.')}\n"
            msg += f"- 核心语言: {', '.join(project_info.get('languages', ['Solidity']))}\n"
            msg += f"- 业务文件数: {project_info.get('file_count', 0)}\n\n"
            
            # 如果用户开启了白名单 (target_files)
            if scope_limited:
                msg += f"## ⚠️ 审计范围严格限定\n"
                msg += f"**{scope_message}**\n\n"
                msg += f"### 目标文件列表\n"
                for f in structure.get('files', []):
                    msg += f"- {f}\n"
                msg += "\n🚨 **警告**：请绝对聚焦于上述文件，忽略其他非核心文件！\n"
            # 如果是全量审计，展示项目结构
            else:
                msg += f"## 目录结构概览\n"
                msg += f"```json\n{json.dumps(structure, ensure_ascii=False, indent=2)}\n```\n"

        # 提取用户配置的漏洞偏好
        target_vulnerabilities = config.get(
            'target_vulnerabilities', 
            [
                'integer_overflow_underflow', # 整数溢出/下溢
                'insecure_randomness',        # 不安全的随机性
                'arithmetic_errors',          # 计算错误
                'access_control',             # 访问控制漏洞
                'logic_errors',               # 逻辑错误
                'flash_loan',                 # 闪电贷攻击
                'gas_limit',                  # Gas限制漏洞
                'denial_of_service',          # 拒绝服务攻击 (DoS)
                'unchecked_external_calls',   # 未检查的外部调用
                'price_oracle_manipulation',  # 价格预言机操纵
                'lack_of_input_validation',   # 缺少输入验证
                'reentrancy',                 # 可重入攻击
                'short_address',              # 短地址攻击
                'assert_failure',             # 断言失败
                'proxy_upgradeability',       # 代理和可升级性漏洞
                'front_running',              # 抢跑攻击 (MEV)
                'timestamp_dependence'        # 时间戳依赖
            ]
        )
        exclude_patterns = config.get('exclude_patterns', ['lib/**', 'test/**', 'node_modules'])
        
        msg += f"""
## 全局审计配置
- 重点关注漏洞: {target_vulnerabilities}
- 验证级别: {config.get('verification_level', 'foundry_sandbox')} (无 PoC 不漏洞，必须动态执行)
- 排除分析目录: {exclude_patterns} (请勿审计这些标准库或测试代码)

## 可用子 Agent
{', '.join(self.sub_agents.keys()) if self.sub_agents else '(暂无子 Agent)'}

请开始你的审计工作。首先思考当前状态，然后决定第一步做什么。"""
        
        return msg
    
    def _parse_llm_response(self, response: str) -> Optional[AgentStep]:
        """解析LLM响应"""
        # 预处理 - 移除 Markdown 格式标记
        cleaned_response = re.sub(r'\*\*Action:\*\*', 'Action:', response)
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
        agent = self.sub_agents.get(agent_name) # 获取agent_name对应的Agent对象，如果不存在则返回None
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

            # 异步可取消包装器
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
                # 获取子 Agent 结果，支持超时和取消
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

                # 兼容 Recon 的 initial_findings
                if "initial_findings" in data:
                    for f in data.get("initial_findings", []):
                        if isinstance(f, dict):
                            normalized = self._normalize_finding(f)
                            if normalized and normalized not in raw_findings:
                                raw_findings.append(normalized)

                # 提取 Web3 视角的 Findings 并使用高级去重逻辑
                valid_findings = [f for f in raw_findings if isinstance(f, dict)]
                
                for new_f in valid_findings:
                    normalized_new = self._normalize_finding(new_f)
                    if not normalized_new:
                        continue

                    new_file = normalized_new.get("file_path", "").lower().strip()
                    new_type = normalized_new.get("vulnerability_type", "").lower()

                    found = False
                    for i, existing_f in enumerate(self._all_findings):
                        existing_file = existing_f.get("file_path", "").lower().strip()
                        existing_type = existing_f.get("vulnerability_type", "").lower()
                        
                        # 判断是否为同一个漏洞：同文件 且 同类型
                        same_file = new_file and existing_file and (new_file == existing_file or new_file.endswith(existing_file) or existing_file.endswith(new_file))
                        same_type = new_type and existing_type and (new_type == existing_type or new_type in existing_type or existing_type in new_type)

                        if same_file and same_type:
                            # 🔥 智能无损合并 (Smart Merge)
                            merged = dict(existing_f)
                            for key, value in normalized_new.items():
                                # 核心规则：新数据存在 且 不为空 时才覆盖
                                # 这样 Verification Agent 不会把 Analysis Agent 写好的 attack_strategy 给洗掉
                                if value is not None and value != "":
                                    # 如果遇到字典或列表且旧值也存在，应该做更精细的判断，但此处主要字段已在 normalize 中展平
                                    merged[key] = value
                            
                            # 状态优先级提升：只要有任何一次被标记为验证成功，就永久保留 True
                            if existing_f.get("is_verified") or normalized_new.get("is_verified"):
                                merged["is_verified"] = True
                                
                            self._all_findings[i] = merged
                            found = True
                            break

                    if not found:
                        self._all_findings.append(normalized_new)

                await self.emit_event("dispatch_complete", f"✅ {agent_name} Agent 完成", agent=agent_name, findings_count=len(self._all_findings))
                
                # 构建给 LLM 读的观察结果
                observation = f"## {agent_name} Agent 执行成功\n**状态**: 成功\n**本次发现漏洞数**: {len(valid_findings)}\n**全局累积漏洞数**: {len(self._all_findings)}\n\n"
                if data.get("summary"):
                    observation += f"### Agent 总结\n{data['summary']}"
                    
                return observation
            else:
                return f"## {agent_name} Agent 执行失败\n\n错误: {result.error}"
                
        except Exception as e:
            logger.error(f"Sub-agent dispatch failed: {e}", exc_info=True)
            return f"## 调度失败\n\n错误: {str(e)}"

    def _validate_file_path(self, file_path: str) -> bool:
        """
        验证文件路径是否真实存在 (防大模型幻觉)
        """
        if not file_path or not file_path.strip():
            return False

        # 获取项目根目录
        project_root = self._runtime_context.get("project_root", "")
        if not project_root:
            return True # 没有根目录时放行，避免误杀

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
        标准化各个 Agent 返回的漏洞发现，统一字段格式，防幻觉校验，并提取 Web3 专属的战果数据。
        """
        normalized = dict(finding)

        # ==========================================
        # 1. 统一文件路径与防幻觉校验 (Foundation)
        # ==========================================
        if "location" in normalized and "file_path" not in normalized:
            location = normalized["location"]
            if isinstance(location, str):
                normalized["file_path"] = location.split(":")[0]

        if "file" in normalized and "file_path" not in normalized:
            normalized["file_path"] = normalized["file"]

        file_path = normalized.get("file_path", "")
        if file_path and not self._validate_file_path(file_path):
            logger.warning(f"[Orchestrator] 🚫 过滤幻觉发现: 文件不存在 '{file_path}' (title: {normalized.get('title', 'N/A')[:50]})")
            return None  # 文件不存在则抛弃

        # ==========================================
        # 2. 兼容 Recon Agent：推断缺失的基础字段
        # ==========================================
        if "vulnerability_type" not in normalized:
            desc = (normalized.get("description", "") + " " + normalized.get("title", "")).lower()
            if "reentran" in desc or "call.value" in desc:
                normalized["vulnerability_type"] = "reentrancy"
            elif "oracle" in desc or "price" in desc:
                normalized["vulnerability_type"] = "oracle_manipulation"
            elif "flash" in desc or "loan" in desc:
                normalized["vulnerability_type"] = "flash_loan_attack"
            elif "access" in desc or "onlyowner" in desc or "role" in desc:
                normalized["vulnerability_type"] = "access_control"
            elif "overflow" in desc or "underflow" in desc or "math" in desc:
                normalized["vulnerability_type"] = "arithmetic_error"
            elif "front" in desc or "run" in desc or "mev" in desc:
                normalized["vulnerability_type"] = "front_running"
            elif "delegatecall" in desc or "proxy" in desc:
                normalized["vulnerability_type"] = "proxy_upgradeability"
            else:
                normalized["vulnerability_type"] = "smart_contract_issue"

        # 确保漏洞类型是标准蛇形命名
        normalized["vulnerability_type"] = normalized["vulnerability_type"].lower().replace(" ", "_")

        # 严重程度：没有明确说明的，默认为 high，防止误报被放大
        if "severity" in normalized:
            normalized["severity"] = str(normalized["severity"]).lower()
        else:
            normalized["severity"] = "high"

        if "title" not in normalized:
            vuln_type = normalized.get("vulnerability_type", "Unknown")
            fp = os.path.basename(file_path) if file_path else "Unknown File"
            normalized["title"] = f"{vuln_type.replace('_', ' ').title()} in {fp}"

        # ==========================================
        # 3. 兼容 Analysis Agent：确保高级字段存在
        # ==========================================
        # 即使上游没有提供，也初始化为空字符串，保证最终报告的 Schema 完整不报错
        analysis_fields = ["target_function_signature", "code_snippet", "source", "sink", "attack_strategy", "suggestion"]
        for field in analysis_fields:
            if field not in normalized:
                normalized[field] = ""

        # ==========================================
        # 4. 兼容 Verification Agent：提取沙箱战果与嵌套 PoC
        # ==========================================
        # 提取判定结论
        if "verdict" in finding:
            normalized["verdict"] = finding["verdict"]
            # 只有明确 confirmed 才算 verified
            if finding["verdict"] == "confirmed":
                normalized["is_verified"] = True

        # 提取利润和 Gas
        if "profit_extracted" in finding and finding["profit_extracted"] is not None:
            normalized["profit_extracted"] = finding["profit_extracted"]
            normalized["is_verified"] = True  # 能榨取利润必定是真实漏洞
        if "gas_used" in finding:
            normalized["gas_used"] = finding["gas_used"]

        # 🚨 重点修复：解析嵌套的 poc 字典，提取真实攻击载荷 (Payload)
        if "poc" in finding and isinstance(finding["poc"], dict):
            poc_data = finding["poc"]
            normalized["poc_file_path"] = poc_data.get("poc_file_path", "")
            normalized["poc_payload"] = poc_data.get("payload", "") # 核心的 Solidity 代码
            normalized["poc_description"] = poc_data.get("description", "")
        else:
            # 兼容扁平结构防御
            if "poc_file_path" in finding:
                normalized["poc_file_path"] = finding["poc_file_path"]
            if "poc_payload" not in normalized:
                normalized["poc_payload"] = ""

        return normalized

    def _summarize_findings(self) -> str:
        """
        汇总发现格式
        """
        if not self._all_findings:
            return "目前还没有发现任何智能合约漏洞。"
        
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        verified_count = 0
        
        for f in self._all_findings:
            if not isinstance(f, dict): continue
            sev = f.get("severity", "low")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            if f.get("is_verified"):
                verified_count += 1
        
        summary = f"""## 审计进度汇总
**总计漏洞**: {len(self._all_findings)} 个
**已通过 PoC 验证**: {verified_count} 个

### 严重程度分布
- Critical: {severity_counts['critical']}
- High: {severity_counts['high']}
- Medium: {severity_counts['medium']}
- Low: {severity_counts['low']}

### 漏洞详情
"""
        for i, f in enumerate(self._all_findings):
            if isinstance(f, dict):
                # 突出 Web3 的验证标志
                status = "🔴 [沙箱 PoC 已验证]" if f.get("is_verified") else "🟡 [静态疑似]"
                profit = f" | 榨取利润: {f.get('profit_extracted')} ETH" if f.get("profit_extracted") else ""
                summary += f"{i+1}. {status} [{f.get('severity')}] {f.get('title')} ({f.get('vulnerability_type')}){profit}\n"
        
        return summary
    
    def _generate_default_summary(self) -> Dict[str, Any]:
        """生成原版格式的默认摘要 (供前端 UI 渲染使用)"""
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        verified_count = 0
        
        for f in self._all_findings:
            if isinstance(f, dict):
                sev = f.get("severity", "low")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
                if f.get("is_verified"):
                    verified_count += 1
        
        return {
            "total_findings": len(self._all_findings),
            "verified_findings": verified_count,
            "severity_distribution": severity_counts,
            "conclusion": "智能合约审计完成。",
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
        """构建 TaskHandoff，支持 Recon -> Analysis -> Verification 的 Web3 数据接力"""
        
        if target_agent == "recon" and not self._agent_results:
            return None

        # ==========================================
        # 1. 快速通道：如果前序 Agent 乖乖生成了 handoff，直接使用
        # ==========================================
        if target_agent == "analysis" and "recon" in self._agent_handoffs:
            recon_handoff = self._agent_handoffs["recon"]
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

        if target_agent == "verification" and "analysis" in self._agent_handoffs:
            analysis_handoff = self._agent_handoffs["analysis"]
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

        # ==========================================
        # 2. 兜底通道：如果没有 Handoff，从原始 results 手工拼凑
        # ==========================================
        logger.info(f"[Orchestrator] Building handoff from _agent_results for {target_agent}")

        work_completed = []
        key_findings = []
        insights = []
        suggested_actions = []
        attention_points = []
        priority_areas = []
        context_data = {}

        # 兜底: Recon -> Analysis
        if target_agent == "analysis" and "recon" in self._agent_results:
            recon_data = self._agent_results["recon"]
            work_completed.append("完成智能合约初步侦察")

            tech_stack = recon_data.get("tech_stack", {})
            if tech_stack:
                work_completed.append(f"识别技术栈: {', '.join(tech_stack.get('languages', []))}")
                context_data["tech_stack"] = tech_stack

            entry_points = recon_data.get("entry_points", [])
            if entry_points:
                work_completed.append(f"发现 {len(entry_points)} 个合约入口点")
                context_data["entry_points"] = entry_points[:20] 

            high_risk_areas = recon_data.get("high_risk_areas", [])
            if high_risk_areas:
                insights.append(f"发现 {len(high_risk_areas)} 个高风险区域")
                priority_areas.extend(high_risk_areas[:15])

            initial_findings = recon_data.get("initial_findings", [])
            if initial_findings:
                for f in initial_findings[:10]:
                    if isinstance(f, dict):
                        key_findings.append(f)
                        suggested_actions.append({
                            "action": "deep_analysis",
                            "target": f.get("file_path", ""),
                            "reason": f.get("title", "需要深入挖掘")
                        })

        # 兜底: Analysis -> Verification
        elif target_agent == "verification":
            if "recon" in self._agent_results:
                recon_data = self._agent_results["recon"]
                context_data["tech_stack"] = recon_data.get("tech_stack", {})
                context_data["entry_points"] = recon_data.get("entry_points", [])[:10]

            if "analysis" in self._agent_results:
                analysis_data = self._agent_results["analysis"]
                work_completed.append("完成智能合约漏洞挖掘")

                findings = analysis_data.get("findings", [])
                if findings:
                    work_completed.append(f"发现 {len(findings)} 个潜在漏洞")
                    
                    # 提取高危漏洞优先交给 Verification 验证
                    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
                    sorted_findings = sorted(
                        findings,
                        key=lambda x: severity_order.get(x.get("severity", "low"), 3)
                    )

                    for f in sorted_findings[:15]:
                        if isinstance(f, dict):
                            key_findings.append(f)
                            suggested_actions.append({
                                "action": "write_poc", 
                                "target": f.get("file_path", ""),
                                "line": f.get("line_start", ""),                                 # ✅ 补全行号
                                "function_signature": f.get("target_function_signature", ""),  # ✅ 补全函数签名
                                "code_snippet": f.get("code_snippet", ""),                       # ✅ 补全代码片段
                                "sink": f.get("sink", ""),                                       # ✅ 补全危险函数
                                "source": f.get("source", ""),                                   # ✅ 补全污染源
                                "vulnerability_type": f.get("vulnerability_type", "unknown"),
                                "attack_strategy": f.get("attack_strategy", ""),                 # ✅ 补全攻击策略
                                "severity": f.get("severity", "medium"),
                                "reason": f.get("title", "")
                            })

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