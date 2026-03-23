"""
Foundry Cheatcodes 知识库

包含Foundry测试框架中常用的cheatcodes及其使用方法
"""

from .base import KnowledgeDocument, KnowledgeCategory

# Foundry Cheatcodes 完整文档
SC_FOUNDRY_CHEATCODES = KnowledgeDocument(
    id="sc_foundry_cheatcodes",
    title="Foundry Cheatcodes 完整指南",
    category=KnowledgeCategory.BEST_PRACTICE,
    severity="info",
    tags=["foundry", "testing", "cheatcodes", "solidity"],
    cwe_ids=[],
    content="""
# Foundry Cheatcodes 完整指南

Foundry 提供了一套强大的 cheatcodes，用于在测试中模拟各种区块链环境和行为。

## 核心 Cheatcodes

### 1. 账户和资金管理

#### vm.deal(address, uint256)
为指定地址分配 ETH。

```solidity
// 为攻击者合约分配 10 ETH
vm.deal(address(attacker), 10 ether);

// 为受害者合约分配初始资金
vm.deal(address(victim), 100 ether);
```

#### vm.prank(address)
将下一个调用的 msg.sender 设置为指定地址。

```solidity
// 以 user 的身份调用函数
vm.prank(user);
vault.withdraw(amount);
```

#### vm.startPrank(address) / vm.stopPrank()
在一个范围内将所有调用的 msg.sender 设置为指定地址。

```solidity
vm.startPrank(attacker);
// 所有后续调用都来自 attacker
vault.deposit(1 ether);
vault.withdraw(1 ether);
vm.stopPrank();
```

### 2. 存储操作

#### vm.store(address, bytes32, bytes32)
直接修改合约存储槽的值。

```solidity
// 修改 balances[user] 的值
bytes32 slot = keccak256(abi.encode(user, 0)); // 假设 balances 在槽 0
vm.store(address(vault), slot, bytes32(uint256(1000 ether)));
```

#### vm.load(address, bytes32)
读取合约存储槽的值。

```solidity
bytes32 value = vm.load(address(vault), slot);
```

### 3. 事件和日志

#### vm.expectEmit(bool, bool, bool, bool)
验证后续调用是否发出了预期的事件。

```solidity
// 验证 Transfer 事件
vm.expectEmit(true, true, false, true);
emit Transfer(from, to, amount);
token.transfer(to, amount);
```

#### console.log()
打印调试信息。

```solidity
import "forge-std/console.sol";

console.log("Profit:", profit);
console.log("Address:", address(this));
console.log("Value:", uint256(123));
```

### 4. 错误处理

#### vm.expectRevert()
验证下一个调用是否会 revert。

```solidity
// 验证调用会 revert
vm.expectRevert();
vault.withdraw(amount);

// 验证特定的错误消息
vm.expectRevert("Insufficient balance");
vault.withdraw(amount);
```

#### vm.expectRevert(bytes4)
验证特定的错误选择器。

```solidity
vm.expectRevert(Vault.InsufficientBalance.selector);
vault.withdraw(amount);
```

### 5. 时间和区块操作

#### vm.warp(uint256)
设置区块时间戳。

```solidity
// 设置时间戳为 1000
vm.warp(1000);

// 快进 1 天
vm.warp(block.timestamp + 1 days);
```

#### vm.roll(uint256)
设置区块号。

```solidity
// 设置区块号为 100
vm.roll(100);
```

### 6. 调用跟踪

#### vm.recordLogs()
记录后续调用的所有日志。

```solidity
vm.recordLogs();
// 执行会产生日志的操作
Vm.Log[] memory logs = vm.getRecordedLogs();
```

### 7. 模拟调用

#### vm.mockCall(address, bytes, bytes)
模拟对外部合约的调用结果。

```solidity
// 模拟 token.balanceOf(user) 返回 1000
vm.mockCall(
    address(token),
    abi.encodeWithSelector(token.balanceOf.selector, user),
    abi.encode(uint256(1000))
);
```

#### vm.clearMockedCalls()
清除所有模拟调用。

```solidity
vm.clearMockedCalls();
```

## PoC 编写最佳实践

### 1. 标准 PoC 结构

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "forge-std/console.sol";
import "../src/Vault.sol";

contract ExploitTest is Test {
    Vault vault;
    address attacker = address(0x1337);
    
    function setUp() public {
        // 部署受害者合约
        vault = new Vault();
        
        // 为受害者合约分配初始资金
        vm.deal(address(vault), 100 ether);
        
        // 为攻击者分配启动资金
        vm.deal(attacker, 10 ether);
    }
    
    function testExploit() public {
        // 以攻击者身份执行攻击
        vm.startPrank(attacker);
        
        // 执行攻击逻辑
        uint256 initialBalance = address(attacker).balance;
        // ... 攻击代码 ...
        uint256 finalBalance = address(attacker).balance;
        
        // 计算利润
        uint256 profit = finalBalance - initialBalance;
        
        // 输出利润（必须！）
        console.log("Profit:", profit);
        
        // 验证攻击成功
        assert(profit > 0);
        
        vm.stopPrank();
    }
}
```

### 2. 处理可重入漏洞

```solidity
contract ReentrancyExploit is Test {
    Vault vault;
    Attacker attacker;
    
    function setUp() public {
        vault = new Vault();
        vm.deal(address(vault), 100 ether);
        
        attacker = new Attacker(vault);
        vm.deal(address(attacker), 1 ether);
    }
    
    function testReentrancy() public {
        // 攻击者先存入 1 ETH
        vm.prank(address(attacker));
        vault.deposit{value: 1 ether}();
        
        // 触发可重入攻击
        vm.prank(address(attacker));
        attacker.attack();
        
        // 验证攻击成功
        uint256 profit = address(attacker).balance - 1 ether;
        console.log("Profit:", profit);
        assert(profit > 0);
    }
}

contract Attacker {
    Vault vault;
    
    constructor(Vault _vault) {
        vault = _vault;
    }
    
    function attack() public {
        vault.withdraw(1 ether);
    }
    
    receive() external payable {
        // 在接收 ETH 时重新调用 withdraw
        if (address(vault).balance > 0) {
            vault.withdraw(1 ether);
        }
    }
}
```

### 3. 处理闪贷攻击

```solidity
contract FlashLoanExploit is Test {
    Pool pool;
    Attacker attacker;
    
    function setUp() public {
        pool = new Pool();
        // 为池子提供流动性
        vm.deal(address(pool), 1000 ether);
        
        attacker = new Attacker(pool);
    }
    
    function testFlashLoan() public {
        // 触发闪贷攻击
        attacker.executeFlashLoan(100 ether);
        
        uint256 profit = address(attacker).balance;
        console.log("Profit:", profit);
        assert(profit > 0);
    }
}

contract Attacker {
    Pool pool;
    
    constructor(Pool _pool) {
        pool = _pool;
    }
    
    function executeFlashLoan(uint256 amount) public {
        // 请求闪贷
        pool.flashLoan(amount, abi.encodeWithSelector(this.onFlashLoan.selector));
    }
    
    function onFlashLoan(uint256 amount) public {
        // 在这里执行攻击逻辑
        // 利用临时获得的资金操纵价格或执行其他攻击
        
        // 偿还闪贷
        // ...
    }
}
```

### 4. 处理访问控制漏洞

```solidity
contract AccessControlExploit is Test {
    Vault vault;
    address attacker = address(0x1337);
    
    function setUp() public {
        vault = new Vault();
        vm.deal(address(vault), 100 ether);
    }
    
    function testAccessControl() public {
        // 以攻击者身份调用只有所有者才能调用的函数
        vm.prank(attacker);
        vault.emergencyWithdraw();
        
        uint256 profit = address(attacker).balance;
        console.log("Profit:", profit);
        assert(profit > 0);
    }
}
```

## 常见错误和解决方案

### 错误1: 忘记导入 console
```solidity
// ❌ 错误
console.log("Value:", value);

// ✅ 正确
import "forge-std/console.sol";
console.log("Value:", value);
```

### 错误2: 使用错误的单位
```solidity
// ❌ 错误
vm.deal(attacker, 10);  // 这是 10 wei，不是 10 ETH

// ✅ 正确
vm.deal(attacker, 10 ether);
```

### 错误3: 忘记 payable 修饰符
```solidity
// ❌ 错误
address(attacker).call{value: 1 ether}("");

// ✅ 正确
(bool success, ) = payable(attacker).call{value: 1 ether}("");
require(success);
```

### 错误4: 不正确的存储槽计算
```solidity
// ❌ 错误 - 假设 balances 在槽 0
bytes32 slot = keccak256(abi.encode(user, 0));

// ✅ 正确 - 需要根据实际合约确定
// 查看合约源代码确定 balances 的实际槽位
```

## 调试技巧

### 1. 使用 console.log 输出调试信息
```solidity
console.log("Current balance:", address(this).balance);
console.log("User address:", user);
console.log("Amount:", amount);
```

### 2. 使用 vm.recordLogs 跟踪事件
```solidity
vm.recordLogs();
vault.withdraw(amount);
Vm.Log[] memory logs = vm.getRecordedLogs();
for (uint i = 0; i < logs.length; i++) {
    console.log("Event:", logs[i].topics[0]);
}
```

### 3. 使用 forge test -vvv 获取详细输出
```bash
forge test -vvv --match-test testExploit
```

## 参考资源

- Foundry 官方文档: https://book.getfoundry.sh/
- Foundry Cheatcodes: https://book.getfoundry.sh/cheatcodes/
- Forge-std 库: https://github.com/foundry-rs/forge-std
""",
)

__all__ = [
    "SC_FOUNDRY_CHEATCODES",
]
