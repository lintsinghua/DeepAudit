"""
Foundry 沙箱工具单元测试（详细日志版）
这段测试代码主要针对 Foundry 沙箱工具集（`FoundryCastTool` 和 `FoundryTestTool`）的核心业务流程进行了验证。

具体来说，它测试了以下三大功能场景：

### 1. FoundryCastTool（源码获取工具）

* **成功下载合约源码 (`test_cast_success`)**：
* **测试内容**：验证工具能否成功下发 `cast source` 和代码行数统计命令。
* **验证点**：确保工具能够正确解析终端输出，准确识别出下载了多少个 `.sol` 文件（测试中为 2 个）、总计多少行代码（测试中为 150 行），并组装成包含 `success=True` 的标准化结果返回。



### 2. FoundryTestTool（漏洞验证工具）

* **成功复现攻击并提取利润 (`test_forge_test_success_with_profit`)**：
* **测试内容**：验证工具在 PoC 脚本执行成功时的表现。
* **验证点**：确保工具能够正确解析 `forge test --json` 返回的复杂 JSON 数据，成功提取出运行状态（`Success`）和消耗的 Gas（105000）。更关键的是，验证了它能通过正则表达式准确从 `decoded_logs` 中提取出打印的利润数值（`15.5` ETH），并判断其是否满足预期。


* **攻击执行失败/Revert 场景 (`test_forge_test_failure_revert`)**：
* **测试内容**：验证工具在 PoC 脚本执行失败（如漏洞利用不成功，合约抛出 Revert）时的错误处理机制。
* **验证点**：确保当底层命令退出码异常或 JSON 状态为 `Failure` 时，工具能够正确捕获拦截，并将返回的 `success` 和 `test_passed` 状态安全地置为 `False`，防止 Agent 产生误判。



总体来看，这份测试覆盖了工具的最核心“主干道”（Happy Path）以及关键的“异常分支”（Sad Path）。

需要我帮你补充诸如“API Key 错误”、“参数缺失”或“网络超时”等边界情况的测试用例吗？
"""

import pytest
import json
import logging
from unittest.mock import MagicMock

from app.services.agent.tools.foundry_tools import FoundryCastTool, FoundryTestTool

# 配置日志输出格式，方便观察内部流转
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s'
)
logger = logging.getLogger("TestFoundrySuite")


class DummySandboxManager:
    """带有状态输出日志的模拟沙箱管理器"""
    def __init__(self, available=True, command_mocks=None):
        self.available = available
        self.executed_commands = []
        self.command_mocks = command_mocks or {}

    async def initialize(self):
        logger.debug("[DummySandbox] 沙箱初始化完成，状态: 可用")

    @property
    def is_available(self):
        return self.available

    async def execute_command(self, command, working_dir=None, env=None, timeout=None):
        logger.info(f"🚀 [DummySandbox] 拦截到系统命令执行: \n      {command}")
        self.executed_commands.append(command)
        
        default_result = {"success": True, "stdout": "", "stderr": "", "exit_code": 0}

        for cmd_key, mock_result in self.command_mocks.items():
            if cmd_key in command:
                logger.debug(f"🔍 [DummySandbox] 命令命中 Mock 规则 [{cmd_key}]，注入虚拟返回值...")
                return {**default_result, **mock_result}
                
        logger.debug("⚠️ [DummySandbox] 未命中特定 Mock 规则，返回默认成功状态")
        return default_result


class TestFoundryCastTool:
    
    @pytest.mark.asyncio
    async def test_cast_success(self):
        logger.info("========== 开始测试: FoundryCastTool 成功下载源码 ==========")
        
        command_mocks = {
            "cast source": {
                "stdout": "Downloading...\n/workspace/src/0x123.../Main.sol\n/workspace/src/0x123.../Lib.sol",
                "exit_code": 0
            },
            "wc -l": {"stdout": " 150 total\n", "exit_code": 0}
        }
        manager = DummySandboxManager(command_mocks=command_mocks)
        tool = FoundryCastTool(sandbox_manager=manager)

        logger.debug("=> 触发 Tool.execute()...")
        result = await tool.execute(
            contract_address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            chain="mainnet",
            etherscan_api_key="fake_api_key",
            output_dir="src"
        )

        logger.info(f"✅ 工具返回状态: success={result.success}")
        logger.debug(f"📦 工具返回核心数据: \n{json.dumps(result.data, indent=2, ensure_ascii=False)}")
        
        assert result.success is True
        assert result.data["file_count"] == 2
        assert result.data["total_lines"] == 150
        logger.info("========== 结束测试: FoundryCastTool 成功 ==========\n")


class TestFoundryTestTool:

    @pytest.mark.asyncio
    async def test_forge_test_success_with_profit(self):
        logger.info("========== 开始测试: FoundryTestTool 成功复现攻击与利润计算 ==========")
        
        mock_forge_json = {
            "tests": {
                "test/Exploit.t.sol:ExploitTest": {
                    "testExploit()": {
                        "status": "Success",
                        "gas_used": 105000,
                        "decoded_logs": ["console::log(\"Profit:\", 15.5)"]
                    }
                }
            }
        }
        
        command_mocks = {
            "test -f": {"stdout": "File exists\n", "exit_code": 0},
            "forge test": {"stdout": "compiler output...\n" + json.dumps(mock_forge_json), "exit_code": 0}
        }
        manager = DummySandboxManager(command_mocks=command_mocks)
        tool = FoundryTestTool(sandbox_manager=manager)

        logger.debug("=> 触发 Tool.execute() 参数传入...")
        result = await tool.execute(
            test_file="test/Exploit.t.sol",
            test_function="testExploit",
            expected_profit=10.0
        )

        logger.info(f"✅ 工具返回状态: success={result.success}")
        analysis_data = result.data.get("analysis", {})
        logger.debug(f"📊 分析数据状态流转结果: 耗费Gas={analysis_data.get('gas_used')}, 实际Profit={analysis_data.get('profit')}")
        
        assert result.success is True
        assert analysis_data["profit"] == 15.5
        assert analysis_data["profit_meets_expectation"] is True
        logger.info("========== 结束测试: FoundryTestTool 利润计算成功 ==========\n")

    @pytest.mark.asyncio
    async def test_forge_test_failure_revert(self):
        logger.info("========== 开始测试: FoundryTestTool 攻击 Revert 失败场景 ==========")
        
        mock_forge_json = {
            "tests": {
                "test/Exploit.t.sol:ExploitTest": {
                    "testExploit()": {
                        "status": "Failure",
                        "gas_used": 5000,
                        "decoded_logs": []
                    }
                }
            }
        }
        
        command_mocks = {
            "test -f": {"stdout": "File exists", "exit_code": 0},
            "forge test": {"stdout": json.dumps(mock_forge_json), "exit_code": 1}
        }
        manager = DummySandboxManager(command_mocks=command_mocks)
        tool = FoundryTestTool(sandbox_manager=manager)

        result = await tool.execute(
            test_file="test/Exploit.t.sol",
            test_function="testExploit",
            rpc_url="https://fake.rpc.com"
        )

        logger.info(f"❌ 工具正确捕获失败状态: success={result.success}")
        logger.debug(f"📄 提取到的 Summary: {result.data['analysis']['summary']}")
        
        assert result.success is False
        assert result.data["test_passed"] is False
        logger.info("========== 结束测试: FoundryTestTool 攻击 Revert 失败 ==========\n")