"""
Verification Agent (漏洞验证层) - LLM 驱动版

LLM 是验证的大脑！
- LLM 决定如何验证每个漏洞
- LLM 构造验证策略
- LLM 分析验证结果
- LLM 判断是否为真实漏洞

类型: ReAct (真正的!)
"""

import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from .base import BaseAgent, AgentConfig, AgentResult, AgentType, AgentPattern, TaskHandoff
from ..json_parser import AgentJsonParser
from ..prompts import CORE_SECURITY_PRINCIPLES, VULNERABILITY_PRIORITIES

logger = logging.getLogger(__name__)



VERIFICATION_SYSTEM_PROMPT = """你是 DeepAudit 的智能合约漏洞利用与验证 Agent (Verification Agent)。你是一位顶尖的 Web3 安全黑客，负责将漏洞理论转化为真实的攻击收益。

## 你的职责
1. **接收情报**：接收上游 Analysis Agent 提供的漏洞分析思路。
2. **自主编写 PoC**：
   - 读取受害者合约代码，精确提取 Interface 或 Contract 定义。
   - 编写 `setUp()` 函数完成合约部署，并为其注入初始资金 (模拟 TVL)。
   - 编写黑客合约 (Attacker Contract) 实现具体的 Exploit 逻辑。
3. **沙箱调试闭环**：将编写好的 PoC 放入 Foundry 沙箱测试。根据报错信息不断调试修复，直到成功盗取资金并输出包含利润的验证报告。

## 你可以使用的核心工具
1. **read_file**: 读取代码文件获取上下文
   - 参数: file_path (str), start_line (int), end_line (int)
2. **write_file**: 将你编写好的 Solidity 攻击脚本完整保存到宿主机的 `test/RealExploit.t.sol`。
   - 参数: file_path (str), content (str)
3. **foundry_test**: 执行 `forge test` 测试你的 PoC。
   - 参数: `test_file` (如 "test/RealExploit.t.sol"), `chain` (默认 "local"), `fork_block` (可选分叉区块号)
   - 返回 JSON 战报，包含编译报错 (stderr) 或执行后的利润 (Profit) 数据。

## Foundry PoC 编写与验证铁律 (必读！) 待检查修改！！
1. **闭环调试 (ReAct)**：如果你调用 `foundry_test` 后返回 `failed_compilation` (包含 stderr 报错)，你必须**仔细阅读报错行号**，重新调用 `write_file` 修正代码，再次调用 `foundry_test`，直到返回 Success。
2. **唯一的胜负判定凭证**：在 `testExploit()` 触发攻击后，**必须**通过 `console.log("Profit:", profit);` 打印出最终盗取的 ETH 净利润。下游解析器只认这行日志！
3. **环境与资金模拟**：在 `setUp()` 中必须使用 `vm.deal(address(this), 10 ether)` 等 cheatcodes 为受害者合约注入 TVL，并为你的攻击者合约提供启动资金。
4. **语法严谨**：必须包含正确的 SPDX 声明、匹配的 `pragma solidity`，以及导入标准库 `import "forge-std/Test.sol";`。注意单位（如 `1 ether`）和 `payable` 修饰符。

## 工作流程
你将收到一批待验证的漏洞发现。对于每个发现：

```
Thought: [分析漏洞类型，读取源码确认接口，设计 PoC 策略]
Action: [工具名称]
Action Input: [参数]
```

如果 `foundry_test` 报错，仔细阅读 `Observation` 中的 `stderr`，修改代码再次 `write_file` 并测试（闭环调试）。验证完毕后输出：

```
Thought: [总结验证结果]
Final Answer: [JSON 格式的验证报告]
```

## ⚠️ 输出格式要求（严格遵守）

**禁止使用 Markdown 格式标记！** 你的输出必须是纯文本格式：

✅ 正确格式：
```
Thought: 我需要读取 Vault.sol 确认提现函数的参数签名。
Action: read_file
Action Input: {"file_path": "src/Vault.sol"}
```

❌ 错误格式（禁止使用）：
```
**Thought:** 我需要读取文件
**Action:** read_file
**Action Input:** {"file_path": "src/Vault.sol"}
```

## Final Answer 格式
```json
{
    "findings": [
        {
            ...原始发现字段...,
            "verdict": "confirmed/execution_reverted/failed_compilation/likely/false_positive",
            "confidence": 0.0-1.0,
            "is_verified": true/false,
            "verification_method": "Foundry 动态沙箱测试",
            "verification_details": "攻击者通过重入成功绕过余额扣减，执行日志显示...",
            "poc": {
                "description": "部署恶意的 Attacker 合约，利用 receive 递归调用提现",
                "poc_file_path": "test/RealExploit.t.sol",
                "payload": "完整的 Solidity 测试脚本代码"
            },
            "profit_extracted": 10.0,
            "gas_used": 135347,
            "impact": "攻击者可完全掏空合约内的所有 ETH",
            "recommended_fix": "遵循 Checks-Effects-Interactions 模式，或引入 OpenZeppelin 的 ReentrancyGuard。"
        }
    ],
    "summary": {
        "total": 数量,
        "confirmed": 数量,
        "likely": 数量,
        "false_positive": 数量
    }
}
```

## 验证判定标准
- **confirmed**: 漏洞确认存在且可利用，有明确证据（如 Harness 成功触发）
- **likely**: 高度可能存在漏洞，代码分析明确但无法动态验证
- **false_positive**: 确认是误报，有明确理由

## 🚨 防止幻觉验证（关键！）

**Analysis Agent 可能报告不存在的文件！** 你必须验证：

1. **文件必须存在** - 使用 read_file 读取发现中指定的文件
   - 如果 read_file 返回"文件不存在"，该发现是 **false_positive**
   - 不要尝试"猜测"正确的文件路径
2. **代码必须匹配** - 发现中的 code_snippet 必须在文件中真实存在
   - 如果文件内容与描述不符，该发现是 **false_positive**
3. **不要"填补"缺失信息** - 如果发现缺少关键信息（如文件路径为空），标记为 uncertain
4. **看懂报错再修改** - 如果 `foundry_test` 失败，它会返回完整的编译器报错（如 `TypeError: Invalid type...` 行号 XX）。**必须根据报错精确定位修改你的 Solidity 代码**。

现在开始验证漏洞发现！"""


@dataclass
class VerificationStep:
    """验证步骤"""
    thought: str
    action: Optional[str] = None
    action_input: Optional[Dict] = None
    observation: Optional[str] = None
    is_final: bool = False
    final_answer: Optional[Dict] = None


class VerificationAgent(BaseAgent):
    """
    漏洞验证 Agent - LLM 驱动版
    
    LLM 全程参与，自主决定：
    1. 如何验证每个漏洞
    2. 使用什么工具
    3. 判断真假
    """
    
    def __init__(
        self,
        llm_service,
        tools: Dict[str, Any],
        event_emitter=None,
    ):
        # 组合增强的系统提示词
        full_system_prompt = f"{VERIFICATION_SYSTEM_PROMPT}\n\n{CORE_SECURITY_PRINCIPLES}\n\n{VULNERABILITY_PRIORITIES}"
        
        config = AgentConfig(
            name="Verification",
            agent_type=AgentType.VERIFICATION,
            pattern=AgentPattern.REACT,
            max_iterations=25,
            system_prompt=full_system_prompt,
        )
        super().__init__(config, llm_service, tools, event_emitter)
        
        self._conversation_history: List[Dict[str, str]] = []
        self._steps: List[VerificationStep] = []



    
    def _parse_llm_response(self, response: str) -> VerificationStep:
        """解析 LLM 响应 - 增强版，更健壮地提取思考内容"""
        step = VerificationStep(thought="")

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
            # 使用增强的 JSON 解析器
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

        # 🔥 提取 Action Input - 增强版，处理多种格式
        input_match = re.search(r'Action Input:\s*(.*?)(?=Thought:|Action:|Observation:|$)', cleaned_response, re.DOTALL)
        if input_match:
            input_text = input_match.group(1).strip()
            input_text = re.sub(r'```json\s*', '', input_text)
            input_text = re.sub(r'```\s*', '', input_text)

            # 🔥 v2.1: 如果 Action Input 为空或只有 **，记录警告
            if not input_text or input_text == '**' or input_text.strip() == '':
                logger.warning(f"[Verification] Action Input is empty or malformed: '{input_text}'")
                step.action_input = {}
            else:
                # 使用增强的 JSON 解析器
                step.action_input = AgentJsonParser.parse(
                    input_text,
                    default={"raw_input": input_text}
                )
        elif step.action:
            # 🔥 v2.1: 有 Action 但没有 Action Input，记录警告
            logger.warning(f"[Verification] Action '{step.action}' found but no Action Input")
            step.action_input = {}

        # 🔥 最后的 fallback：如果整个响应没有任何标记，整体作为思考
        if not step.thought and not step.action and not step.is_final:
            if response.strip():
                step.thought = response.strip()[:500]

        return step
    
    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        执行漏洞验证 - LLM 全程参与！
        """
        import time
        start_time = time.time()
        
        previous_results = input_data.get("previous_results", {})
        config = input_data.get("config", {})
        task = input_data.get("task", "")
        task_context = input_data.get("task_context", "")
        
        # 🔥 处理交接信息
        handoff = input_data.get("handoff")
        if handoff:
            from .base import TaskHandoff
            if isinstance(handoff, dict):
                handoff = TaskHandoff.from_dict(handoff)
            self.receive_handoff(handoff)
        
        # 收集所有待验证的发现
        findings_to_verify = []
        
        # 🔥 优先从交接信息获取发现
        if self._incoming_handoff and self._incoming_handoff.key_findings:
            findings_to_verify = self._incoming_handoff.key_findings.copy()
            logger.info(f"[Verification] 从交接信息获取 {len(findings_to_verify)} 个发现")
        else:
            # 🔥 修复：处理 Orchestrator 传递的多种数据格式
            
            # 格式1: Orchestrator 直接传递 {"findings": [...]}
            if isinstance(previous_results, dict) and "findings" in previous_results:
                direct_findings = previous_results.get("findings", [])
                if isinstance(direct_findings, list):
                    for f in direct_findings:
                        if isinstance(f, dict):
                            # 🔥 Always verify Critical/High findings to generate PoC, even if Analysis sets needs_verification=False
                            severity = str(f.get("severity", "")).lower()
                            needs_verify = f.get("needs_verification", True)
                            
                            if needs_verify or severity in ["critical", "high"]:
                                findings_to_verify.append(f)
                    logger.info(f"[Verification] 从 previous_results.findings 获取 {len(findings_to_verify)} 个发现")
            
            # 格式2: 传统格式 {"phase_name": {"data": {"findings": [...]}}}
            if not findings_to_verify:
                for phase_name, result in previous_results.items():
                    if phase_name == "findings":
                        continue  # 已处理
                    
                    if isinstance(result, dict):
                        data = result.get("data", {})
                    else:
                        data = result.data if hasattr(result, 'data') else {}
                    
                    if isinstance(data, dict):
                        phase_findings = data.get("findings", [])
                        for f in phase_findings:
                            if isinstance(f, dict):
                                severity = str(f.get("severity", "")).lower()
                                needs_verify = f.get("needs_verification", True)
                                
                                if needs_verify or severity in ["critical", "high"]:
                                    findings_to_verify.append(f)
                
                if findings_to_verify:
                    logger.info(f"[Verification] 从传统格式获取 {len(findings_to_verify)} 个发现")
        
        # 🔥 如果仍然没有发现，尝试从 input_data 的其他字段提取
        if not findings_to_verify:
            # 尝试从 task 或 task_context 中提取描述的漏洞
            if task and ("发现" in task or "漏洞" in task or "findings" in task.lower()):
                logger.warning(f"[Verification] 无法从结构化数据获取发现，任务描述: {task[:200]}")
                # 创建一个提示 LLM 从任务描述中理解漏洞的特殊处理
                await self.emit_event("warning", f"无法从结构化数据获取发现列表，将基于任务描述进行验证")
        
        # 去重
        findings_to_verify = self._deduplicate(findings_to_verify)

        # 🔥 FIX: 优先处理有明确文件路径的发现，将没有文件路径的发现放到后面
        # 这确保 Analysis 的具体发现优先于 Recon 的泛化描述
        def has_valid_file_path(finding: Dict) -> bool:
            file_path = finding.get("file_path", "")
            return bool(file_path and file_path.strip() and file_path.lower() not in ["unknown", "n/a", ""])

        findings_with_path = [f for f in findings_to_verify if has_valid_file_path(f)]
        findings_without_path = [f for f in findings_to_verify if not has_valid_file_path(f)]

        # 合并：有路径的在前，没路径的在后
        findings_to_verify = findings_with_path + findings_without_path

        if findings_with_path:
            logger.info(f"[Verification] 优先处理 {len(findings_with_path)} 个有明确文件路径的发现")
        if findings_without_path:
            logger.info(f"[Verification] 还有 {len(findings_without_path)} 个发现需要自行定位文件")

        if not findings_to_verify:
            logger.warning(f"[Verification] 没有需要验证的发现! previous_results keys: {list(previous_results.keys()) if isinstance(previous_results, dict) else 'not dict'}")
            await self.emit_event("warning", "没有需要验证的发现 - 可能是数据格式问题")
            return AgentResult(
                success=True,
                data={"findings": [], "verified_count": 0, "note": "未收到待验证的发现"},
            )
        
        # 限制数量
        findings_to_verify = findings_to_verify[:20]
        
        await self.emit_event(
            "info",
            f"开始验证 {len(findings_to_verify)} 个发现"
        )
        
        # 🔥 记录工作开始
        self.record_work(f"开始验证 {len(findings_to_verify)} 个漏洞发现")
        
        # 🔥 构建包含交接上下文的初始消息
        handoff_context = self.get_handoff_context()

        findings_summary = []
        
        # 提取 suggested_actions 列表，如果没有则为空列表
        suggested_actions = []
        if self._incoming_handoff and self._incoming_handoff.suggested_actions:
            suggested_actions = self._incoming_handoff.suggested_actions

        # 同步遍历 findings 和 suggested_actions
        for i, f in enumerate(findings_to_verify):
            # 正确处理 file_path 格式，可能包含行号
            file_path = f.get('file_path', 'unknown')
            line_start = f.get('line_start', 0)

            if isinstance(file_path, str) and ':' in file_path:
                parts = file_path.split(':', 1)
                if len(parts) == 2 and parts[1].split()[0].isdigit():
                    file_path = parts[0]
                    try:
                        line_start = int(parts[1].split()[0])
                    except ValueError:
                        pass

            # 同步获取对应的 action（包含越界保护，以防列表长度不一致）
            action = suggested_actions[i] if i < len(suggested_actions) else None

            # 💡 构建单个漏洞的完整上下文提示 (无截断)
            finding_text = f"### 发现 {i+1}: {f.get('title', 'Unknown')}\n"
            finding_text += f"- 类型: {f.get('vulnerability_type', 'unknown')}\n"
            finding_text += f"- 严重度: {f.get('severity', 'medium')}\n"
            finding_text += f"- 文件: {file_path} (行 {line_start})\n"
            
            # 如果同步获取到了专属的 PoC 编写动作指导，高亮注入
            if action:
                strategy = action.get('attack_strategy', '未提供')
                formatted_strategy = strategy.replace('\n', '\n  ') # 缩进排版更美观
                finding_text += f"- 🎯 **目标函数 (Function)**: `{action.get('function_signature', 'N/A')}`\n"
                
                if action.get('source'):
                    finding_text += f"- 🎯 **污染源 (Source)**: {action.get('source')}\n"
                if action.get('sink'):
                    finding_text += f"- 🎯 **危险点 (Sink)**: {action.get('sink')}\n"
                
                finding_text += f"- 🎯 **PoC 攻击策略 (Attack Strategy)**:\n  {formatted_strategy}\n"
            else:
                # 兜底：如果 action 列表比 finding 列表短，使用 finding 本身的字段
                finding_text += f"- 🎯 目标函数: {f.get('target_function_signature', 'N/A')}\n"
                strategy = f.get('attack_strategy', f.get('description', 'N/A'))
                finding_text += f"- 🎯 攻击思路: {strategy}\n"
            
            finding_text += f"- 代码片段:\n```solidity\n{f.get('code_snippet', 'N/A')}\n```\n"
            finding_text += f"- 详细描述: {f.get('description', f.get('descriptions', 'N/A'))}\n\n"
            
            findings_summary.append(finding_text)
        
        initial_message = f"""请验证以下 {len(findings_to_verify)} 个安全发现。

{handoff_context if handoff_context else ''}

## 待验证发现
{''.join(findings_summary)}

## ⚠️ 重要验证指南
1. **直接使用上面列出的文件路径** - 不要猜测或搜索其他路径
2. **如果文件路径包含冒号和行号** (如 "app.py:36"), 请提取文件名 "app.py" 并使用 read_file 读取
3. **先读取文件内容，再判断漏洞是否存在**
4. **不要假设文件在子目录中** - 使用发现中提供的精确路径

## 验证要求
- 验证级别: {config.get('verification_level', 'standard')}

## 可用工具
{self.get_tools_description()}

请开始验证。对于每个发现：
1. 首先使用 read_file 读取发现中指定的文件（使用精确路径）
2. 分析代码上下文
3. 编写PoC，沙箱模拟攻击判断是否为真实漏洞
{f"特别注意 Analysis Agent 提到的关注点。" if handoff_context else ""}"""

        # 初始化对话历史
        self._conversation_history = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": initial_message},
        ]
        
        self._steps = []
        final_result = None
        
        await self.emit_thinking("🔐 Verification Agent 启动，LLM 开始自主验证漏洞...")
        
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

                # 🔥 Handle empty LLM response to prevent loops
                if not llm_output or not llm_output.strip():
                    logger.warning(f"[{self.name}] Empty LLM response in iteration {self._iteration}")
                    await self.emit_llm_decision("收到空响应", "LLM 返回内容为空，尝试重试通过提示")
                    
                    # 💡 Web3 升级：调整空响应重试时的工具列表建议
                    self._conversation_history.append({
                        "role": "user",
                        "content": "Received empty response. Please output your Thought and Action. Use tools like read_file, write_file, foundry_test.",
                    })
                    continue

                # 解析 LLM 响应
                step = self._parse_llm_response(llm_output)
                self._steps.append(step)
                
                # 🔥 发射 LLM 思考内容事件 - 展示验证的思考过程
                if step.thought:
                    await self.emit_llm_thought(step.thought, iteration + 1)
                
                # 添加 LLM 响应到历史
                self._conversation_history.append({
                    "role": "assistant",
                    "content": llm_output,
                })
                
                # 检查是否完成
                if step.is_final:
                    # 🔥 强制检查：必须至少调用过一次工具才能完成
                    if self._tool_calls == 0:
                        logger.warning(f"[{self.name}] LLM tried to finish without any tool calls! Forcing tool usage.")
                        await self.emit_thinking("⚠️ 拒绝过早完成：必须先使用工具验证漏洞")
                        
                        # 💡 Web3 升级：调整强制要求使用的工具列表
                        self._conversation_history.append({
                            "role": "user",
                            "content": (
                                "⚠️ **系统拒绝**: 你必须先使用工具验证漏洞！\n\n"
                                "不允许在没有调用任何工具的情况下直接输出 Final Answer。\n\n"
                                "请立即使用以下工具之一进行验证：\n"
                                "1. `read_file` - 读取漏洞所在文件的代码\n"
                                "2. `write_file` - 编写 PoC 代码保存到文件\n"
                                "3. `foundry_test` - 执行沙箱测试来验证 PoC\n\n"
                                "现在请输出 Thought 和 Action，开始验证第一个漏洞。"
                            ),
                        })
                        continue

                    await self.emit_llm_decision("完成漏洞验证", "LLM 判断验证已充分")
                    final_result = step.final_answer
                    
                    # 🔥 记录洞察和工作
                    if final_result and "findings" in final_result:
                        verified_count = len([f for f in final_result["findings"] if f.get("is_verified")])
                        fp_count = len([f for f in final_result["findings"] if f.get("verdict") in ["false_positive", "execution_reverted", "failed_compilation"]])
                        self.add_insight(f"验证了 {len(final_result['findings'])} 个发现，{verified_count} 个确认，{fp_count} 个误报/失败")
                        self.record_work(f"完成漏洞验证: {verified_count} 个确认, {fp_count} 个误报/失败")
                    
                    await self.emit_llm_complete(
                        f"验证完成",
                        self._total_tokens
                    )
                    break
                
                # 执行工具
                if step.action:
                    # 🔥 发射 LLM 动作决策事件
                    await self.emit_llm_action(step.action, step.action_input or {})
                    
                    start_tool_time = time.time()
                    
                    # 🔥 智能循环检测: 追踪重复调用 (无论成功与否)
                    tool_call_key = f"{step.action}:{json.dumps(step.action_input or {}, sort_keys=True)}"
                    
                    if not hasattr(self, '_tool_call_counts'):
                        self._tool_call_counts = {}
                    
                    self._tool_call_counts[tool_call_key] = self._tool_call_counts.get(tool_call_key, 0) + 1
                    
                    # 如果同一操作重复尝试超过3次，强制干预
                    if self._tool_call_counts[tool_call_key] > 3:
                        logger.warning(f"[{self.name}] Detected repetitive tool call loop: {tool_call_key}")
                        observation = (
                            f"⚠️ **系统干预**: 你已经使用完全相同的参数调用了工具 '{step.action}' 超过3次。\n"
                            "请**不要**重复尝试相同的操作。这是无效的。\n"
                            "请尝试：\n"
                            "1. 修改参数 (例如改变 input payload)\n"
                            "2. 使用不同的工具\n"
                            "3. 如果之前的尝试都失败了，请尝试 analyze_file 重新分析代码\n"
                            "4. 如果无法验证，请输出 Final Answer 并标记为 uncertain"
                        )
                        
                        # 模拟观察结果，跳过实际执行
                        step.observation = observation
                        await self.emit_llm_observation(observation)
                        self._conversation_history.append({
                            "role": "user",
                            "content": f"Observation:\n{observation}",
                        })
                        continue

                    # 🔥 循环检测：追踪工具调用失败历史 (保留原有逻辑用于错误追踪)
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
                            observation += "2. 跳过此发现的验证，继续验证其他发现\n"
                            observation += "3. 如果已有足够验证结果，直接输出 Final Answer"
                            
                            # 重置计数器
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
                    await self.emit_llm_decision("继续验证", "LLM 需要更多验证")
                    self._conversation_history.append({
                        "role": "user",
                        "content": "请继续验证。你输出了 Thought 但没有输出 Action。请**立即**选择一个工具执行，或者如果验证完成，输出 Final Answer 汇总所有验证结果。",
                    })
            
            # 处理结果
            duration_ms = int((time.time() - start_time) * 1000)
            
            # 🔥 如果被取消，返回取消结果
            if self.is_cancelled:
                await self.emit_event(
                    "info",
                    f"🛑 Verification Agent 已取消: {self._iteration} 轮迭代"
                )
                return AgentResult(
                    success=False,
                    error="任务已取消",
                    data={"findings": findings_to_verify},
                    iterations=self._iteration,
                    tool_calls=self._tool_calls,
                    tokens_used=self._total_tokens,
                    duration_ms=duration_ms,
                )
            
            # 处理最终结果
            verified_findings = []

            # 🔥 Robustness: If LLM returns empty findings but we had input, fallback to original
            llm_findings = []
            if final_result and "findings" in final_result:
                llm_findings = final_result["findings"]

            if not llm_findings and findings_to_verify:
                logger.warning(f"[{self.name}] LLM returned empty findings despite {len(findings_to_verify)} inputs. Falling back to originals.")
                # Fallback to logic below (else branch)
                final_result = None

            if final_result and "findings" in final_result:
                # 🔥 DEBUG: Log what LLM returned for verdict diagnosis
                verdicts_debug = [(f.get("file_path", "?"), f.get("verdict"), f.get("confidence")) for f in final_result["findings"]]
                logger.info(f"[{self.name}] LLM returned verdicts: {verdicts_debug}")

                for f in final_result["findings"]:
                    # 💡 Web3 升级：处理新的 verdict 状态 (execution_reverted, failed_compilation)
                    verdict = f.get("verdict")
                    if not verdict or verdict not in ["confirmed", "execution_reverted", "failed_compilation", "false_positive", "uncertain", "likely"]:
                        # Try to infer verdict from other fields
                        if f.get("is_verified") is True:
                            verdict = "confirmed"
                        elif f.get("confidence", 0) <= 0.3:
                            verdict = "false_positive"
                        else:
                            verdict = "failed_compilation" # 在 Web3 中，未确认大多是因为编译失败
                        logger.warning(f"[{self.name}] Missing/invalid verdict for {f.get('file_path', '?')}, inferred as: {verdict}")

                    # 💡 Web3 升级：提取沙箱利润与 Gas 数据，打通大盘战果统计
                    verified = {
                        **f,
                        "verdict": verdict,  
                        "confidence": f.get("confidence", 0),
                        "is_verified": verdict == "confirmed",
                    }

                    # 添加修复建议 (优先使用大模型生成的 Web3 修复建议)
                    if not verified.get("recommendation") and not verified.get("recommended_fix"):
                        verified["recommendation"] = self._get_recommendation(f.get("vulnerability_type", ""))
                    elif verified.get("recommended_fix"):
                        verified["recommendation"] = verified["recommended_fix"]

                    verified_findings.append(verified)
            else:
                # 如果没有最终结果，使用原始发现
                for f in findings_to_verify:
                    verified_findings.append({
                        **f,
                        "verdict": "false_positive", 
                        "confidence": 0.0,
                        "is_verified": False,
                    })
            
            # 💡 Web3 升级：调整统计逻辑。
            confirmed_count = len([f for f in verified_findings if f.get("verdict") == "confirmed"])
            likely_count = len([f for f in verified_findings if f.get("verdict") == "likely"])
            false_positive_count = len([f for f in verified_findings if f.get("verdict") in ["false_positive", "execution_reverted", "failed_compilation"]])

            await self.emit_event(
                "info",
                f"Verification Agent 完成: {confirmed_count} 确认, {false_positive_count} 误报/拦截"
            )

            # 🔥 CRITICAL: Log final findings count before returning
            logger.info(f"[{self.name}] Returning {len(verified_findings)} verified findings")

            # 🔥 创建 TaskHandoff - 记录验证结果，供 Orchestrator 汇总
            handoff = self._create_verification_handoff(
                verified_findings, confirmed_count, likely_count, false_positive_count
            )

            return AgentResult(
                success=True,
                data={
                    "findings": verified_findings,
                    "verified_count": confirmed_count,
                    "likely_count": likely_count,
                    "false_positive_count": false_positive_count,
                },
                iterations=self._iteration,
                tool_calls=self._tool_calls,
                tokens_used=self._total_tokens,
                duration_ms=duration_ms,
                handoff=handoff,  # 🔥 添加 handoff
            )
            
        except Exception as e:
            logger.error(f"Verification Agent failed: {e}", exc_info=True)
            return AgentResult(success=False, error=str(e))
    
    def _get_recommendation(self, vuln_type: str) -> str:
        """获取修复建议"""
        recommendations = {
            "integer_overflow_underflow": "在 Solidity 0.8+ 环境下依赖默认溢出检查，避免无限制使用 unchecked 代码块；对关键不变量使用显式检查。在非 EVM 链需明确默认溢出语义，对复杂的定点数运算应使用经过充分审查的数学库。",
            "insecure_randomness": "避免依赖可被矿工操纵的区块属性（如 block.timestamp、blockhash 或 block.difficulty）生成随机数；应采用受信任的预言机（如 Chainlink VRF）或实施提交-揭示（Commit-Reveal）的密码学方案。",
            "arithmetic_errors": "明确定义并测试舍入策略（决定偏袒协议还是用户），避免因截断导致份额流失。针对复杂运算依赖安全数学库，结合不变量检查，并利用差异测试验证重复操作的边缘情况。",
            "access_control": "避免定制角色系统，优先采用经过实战检验的原语（如 OpenZeppelin 的 Ownable 或 AccessControl）；对资金移动、跨模块信任以及代理升级的特权角色强制实施多重签名或时间锁，防止单一 EOA 故障。",
            "logic_errors": "全面审查核心业务逻辑以确保状态变量（如用户余额与总储备量）被正确且同步地更新；对代币铸造和借贷实施适当的制衡护栏，并编写覆盖边缘操作的综合测试用例。",
            "flash_loan": "系统设计必须假定存在任意规模的瞬时闪电贷；对高影响状态的转换实施速率限制（如每区块限次），设定借款上限与最大滑点以限制单次交互敞口，并确保底层预言机不受瞬时流动性操纵。",
            "gas_limit": "避免使用受用户输入控制且长度可无限增长的动态数组循环；对必须的循环业务设定合理的硬性迭代上限，或者重构为利用算术运算即可实现恒定 Gas 消耗 (O(1)) 的逻辑。",
            "denial_of_service": "切勿让核心业务流程依赖外部不受信任地址的调用成功（防止恶意 revert 卡死合约）。处理转账时应采用“拉取而非推送（Pull over Push）”模式，且避免单一角色过度授权引发单点故障。",
            "unchecked_external_calls": "将所有外部调用视为不可信，采用 Checks-Effects-Interactions 模式（在调用前更新状态）。严格检查外部调用的返回值，并优先使用 OpenZeppelin 的 SafeERC20 包装库处理代币转移。",
            "price_oracle_manipulation": "避免依赖流动性薄弱的单一现货价格源。应聚合多个预言机数据流检查异常偏差与数据新鲜度，并在去中心化交易所采用长期窗口的 TWAP 以抵御即时或闪电贷操纵。",
            "lack_of_input_validation": "对函数参数、链下签名和跨链桥负载实施严格边界校验；强制校验非零地址、费率范围与防重放 Nonce，并将管理员及治理的配置输入等同于不受信任的危险数据进行同样级别的验证。",
            "reentrancy": "在所有涉及代币转移或触发钩子回调的函数中严格遵循检查-生效-交互（Checks-Effects-Interactions）模式；对高风险的状态修改函数使用互斥锁（如 OpenZeppelin 的 ReentrancyGuard）。",
            "short_address": "将合约升级并使用 Solidity 0.5.0 及更高版本，以利用编译器内置的 calldata 长度自动验证机制。若必须维护低版本环境，需加入自定义修饰符强制校验外部调用传入的 payload 字节大小。",
            "assert_failure": "区分错误处理场景：对用户输入和外部条件验证应统一使用 require 判定；将 assert 仅限制应用于状态机内绝对不应被打破的业务不变量检查，以免无意中触发 panic 并导致资金锁定或拒绝服务。",
            "proxy_upgradeability": "使用标准的代理模式（如透明代理或 UUPS）；在逻辑合约部署时立即调用初始化守卫（锁定实现合约防止篡改），对代理升级权限应用时间锁机制，并确保新老合约不存在存储槽冲突。",
            "front_running": "在涉及交易代币和兑换比例的函数中引入并强制校验滑点限制参数（如 amountOutMin）。对排序高度敏感的核心业务，考虑引入提交-揭示（Commit-Reveal）两步延迟流程抵御内存池窥视。",
            "timestamp_dependence": "禁止将 block.timestamp 作为核心业务的极度精准条件触发器。如果必须依赖时间（如拍卖或锁定释放），应在合约设计中引入合理的时间宽限期（Time Buffer）机制来抵御矿工十几秒内的时间戳微调。"
        }
        
        return recommendations.get(vuln_type, "请遵循 Checks-Effects-Interactions 模式，并根据最新的 Web3 安全审计标准进行代码审查与加固。")
    
    def _deduplicate(self, findings: List[Dict]) -> List[Dict]:
        """去重"""
        seen = set()
        unique = []
        
        for f in findings:
            key = (
                f.get("file_path", ""),
                f.get("line_start", 0),
                f.get("vulnerability_type", ""),
            )
            
            if key not in seen:
                seen.add(key)
                unique.append(f)
        
        return unique
    
    def get_conversation_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self._conversation_history

    def get_steps(self) -> List[VerificationStep]:
        """获取执行步骤"""
        return self._steps

    def _create_verification_handoff(
        self,
        verified_findings: List[Dict[str, Any]],
        confirmed_count: int,
        likely_count: int,
        false_positive_count: int,
    ) -> TaskHandoff:
        """
        创建 Verification Agent 的任务交接信息

        Args:
            verified_findings: 验证后的发现列表
            confirmed_count: 确认的漏洞数量
            likely_count: 可能的漏洞数量
            false_positive_count: 误报数量

        Returns:
            TaskHandoff 对象，供 Orchestrator 汇总
        """
        # 按验证结果分类
        confirmed = [f for f in verified_findings if f.get("verdict") == "confirmed"]

        # 提取关键发现（已确认的高危漏洞）
        key_findings = []
        for f in confirmed:
            if f.get("severity") in ["critical", "high"]:
                key_findings.append(f)
        # 如果高危不够，添加其他确认的漏洞
        if len(key_findings) < 10:
            for f in confirmed:
                if f not in key_findings:
                    key_findings.append(f)
                    if len(key_findings) >= 10:
                        break

        # 构建建议行动 - 修复建议
        suggested_actions = []
        for f in confirmed[:10]:
            suggestion = f.get("suggestion", "") or f.get("recommendation", "")
            suggested_actions.append({
                "action": "fix_vulnerability",
                "target": f.get("file_path", ""),
                "line": f.get("line_start", 0),
                "vulnerability_type": f.get("vulnerability_type", "unknown"),
                "severity": f.get("severity", "medium"),
                "recommendation": suggestion[:200] if suggestion else "请根据漏洞类型进行修复"
            })

        # 💡 Web3 升级：构建专属洞察文本
        insights = [
            f"利用沙箱验证完成: {confirmed_count}个确认, {likely_count}个可能, {false_positive_count}个误报",
            f"验证准确率: {confirmed_count / len(verified_findings) * 100:.1f}%" if verified_findings else "无数据",
        ]

        # 统计各类型漏洞
        type_counts = {}
        for f in confirmed:
            vtype = f.get("vulnerability_type", "unknown")
            type_counts[vtype] = type_counts.get(vtype, 0) + 1
        if type_counts:
            top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            insights.append(f"被利用的主要漏洞类型: {', '.join([f'{t}({c})' for t, c in top_types])}")

        # 需要关注的文件（有确认漏洞的文件）
        attention_points = []
        files_with_confirmed = {}
        for f in confirmed:
            fp = f.get("file_path", "")
            if fp:
                files_with_confirmed[fp] = files_with_confirmed.get(fp, 0) + 1
        for fp, count in sorted(files_with_confirmed.items(), key=lambda x: x[1], reverse=True)[:10]:
            attention_points.append(f"{fp} ({count}个确认漏洞)")

        # 优先修复的区域
        priority_areas = []
        for f in confirmed:
            if f.get("severity") in ["critical", "high"]:
                fp = f.get("file_path", "")
                if fp and fp not in priority_areas:
                    priority_areas.append(fp)

        # 上下文数据
        context_data = {
            "confirmed_count": confirmed_count,
            "likely_count": likely_count,
            "false_positive_count": false_positive_count,
            "vulnerability_types": type_counts,
            "files_with_confirmed": files_with_confirmed,
            "poc_generated": len([f for f in verified_findings if f.get("poc_code") or f.get("poc")]),
        }

        # 构建摘要
        summary = f"验证完成: {confirmed_count}个确认可利用漏洞, {false_positive_count}个未突破漏洞"
        if confirmed_count > 0:
            high_count = len([f for f in confirmed if f.get("severity") in ["critical", "high"]])
            if high_count > 0:
                summary += f", 其中{high_count}个高危"

        return self.create_handoff(
            to_agent="orchestrator",
            summary=summary,
            key_findings=key_findings,
            suggested_actions=suggested_actions,
            attention_points=attention_points,
            priority_areas=priority_areas,
            context_data=context_data,
        )