"""
Recon Agent (信息收集层) - LLM 驱动版

LLM 是真正的大脑！
- LLM 决定收集什么信息
- LLM 决定使用哪个工具
- LLM 决定何时信息足够
- LLM 动态调整收集策略

类型: ReAct (真正的!)
"""

import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .base import BaseAgent, AgentConfig, AgentResult, AgentType, AgentPattern, TaskHandoff
from ..json_parser import AgentJsonParser
from ..prompts import TOOL_USAGE_GUIDE

# 获取模块日志记录器，用于记录 Agent 运行过程中的信息
logger = logging.getLogger(__name__)


RECON_SYSTEM_PROMPT = """你是 DeepAudit 的智能合约侦察 Agent，负责收集和分析 Web3 资产的情报与物理源码。

## 你的职责
作为安全审计的“侦察前锋”，你必须基于真实的文件数据完成以下任务：
1. **获取源码**：如果输入是链上地址，第一步必须下载代码到本地沙箱。
2. **分析项目结构**：识别底层框架（Foundry/Hardhat）及核心业务 `.sol` 文件。
3. **识别依赖与版本**：提取 Solidity 编译器版本及第三方依赖库（如 OpenZeppelin）。
4. **识别核心入口点**：找出所有的 `external`/`public`、`payable`、`fallback()` 和 `receive()` 函数。
5. **定位高危与敏感区域**：寻找底层的 `.call{value:}`、`delegatecall`、内联汇编 `assembly` 等易爆点。

## 侦察目标

### 1. 核心入口点发现 (Entry Points)
- 资金接收点
- 外部交互接口
- 资金注入通道
- 特权后门

### 2. 高危敏感区域定位 (Red Zones)
- 资金转出与底层调用
- 逻辑委托
- 外部合约调用
- 预言机与价格机制
- 内联汇编

### 3. 架构与配置分析
- 编译器配置
- 代理与可升级模式
- 硬编码地址

## 你可以使用的核心工具
- **foundry_cast**: **🔥 最高优先级**。如果审计目标是 `0x` 开头的地址，必须先用此工具拉取链上真实源码！
- **list_files**: 查看本地文件目录结构。
- **read_file**: 读取主合约内容，提取版本、依赖和具体逻辑。
- **search_code**: 全局搜索关键语法（如搜 `payable` 或 `call` 快速定位入口和风险点）。

## 工作方式 (ReAct 模式)
每一步，你需要严格输出：

```
Thought: [分析当前目标，决定需要调用哪个工具]
Action: [工具名称]
Action Input: {"参数1": "值1"}
```
🚨 警告：输出完 Action Input 后，**必须立刻停止输出！绝对禁止你自己生成 Observation！**

当你通过工具确认了足够的情报后，输出最终侦察报告：

```
Thought: [总结收集到的智能合约信息]
Final Answer: [严格的 JSON 格式结果]
```

## ⚠️ 输出格式要求 (绝对红线)
**禁止使用 Markdown 格式标记 (`**`) 修饰流程关键字！** 你的中间过程必须是纯文本。

✅ 正确格式：
```
Thought: 我需要查看项目结构来了解项目组成
Action: list_files
Action Input: {"directory": "."}
```

❌ 错误格式（禁止使用）：
```
**Thought:** 我需要查看项目结构
**Action:** list_files
**Action Input:** {"directory": "."}
```

规则：
1. 不要在 `Thought:`、`Action:`、`Action Input:`、`Final Answer:` 前后添加 `**` 或 `###`。
2. `Action Input` 必须是完整的 JSON 对象，不能为空或截断。
2. 不要使用其他 Markdown 格式（如 `###`、`*斜体*` 等）

## Final Answer JSON 格式规范
必须严格输出以下 JSON 结构（Orchestrator 依赖这些具体字段）：
```json
{
    "tech_stack": {"solidity_versions": [...], "dependencies": ["OpenZeppelin"]},
    "entry_points": [
        {"type": "payable_function", "file": "src/Vault.sol", "line": 7, "method": "deposit()"},
        {"type": "external_function", "file": "src/Vault.sol", "line": 11, "method": "withdraw(uint256)"}
    ],
    "high_risk_areas": [
        "文件路径:行号 - 风险描述",
    ],
    "initial_findings": [
        {"title": "...", "file_path": "...", "line_start": ..., "description": "..."}
    ],
    "summary": "合约初步分析完成，核心业务逻辑在 Vault.sol 中，发现 1 个高危 call 调用，已记录为 initial_findings。"
}
```

## ⚠️ 重要输出要求

### high_risk_areas 格式要求
每个高风险区域**必须**包含具体的文件路径，格式为：
- `"src/Vault.sol:42 - delegatecall 调用可控地址"`

**禁止**输出纯描述性文本如 "File write operations with user-controlled paths"，必须指明具体文件。

### initial_findings 格式要求
每个发现**必须**包含：
- `title`: 漏洞标题
- `file_path`: 具体文件路径
- `line_start`: 行号
- `description`: 详细描述

## 🚨 防止幻觉与核心约束 (违背将导致系统崩溃)！
1. **禁止直接交卷**：你必须先调用工具（至少调用 `list_files` 或 `foundry_cast`），绝不允许不看代码直接输出 `Final Answer`。
2. **地址优先规则**：如果任务目标是 `0x` 开头的地址，你的 **第一个 Action 必须是 `foundry_cast`**！不要去读本地空目录。
3. **真实文件与行号规则（眼见为实）**：
   - `core_contracts` 必须是你通过工具真实看到的 `.sol` 文件，绝不能凭空捏造 `Token.sol`。
   - `high_risk_areas` 和 `initial_findings` 中的 `file_path` 和 `line_start` **必须绝对精确**！必须是你通过 `read_file` 或 `search_code` 看到的真实代码行，严禁编造行号！
4. 🚨 警告：输出完 Action Input 后，**必须立刻停止输出！绝对禁止你自己生成 Observation！** 
"""

@dataclass
class ReconStep:
    """信息收集步骤 - ReAct 模式的单步执行单元"""
    thought: str
    action: Optional[str] = None
    action_input: Optional[Dict] = None
    observation: Optional[str] = None
    is_final: bool = False
    final_answer: Optional[Dict] = None

class ReconAgent(BaseAgent):
    """
    智能合约侦察 Agent - Web3 安全审计的核心入口
    
    继承自 BaseAgent，实现了针对智能合约领域的定制化侦察逻辑。
    融合了通用侦察 Agent 的高鲁棒性机制（防幻觉解析、错误熔断、多轮重试）。
    """

    def __init__(
        self,
        llm_service,
        tools: Dict[str, Any],
        event_emitter=None,
    ):
        full_system_prompt = f"{RECON_SYSTEM_PROMPT}\n\n{TOOL_USAGE_GUIDE}"  # 待检查修改！！！ TOOL_USAGE_GUIDE
        
        config = AgentConfig(
            name="Recon",
            agent_type=AgentType.RECON,
            pattern=AgentPattern.REACT,
            max_iterations=15,
            system_prompt=full_system_prompt,
        )
        super().__init__(config, llm_service, tools, event_emitter)
        
        self._conversation_history: List[Dict[str, str]] = []
        self._steps: List[ReconStep] = []

    def _parse_llm_response(self, response: str) -> ReconStep:
        """解析 LLM 响应 - 增强版，更健壮地提取思考内容"""
        step = ReconStep(thought="")

        # 🔥 预处理 - 移除 Markdown 格式标记
        cleaned_response = response
        cleaned_response = re.sub(r'\*\*Action:\*\*', 'Action:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Action Input:\*\*', 'Action Input:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Thought:\*\*', 'Thought:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Final Answer:\*\*', 'Final Answer:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Observation:\*\*', 'Observation:', cleaned_response)

        # 🔥 尝试提取明确的 Thought 标记
        thought_match = re.search(r'Thought:\s*(.*?)(?=Action:|Final Answer:|$)', cleaned_response, re.DOTALL)
        if thought_match:
            step.thought = thought_match.group(1).strip()

        # 🔥 检查是否是最终答案
        final_match = re.search(r'Final Answer:\s*(.*?)$', cleaned_response, re.DOTALL)
        if final_match:
            step.is_final = True
            answer_text = final_match.group(1).strip()
            answer_text = re.sub(r'```json\s*', '', answer_text)
            answer_text = re.sub(r'```\s*', '', answer_text)
            # 使用增强的 JSON 解析器
            step.final_answer = AgentJsonParser.parse(
                answer_text,
                default={"raw_answer": answer_text}
            )
            # 确保 findings 格式正确
            if "initial_findings" in step.final_answer:
                step.final_answer["initial_findings"] = [
                    f for f in step.final_answer["initial_findings"]
                    if isinstance(f, dict)
                ]

            # 🔥 如果没有提取到 thought，使用 Final Answer 前的内容作为思考
            if not step.thought:
                before_final = cleaned_response[:cleaned_response.find('Final Answer:')].strip()
                if before_final:
                    # 移除可能的 Thought: 前缀
                    before_final = re.sub(r'^Thought:\s*', '', before_final)
                    step.thought = before_final[:500] if len(before_final) > 500 else before_final

            return step

        # 🔥 提取 Action
        action_match = re.search(r'Action:\s*(\w+)', cleaned_response)
        if action_match:
            step.action = action_match.group(1).strip()

            # 🔥 如果没有提取到 thought，提取 Action 之前的内容作为思考
            if not step.thought:
                action_pos = cleaned_response.find('Action:')
                if action_pos > 0:
                    before_action = cleaned_response[:action_pos].strip()
                    # 移除可能的 Thought: 前缀
                    before_action = re.sub(r'^Thought:\s*', '', before_action)
                    if before_action:
                        step.thought = before_action[:500] if len(before_action) > 500 else before_action

        # 🔥 提取 Action Input
        input_match = re.search(r'Action Input:\s*(.*?)(?=Thought:|Action:|Observation:|$)', cleaned_response, re.DOTALL)
        if input_match:
            input_text = input_match.group(1).strip()
            input_text = re.sub(r'```json\s*', '', input_text)
            input_text = re.sub(r'```\s*', '', input_text)
            # 使用增强的 JSON 解析器
            step.action_input = AgentJsonParser.parse(
                input_text,
                default={"raw_input": input_text}
            )

        # 🔥 最后的 fallback：如果整个响应没有任何标记，整体作为思考
        if not step.thought and not step.action and not step.is_final:
            if response.strip():
                step.thought = response.strip()[:500]

        return step

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        执行信息收集 - LLM 全程参与！
        """
        import time
        start_time = time.time()
        
        project_info = input_data.get("project_info", {})
        config = input_data.get("config", {})
        task = input_data.get("task", "")
        task_context = input_data.get("task_context", "")
        
        # 🔥 获取白名单与黑名单配置
        target_files = config.get("target_files", [])
        exclude_patterns = config.get("exclude_patterns", [])
        
        target = config.get('target_address', [])
        is_contract_address = len(target) > 0
        
        initial_message = f"""请开始收集智能合约项目信息。

## 审计目标
* 目标: {target}
"""
        # 智能分支：地址抓取 vs 范围审计
        if is_contract_address:
            initial_message += """
🚨 **最高级别系统指令**：检测到目标为以太坊合约地址！
你当前的本地目录是**空的**！
你的**第一个 Action 必须且只能是 `foundry_cast`**！
如果你的第一步没有调用 `foundry_cast`，系统将直接判定任务失败！
下载完成后，再使用 list_files 查看源码结构。
"""
        else:
            initial_message += f"""这是一个本地/代码库中的智能合约项目。
- 根目录: {project_info.get('root', '.')}
- 文件数量: {project_info.get('file_count', 'unknown')}
"""
            if target_files:
                initial_message += f"""
⚠️ **重要**: 用户指定了 {len(target_files)} 个目标文件进行审计：
"""
                for tf in target_files[:10]:
                    initial_message += f"- {tf}\n"
                if len(target_files) > 10:
                    initial_message += f"- ... 还有 {len(target_files) - 10} 个文件\n"
                initial_message += """
请直接读取和分析这些指定的文件，不要浪费时间遍历其他目录。
"""
            else:
                initial_message += "全项目审计（无特定文件限制）。请使用 `list_files` 查看项目结构，找出核心的 `.sol` 文件进行分析。\n"

        if exclude_patterns:
            initial_message += f"\n排除模式: {', '.join(exclude_patterns[:5])}\n"

        initial_message += f"""
## 任务上下文
{task_context or task or '进行全面的智能合约信息收集，识别资金流向和关键入口，为安全审计做准备。'}

## 可用工具
{self.get_tools_description()}

请开始你的信息收集工作。首先思考应该收集什么信息，然后**立即**选择合适的工具执行（输出 Action）。不要只输出 Thought，必须紧接着输出 Action。"""

        # 初始化对话历史
        self._conversation_history = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": initial_message},
        ]
        
        self._steps = []
        final_result = None
        error_message = None  # 🔥 跟踪错误信息
        
        await self.emit_thinking("Recon Agent 启动，LLM 开始自主收集信息...")
        
        try:
            for iteration in range(self.config.max_iterations):
                if self.is_cancelled:
                    break
                
                self._iteration = iteration + 1
                
                # 🔥 再次检查取消标志（在LLM调用之前）
                if self.is_cancelled:
                    await self.emit_thinking("🛑 任务已取消，停止执行")
                    break
                
                # 调用 LLM 进行思考和决策（使用基类统一方法）
                try:
                    llm_output, tokens_this_round = await self.stream_llm_call(
                        self._conversation_history
                        # 🔥 不传递 temperature 和 max_tokens，使用用户配置
                    )
                except asyncio.CancelledError:
                    logger.info(f"[{self.name}] LLM call cancelled")
                    break
                
                self._total_tokens += tokens_this_round

                # ==========================================
                # 🔥 终极物理截断防线：斩断幻觉！
                # 只要大模型试图自己输出 Observation，直接把后面的所有内容砍掉！
                # ==========================================
                if "Observation:" in llm_output:
                    logger.warning(f"[{self.name}] 拦截到 LLM 试图幻觉 Observation，进行物理截断！")
                    llm_output = llm_output.split("Observation:")[0].strip()
                elif "**Observation:**" in llm_output:
                    llm_output = llm_output.split("**Observation:**")[0].strip()
                # ==========================================
                
                # 高容错增强版：处理空响应
                if not llm_output or not llm_output.strip():
                    empty_retry_count = getattr(self, '_empty_retry_count', 0) + 1
                    self._empty_retry_count = empty_retry_count
                    
                    # 🔥 记录更详细的诊断信息
                    logger.warning(
                        f"[{self.name}] Empty LLM response in iteration {self._iteration} "
                        f"(retry {empty_retry_count}/3)"
                    )
                    
                    if empty_retry_count >= 3:
                        logger.error(f"[{self.name}] Too many empty responses, generating fallback result")
                        error_message = "连续收到空响应，使用回退结果"
                        await self.emit_event("warning", error_message)
                        # 🔥 不是直接 break，而是尝试生成一个回退结果
                        break
                    
                    retry_prompt = f"""收到空响应。请根据以下格式输出你的思考和行动：

Thought: [你对当前情况的分析]
Action: [工具名称，如 foundry_cast, list_files, read_file, search_code]
Action Input: {{"参数名": "参数值"}}

可用工具: {', '.join(self.tools.keys())}

如果你认为信息收集已经完成，请输出：
Thought: [总结收集到的信息]
Final Answer: [JSON格式的结果]"""
                    
                    self._conversation_history.append({
                        "role": "user", 
                        "content": retry_prompt
                    })
                    continue
                
                # 重置空响应计数器
                self._empty_retry_count = 0

                # 解析 LLM 响应
                step = self._parse_llm_response(llm_output)
                self._steps.append(step)
                
                # 🔥 发射 LLM 思考内容事件 - 展示 LLM 在想什么
                if step.thought:
                    await self.emit_llm_thought(step.thought, iteration + 1)
                
                # 添加 LLM 响应到历史
                self._conversation_history.append({
                    "role": "assistant",
                    "content": llm_output,
                })
                
                # 检查是否完成
                if step.is_final:
                    await self.emit_llm_decision("完成合约分析", "已梳理出关键高危区域与架构")
                    await self.emit_llm_complete(
                        f"信息收集完成，共 {self._iteration} 轮思考",
                        self._total_tokens
                    )
                    final_result = step.final_answer
                    break
                
                # 执行工具
                if step.action:
                    # 🔥 发射 LLM 动作决策事件
                    await self.emit_llm_action(step.action, step.action_input or {})
                    
                    # 🔥 循环检测：追踪工具调用失败历史
                    tool_call_key = f"{step.action}:{json.dumps(step.action_input or {}, sort_keys=True)}"
                    if not hasattr(self, '_failed_tool_calls'):
                        self._failed_tool_calls = {}
                    
                    observation = await self.execute_tool(
                        step.action,
                        step.action_input or {}
                    )
                    
                    # 🔥 检测工具调用失败并追踪
                    is_tool_error = (
                        "失败" in observation or 
                        "错误" in observation or 
                        "不存在" in observation or
                        "文件过大" in observation or
                        "Error" in observation
                    )
                    
                    if is_tool_error:
                        self._failed_tool_calls[tool_call_key] = self._failed_tool_calls.get(tool_call_key, 0) + 1
                        fail_count = self._failed_tool_calls[tool_call_key]
                        
                        # 🔥 如果同一调用连续失败3次，添加强制跳过提示
                        if fail_count >= 3:
                            logger.warning(f"[{self.name}] Tool call failed {fail_count} times: {tool_call_key}")
                            observation += f"\n\n⚠️ **系统提示**: 此工具调用已连续失败 {fail_count} 次。请：\n"
                            observation += "1. 尝试使用不同的参数（如指定较小的行范围）\n"
                            observation += "2. 使用 search_code 工具定位关键代码片段\n"
                            observation += "3. 跳过此文件，继续分析其他文件\n"
                            observation += "4. 如果已有足够信息，直接输出 Final Answer"
                            
                            # 重置计数器但保留记录
                            self._failed_tool_calls[tool_call_key] = 0
                    else:
                        # 成功调用，重置失败计数
                        if tool_call_key in self._failed_tool_calls:
                            del self._failed_tool_calls[tool_call_key]
                    
                    # 🔥 工具执行后检查取消状态
                    if self.is_cancelled:
                        logger.info(f"[{self.name}] Cancelled after tool execution")
                        break
                    
                    step.observation = observation
                    
                    # 🔥 发射 LLM 观察事件
                    await self.emit_llm_observation(observation)
                    
                    # 添加观察结果到历史
                    self._conversation_history.append({
                        "role": "user",
                        "content": f"Observation:\n{observation}",
                    })
                else:
                    # LLM 没有选择工具，提示它继续
                    await self.emit_llm_decision("继续思考", "LLM 需要更多信息")
                    self._conversation_history.append({
                        "role": "user",
                        "content": "请继续。你输出了 Thought 但没有输出 Action。请**立即**选择一个工具执行（Action: ...），或者如果信息收集完成，输出 Final Answer。",
                    })
            
            # 迭代耗尽时的强制总结 (适配 Web3 专属 JSON)
            if not final_result and not self.is_cancelled and not error_message:
                await self.emit_thinking("📝 侦察阶段结束，正在生成合约总结...")
                self._conversation_history.append({
                    "role": "user",
                    "content": """信息收集已达上限，请立即输出 Final Answer，总结你收集到的智能合约信息。

请按以下 JSON 格式输出：
```json
{
    "tech_stack": {"solidity_versions": [...], "dependencies": ["OpenZeppelin"]},
    "entry_points": [
        {"type": "payable_function", "file": "src/Vault.sol", "line": 7, "method": "deposit()"},
        {"type": "external_function", "file": "src/Vault.sol", "line": 11, "method": "withdraw(uint256)"}
    ],
    "high_risk_areas": [
        "文件路径:行号 - 风险描述",
    ],
    "initial_findings": [
        {"title": "...", "file_path": "...", "line_start": ..., "description": "..."}
    ],
    "summary": "合约初步分析完成，核心业务逻辑在 Vault.sol 中，发现 1 个高危 call 调用，已记录为 initial_findings。"
}
```

Final Answer:""",
                })

                try:
                    summary_output, _ = await self.stream_llm_call(
                        self._conversation_history,
                        # 🔥 不传递 temperature 和 max_tokens，使用用户配置
                    )
                    
                    if summary_output and summary_output.strip():
                        # 解析总结输出
                        summary_text = summary_output.strip()
                        summary_text = re.sub(r'```json\s*', '', summary_text)
                        summary_text = re.sub(r'```\s*', '', summary_text)
                        final_result = AgentJsonParser.parse(
                            summary_text,
                            default=self._summarize_from_steps()
                        )
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to generate summary: {e}")
            
            # 处理结果
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 🔥 如果被取消，返回取消结果
            if self.is_cancelled:
                await self.emit_event(
                    "info",
                    f"🛑 Recon Agent 已取消: {self._iteration} 轮迭代"
                )
                return AgentResult(
                    success=False,
                    error="任务已取消",
                    data=self._summarize_from_steps(),
                    iterations=self._iteration,
                    tool_calls=self._tool_calls,
                    tokens_used=self._total_tokens,
                    duration_ms=duration_ms,
                )
            
            # 🔥 如果有错误，返回失败结果
            if error_message:
                await self.emit_event(
                    "error",
                    f"❌ Recon Agent 失败: {error_message}"
                )
                return AgentResult(
                    success=False,
                    error=error_message,
                    data=self._summarize_from_steps(),
                    iterations=self._iteration,
                    tool_calls=self._tool_calls,
                    tokens_used=self._total_tokens,
                    duration_ms=duration_ms,
                )
            
            # 如果没有最终结果，从历史中汇总
            if not final_result:
                final_result = self._summarize_from_steps()
            
            # 🔥 记录工作和洞察
            self.record_work(f"完成合约代码抓取与分析，确认 {len(final_result.get('entry_points', []))} 个外部入口。")
            
            if final_result.get("high_risk_areas"):
                self.add_insight(f"标记了 {len(final_result['high_risk_areas'])} 处底层调用或资金转移高危行。")

            await self.emit_event(
                "info",
                f"Recon Agent 完成: {self._iteration} 轮迭代, {self._tool_calls} 次工具调用"
            )

            # 🔥 创建 TaskHandoff - 传递给下游 Agent
            handoff = self._create_recon_handoff(final_result)

            return AgentResult(
                success=True,
                data=final_result,
                iterations=self._iteration,
                tool_calls=self._tool_calls,
                tokens_used=self._total_tokens,
                duration_ms=duration_ms,
                handoff=handoff,  # 🔥 添加 handoff
            )
            
        except Exception as e:
            logger.error(f"Recon Agent failed: {e}", exc_info=True)
            return AgentResult(success=False, error=str(e))

    def _summarize_from_steps(self) -> Dict[str, Any]:  # 待检查修改！！！(已修改过一版)
        """后备总结机制 - 从历史步骤中强行汇总结果，防范大模型输出格式崩溃"""
        import re
        
        # 1. 严格对齐最新的 Web3 目标 JSON 结构
        # 适度保留了 project_structure 以防下游 Orchestrator 需要核心文件列表
        result = {
            "tech_stack": {
                "solidity_versions": [], 
                "dependencies": []
            },
            "entry_points": [],
            "high_risk_areas": [],
            "initial_findings": [],
            "summary": "",
        }
        
        thoughts = []
        
        # 2. 遍历所有历史步骤，提取蛛丝马迹
        for step in self._steps:
            if step.thought:
                thoughts.append(step.thought)
                
            if step.observation:
                obs_lower = step.observation.lower()
                obs_text = step.observation
                    
                # 规则 A: 依赖库识别
                if "openzeppelin" in obs_lower and "OpenZeppelin" not in result["tech_stack"]["dependencies"]:
                    result["tech_stack"]["dependencies"].append("OpenZeppelin")
                if "solmate" in obs_lower and "Solmate" not in result["tech_stack"]["dependencies"]:
                    result["tech_stack"]["dependencies"].append("Solmate")
                
                # 规则 B: 编译器版本提取 (如: pragma solidity ^0.8.20;)
                version_matches = re.findall(r'pragma\s+solidity\s+([^;]+);', obs_text)
                for v in version_matches:
                    clean_v = v.strip()
                    if clean_v not in result["tech_stack"]["solidity_versions"]:
                        result["tech_stack"]["solidity_versions"].append(clean_v)

                # 规则 C: 高危区域提取 (尝试抓取文件和关联行号)
                # 匹配诸如 "src/Vault.sol:15" 附近的底层调用
                risk_matches = re.findall(r'([\w/]+\.sol)(?::(\d+))?.*?(call\{value|delegatecall|selfdestruct|assembly)', obs_text, re.IGNORECASE)
                for match in risk_matches:
                    file_path = match[0]
                    line_num = match[1] if match[1] else "?"
                    risk_type = match[2].lower()
                    risk_str = f"{file_path}:{line_num} - 发现底层操作 ({risk_type})"
                    if risk_str not in result["high_risk_areas"]:
                        result["high_risk_areas"].append(risk_str)
                        
                # 规则 D: 入口点粗略提取 (提取 function xxx() public/external/payable)
                entry_matches = re.findall(r'function\s+(\w+)\s*\(.*?\)\s*(?:external|public|payable)', obs_text)
                for func_name in entry_matches:
                    # 简单去重
                    if not any(func_name in ep.get("method", "") for ep in result["entry_points"]):
                        # 兜底情况下很难精准拿到具体哪个文件哪一行，取第一个 core_contract 作为备用
                        guess_file = result["project_structure"]["core_contracts"][0] if result["project_structure"]["core_contracts"] else "unknown.sol"
                        result["entry_points"].append({
                            "type": "external/payable",
                            "file": guess_file,
                            "line": "?",
                            "method": f"{func_name}()"
                        })
                        
        # 3. 数据清理与去重
        result["tech_stack"]["solidity_versions"] = list(set(result["tech_stack"]["solidity_versions"]))[:3]
        result["entry_points"] = result["entry_points"][:15]
        
        # 4. 汇总 LLM 的思考碎片作为 summary，同时明确标记这是系统强制的兜底数据
        if thoughts:
            result["summary"] = "⚠️ [System Fallback] 由于未能成功输出标准 JSON，此为系统强制抓取的后备汇总：\n" + "\n".join(thoughts[-3:])
        else:
            result["summary"] = "⚠️ [System Fallback] 兜底汇总完成，未抓取到有效分析数据。"
            
        return result

    def _create_recon_handoff(self, final_result: Dict[str, Any]) -> TaskHandoff:  # 待检查修改！！！
        """
        创建 Recon Agent 的任务交接信息

        Args:
            final_result: Recon 收集的最终结果

        Returns:
            TaskHandoff 对象，供 Analysis Agent 使用
        """
        # 提取关键发现
        key_findings = final_result.get("initial_findings", [])[:10]
        
        # 构建建议行动
        suggested_actions = []
        for area in final_result.get("high_risk_areas", [])[:10]:
            suggested_actions.append({
                "action": "deep_analysis",
                "target": area,
                "reason": "包含特权控制或底层资产转移，需深度审查"
            })

        # 提取入口点作为关注点
        attention_points = []
        for ep in final_result.get("entry_points", [])[:15]:
            ep_type = ep.get('type', 'func')
            ep_file = ep.get('file', 'unknown')
            ep_line = ep.get('line', '?')
            ep_method = ep.get('method', 'unknown')
            attention_points.append(f"[{ep_type}] {ep_file}:{ep_line} :: {ep_method}")

        # 构建摘要
        summary = f"完成智能合约侦察: "
        if final_result.get("tech_stack", {}).get("solidity_versions"):
            summary += f"版本={final_result['tech_stack']['solidity_versions'][0]}; "
        summary += f"识别到 {len(final_result.get('entry_points', []))} 个外部入口; "
        summary += f"发现 {len(final_result.get('high_risk_areas', []))} 处高危特征。"

        return self.create_handoff(
            to_agent="analysis",
            summary=summary,
            key_findings=key_findings,
            suggested_actions=suggested_actions,
            attention_points=attention_points,
            priority_areas=final_result.get("high_risk_areas", [])[:15],
            context_data=final_result,
        )

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self._conversation_history

    def get_steps(self) -> List[ReconStep]:
        """获取执行步骤"""
        return self._steps