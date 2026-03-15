import pytest
import asyncio
import logging
import sys
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any

# 设置全局日志，将 DEBUG 级别以上的日志输出到控制台
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("app.services.agent.agents.smart_contract_orchestrator")
logger.setLevel(logging.DEBUG)
test_logger = logging.getLogger("TestRunner")

from app.services.agent.agents.smart_contract_orchestrator import OrchestratorAgent
from app.services.agent.agents.base import BaseAgent, AgentResult, TaskHandoff

# ==========================================
# 0. 模拟控制台事件发射器 (修复了 emit 方法缺失问题)
# ==========================================
class ConsoleEventEmitter:
    """模拟前端 SSE 推送，直接在控制台彩色打印输出"""
    
    async def emit(self, event_data: Any):
        """底层 BaseAgent 会调用这个方法，必须实现"""
        event_type = getattr(event_data, "event_type", "UNKNOWN")
        msg = getattr(event_data, "message", "")
        # 如果是 thinking_token，避免刷屏，只在整句时打印
        if event_type == "thinking_token":
            return
        print(f"\n[📢 实时事件 - {str(event_type).upper()}] {msg}")

# ==========================================
# 1. 构造测试替身 (Fixtures)
# ==========================================

@pytest.fixture
def mock_llm_service():
    """模拟大模型服务"""
    service = AsyncMock()
    service.stream_call.return_value = ("Thought: 任务完成\nAction: finish\nAction Input: {\"conclusion\": \"done\"}", 100)
    return service

@pytest.fixture
def mock_sub_agents():
    """模拟三个子 Agent 的行为"""
    recon = MagicMock(spec=BaseAgent)
    analysis = MagicMock(spec=BaseAgent)
    verification = MagicMock(spec=BaseAgent)
    
    # 🔥 修复：补全 _registered 等底层状态属性
    for agent in [recon, analysis, verification]:
        agent.set_parent_id = MagicMock()
        agent._register_to_registry = MagicMock()
        agent._registered = True  # 防止 _dispatch_agent 打印日志时报错
        agent.cancel = MagicMock()
        agent.get_stats = MagicMock(return_value={"iterations": 1, "tool_calls": 1, "tokens_used": 100})
    
    # 模拟真实执行结果
    recon.run = AsyncMock(return_value=AgentResult(
        success=True, 
        data={"initial_findings": [], "entry_points": ["Vault.sol:10"]}
    ))
    
    analysis.run = AsyncMock(return_value=AgentResult(
        success=True, 
        data={"findings": [{"title": "Reentrancy in Vault", "file_path": "Vault.sol", "vulnerability_type": "reentrancy", "severity": "high"}]}
    ))
    
    # 模拟 Verification 沙箱成功榨取利润
    verification.run = AsyncMock(return_value=AgentResult(
        success=True, 
        data={"findings": [{"title": "Reentrancy in Vault", "file_path": "Vault.sol", "vulnerability_type": "reentrancy", "profit_extracted": 1.5, "is_verified": True}]}
    ))
    
    return {
        "recon": recon,
        "analysis": analysis,
        "verification": verification
    }

@pytest.fixture
def orchestrator(mock_llm_service, mock_sub_agents):
    """初始化 Orchestrator"""
    agent = OrchestratorAgent(
        llm_service=mock_llm_service,
        tools={},
        event_emitter=ConsoleEventEmitter(),
        sub_agents=mock_sub_agents
    )
    agent._validate_file_path = MagicMock(return_value=True) 
    agent._total_tokens = 0
    agent._tool_calls = 0
    agent._cancel_callback = None 
    
    # 🔥 修复：手动注入字典格式的 _timeout_config，防止环境默认将其设为协程对象
    agent._timeout_config = {"sub_agent_timeout": 600}
    
    return agent

@pytest.fixture
def sample_input_data():
    return {
        "task_id": "test_uuid_123",
        "project_root": "/tmp/test",
        "project_info": {"name": "TestProject", "file_count": 0, "structure": {}},
        "config": {
            "target_address": "0x1234567890abcdef",
            "chain": "bsc",
            "expected_profit_threshold": 0.5,
            "target_vulnerabilities": ["reentrancy", "access_control"]
        }
    }

# ==========================================
# 2. 核心流转与合并测试用例
# ==========================================

@pytest.mark.asyncio
async def test_finding_aggregation_and_profit_merge(orchestrator, sample_input_data):
    """测试 Web3 战果智能合并逻辑"""
    print("\n" + "="*50)
    test_logger.info("开始测试：Web3 漏洞聚合与利润合并")
    
    orchestrator._runtime_context = sample_input_data
    orchestrator._agent_id = "orch_1"
    
    await orchestrator._dispatch_agent({"agent": "analysis", "task": "analyze"})
    assert len(orchestrator._all_findings) == 1
    assert orchestrator._all_findings[0]["vulnerability_type"] == "reentrancy"
    assert orchestrator._all_findings[0].get("is_verified") is not True
    
    await orchestrator._dispatch_agent({"agent": "verification", "task": "verify"})
    assert len(orchestrator._all_findings) == 1
    merged_finding = orchestrator._all_findings[0]
    assert merged_finding["is_verified"] is True
    assert merged_finding["profit_extracted"] == 1.5

@pytest.mark.asyncio
async def test_full_run_loop(orchestrator, sample_input_data):
    """测试完整的 ReAct 编排主循环"""
    print("\n" + "="*50)
    test_logger.info("开始测试：完整的 LLM 编排主循环")
    
    orchestrator.stream_llm_call = AsyncMock(side_effect=[
        ("Thought: 这是链上地址，去侦察。\nAction: dispatch_agent\nAction Input: {\"agent\": \"recon\", \"task\": \"拉源码\"}", 150),
        ("Thought: 接下来挖掘漏洞。\nAction: dispatch_agent\nAction Input: {\"agent\": \"analysis\", \"task\": \"挖掘\"}", 150),
        ("Thought: 验证重入漏洞。\nAction: dispatch_agent\nAction Input: {\"agent\": \"verification\", \"task\": \"验证\"}", 150),
        ("Thought: 沙箱成功爆破，利润达到阈值。准备输出报告。\nAction: finish\nAction Input: {\"conclusion\": \"审计完美结束，成功爆破资金\"}", 100),
    ])
    
    result = await orchestrator.run(sample_input_data)
    
    assert result.success is True
    assert result.iterations == 4
    assert len(result.data["steps"]) == 4
    assert result.data["summary"]["conclusion"] == "审计完美结束，成功爆破资金"

# ==========================================
# 3. 边界与防御机制测试
# ==========================================

@pytest.mark.asyncio
async def test_dispatch_duplicate_agent(orchestrator):
    """防止死循环：测试重复调度同一个 Agent 时的拦截机制"""
    print("\n" + "="*50)
    test_logger.info("开始测试：重复调度防御机制")
    
    orchestrator._dispatched_tasks["analysis"] = 2
    params = {"agent": "analysis", "task": "find bugs"}
    result_msg = await orchestrator._dispatch_agent(params)
    
    assert "重复调度警告" in result_msg
    assert orchestrator.sub_agents["analysis"].run.call_count == 0

def test_parse_llm_response(orchestrator):
    """测试带有干扰的 LLM 输出格式能否被正确解析"""
    print("\n" + "="*50)
    test_logger.info("开始测试：LLM 格式容错解析")
    
    dirty_response = """
    **Thought:** 我需要调用侦察特工。
    **Action:** dispatch_agent
    **Action Input:** ```json
    {"agent": "recon", "task": "download"}
    ```
    """
    step = orchestrator._parse_llm_response(dirty_response)
    
    assert step is not None
    assert step.action == "dispatch_agent"
    assert step.action_input["agent"] == "recon"

@pytest.mark.asyncio
async def test_build_initial_message_on_chain(orchestrator, sample_input_data):
    """测试链上地址的初始上下文构建"""
    print("\n" + "="*50)
    test_logger.info("开始测试：Web3 初始 Prompt 构建")
    
    msg = orchestrator._build_initial_message(
        sample_input_data["project_info"], 
        sample_input_data["config"]
    )
    
    assert "0x1234567890abcdef" in msg
    assert "所在链: bsc" in msg
    # 🔥 修复：匹配最新的 Prompt 字符串
    assert "你的第一步**必须**是调度 `recon` Agent" in msg
    assert "0.5 ETH" in msg