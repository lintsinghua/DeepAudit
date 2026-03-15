"""
智能合约程序逻辑漏洞知识
"""

from ..base import KnowledgeDocument, KnowledgeCategory
REENTRANCY = KnowledgeDocument(
    id="vuln_reentrancy",
    title="Reentrancy Attacks",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["reentrancy", "logic"],
    severity="critical",
    cwe_ids=["CWE-841"],
    owasp_ids=["SC05:2025"],
    content="""
可重入攻击（Reentrancy Attacks）利用了在脆弱函数执行完成前重新进入该函数的能力。当智能合约执行外部调用（调用另一个合约或地址）时，被调用者可以在第一次调用完成且状态完全更新之前，回调（call back into）到原始合约中。

如果调用者没有被设计为防重入的安全模式，回调就可以观察到陈旧的状态并加以利用——例如，提取超过调用者余额的资金、重复计算奖励或在复杂的多步流程中操纵记账。这会导致重复的状态变更，通常会导致合约资金被抽干或逻辑被破坏。重入可以是单函数的（同一个函数被递归调用）、跨函数的（回调进入另一个不同的函数），或者是跨合约的（回调穿越多个合约）。


## 危险模式

### 经典的“更新前提取”（Withdraw-before-update）
最常见的危险模式是在更新内部状态（如扣除余额）之前，先进行了外部调用（如转移代币）。
```solidity
# 危险 - 在外部调用后才更新状态，留下重入窗口
contract Solidity_Reentrancy {
    mapping(address => uint) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        uint amount = balances[msg.sender];
        require(amount > 0, "Insufficient balance");

        // Vulnerability: Ether is sent before updating the user's balance, allowing reentrancy.
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        // Update balance after sending Ether
        balances[msg.sender] = 0;
    }
}
# 使用恶意代币或代理的攻击者可以从 transfer 调用内重新进入 withdraw，基于未更改的 balances[msg.sender] 反复提取资金。
```

## 攻击方式
1. 利用恶意代币或接收者在转移/钩子回调（transfer/hook callbacks）时触发重入。
2. 利用闪电贷回调，在还款前执行攻击者逻辑。
3. 利用复杂的调用图，在模块间交易中途出现状态不一致时发起攻击。

## 检测要点
1. 审查经典的“更新前提取”模式（即在外部调用后才发生状态改变）。
2. 审查回调和钩子接口（例如 ERC-777 钩子、ERC-721/1155 接收者钩子、ERC-4626、闪电贷回调）。
3. 审查跨函数重入（函数之间基于已读即已写的假设）。
4. 审查只读重入（Read-only reentrancy），即 view 函数或预言机在回调期间读取了陈旧/不一致的状态。
5. 审查跨合约和多模块重入（例如“金库 -> 策略 -> DEX”这种涉及多合约调用的复杂流程）。

## 安全实践
1. 遵循**检查-生效-交互（Checks-Effects-Interactions）**模式：先检查前置条件，接着应用所有状态更改（生效），最后才调用外部合约（交互）。
2. 在修改余额/内部记账或执行可能重入的外部调用的状态函数上，使用 ReentrancyGuard 或类似的重入锁。
3. 将 ERC-777 钩子、ERC-4626 钩子和其他回调严格视为重入攻击向量。
4. 仔细审查跨函数交互（例如 deposit 内部调用 withdraw）以及可能跨越多个模块发生重入的多合约系统。
5. 包含专注于重入的模糊测试和单元测试，特别是在涉及外部调用的地方。

## 修复示例
```solidity 
# 安全 - 应用 Checks-Effects-Interactions 模式并结合互斥锁防重入
contract Solidity_Reentrancy {
    mapping(address => uint) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        uint amount = balances[msg.sender];
        require(amount > 0, "Insufficient balance");

        // Fix: Update the user's balance before sending Ether
        balances[msg.sender] = 0;

        // Then send Ether
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");
    }
}
```

"""
)


SHORT_ADDRESS = KnowledgeDocument(
    id="vuln_short_address",
    title="Short Address Attack",
    category=KnowledgeCategory.VULNERABILITY,
    tags=["address", "validation"],
    severity="low",
    cwe_ids=["CWE-1284"],
    owasp_ids=["None"],
    content="""
短地址攻击在以太坊中是指利用以太坊地址的十六进制格式（40个字符，即20字节）和某些智能合约对地址参数处理不当的漏洞，来执行恶意操作的一种攻击手段。
在 Solidity 中，`address` 类型的变量总是占用 20 字节，因此直接传递短地址不会导致问题，因为 Solidity 会自动将其填充至 20 字节。然而，某些合约可能从外部调用接收数据，如果这些数据被错误地解释为地址，且合约没有正确处理或验证这些数据，就可能发生短地址攻击。这种攻击主要出现在智能合约没有正确验证地址参数长度的情况下。尽管实际的以太坊地址长度固定，但攻击者可能尝试传递较短的地址字符串，试图欺骗合约执行非预期的功能。

## 危险模式
### 依赖 EVM 自动补零机制的低级调用
当一个代币合约接受如 `transfer(address to, uint256 amount)` 的调用时，如果用户传入的 `to` 地址由于长度不足缺失了最后的字节，EVM 会为了满足 32 字节的字长对齐，自动将后续参数（如 `amount`）的数据前移，并在整个调用数据的末尾补零。
```solidity
# 危险 - 在旧版本 Solidity (< 0.5.0) 中，未对 msg.data.length 进行校验
contract VulnerableContract {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    // 错误地尝试将任意数据解析为地址
    function setAddress(bytes data) public {
        // 注意：这里使用了一个不安全的方法将数据解析为地址
        // 实际上，如果data的长度小于20字节，这将产生一个无效的地址
        assembly {
            owner := mload(add(data, 0x14)) // 加载20字节的数据并赋值给owner
        }
    }

    function getOwner() public view returns (address) {
        return owner;
    }
}
```

## 攻击方式
1. 攻击者故意构造一个缺少末尾字节的短地址（例如在交易所发起提币操作时提交）。
2. EVM 解析 calldata 时，自动用后面的参数数据（如 amount）来填补地址缺失的字节。
3. 这会导致后续的数值参数向左偏移并在末尾填充 0。原本的 amount 值在十六进制下末尾增加了 0，相当于数值被放大了 256 倍（如果是缺失 1 字节），导致合约转移了远超预期的代币数量。

## 检测要点
1. 检查智能合约的 Solidity 编译器版本。Solidity 0.5.0 及更高版本在编译外部调用时已经内置了针对 calldata 长度的严格校验，这使得短地址攻击在现代智能合约中基本失效。
2. 检查合约中是否在底层汇编（assembly）中自行解析了 msg.data，如果存在手动解析操作，验证是否正确处理了地址参数的长度校验。

## 安全实践
1. 验证数据长度：确保所有接收的地址数据都是完整的20字节。
2. 使用类型安全的函数：避免直接使用低级汇编语句处理数据，而是使用类型安全的Solidity函数。
3. 单元测试：进行详尽的单元测试，包括边界条件和异常情况，确保合约在各种输入下都能正常工作。
4. 在实际开发中，应避免直接在低级汇编中操作地址，而是使用Solidity提供的安全函数和类型检查来处理地址数据。

## 修复示例
```solidity
# 安全 - 添加针对调用数据长度的修饰符 (针对较老的代码库) 或直接升级 Solidity >= 0.5.0
contract SafeToken {
    // 强制验证 payload 长度，确保包含 4字节函数签名 + 32字节地址 + 32字节金额 = 68 字节
    modifier onlyPayloadSize(uint256 size) {
        require(msg.data.length >= size + 4, "Short address attack detected");
        _;
    }

    // 在 Solidity 0.4.x 环境下，通过修饰符进行额外防护
    function transfer(address to, uint256 amount) public onlyPayloadSize(2 * 32) returns (bool) {
        require(balances[msg.sender] >= amount);
        balances[msg.sender] -= amount;
        balances[to] += amount;
        return true;
    }
}
```


"""
)

ASSERT_FAILURE = KnowledgeDocument(
id="vuln_assert_failure",
title="Assert Failure",
category=KnowledgeCategory.VULNERABILITY,
tags=["assert", "dos"],
severity="medium",
cwe_ids=["CWE-617"],
owasp_ids=["None"],
content="""

断言（`assert`）在智能合约中用于确保内部逻辑的一致性和正确性，但如果使用不当，确实可能导致意外的合约终止或资金锁定。这是因为 `assert` 主要用于检测程序内部的错误（例如算法错误或逻辑错误），它假定这些错误在正常运行时绝对不会发生。
一旦 `assert` 失败，交易将被立即回滚。在 Solidity 0.8.0 之前的版本中，`assert` 失败不仅会回滚状态，而且不退还任何剩余的 Gas 费用。即使在现代版本中，不当的断言失败对于合约的用户来说也可能是灾难性的，特别是如果这导致了合约的关键功能无法使用。

## 危险模式

### 错误地将 assert 用于外部条件验证
最常见的错误是将 `assert` 用于验证用户输入或外部合约调用的结果，而这些操作本应该使用 `require`。
```solidity
# 危险 - 使用 assert 验证用户输入，失败时惩罚过重（如耗尽 Gas 或抛出 Panic）
contract WithdrawalContract {
    address payable public owner;
    uint256 public balance;

    constructor() {
        owner = payable(msg.sender);
        balance = 0;
    }

    receive() external payable {
        balance += msg.value;
    }

    function withdraw(uint256 amount) public {
        assert(msg.sender == owner); // 确保只有合约所有者可以提取资金
        require(balance >= amount, "Insufficient funds"); // 确保有足够的余额
        balance -= amount;
        owner.transfer(amount); // 向所有者转移资金
    }
}
```

## 攻击方式与影响
1. 如果 assert 条件被不合理的业务逻辑卡死，可能会导致核心功能（如用户提款）被永久阻塞，造成拒绝服务（DoS）和资金锁定。
2. 在旧版本以太坊虚拟机（EVM）机制下，攻击者可以诱导用户触发 assert 失败，从而恶意耗尽用户的 Gas 费用。

## 检测要点
1. 全局搜索合约中的 assert() 语句。
2. 检查 assert 内的条件。如果该条件受到 msg.sender、msg.value、函数传参或外部合约返回值的直接影响，则极有可能是误用。
3. 确保 assert 仅被用于检查状态机中的不变量（Invariants），例如“代币的总供应量必须等于所有用户余额的总和”。

## 安全实践
1. 使用require代替assert：对于用户输入或预条件检查，使用require更为合适，因为它明确表示这是对外部条件的检查，而非内部逻辑错误。
2. 添加紧急撤资功能：设计一个允许在紧急情况下提取资金的机制，例如，如果owner地址被锁定，可以有一个多重签名的“董事会”来决定如何解锁资金。
3. 确保合约所有者的可变更性：允许合约所有者更改，以防原始所有者丢失私钥或地址被锁定。

## 修复示例
```solidity
# 安全 - 采用 require 进行常规条件检查，保留 assert 仅作内部状态校验
contract ImprovedWithdrawalContract {
    address payable public owner;
    uint256 public balance;

    constructor() {
        owner = payable(msg.sender);
    }

    receive() external payable {
        balance += msg.value;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Only the contract owner can call this function");
        _;
    }

    function withdraw(uint256 amount) public onlyOwner {
        require(balance >= amount, "Insufficient funds");
        balance -= amount;
        owner.transfer(amount);
    }

    // 添加一个功能，允许更改所有者
    function changeOwner(address payable newOwner) public onlyOwner {
        owner = newOwner;
    }
}
```


"""
)

