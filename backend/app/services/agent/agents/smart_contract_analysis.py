"""
Analysis Agent (漏洞分析层) - LLM 驱动版

LLM 是真正的安全分析大脑！
- LLM 决定分析策略
- LLM 选择使用什么工具
- LLM 决定深入分析哪些代码
- LLM 判断发现的问题是否是真实漏洞

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
from ..prompts import CORE_SECURITY_PRINCIPLES, VULNERABILITY_PRIORITIES

logger = logging.getLogger(__name__)


ANALYSIS_SYSTEM_PROMPT = """你是 DeepAudit 的智能合约漏洞分析 Agent，一个精通 EVM 底层与 OWASP 智能合约安全标准的**自主**专家。

## 你的角色
你是安全审计的**核心大脑**，不是工具执行器。你需要：
1. 自主制定分析策略
2. 选择最有效的工具和方法
3. 深入分析可疑代码
4. 判断是否是真实漏洞
5. 动态调整分析方向
6. 输出具体的**攻击思路**供下游编写 PoC

## 🔧 你可以使用的核心工具 (按优先级)

### 第一优先级：知识检索 ⭐⭐⭐ 【必须结合理论分析！】
- **query_security_knowledge**: 查询安全知识库，获取漏洞类型、检测方法、修复建议等专业知识。
- **get_vulnerability_knowledge**: 获取特定漏洞类型的完整知识。

### 辅助工具（RAG 优先！）
- **read_file**: 读取文件内容
  参数: file_path (str), start_line (int), end_line (int)
- **security_search**: **🔥 首选** 安全相关搜索
  参数: query (str)
- **search_code**: - 全局搜索关键语法（如搜 `payable` 或 `call` 快速定位入口和风险点）。
- **list_files**: ⚠️ 仅列出目录，严禁遍历

## 🚨 知识工具使用警告（防止幻觉！）

**知识库 (RAG) 中返回的代码片段仅供原理解释，绝对不是靶机或目标合约的代码！**

当你使用 `get_vulnerability_knowledge` 或 `query_security_knowledge` 查阅漏洞原理时：
1. **知识示例 ≠ 项目代码**：知识库可能会返回经典的漏洞代码（如 The DAO 攻击代码），这只是教科书示例，绝不是你当前正在审计的合约代码！
2. **必须在实际代码中取证**：你只能报告你在 `read_file` 或 `search_code` 中**亲眼看到**的业务逻辑缺陷。
3. **禁止主观臆断与套用**：不要因为知识库提到“AMM 极易受到闪电贷攻击”，就在没看清价格计算公式的情况下，盲目假设项目中存在操纵价格漏洞。

❌ 错误做法（典型的严重幻觉）：
```
1. 查询 reentrancy 知识 -> 看到一段带有 .call{value:} 的转账示例
2. 并没有在目标合约的 withdraw() 中实际看到违反 CEI 模式的代码
3. 仍然在 Final Answer 中报告 "存在可重入漏洞"  <- 这是幻觉！
```

✅ 正确做法：
```
1. 查询 flash_loan 知识 -> 理解了如何利用瞬时现货价格 (Spot Price) 操纵预言机
2. 使用 read_file 仔细阅读项目代码中计算抵押物价值的函数
3. 只有真实看到代码中使用了容易被操纵的底层池余额 (如 getReserves) 计算价格时，才报告此漏洞！
```

## 🎯 重点关注的漏洞类型
- 整数上溢出和下溢 (unchecked, +, -, *, <<)
- 访问控制漏洞 (msg.sender, tx.origin, onlyOwner, modifier missing)
- 可重入攻击 (call{value:}, transfer, fallback, receive, nonReentrant, CEI violation)
- 闪贷攻击 (flashLoan, flashMint, balance manipulation, unbacked mint)
- 操纵价格 (getReserves, latestRoundData, spot price, AMM)
- 代理和可升级性漏洞 (delegatecall, upgradeTo, initialize, storage collision)
- 逻辑错误 (totalLendingPool, shares, userBalances, state update missing)
- 计算错误 (/, *, rounding down, precision loss, decimals mismatch)
- 不安全的随机性 (block.timestamp, blockhash, block.difficulty, abi.encodePacked)
- 拒绝服务攻击 (push payment, unbounded loop, external call revert)
- 未检查的外部调用 (bool success, call, send, unchecked return)
- 缺少输入验证 (require, address(0), slippage bounds, calldata checks)
- 抢跑攻击 / MEV (mempool, amountOutMin, deadline, swapExactETHForTokens)
- Gas限制漏洞 (for, while, push, dynamic array growth)
- 断言失败 (assert vs require, panic, gas exhaustion)
- 时间戳依赖 (block.timestamp, now, strict equality, deadline)
- 短地址攻击 (calldata length, msg.data, assembly parsing)

## 工作方式
每一步，你需要输出：

```
Thought: [分析当前情况，思考下一步应该做什么]
Action: [工具名称]
Action Input: [JSON 格式的参数]
```

完成分析后，输出：
```
Thought: [总结发现的漏洞与攻击思路]
Final Answer: [JSON 格式的漏洞报告]
```

**禁止使用 Markdown 格式标记！** 你的输出必须是纯文本格式：

✅ 正确：
```
Thought: 我需要使用 rag_query 扫描代码。
Action: rag_query
Action Input: {"query": "reentrancy vulnerability", "top_k": 5}
```

❌ 错误（禁止）：
```
**Thought:** 扫描代码。
**Action:** rag_query
**Action Input:** {...}
```

## ⚠️ Final Answer JSON 格式规范（严格遵守）

```json
{
    "findings": [
        {
            "vulnerability_type": "reentrancy",
            "severity": "critical",
            "title": "withdraw 函数存在可重入漏洞",
            "description": "Vault 合约的 withdraw 函数在向用户发送 ETH 之后才扣除用户的余额。这违背了 CEI（检查-生效-交互）模式，使得恶意合约可以通过 fallback/receive 函数在余额扣除前重复调用 withdraw，从而排干金库资金。",
            "file_path": "src/Vault.sol",
            "line_start": 45,
            "target_function_signature": "function withdraw(uint256 amount) public",
            "code_snippet": "(bool success, ) = msg.sender.call{value: amount}(\"\");\nrequire(success);\nbalances[msg.sender] -= amount;",
            "source": "amount (用户可控的提款参数)",
            "sink": ".call{value: } (底层 ETH 转账函数)",
            "attack_strategy": "1. 攻击者部署恶意合约 Attacker。\n2. Attacker 先调用 deposit() 存入 1 ETH 激活账本。\n3. Attacker 调用 withdraw(1 ether) 触发提款。\n4. Vault 通过 call 发送 ETH，触发 Attacker 的 receive() 回调。\n5. 在 receive() 中，Attacker 再次调用 withdraw(1 ether)，循环直到 Vault 被掏空。",
            "suggestion": "1. 遵循 CEI 模式，将状态更新 `balances[msg.sender] -= amount;` 移至 `.call` 之前。2. 引入 OpenZeppelin 的 ReentrancyGuard 并添加 nonReentrant 修饰符。",
            "confidence": 0.95,
            "requires_poc": true
        }
    ],
    "summary": "代码深度分析完成，重点发掘了 1 个致命级别的重入漏洞，其攻击路径和底层 sink 清晰，已输出具体攻击策略，强烈建议立即派发给 Verification Agent 进行沙箱 PoC 验证。"
}
```

## 重要原则
1. **质量优先** - 宁可深入分析几个真实漏洞，不要浅尝辄止报告大量误报
2. **上下文分析** - 看到可疑代码要读取上下文，理解完整逻辑
3. **自主判断** - 不要机械相信工具输出，要用你的专业知识判断

## ⚠️ 关键约束 - 必须遵守！
1. **禁止直接输出 Final Answer** - 你必须先调用工具来分析代码
2. **至少调用两个工具** - 使用 `get_vulnerability_knowledge` 或 `query_security_knowledge` 查阅漏洞原理，然后用 read_file 查看代码
3. **没有工具调用的分析无效** - 不允许仅凭推测直接报告漏洞
4. **先 Action 后 Final Answer** - 必须先执行工具，获取 Observation，再输出最终结论
```

现在开始你的安全分析！"""


@dataclass
class AnalysisStep:
    """分析步骤"""
    thought: str
    action: Optional[str] = None
    action_input: Optional[Dict] = None
    observation: Optional[str] = None
    is_final: bool = False
    final_answer: Optional[Dict] = None


class AnalysisAgent(BaseAgent):
    """
    漏洞分析 Agent - LLM 驱动版
    
    LLM 全程参与，自主决定：
    1. 分析什么
    2. 使用什么工具
    3. 深入哪些代码
    4. 报告什么发现
    """
    
    def __init__(
        self,
        llm_service,
        tools: Dict[str, Any],
        event_emitter=None,
    ):
        # 组合增强的系统提示词，注入核心安全原则和漏洞优先级
        full_system_prompt = f"{ANALYSIS_SYSTEM_PROMPT}\n\n{CORE_SECURITY_PRINCIPLES}\n\n{VULNERABILITY_PRIORITIES}"

        config = AgentConfig(
            name="Analysis",
            agent_type=AgentType.ANALYSIS,
            pattern=AgentPattern.REACT,
            max_iterations=30,
            system_prompt=full_system_prompt,
        )
        super().__init__(config, llm_service, tools, event_emitter)
        
        self._conversation_history: List[Dict[str, str]] = []
        self._steps: List[AnalysisStep] = []
    

    

    def _parse_llm_response(self, response: str) -> AnalysisStep:
        """解析 LLM 响应 - 增强版，更健壮地提取思考内容"""
        step = AnalysisStep(thought="")

        # 🔥 v2.1: 预处理 - 移除 Markdown 格式标记（LLM 有时会输出 **Action:** 而非 Action:）
        cleaned_response = response
        cleaned_response = re.sub(r'\*\*Action:\*\*', 'Action:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Action Input:\*\*', 'Action Input:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Thought:\*\*', 'Thought:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Final Answer:\*\*', 'Final Answer:', cleaned_response)
        cleaned_response = re.sub(r'\*\*Observation:\*\*', 'Observation:', cleaned_response)

        # 🔥 首先尝试提取明确的 Thought 标记
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
            # 使用增强的 JSON 解析器，更新了针对智能合约的默认字段
            step.final_answer = AgentJsonParser.parse(
                answer_text,
                default={"findings": [], "raw_answer": answer_text}
            )
            # 确保 findings 格式正确
            if "findings" in step.final_answer:
                step.final_answer["findings"] = [
                    f for f in step.final_answer["findings"]
                    if isinstance(f, dict)
                ]

            # 🔥 如果没有提取到 thought，使用 Final Answer 前的内容作为思考
            if not step.thought:
                before_final = cleaned_response[:cleaned_response.find('Final Answer:')].strip()
                if before_final:
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
        执行漏洞分析 - LLM 全程参与！
        """
        import time
        start_time = time.time()
        
        project_info = input_data.get("project_info", {})
        config = input_data.get("config", {})
        plan = input_data.get("plan", {})
        previous_results = input_data.get("previous_results", {})
        task = input_data.get("task", "")
        task_context = input_data.get("task_context", "")
        
        # 🔥 处理交接信息
        handoff = input_data.get("handoff")
        if handoff:
            from .base import TaskHandoff
            if isinstance(handoff, dict):
                handoff = TaskHandoff.from_dict(handoff)
            self.receive_handoff(handoff)
        
        # 从 Recon 结果获取上下文
        recon_data = previous_results.get("recon", {})
        if isinstance(recon_data, dict) and "data" in recon_data:
            recon_data = recon_data["data"]
        
        tech_stack = recon_data.get("tech_stack", {})
        entry_points = recon_data.get("entry_points", [])
        high_risk_areas = recon_data.get("high_risk_areas", plan.get("high_risk_areas", []))
        initial_findings = recon_data.get("initial_findings", [])
        
        # 🔥 构建包含交接上下文的初始消息
        handoff_context = self.get_handoff_context()
        
        # 🔥 获取目标文件列表
        target_files = config.get("target_files", [])
        
        initial_message = f"""请开始对项目进行安全漏洞分析。

## 项目信息
- 名称: {project_info.get('name', 'unknown')}
- 语言: {tech_stack.get('languages', [])}
- 框架: {tech_stack.get('frameworks', [])}

"""
        # 🔥 如果指定了目标文件，明确告知 Agent
        if target_files:
            initial_message += f"""## ⚠️ 审计范围
用户指定了 {len(target_files)} 个目标文件进行审计：
"""
            for tf in target_files[:10]:
                initial_message += f"- {tf}\n"
            if len(target_files) > 10:
                initial_message += f"- ... 还有 {len(target_files) - 10} 个文件\n"
            initial_message += """
请直接分析这些指定的文件，不要分析其他文件。

"""
        
        initial_message += f"""{handoff_context if handoff_context else f'''## 上下文信息
### ⚠️ 高风险区域（来自 Recon Agent，必须优先分析）
以下是 Recon Agent 识别的高风险区域，请**务必优先**读取和分析这些文件：
{json.dumps(high_risk_areas[:20], ensure_ascii=False)}

**重要**: 请使用 read_file 工具读取上述高风险文件，不要假设文件路径或使用其他路径。

### 入口点 (前10个)
{json.dumps(entry_points[:10], ensure_ascii=False, indent=2)}

### 初步发现 (如果有)
{json.dumps(initial_findings[:5], ensure_ascii=False, indent=2) if initial_findings else "无"}'''}

## 任务
{task_context or task or '进行全面的智能合约安全漏洞分析，发现代码中的深层逻辑或 EVM 底层问题。'}

## ⚠️ 分析策略要求
1. **首先**：使用 read_file 读取上面列出的高风险文件
2. **然后**：深入分析函数调用链、状态更新顺序和外部交互
3. **结合**：遇到不确定的风险模式，使用 query_security_knowledge等工具 检索相关漏洞的确认标准

**禁止**：不要跳过高风险区域直接随意搜索

## 目标漏洞类型
{config.get('target_vulnerabilities', ['reentrancy', 'access_control', 'logic_errors', 'flash_loan_attacks', 'oracle_manipulation'])}

## 可用工具
{self.get_tools_description()}

请开始你的安全分析。首先读取高风险区域的文件，然后**立即**分析其中的安全问题（输出 Action）。"""
        
        # 🔥 记录工作开始
        self.record_work("开始智能合约安全漏洞分析")

        # 初始化对话历史
        self._conversation_history = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": initial_message},
        ]
        
        self._steps = []
        all_findings = []
        error_message = None  # 🔥 跟踪错误信息
        
        await self.emit_thinking("🔬 Analysis Agent 启动，LLM 开始自主安全分析...")
        
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
                # 🔥 使用用户配置的 temperature 和 max_tokens
                try:
                    llm_output, tokens_this_round = await self.stream_llm_call(
                        self._conversation_history,
                        # 🔥 不传递 temperature 和 max_tokens，使用用户配置
                    )
                except asyncio.CancelledError:
                    logger.info(f"[{self.name}] LLM call cancelled")
                    break
                
                self._total_tokens += tokens_this_round

                # 🔥 Enhanced: Handle empty LLM response with better diagnostics
                if not llm_output or not llm_output.strip():
                    empty_retry_count = getattr(self, '_empty_retry_count', 0) + 1
                    self._empty_retry_count = empty_retry_count
                    
                    # 🔥 记录更详细的诊断信息
                    logger.warning(
                        f"[{self.name}] Empty LLM response in iteration {self._iteration} "
                        f"(retry {empty_retry_count}/3, tokens_this_round={tokens_this_round})"
                    )
                    
                    if empty_retry_count >= 3:
                        logger.error(f"[{self.name}] Too many empty responses, generating fallback result")
                        error_message = "连续收到空响应，使用回退结果"
                        await self.emit_event("warning", error_message)
                        # 🔥 不是直接 break，而是尝试生成一个回退结果
                        break
                    
                    # 🔥 更有针对性的重试提示
                    retry_prompt = f"""收到空响应。请根据以下格式输出你的思考和行动：

Thought: [你对当前安全分析情况的思考]
Action: [工具名称，如 read_file, search_code, rag_query]
Action Input: {{"参数名": "参数值"}}

可用工具: {', '.join(self.tools.keys())}

如果你已完成分析，请输出：
Thought: [总结所有发现]
Final Answer: {{"findings": [...], "summary": "..."}}"""
                    
                    self._conversation_history.append({
                        "role": "user",
                        "content": retry_prompt,
                    })
                    continue
                
                # 重置空响应计数器
                self._empty_retry_count = 0

                # 解析 LLM 响应
                step = self._parse_llm_response(llm_output)
                self._steps.append(step)
                
                # 🔥 发射 LLM 思考内容事件 - 展示安全分析的思考过程
                if step.thought:
                    await self.emit_llm_thought(step.thought, iteration + 1)
                
                # 添加 LLM 响应到历史
                self._conversation_history.append({
                    "role": "assistant",
                    "content": llm_output,
                })
                
                # 检查是否完成
                if step.is_final:
                    await self.emit_llm_decision("完成安全分析", "LLM 判断分析已充分")
                    logger.info(f"[{self.name}] Received Final Answer: {step.final_answer}")
                    if step.final_answer and "findings" in step.final_answer:
                        all_findings = step.final_answer["findings"]
                        logger.info(f"[{self.name}] Final Answer contains {len(all_findings)} findings")
                        # 🔥 发射每个发现的事件
                        for finding in all_findings[:5]:  # 限制数量
                            await self.emit_finding(
                                finding.get("title", "Unknown"),
                                finding.get("severity", "medium"),
                                finding.get("vulnerability_type", "other"),
                                finding.get("file_path", "")
                            )
                            # 🔥 记录洞察
                            self.add_insight(
                                f"发现 {finding.get('severity', 'medium')} 级别漏洞: {finding.get('title', 'Unknown')}"
                            )
                    else:
                        logger.warning(f"[{self.name}] Final Answer has no 'findings' key or is None: {step.final_answer}")
                    
                    # 🔥 记录工作完成
                    self.record_work(f"完成安全分析，发现 {len(all_findings)} 个潜在的智能合约漏洞")
                    
                    await self.emit_llm_complete(
                        f"分析完成，发现 {len(all_findings)} 个潜在漏洞",
                        self._total_tokens
                    )
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
                            observation += "4. 如果已有足够发现，直接输出 Final Answer"
                            
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
                    await self.emit_llm_decision("继续分析", "LLM 需要更多分析")
                    self._conversation_history.append({
                        "role": "user",
                        "content": "请继续分析。你输出了 Thought 但没有输出 Action。请**立即**选择一个工具执行，或者如果分析完成，输出 Final Answer 汇总所有发现。",
                    })
            
            # 🔥 如果循环结束但没有发现，强制 LLM 总结
            if not all_findings and not self.is_cancelled and not error_message:
                await self.emit_thinking("📝 分析阶段结束，正在生成漏洞总结...")
                
                # 添加强制总结的提示 (使用新版的 Web3 结构)
                self._conversation_history.append({
                    "role": "user",
                    "content": """分析阶段已结束。请立即输出 Final Answer，总结你发现的所有智能合约安全问题。

即使没有发现严重漏洞，也请总结你的分析过程和观察到的潜在风险点。

请按以下 JSON 格式输出：
```json
{
    "findings": [
        {
            "vulnerability_type": "reentrancy",
            "severity": "critical",
            "title": "withdraw 函数存在可重入漏洞",
            "description": "Vault 合约的 withdraw 函数在向用户发送 ETH 之后才扣除用户的余额。这违背了 CEI（检查-生效-交互）模式，使得恶意合约可以通过 fallback/receive 函数在余额扣除前重复调用 withdraw，从而排干金库资金。",
            "file_path": "src/Vault.sol",
            "line_start": 45,
            "target_function_signature": "function withdraw(uint256 amount) public",
            "code_snippet": "(bool success, ) = msg.sender.call{value: amount}(\"\");\nrequire(success);\nbalances[msg.sender] -= amount;",
            "source": "amount (用户可控的提款参数)",
            "sink": ".call{value: } (底层 ETH 转账函数)",
            "attack_strategy": "1. 攻击者部署恶意合约 Attacker。\n2. Attacker 先调用 deposit() 存入 1 ETH 激活账本。\n3. Attacker 调用 withdraw(1 ether) 触发提款。\n4. Vault 通过 call 发送 ETH，触发 Attacker 的 receive() 回调。\n5. 在 receive() 中，Attacker 再次调用 withdraw(1 ether)，循环直到 Vault 被掏空。",
            "suggestion": "1. 遵循 CEI 模式，将状态更新 `balances[msg.sender] -= amount;` 移至 `.call` 之前。2. 引入 OpenZeppelin 的 ReentrancyGuard 并添加 nonReentrant 修饰符。",
            "confidence": 0.95,
            "requires_poc": true
        }
    ],
    "summary": "代码深度分析完成，重点发掘了 1 个致命级别的重入漏洞，其攻击路径和底层 sink 清晰，已输出具体攻击策略。"
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
                        import re
                        summary_text = summary_output.strip()
                        summary_text = re.sub(r'```json\s*', '', summary_text)
                        summary_text = re.sub(r'```\s*', '', summary_text)
                        parsed_result = AgentJsonParser.parse(
                            summary_text,
                            default={"findings": [], "summary": ""}
                        )
                        if "findings" in parsed_result:
                            all_findings = parsed_result["findings"]
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to generate summary: {e}")
            
            # 处理结果
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 🔥 如果被取消，返回取消结果
            if self.is_cancelled:
                await self.emit_event(
                    "info",
                    f"🛑 Analysis Agent 已取消: {len(all_findings)} 个发现, {self._iteration} 轮迭代"
                )
                return AgentResult(
                    success=False,
                    error="任务已取消",
                    data={"findings": all_findings},
                    iterations=self._iteration,
                    tool_calls=self._tool_calls,
                    tokens_used=self._total_tokens,
                    duration_ms=duration_ms,
                )
            
            # 🔥 如果有错误，返回失败结果
            if error_message:
                await self.emit_event(
                    "error",
                    f"❌ Analysis Agent 失败: {error_message}"
                )
                return AgentResult(
                    success=False,
                    error=error_message,
                    data={"findings": all_findings},
                    iterations=self._iteration,
                    tool_calls=self._tool_calls,
                    tokens_used=self._total_tokens,
                    duration_ms=duration_ms,
                )
            
            # 标准化发现 - 兼容 Web3 新字段
            logger.info(f"[{self.name}] Standardizing {len(all_findings)} findings")
            standardized_findings = []
            for finding in all_findings:
                # 确保 finding 是字典
                if not isinstance(finding, dict):
                    logger.warning(f"Skipping invalid finding (not a dict): {finding}")
                    continue
                    
                standardized = {
                    "vulnerability_type": finding.get("vulnerability_type", "other"),
                    "severity": finding.get("severity", "medium"),
                    "title": finding.get("title", "Unknown Vulnerability"),
                    "description": finding.get("description", ""),
                    "file_path": finding.get("file_path", ""),
                    "line_start": finding.get("line_start", 0),
                    "target_function_signature": finding.get("target_function_signature", ""),
                    "code_snippet": finding.get("code_snippet", ""),
                    "source": finding.get("source", ""),
                    "sink": finding.get("sink", ""),
                    "attack_strategy": finding.get("attack_strategy", ""),
                    "suggestion": finding.get("suggestion", ""),
                    "confidence": finding.get("confidence", 0.8),
                    "requires_poc": True,
                }
                standardized_findings.append(standardized)
            
            await self.emit_event(
                "info",
                f"Analysis Agent 完成: {len(standardized_findings)} 个发现, {self._iteration} 轮迭代, {self._tool_calls} 次工具调用"
            )

            # 🔥 CRITICAL: Log final findings count before returning
            logger.info(f"[{self.name}] Returning {len(standardized_findings)} standardized findings")

            # 🔥 创建 TaskHandoff - 传递给 Verification Agent
            handoff = self._create_analysis_handoff(standardized_findings)

            return AgentResult(
                success=True,
                data={
                    "findings": standardized_findings,
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
                handoff=handoff,  # 🔥 添加 handoff
            )
            
        except Exception as e:
            logger.error(f"Analysis Agent failed: {e}", exc_info=True)
            return AgentResult(success=False, error=str(e))
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self._conversation_history

    def get_steps(self) -> List[AnalysisStep]:
        """获取执行步骤"""
        return self._steps

    def _create_analysis_handoff(self, findings: List[Dict[str, Any]]) -> TaskHandoff:
        """
        创建 Analysis Agent 的任务交接信息

        Args:
            findings: 分析发现的漏洞列表

        Returns:
            TaskHandoff 对象，供 Verification Agent 使用
        """
        # 按严重程度排序
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_findings = sorted(
            findings,
            key=lambda x: severity_order.get(x.get("severity", "low"), 3)
        )

        # 提取关键发现（优先高危漏洞）
        key_findings = sorted_findings[:15]

        # 构建建议行动 - 哪些漏洞需要优先验证
        suggested_actions = []
        for f in sorted_findings[:15]:
            suggested_actions.append({
                "action": "verify_vulnerability",
                "target": f.get("file_path", ""),
                "line": f.get("line_start", 0),
                "function_signature": f.get("target_function_signature", ""), # 使用函数签名方便 PoC 编写
                "code_snippet": f.get("code_snippet", ""),
                "sink": f.get("sink", ""),
                "source": f.get("source", ""),
                "vulnerability_type": f.get("vulnerability_type", "unknown"),
                "attack_strategy": f.get("attack_strategy", ""),
                "severity": f.get("severity", "medium"),
                "priority": "high" if f.get("severity") in ["critical", "high"] else "normal",
                "reason": f.get("title", "需要编写 PoC 验证的智能合约漏洞")
            })

        # 统计漏洞类型和严重程度
        severity_counts = {}
        type_counts = {}
        for f in findings:
            sev = f.get("severity", "unknown")
            vtype = f.get("vulnerability_type", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            type_counts[vtype] = type_counts.get(vtype, 0) + 1

        # 构建洞察
        insights = [
            f"发现 {len(findings)} 个潜在智能合约漏洞需要验证",
            f"严重程度分布: Critical={severity_counts.get('critical', 0)}, "
            f"High={severity_counts.get('high', 0)}, "
            f"Medium={severity_counts.get('medium', 0)}, "
            f"Low={severity_counts.get('low', 0)}",
        ]

        # 最常见的漏洞类型
        if type_counts:
            top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            insights.append(f"主要智能合约漏洞类型: {', '.join([f'{t}({c})' for t, c in top_types])}")

        # 需要关注的文件
        attention_points = []
        files_with_findings = {}
        for f in findings:
            fp = f.get("file_path", "")
            if fp:
                files_with_findings[fp] = files_with_findings.get(fp, 0) + 1

        for fp, count in sorted(files_with_findings.items(), key=lambda x: x[1], reverse=True)[:10]:
            attention_points.append(f"{fp} ({count}个漏洞)")

        # 优先验证的区域 - 高危漏洞所在文件
        priority_areas = []
        for f in sorted_findings[:10]:
            if f.get("severity") in ["critical", "high"]:
                fp = f.get("file_path", "")
                if fp and fp not in priority_areas:
                    priority_areas.append(fp)

        # 上下文数据
        context_data = {
            "severity_distribution": severity_counts,
            "vulnerability_types": type_counts,
            "files_with_findings": files_with_findings,
        }

        # 构建摘要
        high_count = severity_counts.get("critical", 0) + severity_counts.get("high", 0)
        summary = f"完成智能合约逻辑分析: 发现{len(findings)}个漏洞, 其中{high_count}个高危漏洞，已输出攻击策略"

        return self.create_handoff(
            to_agent="verification",
            summary=summary,
            key_findings=key_findings,
            suggested_actions=suggested_actions,
            attention_points=attention_points,
            priority_areas=priority_areas,
            context_data=context_data,
        )