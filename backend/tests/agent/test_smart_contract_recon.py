import pytest
import asyncio
import logging
import sys
import json
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any

# 设置全局日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("app.services.agent.agents.smart_contract_recon")
logger.setLevel(logging.DEBUG)
test_logger = logging.getLogger("TestRunner")

# 引入 ReconAgent 和真实的 ReconStep 数据类
from app.services.agent.agents.smart_contract_recon import ReconAgent, ReconStep
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
    default_answer = {
        "project_structure": {"framework": "Foundry", "core_contracts": ["src/Vault.sol"]},
        "tech_stack": {"solidity_versions": ["^0.8.20"], "dependencies": []},
        "entry_points": [{"type": "payable", "file": "src/Vault.sol", "method": "deposit()"}],
        "high_risk_areas": ["src/Vault.sol:10 - call"],
        "initial_findings": [{"title": "Reentrancy", "file_path": "src/Vault.sol"}],
        "summary": "测试汇总"
    }
    service.stream_call.return_value = (f"Thought: 我已了解情况\nFinal Answer: ```json\n{json.dumps(default_answer)}\n```", 150)
    return service

@pytest.fixture
def recon_agent(mock_llm_service):
    """初始化 Recon Agent"""
    agent = ReconAgent(
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
def sample_onchain_input():
    return {
        "project_info": {"name": "0xdAC17F958D2ee523a2206206994597C13D831ec7"},
        "config": {"chain": "mainnet"},
        "task": "信息收集"
    }

@pytest.fixture
def sample_local_input():
    return {
        "project_info": {"name": "LocalDeFi", "root": "/tmp/defi", "file_count": 50},
        "config": {"target_files": ["src/Vault.sol", "src/Token.sol"]},
        "task": "信息收集"
    }

# ==========================================
# 2. 测试用例 (Test Cases)
# ==========================================

def test_parse_dirty_llm_response(recon_agent):
    """测试 1: 脏数据与 Markdown 清洗机制"""
    test_logger.info(">>> 测试: LLM 脏格式响应解析")
    dirty_response = """
    **Thought:** 我需要调用下载工具。
    **Action:** foundry_cast
    **Action Input:** ```json
    {"contract_address": "0x123"}
    ```
    """
    step = recon_agent._parse_llm_response(dirty_response)
    assert step.thought == "我需要调用下载工具。"
    assert step.action == "foundry_cast"
    assert step.action_input["contract_address"] == "0x123"

def test_parse_missing_thought(recon_agent):
    """测试 2: 提取未标记的思考过程"""
    test_logger.info(">>> 测试: 缺失 Thought 标签时的提取")
    response = """
    这是一个 DeFi 项目，我发现它有很多入口。
    Action: read_file
    Action Input: {"file": "Vault.sol"}
    """
    step = recon_agent._parse_llm_response(response)
    assert "这是一个 DeFi 项目" in step.thought
    assert step.action == "read_file"

@pytest.mark.asyncio
async def test_initial_prompt_building(recon_agent, sample_onchain_input, sample_local_input):
    """测试 3: 初始 Prompt 上下文动态构建"""
    test_logger.info(">>> 测试: 初始策略 Prompt 构建")
    recon_agent.stream_llm_call = AsyncMock(return_value=("Final Answer: {}", 10))
    
    # 验证链上地址 Prompt (🔥 修复断言，匹配星号)
    await recon_agent.run(sample_onchain_input)
    prompt_onchain = recon_agent._conversation_history[1]["content"]
    assert "0xdAC17F958D2ee523a2206206994597C13D831ec7" in prompt_onchain
    assert "**必须** 是使用 `foundry_cast` 工具" in prompt_onchain
    
    # 验证本地项目 Prompt
    await recon_agent.run(sample_local_input)
    prompt_local = recon_agent._conversation_history[1]["content"]
    assert "用户指定了 2 个目标文件" in prompt_local
    assert "src/Vault.sol" in prompt_local

@pytest.mark.asyncio
async def test_empty_response_fallback(recon_agent, sample_onchain_input):
    """测试 4: 连续空响应熔断与兜底机制"""
    test_logger.info(">>> 测试: 连续空响应的容错与兜底机制")
    
    # 🔥 修复：让大模型先成功跑一步，把数据塞入内部状态，然后开始连续抽风
    recon_agent.stream_llm_call = AsyncMock(side_effect=[
        ("Thought: 先看看项目里有什么\nAction: list_files\nAction Input: {}", 10),
        ("   ", 10), # 第1次空响应
        ("   ", 10), # 第2次空响应
        ("   ", 10), # 第3次空响应 -> 触发熔断兜底！
    ])
    
    # 模拟底层的沙箱工具返回了带有关键特征的情报
    recon_agent.execute_tool = AsyncMock(
        return_value="找到 foundry.toml 和 openzeppelin 库，并在 src/Vault.sol 发现 call{value} 操作"
    )
    
    result = await recon_agent.run(sample_onchain_input)
    
    # 1. 验证系统是否因为空响应正常熔断报错
    assert result.success is False
    assert "连续收到空响应" in result.error
    
    # 2. 验证系统在崩溃前，是否成功利用最后一点线索拼凑出了兜底情报
    fallback_data = result.data
    assert fallback_data["project_structure"]["framework"] == "Foundry"
    assert "OpenZeppelin" in fallback_data["tech_stack"]["dependencies"]
    assert len(fallback_data["high_risk_areas"]) > 0
    assert "src/Vault.sol" in fallback_data["high_risk_areas"][0]
@pytest.mark.asyncio
async def test_tool_error_recovery(recon_agent, sample_onchain_input):
    """测试 5: 工具连续失败的强制干预机制"""
    test_logger.info(">>> 测试: 工具连续失败时的系统强制干预")
    
    recon_agent.stream_llm_call = AsyncMock(return_value=(
        "Thought: 读文件\nAction: read_file\nAction Input: {\"file\": \"not_exist.sol\"}", 50
    ))
    recon_agent.execute_tool = AsyncMock(return_value="执行失败：文件不存在")
    recon_agent.config.max_iterations = 4 
    
    await recon_agent.run(sample_onchain_input)
    
    # 🔥 修复：在整个对话历史文本中搜索干预警告（因为最后一条会被 fallback 提示覆盖）
    history_text = json.dumps(recon_agent._conversation_history, ensure_ascii=False)
    assert "⚠️ **系统提示**: 此工具调用已连续失败" in history_text
    assert "直接输出 Final Answer" in history_text

@pytest.mark.asyncio
async def test_full_recon_loop(recon_agent, sample_onchain_input):
    """测试 6: 完整的 ReAct 侦察闭环与交接生成"""
    test_logger.info(">>> 测试: 完整的 ReAct 侦察流水线")
    
    recon_agent.stream_llm_call = AsyncMock(side_effect=[
        ("Thought: 这是地址，我要下载源码\nAction: foundry_cast\nAction Input: {\"address\": \"0x123\"}", 100),
        ("Thought: 下载好了，我总结一下\nFinal Answer: ```json\n" + json.dumps({
            "project_structure": {"framework": "Foundry", "core_contracts": ["src/Core.sol"]},
            "tech_stack": {"solidity_versions": ["^0.8.0"], "dependencies": []},
            "entry_points": [{"type": "public", "file": "src/Core.sol", "method": "swap()"}],
            "high_risk_areas": ["src/Core.sol:50 - delegatecall"],
            "initial_findings": [{"title": "任意调用", "file_path": "src/Core.sol"}],
            "recommended_tools": {"must_use": ["foundry_test"]},
            "summary": "分析完毕"
        }) + "\n```", 150)
    ])
    
    recon_agent.execute_tool = AsyncMock(return_value="源码下载成功，存在 src/Core.sol 文件。")
    
    result = await recon_agent.run(sample_onchain_input)
    
    assert result.success is True
    assert result.iterations == 2
    # 🔥 修复：通过 Mock 的 call_count 来验证工具是否被调度
    assert recon_agent.execute_tool.call_count == 1
    
    handoff = result.handoff
    assert handoff.to_agent == "analysis"
    assert "任意调用" in handoff.key_findings[0]["title"]