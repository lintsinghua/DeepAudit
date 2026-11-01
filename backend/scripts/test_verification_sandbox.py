"""
模块说明：用于脚本化执行的工具脚本：test_verification_sandbox。
"""


import asyncio
import os
import sys
import json
import logging
from typing import Dict, Any, List

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import AsyncSessionLocal
from app.models.user_config import UserConfig
from app.services.llm.service import LLMService
from app.services.agent.agents.verification import VerificationAgent
from app.services.agent.tools.sandbox_tool import SandboxTool, SandboxHttpTool, VulnerabilityVerifyTool, SandboxManager, SandboxConfig
from app.services.agent.agents.base import AgentType
from app.services.agent.config import AgentConfig
from app.core.config import settings
from sqlalchemy import select

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_user_llm_config():
    """Fetch LLM configuration from the first user in the database"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserConfig))
        user_config = result.scalars().first()
        
        if not user_config:
            logger.error("❌ No user config found in database!")
            return None
            
        logger.info(f"✅ Loaded config for user_id: {user_config.user_id}")
        
        import json
        raw_config = user_config.llm_config
        llm_data = json.loads(raw_config) if raw_config else {}
        logger.info(f"📂 Loaded LLM config keys: {list(llm_data.keys())}")
        
        # Try to find keys regardless of naming convention (camelCase vs snake_case)
        api_key = llm_data.get("api_key") or llm_data.get("llmApiKey") or llm_data.get("apiKey")
        base_url = llm_data.get("base_url") or llm_data.get("llmBaseUrl") or llm_data.get("baseUrl")
        model = llm_data.get("model") or llm_data.get("llmModel")
        provider = llm_data.get("provider") or llm_data.get("llmProvider")
        
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "provider": provider
        }

async def run_verification_test():
    print("\n🚀 Starting Verification Agent Sandbox Test (Standalone Mode)\n")
    
    llm_config = await get_user_llm_config()
    if not llm_config:
        return

    override_provider = os.getenv("TEST_LLM_PROVIDER")
    override_api_key = os.getenv("TEST_LLM_API_KEY")
    override_model = os.getenv("TEST_LLM_MODEL")

    if override_provider or override_api_key or override_model:
        llm_config["provider"] = override_provider or llm_config.get("provider")
        llm_config["api_key"] = override_api_key or llm_config.get("api_key")
        llm_config["model"] = override_model or llm_config.get("model")

    # 2. Initialize LLM Service
    # Transform simple config to the structure LLMService expects
    service_user_config = {
        "llmConfig": {
            "llmProvider": llm_config.get("provider"),
            "llmApiKey": llm_config.get("api_key"),
            "llmModel": llm_config.get("model"),
            "llmBaseUrl": llm_config.get("base_url")
        }
    }
    llm_service = LLMService(user_config=service_user_config)
    
    # Also update settings just in case
    if llm_config.get("api_key"):
        settings.LLM_API_KEY = llm_config["api_key"]

    print(f"🔧 Configured LLM: {llm_config.get('provider')} / {llm_config.get('model')}")

    # 3. Initialize Sandbox Tools
    print("📦 Initializing Sandbox Tools...")
    try:
        sandbox_config = SandboxConfig(
            image=settings.SANDBOX_IMAGE,
            memory_limit=settings.SANDBOX_MEMORY_LIMIT,
            cpu_limit=settings.SANDBOX_CPU_LIMIT,
            timeout=settings.SANDBOX_TIMEOUT,
            network_mode=settings.SANDBOX_NETWORK_MODE,
        )
        sandbox_manager = SandboxManager(config=sandbox_config)
        # Pre-check docker
        await sandbox_manager.initialize()
        if sandbox_manager.is_available:
            print("✅ Docker Sandbox is AVAILABLE")
        else:
            print("⚠️ Docker Sandbox is UNAVAILABLE (Tools will return error messages)")
            
        tools = {
            "sandbox_exec": SandboxTool(sandbox_manager),
            "sandbox_http": SandboxHttpTool(sandbox_manager),
            "verify_vulnerability": VulnerabilityVerifyTool(sandbox_manager)
        }
    except Exception as e:
        print(f"❌ Failed to init sandbox: {e}")
        return

    # 4. Initialize Verification Agent
    # VerificationAgent.__init__ does not take 'config' argument, it builds it internally.
    agent = VerificationAgent(
        llm_service=llm_service,
        tools=tools
    )
    
    # 5. Create Mock Input (Simulating a Command Injection Finding)
    mock_findings = [
        {
            "id": "finding_123",
            "type": "command_injection",
            "file": "legacy/vuln.php",
            "line": 42,
            "code": "<?php system($_GET['cmd']); ?>",
            "confidence": "high",
            "severity": "critical",
            "description": "User input is directly passed to system() function.",
            "context": "Legacy admin panel file."
        }
    ]
    
    input_data = {
        "previous_results": {
            "findings": mock_findings
        },
        "task": "Verify this critical command injection vulnerability using sandbox tools.",
    }
    
    print("\n🎯 Starting Verification Task...")
    print(f"Input: {json.dumps(input_data, indent=2, ensure_ascii=False)}")
    print("-" * 50)

    # 6. Run Agent
    try:
        result = await agent.run(input_data)
        print("\n✅ Verification Completed!")
        print("-" * 50)
        if hasattr(result, "model_dump"):
            print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        elif hasattr(result, "__dict__"):
            print(json.dumps(result.__dict__, indent=2, ensure_ascii=False, default=str))
        else:
            print(str(result))
        
        stats = agent.get_stats()
        print(f"\n📊 Stats: Tool Calls={stats['tool_calls']}, Tokens={stats['tokens_used']}")
        if stats.get("tool_calls", 0) == 0:
            print("\n⚠️ LLM 未调用任何工具，直接通过 VerificationAgent.execute_tool 测试 sandbox_exec...")
            observation = await agent.execute_tool(
                "sandbox_exec",
                {"command": "echo sandbox_test", "timeout": 10}
            )
            print("\n🔍 Direct sandbox_exec result:")
            print(observation)
        
    except Exception as e:
        print(f"\n❌ Execution Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_verification_test())
