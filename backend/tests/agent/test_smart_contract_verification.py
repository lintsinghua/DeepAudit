import pytest
import asyncio
import logging
import sys
import json
from unittest.mock import AsyncMock
from typing import Dict, Any

# 设置全局日志，将 DEBUG 级别以上的日志输出到控制台
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("app.services.agent.agents.smart_contract_verification")
logger.setLevel(logging.DEBUG)
test_logger = logging.getLogger("TestRunner")

# 引入待测的 VerificationAgent
from app.services.agent.agents.smart_contract_verification import VerificationAgent, VerificationStep
from app.services.agent.agents.base import BaseAgent, AgentResult, TaskHandoff

# ==========================================
# 0. 模拟控制台事件发射器 (用于详细日志展示)
# ==========================================
class ConsoleEventEmitter:
    """模拟前端 SSE 推送，直接在控制台彩色打印输出"""
    async def emit(self, event_data: Any):
        event_type = getattr(event_data, "event_type", "UNKNOWN")
        msg = getattr(event_data, "message", "")
        if event_type == "thinking_token":
            return
        
        prefix_map = {
            "thinking": "💡 [思考状态]",
            "llm_thought": "🧠 [LLM 推理]",
            "llm_action": "🛠️ [沙箱工具]",
            "llm_observation": "👁️ [编译/执行结果]",
            "info": "ℹ️ [系统信息]",
            "warning": "⚠️ [系统警告]",
            "error": "❌ [系统错误]"
        }
        prefix = prefix_map.get(event_type, f"📢 [{event_type.upper()}]")
        print(f"\n{prefix} {msg}")

# ==========================================
# 1. 构造测试替身 (Fixtures)
# ==========================================

@pytest.fixture
def mock_llm_service():
    """模拟大模型服务"""
    service = AsyncMock()
    return service

@pytest.fixture
def verification_agent(mock_llm_service):
    """初始化 Verification Agent"""
    agent = VerificationAgent(
        llm_service=mock_llm_service,
        tools={}, 
        event_emitter=ConsoleEventEmitter()
    )
    agent._total_tokens = 0
    agent._tool_calls = 0
    agent._cancel_callback = None 
    agent._timeout_config = {"sub_agent_timeout": 600}
    return agent

@pytest.fixture
def sample_analysis_findings():
    """模拟从 Analysis Agent 传递过来的完美情报（包含函数签名和攻击思路）"""
    return {
        "previous_results": {
            "findings": [
                {
                    "title": "Vault 重入漏洞",
                    "vulnerability_type": "reentrancy",
                    "severity": "critical",
                    "file_path": "src/Vault.sol",
                    "line_start": 42,
                    # Web3 核心情报
                    "target_function_signature": "function withdraw(uint amount)",
                    "attack_strategy": "使用回退函数触发重入，反复调用 withdraw。",
                    "needs_verification": True
                }
            ]
        },
        "task": "编写 PoC 验证重入漏洞"
    }

# ==========================================
# 2. 测试用例 (Test Cases)
# ==========================================

@pytest.mark.asyncio
async def test_context_and_prompt_injection(verification_agent, sample_analysis_findings):
    """测试 1: 验证 Analysis 传来的 Web3 情报是否无损注入 Prompt"""
    test_logger.info(">>> 测试: Web3 专属字段的情报注入")
    
    # 拦截 LLM 调用以查看生成的 Prompt
    verification_agent.stream_llm_call = AsyncMock(return_value=("Final Answer: {}", 10))
    await verification_agent.run(sample_analysis_findings)
    
    # 检查给 LLM 的 initial_message
    system_prompt = verification_agent._conversation_history[1]["content"]
    
    # 断言：必须包含关键的函数签名和攻击思路
    assert "function withdraw(uint amount)" in system_prompt
    assert "使用回退函数触发重入" in system_prompt
    assert "src/Vault.sol" in system_prompt
    test_logger.info("✅ 目标函数签名与攻击思路已成功送达黑客大脑！")

@pytest.mark.asyncio
async def test_tool_loop_and_intervention(verification_agent, sample_analysis_findings):
    """测试 2: 沙箱工具连错时的系统强制干预机制"""
    test_logger.info(">>> 测试: 编译/工具连续失败的死锁解脱机制")
    
    # 模拟大模型像个无头苍蝇一样疯狂调同一个错误的路径
    verification_agent.stream_llm_call = AsyncMock(return_value=(
        "Thought: 让我试试编译\nAction: foundry_test\nAction Input: {\"test_file\": \"fake.t.sol\"}", 50
    ))
    verification_agent.execute_tool = AsyncMock(return_value="错误：文件不存在")
    verification_agent.config.max_iterations = 4 
    
    await verification_agent.run(sample_analysis_findings)
    
    # 检查整个历史记录中是否插入了系统警告
    history_text = json.dumps(verification_agent._conversation_history, ensure_ascii=False)
    assert "⚠️ **系统提示**: 此工具调用已连续失败 3 次" in history_text
    test_logger.info("✅ 沙箱死循环拦截成功，干预指令已发送！")

@pytest.mark.asyncio
async def test_compilation_failure_handling(verification_agent, sample_analysis_findings):
    """测试 3: 编译失败推断与状态归一化容错"""
    test_logger.info(">>> 测试: 不规范结果的启发式状态推断 (failed_compilation)")
    
    bad_answer = {
        "findings": [{
            "file_path": "src/Vault.sol",
            "vulnerability_type": "reentrancy",
            "confidence": 0.2, 
            "is_verified": False
        }],
        "summary": "编译实在跑不通，我放弃了。"
    }
    
    call_count = 0
    async def fake_stream_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ("Thought: 我要试试编译\nAction: foundry_test\nAction Input: {}", 50)
        else:
            return (f"Thought: 放弃\nFinal Answer: ```json\n{json.dumps(bad_answer)}\n```", 100)

    verification_agent.stream_llm_call = fake_stream_call
    
    # 🔥 终极修复：定制一个假的执行器，不但返回假结果，还真实地增加系统的工具计数！
    async def fake_execute_tool(action, action_input):
        verification_agent._tool_calls += 1  # 骗过防偷懒机制的核心！
        return "编译报错！"
    verification_agent.execute_tool = AsyncMock(side_effect=fake_execute_tool)
    
    result = await verification_agent.run(sample_analysis_findings)
    
    assert result.success is True
    verdict = result.data["findings"][0]["verdict"]
    assert verdict in ["false_positive", "failed_compilation"]
    assert result.data["false_positive_count"] == 1
    assert result.data["verified_count"] == 0
    test_logger.info("✅ 编译失败状态推断完美生效，统计归一化成功！")


@pytest.mark.asyncio
async def test_profit_extraction_and_handoff(verification_agent, sample_analysis_findings):
    """测试 4: 核心战果数据 (Profit/Gas) 的无损透传与闭环"""
    test_logger.info(">>> 测试: [最核心] Profit 资金数据向上的无损透传")
    
    victorious_answer = {
        "findings": [{
            "title": "Vault 重入漏洞",
            "vulnerability_type": "reentrancy",
            "severity": "critical",
            "file_path": "src/Vault.sol",
            "verdict": "confirmed",
            "is_verified": True,
            "profit_extracted": 15.5, 
            "gas_used": 120500,       
            "poc": {
                "poc_file_path": "test/Exploit.t.sol",
                "payload": "contract Attacker { ... }"
            }
        }],
        "summary": "成功盗取资金！"
    }
    
    call_count = 0
    async def fake_stream_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ("Thought: 运行 PoC\nAction: foundry_test\nAction Input: {}", 50)
        else:
            return (f"Thought: 拿到钱了！\nFinal Answer: ```json\n{json.dumps(victorious_answer)}\n```", 300)

    verification_agent.stream_llm_call = fake_stream_call
    
    # 🔥 终极修复：增加计数并返回假利润
    async def fake_execute_tool(action, action_input):
        verification_agent._tool_calls += 1  # 骗过防偷懒机制的核心！
        return "Profit: 15.5 ETH"
    verification_agent.execute_tool = AsyncMock(side_effect=fake_execute_tool)
    
    result = await verification_agent.run(sample_analysis_findings)
    
    assert result.success is True
    verified_finding = result.data["findings"][0]
    
    assert verified_finding["verdict"] == "confirmed"
    assert verified_finding["profit_extracted"] == 15.5
    assert verified_finding["gas_used"] == 120500
    assert "poc_file_path" in verified_finding["poc"]
    
    handoff = result.handoff
    assert handoff is not None
    assert handoff.context_data["confirmed_count"] == 1
    assert handoff.context_data["poc_generated"] == 1
    assert "1个确认可利用漏洞" in handoff.summary
    test_logger.info("✅ 完美沙箱攻击闭环！利润 (Profit) 数据已成功打包，等待 Orchestrator 检阅！")