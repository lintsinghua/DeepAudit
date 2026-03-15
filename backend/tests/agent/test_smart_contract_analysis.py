import pytest
import asyncio
import logging
import sys
import json
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any

# 设置全局日志，将 DEBUG 级别以上的日志输出到控制台
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("app.services.agent.agents.smart_contract_analysis")
logger.setLevel(logging.DEBUG)
test_logger = logging.getLogger("TestRunner")

# 引入待测的 AnalysisAgent
from app.services.agent.agents.smart_contract_analysis import AnalysisAgent, AnalysisStep
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
            "llm_action": "🛠️ [工具调用]",
            "llm_observation": "👁️ [观察结果]",
            "info": "ℹ️ [系统信息]",
            "warning": "⚠️ [系统警告]",
            "error": "❌ [系统错误]",
            "finding": "🎯 [发现漏洞]" # Analysis 专属事件
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
    # 默认返回一个 Web3 专属格式的有效 JSON
    default_answer = {
        "findings": [
            {
                "vulnerability_type": "reentrancy",
                "severity": "critical",
                "title": "withdraw 重入漏洞",
                "file_path": "src/Vault.sol",
                # 注意：故意不写 description 和 line_start，测试向下兼容逻辑
                "target_function_signature": "function withdraw(uint amount)",
                "code_snippet": "msg.sender.call{value: amount}(''); balances[msg.sender] -= amount;",
                "attack_strategy": "攻击者可以通过 fallback 函数重入，在余额清零前多次提取资金。"
            }
        ],
        "summary": "分析完毕，发现重入漏洞。"
    }
    service.stream_call.return_value = (f"Thought: 分析结束，输出报告。\nFinal Answer: ```json\n{json.dumps(default_answer)}\n```", 200)
    return service

@pytest.fixture
def analysis_agent(mock_llm_service):
    """初始化 Analysis Agent"""
    agent = AnalysisAgent(
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
def sample_input_data():
    """模拟从 Recon Agent 传递过来的上下文数据"""
    return {
        "project_info": {"name": "DeFi_Protocol"},
        "config": {"target_vulnerabilities": ["reentrancy", "access_control"]},
        "previous_results": {
            "recon": {
                "data": {
                    "tech_stack": {"languages": ["Solidity"], "frameworks": ["Foundry"]},
                    "entry_points": [{"type": "public", "file": "src/Vault.sol", "method": "deposit()"}],
                    "high_risk_areas": ["src/Vault.sol - 发现底层 call 操作"],
                    "initial_findings": []
                }
            }
        },
        "task": "深度挖掘合约漏洞"
    }

# ==========================================
# 2. 测试用例 (Test Cases)
# ==========================================

def test_parse_dirty_llm_response(analysis_agent):
    """测试 1: 脏数据清洗与无标签思考提取"""
    test_logger.info(">>> 测试: LLM 脏格式响应解析")
    
    dirty_response = """
    我已经阅读了代码，发现里面存在缺少鉴权的问题。
    **Action:** search_code
    **Action Input:** ```json
    {"keyword": "onlyOwner"}
    ```
    """
    step = analysis_agent._parse_llm_response(dirty_response)
    
    assert "我已经阅读了代码" in step.thought
    assert step.action == "search_code"
    assert step.action_input["keyword"] == "onlyOwner"
    assert step.is_final is False
    test_logger.info("✅ 脏数据清洗与隐性思考提取成功")

@pytest.mark.asyncio
async def test_context_injection(analysis_agent, sample_input_data):
    """测试 2: Recon 高危区域上下文注入"""
    test_logger.info(">>> 测试: Recon 侦察情报的动态注入")
    
    # 拦截 LLM 调用以查看生成的 Prompt
    analysis_agent.stream_llm_call = AsyncMock(return_value=("Final Answer: {}", 10))
    await analysis_agent.run(sample_input_data)
    
    system_prompt = analysis_agent._conversation_history[1]["content"]
    assert "src/Vault.sol - 发现底层 call 操作" in system_prompt
    assert "请使用 read_file 工具读取上述高风险文件" in system_prompt
    test_logger.info("✅ 高危区域警告成功注入 Prompt")

@pytest.mark.asyncio
async def test_tool_error_recovery(analysis_agent, sample_input_data):
    """测试 3: 工具连续失败强制干预"""
    test_logger.info(">>> 测试: 工具连续失败时的系统强制干预")
    
    analysis_agent.stream_llm_call = AsyncMock(return_value=(
        "Thought: 读文件\nAction: read_file\nAction Input: {\"file\": \"fake.sol\"}", 50
    ))
    analysis_agent.execute_tool = AsyncMock(return_value="错误：文件不存在")
    analysis_agent.config.max_iterations = 4 
    
    await analysis_agent.run(sample_input_data)
    
    history_text = json.dumps(analysis_agent._conversation_history, ensure_ascii=False)
    assert "⚠️ **系统提示**: 此工具调用已连续失败" in history_text
    assert "使用 search_code 工具定位" in history_text
    test_logger.info("✅ 工具死循环干预机制生效")

@pytest.mark.asyncio
async def test_data_standardization_and_handoff(analysis_agent, sample_input_data):
    """测试 4: 核心！Web3 字段标准化与向下兼容性映射"""
    test_logger.info(">>> 测试: Web3 字段提取、标准化映射及交接棒生成")
    
    # 构造一个符合 Web3 专属格式的有效 JSON
    default_answer = {
        "findings": [
            {
                "vulnerability_type": "reentrancy",
                "severity": "critical",
                "title": "withdraw 重入漏洞",
                "file_path": "src/Vault.sol",
                # 注意：故意不写 description 和 line_start，测试向下兼容逻辑
                "target_function_signature": "function withdraw(uint amount)",
                "code_snippet": "msg.sender.call{value: amount}(''); balances[msg.sender] -= amount;",
                "attack_strategy": "攻击者可以通过 fallback 函数重入，在余额清零前多次提取资金。"
            }
        ],
        "summary": "分析完毕，发现重入漏洞。"
    }
    
    # 🔥 修复：直接在 Agent 级别 Mock 掉 stream_llm_call，绕过底层坑爹的流式迭代器！
    analysis_agent.stream_llm_call = AsyncMock(
        return_value=(
            f"Thought: 分析结束，输出报告。\nFinal Answer: ```json\n{json.dumps(default_answer)}\n```", 
            200
        )
    )
    
    result = await analysis_agent.run(sample_input_data)
    
    assert result.success is True
    findings = result.data["findings"]
    assert len(findings) == 1
    f = findings[0]
    
    # 💡 核心断言：验证隐式映射是否成功
    assert f["title"] == "withdraw 重入漏洞"
    assert f["vulnerability_type"] == "reentrancy"
    assert f["target_function_signature"] == "function withdraw(uint amount)"
    
    # 验证 attack_strategy 是否成功兜底赋给了 description
    assert f["description"] == "攻击者可以通过 fallback 函数重入，在余额清零前多次提取资金。"
    assert f["attack_strategy"] == "攻击者可以通过 fallback 函数重入，在余额清零前多次提取资金。"
    
    # 验证缺失的 line_start 是否被安全地设置为 0，防止报错
    assert f["line_start"] == 0
    assert f["needs_verification"] is True
    
    # 💡 验证生成的 TaskHandoff
    handoff = result.handoff
    assert handoff is not None
    assert handoff.to_agent == "verification"
    assert len(handoff.suggested_actions) > 0
    
    action = handoff.suggested_actions[0]
    assert action["action"] == "verify_vulnerability"
    # 验证是否同时向沙箱传递了行号和函数签名
    assert action["line"] == 0
    assert action["function_signature"] == "function withdraw(uint amount)"
    
    test_logger.info("✅ 数据双轨兼容映射完美通过！")

@pytest.mark.asyncio
async def test_empty_response_fallback(analysis_agent, sample_input_data):
    """测试 5: 连续空响应熔断兜底"""
    test_logger.info(">>> 测试: 连续空响应的容错与兜底机制")
    
    analysis_agent.stream_llm_call = AsyncMock(side_effect=[
        ("Thought: 开始分析\nAction: search_code\nAction Input: {}", 10),
        ("   ", 10), 
        ("   ", 10), 
        ("   ", 10), # 触发兜底
    ])
    
    analysis_agent.execute_tool = AsyncMock(return_value="查找到 reentrancy")
    
    result = await analysis_agent.run(sample_input_data)
    
    assert result.success is False
    assert "连续收到空响应" in result.error
    # 确保兜底返回了结构依然安全的空 findings 列表
    assert isinstance(result.data["findings"], list)
    test_logger.info("✅ 空响应安全熔断")